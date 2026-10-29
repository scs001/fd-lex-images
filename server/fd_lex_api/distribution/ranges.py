"""HTTP Range 解析与文件流式迭代（断点续传）。

语义（RFC 7233 实用子集）：
- ``bytes=start-end`` / ``bytes=start-`` / ``bytes=-suffix`` 单区间；
- 多区间（逗号）不实现——按整文件 200 返回（允许服务器忽略 Range）；
- 语法非法 → 忽略（200 整文件）；
- 语法合法但不可满足（start >= size 等）→ 416 + ``Content-Range: bytes */size``。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

CHUNK_SIZE = 1024 * 256


@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int  # inclusive
    total: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    def content_range(self) -> str:
        return f"bytes {self.start}-{self.end}/{self.total}"


@dataclass(frozen=True)
class RangeParse:
    byte_range: ByteRange | None
    unsatisfiable: bool = False
    ignored: bool = False


def parse_range(header: str | None, size: int) -> RangeParse:
    """解析 Range 头；size=0 或非法输入按忽略/不可满足处理。"""
    if not header:
        return RangeParse(None)
    value = header.strip()
    if not value.lower().startswith("bytes="):
        return RangeParse(None, ignored=True)
    spec = value[len("bytes="):].strip()
    if "," in spec:
        return RangeParse(None, ignored=True)  # 多区间不支持：忽略
    if "-" not in spec or size <= 0:
        return RangeParse(None, ignored=True)
    first, _, last = spec.partition("-")
    first, last = first.strip(), last.strip()
    try:
        if first == "" and last != "":
            suffix = int(last)
            if suffix <= 0:
                return RangeParse(None, unsatisfiable=True)
            start = max(size - suffix, 0)
            end = size - 1
        elif first != "":
            start = int(first)
            end = int(last) if last else size - 1
        else:
            return RangeParse(None, ignored=True)
    except ValueError:
        return RangeParse(None, ignored=True)
    if start < 0 or end < start:
        return RangeParse(None, unsatisfiable=True)
    if start >= size:
        return RangeParse(None, unsatisfiable=True)
    return RangeParse(ByteRange(start=start, end=min(end, size - 1), total=size))


def iter_file(path: Path, start: int = 0, end: int | None = None) -> Iterator[bytes]:
    """从 start 读到 end（含），块大小 CHUNK_SIZE，全程只读。"""
    remaining = None if end is None else end - start + 1
    with open(path, "rb") as handle:
        handle.seek(start)
        while True:
            want = CHUNK_SIZE if remaining is None else min(CHUNK_SIZE, remaining)
            if want <= 0:
                break
            block = handle.read(want)
            if not block:
                break
            if remaining is not None:
                remaining -= len(block)
            yield block
#!/usr/bin/env python3
"""电子签闸门法条核验脚本（change lex-contract-esignature task 4.1 的可复跑形态）。

经 fd-legal-search-mcp 的 MCP 端点取《电子签名法》第三条/第十三条/第十四条原文，
逐字写入 ``fd_lex_api/esignature/legal_basis.json``（不手工改条文）。

用法：
    python scripts/verify_legal_basis.py            # 打印结果，不写盘
    python scripts/verify_legal_basis.py --write    # 核验通过后写盘

纪律：工具返回的条文原样落盘（含 provenance），MUST NOT 改写或补写；
检索为空的项目写 retrieved=false（如人社部《电子劳动合同订立指引》当前未被
法规库收录），闸门据此不引用其条文。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

MCP_URL = "http://cheap6.mesh.finddata.cn:31884/mcp"
CITATIONS = {
    "article_3": "《中华人民共和国电子签名法》第三条",
    "article_13": "《中华人民共和国电子签名法》第十三条",
    "article_14": "《中华人民共和国电子签名法》第十四条",
}
OUT_PATH = Path(__file__).resolve().parents[1] / "fd_lex_api" / "esignature" / "legal_basis.json"


def _payload(resp: httpx.Response):
    if "text/event-stream" in resp.headers.get("content-type", ""):
        events = []
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                try:
                    events.append(json.loads(line[5:].strip()))
                except ValueError:
                    pass
        return events[-1] if events else None
    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text[:400]}


def _text_of(result: dict) -> str:
    for item in result.get("content") or []:
        if item.get("type") == "text":
            return item["text"]
    return json.dumps(result, ensure_ascii=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="核验通过后写盘")
    args = ap.parse_args()

    headers = {"content-type": "application/json", "accept": "application/json, text/event-stream"}
    with httpx.Client(timeout=60, trust_env=False) as client:
        init = client.post(MCP_URL, headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "lex-legal-basis-verify", "version": "1"}},
        })
        sid = init.headers.get("mcp-session-id")
        h = dict(headers)
        if sid:
            h["mcp-session-id"] = sid
        client.post(MCP_URL, headers=h, json={"jsonrpc": "2.0", "method": "notifications/initialized"})

        def call(name: str, arguments: dict) -> dict:
            resp = client.post(MCP_URL, headers=h, json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            })
            return json.loads(_text_of(_payload(resp).get("result", {})))

        found = call("law_search", {"title_query": "电子签名法"})
        hits = [r for r in found.get("results", []) if r.get("title") == "中华人民共和国电子签名法"]
        if not hits:
            print("FAIL: 未检索到《中华人民共和国电子签名法》", file=sys.stderr)
            return 2
        statute = hits[0]
        if statute.get("status") != "有效":
            print(f"FAIL: 效力状态为 {statute.get('status')}，禁止作为现行法引用", file=sys.stderr)
            return 2

        articles = {}
        for key, citation in CITATIONS.items():
            data = call("law_reference", {"citation": citation})
            art = data.get("article") or {}
            if not art.get("text") and not art.get("excerpt"):
                print(f"FAIL: {citation} 未返回条文", file=sys.stderr)
                return 2
            articles[key] = {
                "no": art.get("no"),
                "display": art.get("display"),
                "text": (art.get("text") or art.get("excerpt") or "").rstrip("\n"),
                "chunk_provenance": (data.get("chunk") or {}).get("provenance"),
            }

        guideline = call("law_search", {"title_query": "电子劳动合同订立指引"})
        guideline_hit = guideline.get("results") or []

    basis = {
        "_doc": ("电子签适用性闸门的法条依据（change lex-contract-esignature task 4.1）。"
                 "本文件全部文本来自 fd-legal-search-mcp 的工具返回，逐字摘录、未改写；"
                 "禁止人工补写条文。重新核验时整体替换本文件。"),
        "retrieved_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "tool": {"endpoint": MCP_URL, "server": "fd-legal-search-mcp",
                 "calls": ["law_search(title_query=电子签名法)"]
                 + [f"law_reference(citation={c})" for c in CITATIONS.values()]},
        "statute": {"id": statute.get("id"), "title": statute.get("title"),
                    "type": statute.get("type"), "status": statute.get("status"),
                    "publish": (statute.get("publish") or "")[:10],
                    "provenance": statute.get("provenance")},
        **articles,
        "labor_guideline": {
            "retrieved": bool(guideline_hit),
            "title": "电子劳动合同订立指引（人力资源社会保障部办公厅）",
            "note": ("法规库未收录该部门规范性文件，条文原文未获核验；闸门 MUST NOT 引用其条文。"
                     if not guideline_hit else "已收录，条文以 law_reference 返回为准。"),
        },
    }

    print(json.dumps({k: v for k, v in basis.items() if k != "_doc"}, ensure_ascii=False, indent=2)[:1200])
    if args.write:
        OUT_PATH.write_text(json.dumps(basis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n写入 {OUT_PATH}")
    else:
        print("\n（未写盘；加 --write 落盘）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

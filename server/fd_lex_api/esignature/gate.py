"""电子文书适用性闸门（spec 第 5 条）。

两层判定：

1. **确定性排除**（阻断）：类别命中 ``EXCLUDED_CATEGORIES`` 或标题命中
   ``EXCLUDED_TITLE_PATTERNS``。口径=《电子签名法》第三条第二款排除情形——
   婚姻/收养/继承等人身关系、停止供水供热供气等公用事业服务、
   法律法规规定不适用的其他情形。
2. **专项提示后放行**（acknowledge 确认后方可发起，提示与确认动作入账留痕）：
   劳动合同、民间借贷。

**法条文本的唯一来源=``legal_basis.json``**（task 4.1 已由
``fd-legal-search-mcp`` 核验落地：法条 id 18881、status=有效）。本模块
MUST NOT 手写任何条文；未核验的内容一律不展示条文原文，只报「未核验」。
人社部《电子劳动合同订立指引》当前**未被法规库收录**（law_search /
legal_docs_search 均 0 条，见 legal_basis.json），故劳动提示只引用已核验的
《电子签名法》第十三条，不引用该指引条文。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CATEGORIES: tuple[str, ...] = (
    "labor",
    "loan",
    "nda",
    "sale",
    "service",
    "other",
    "marriage-family",
    "inheritance",
    "utility",
)

EXCLUDED_CATEGORIES = frozenset({"marriage-family", "inheritance", "utility"})

#: 标题级排除线索（确定性词表，宁窄勿宽：仅强指向排除情形的词组）
EXCLUDED_TITLE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"婚姻|结婚|离婚|收养|解除收养|监护|扶养|赡养|继承|遗赠|遗嘱|人身关系"),
    re.compile(r"停止(供水|供电|供热|供气)|中断(供水|供电|供热|供气)"),
)

_BASIS_PATH = Path(__file__).with_name("legal_basis.json")


def legal_basis() -> dict[str, Any] | None:
    """已核验的法条依据（task 4.1 产物）；缺失/损坏返回 None。"""
    try:
        raw = json.loads(_BASIS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _basis_digest(basis: dict[str, Any]) -> dict[str, Any]:
    """展示用摘要：只取已核验条文与其效力状态、溯源。"""
    statute = basis.get("statute") or {}
    art3 = basis.get("article_3") or {}
    return {
        "statute": statute.get("title"),
        "status": statute.get("status"),
        "publish": statute.get("publish"),
        "article": art3.get("display"),
        "text": art3.get("text"),
        "provenance": art3.get("chunk_provenance"),
    }


def _labor_notice(basis: dict[str, Any] | None) -> str:
    art13 = (basis or {}).get("article_13") or {}
    text13 = art13.get("text") or ""
    guideline = (basis or {}).get("labor_guideline") or {}
    unverified = (
        "（人社部《电子劳动合同订立指引》属部门规范性文件，法规库未收录、条文原文"
        "未经核验，本提示不引用其条文；请以人社部发布文本为准）"
        if not guideline.get("retrieved")
        else "（该指引条文已核验，见 legal_basis.json）"
    )
    return (
        "劳动合同电子签须满足《电子签名法》第十三条可靠电子签名四要件"
        "（已核验条文：" + text13 + "）。"
        "请确认实名与意愿认证全程留痕、双方各持可查阅可下载的合同文本。"
        + unverified
    )


def _loan_notice() -> str:
    return (
        "提示（经验性风控，非法条结论）：借贷/借条类合同纠纷常围绕「是否本人签署」"
        "举证，存在冒名签署争点。请确保实名与意愿认证全程留痕——"
        "《电子签名法》第十三条要求签署时电子签名制作数据仅由电子签名人控制。"
    )


def evaluate(category: str, title: str, body_excerpt: str = "") -> dict[str, Any]:
    """发起前判定：返回 {verdict: block|notice|pass, ...}。"""
    cat = (category or "other").strip()
    text = f"{title or ''} {body_excerpt or ''}"
    hit = next((p.pattern for p in EXCLUDED_TITLE_PATTERNS if p.search(text)), None)
    basis = legal_basis()
    if cat in EXCLUDED_CATEGORIES or hit:
        result: dict[str, Any] = {
            "verdict": "block",
            "category": cat,
            "title_hit": hit,
        }
        if basis:
            result["legal_basis"] = _basis_digest(basis)
        else:
            result["basis_pending"] = (
                "阻断依据=《电子签名法》第三条第二款排除情形；条文文本尚未经"
                "法律数据工具核验落地（legal_basis.json，tasks 4.1），"
                "不展示未核验引文，仅按确定性口径阻断"
            )
        return result
    if cat == "labor":
        return {"verdict": "notice", "category": cat, "notice": _labor_notice(basis)}
    if cat == "loan":
        return {"verdict": "notice", "category": cat, "notice": _loan_notice()}
    return {"verdict": "pass", "category": cat}


__all__ = [
    "CATEGORIES",
    "EXCLUDED_CATEGORIES",
    "EXCLUDED_TITLE_PATTERNS",
    "evaluate",
    "legal_basis",
]

# -*- coding: utf-8 -*-
"""
전 파일 자유 텍스트 검색 — 일본어 원문/번역으로 찾아 편집 위치로 이동.

플레이 중 "이거 고쳐야겠다" 한 문장을 원문이나 번역으로 검색 → 결과 클릭 →
해당 파일의 그 문장으로 점프(`web/app.js jumpTo`).
"""
from __future__ import annotations
from typing import Dict, Any, List

from . import textcodec


def search_units(proj: Dict[str, Any], query: str, scope: str = "both",
                 cap: int = 300) -> List[dict]:
    """query 를 자유 텍스트의 jp/ko 에서 부분검색(대소문자 무시).
    scope: 'both'|'jp'|'ko'. 반환: [{rel,sid,cat,speaker,jp,ko,in_jp,in_ko}]."""
    q = (query or "").strip()
    if not q:
        return []
    ql = q.lower()
    want_jp = scope in ("both", "jp")
    want_ko = scope in ("both", "ko")
    out: List[dict] = []
    for rel, f in proj["files"].items():
        for u in f["units"]:
            if u["kind"] != "free" or u.get("control"):
                continue
            jp = textcodec.decode(u["jp"])
            ko = textcodec.decode(u.get("ko", ""))
            in_jp = want_jp and ql in jp.lower()
            in_ko = want_ko and bool(ko) and ql in ko.lower()
            if not (in_jp or in_ko):
                continue
            out.append({
                "rel": rel, "sid": u["id"], "cat": u.get("cat"),
                "speaker": u.get("speaker"),
                "jp": jp.replace("\n", " ").strip()[:100],
                "ko": ko.replace("\n", " ").strip()[:100],
                "in_jp": in_jp, "in_ko": in_ko,
            })
            if len(out) >= cap:
                return out
    return out

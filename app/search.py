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
                 cap: int = 300, include_control: bool = False,
                 jp_cond: str = "") -> List[dict]:
    """query 를 자유 텍스트의 jp/ko 에서 부분검색(대소문자 무시).
    scope: 'both'|'jp'|'ko'. include_control: 제어기호/치환자뿐 유닛 포함(%변수% 사용처 점프용).
    jp_cond 를 주면 원문에 그 문자열이 있는 유닛만 (찾아 바꾸기의 원문 조건과 동일 기준).
    반환: [{rel,sid,cat,speaker,jp,ko,in_jp,in_ko}]."""
    q = (query or "").strip()
    jp_cond = (jp_cond or "").strip()
    if not q and not jp_cond:
        return []
    ql = q.lower()
    want_jp = scope in ("both", "jp")
    want_ko = scope in ("both", "ko")
    out: List[dict] = []
    for rel, f in proj["files"].items():
        for u in f["units"]:
            if u["kind"] != "free" or (u.get("control") and not include_control):
                continue
            jp = textcodec.decode(u["jp"])
            if jp_cond and jp_cond not in jp:
                continue
            ko = textcodec.decode(u.get("ko", ""))
            # 검색어 없이 원문 조건만 있으면: 그 원문을 포함한 문장 전부
            # (찾아 바꾸기에서 옛 표기를 눈으로 찾는 용도)
            in_jp = bool(q) and want_jp and ql in jp.lower()
            in_ko = bool(q) and want_ko and bool(ko) and ql in ko.lower()
            if q and not (in_jp or in_ko):
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


def replace_in_ko(proj: Dict[str, Any], query: str, repl: str,
                  dry: bool = False, jp_cond: str = "") -> Dict[str, int]:
    """번역문(ko) 전체에서 query → repl 리터럴 치환. 원문(jp)은 건드리지 않는다.
    용어 오타(사바→사바나)가 초안에 구워진 뒤의 일괄 복구용. 대소문자 구분(정확 일치).
    jp_cond 를 주면 "원문에 그 문자열이 있는 칸"만 대상으로 좁힌다
    (예: サバンナ 문장 안의 사바만 치환 — 무관한 사바 오폭 방지).
    dry=True 면 세기만 하고 바꾸지 않는다. 반환 {units, hits}."""
    q = query or ""
    jp_cond = (jp_cond or "").strip()
    if not q or repl is None:
        return {"units": 0, "hits": 0}
    units = hits = 0
    for f in proj["files"].values():
        for u in f["units"]:
            if u["kind"] != "free" or u.get("control"):
                continue
            if jp_cond and jp_cond not in textcodec.decode_field(u["field"], u["jp"]):
                continue
            ko = textcodec.decode_field(u["field"], u.get("ko", ""))
            if not ko or q not in ko:
                continue
            units += 1
            hits += ko.count(q)
            if not dry:
                u["ko"] = textcodec.encode_field(u["field"], ko.replace(q, repl))
    return {"units": units, "hits": hits}

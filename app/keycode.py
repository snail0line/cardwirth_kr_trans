# -*- coding: utf-8 -*-
"""
키코드 병기(倂記) — 일본어 키코드에 한국어 키코드 줄을 덧붙인다.

CardWirth 키코드는 여러 줄(줄 구분자 = 리터럴 "\\n") 중 하나라도 아이템/스킬의
키코드와 일치하면 발동한다. 그래서 원문(JP) 줄을 지우지 않고 KO 줄을 **덧붙이면**
- 일본어 원본 아이템(JP 키코드) → 그대로 발동
- 한글판 표준 아이템/스킬(KO 키코드) → 추가된 KO 줄로 발동
둘 다 매칭돼 호환된다. krarrange(한글화) 스킨의 표준 액션카드가 쓰는 방식과 동일.

내장 사전(app/keycodes.json)은 krarrange 스킨 + The Cave 확정 병기 + 표준 키코드에서
추린 JP→KO 매핑. 사전에 있는 JP 줄만 KO 를 붙이고, 매칭 안 되는 줄은 그대로 둔다.
결과는 초안(사용자가 키코드 패널에서 검수·수정)이다.
"""
from __future__ import annotations
import json
import os
from typing import Dict, List, Optional

from . import schema

NL = "\\n"  # CardWirth 키코드 줄 구분자(리터럴 백슬래시+n)
_DICT_PATH = os.path.join(os.path.dirname(__file__), "keycodes.json")
_cache: Optional[Dict[str, str]] = None


def load_dict() -> Dict[str, str]:
    """내장 키코드 사전(JP→KO). 파일 없으면 빈 dict."""
    global _cache
    if _cache is None:
        try:
            with open(_DICT_PATH, encoding="utf-8") as f:
                d = json.load(f)
            _cache = {str(k).strip(): str(v).strip()
                      for k, v in d.items() if str(k).strip() and str(v).strip()}
        except (OSError, ValueError):
            _cache = {}
    return _cache


def bilingual(jp_block: str, kdict: Optional[Dict[str, str]] = None) -> Optional[str]:
    """키코드 블록(JP)에 사전 매칭되는 KO 줄을 덧붙여 병기 블록을 만든다.

    - 사전에 걸리는 JP 줄이 하나도 없으면 None(손대지 않음).
    - 이미 블록 안에 있는 KO 줄은 중복 추가하지 않는다(재실행 안전).
    - 원문 줄 순서·빈 줄은 보존하고 KO 줄만 뒤에 붙인다.
    """
    if kdict is None:
        kdict = load_dict()
    lines = jp_block.split(NL)
    present = {l.strip() for l in lines}
    appended: List[str] = []
    for l in lines:
        ko = kdict.get(l.strip())
        if ko and ko not in present and ko not in appended:
            appended.append(ko)
    if not appended:
        return None
    # 원문이 후행 빈 줄(…\n)로 끝나면 그 \n 을 구분자로 재사용 → 이중 빈 줄 방지
    sep = "" if jp_block.endswith(NL) else NL
    return jp_block + sep + NL.join(appended)


def fill_bilingual(proj: Dict) -> Dict:
    """프로젝트의 키코드 엔티티(ko 빈칸)에 병기 초안을 채운다.

    이미 번역/병기된 키코드(ko 있음)는 건드리지 않는다 — 검수한 값 보호.
    반환: {"filled": n, "skipped_no_match": m, "already": k, "items": [{gkey, jp, ko}]}
    """
    kdict = load_dict()
    filled = no_match = already = 0
    items: List[Dict] = []
    for gk, g in proj.get("glossary", {}).items():
        if g.get("etype") != schema.ENT_KEYCODE:
            continue
        if (g.get("ko") or "").strip():
            already += 1
            continue
        bi = bilingual(g["jp"], kdict)
        if bi is None:
            no_match += 1
            continue
        g["ko"] = bi
        filled += 1
        items.append({"gkey": gk, "jp": g["jp"], "ko": bi})
    return {"filled": filled, "skipped_no_match": no_match,
            "already": already, "items": items}

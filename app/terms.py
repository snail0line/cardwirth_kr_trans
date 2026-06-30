# -*- coding: utf-8 -*-
"""
용어집(번역 메모리) — 자유 텍스트에서 반복되는 선택지/단어 감지 + 일괄 적용.

두 종류:
  exact : 같은 자유 텍스트 '값'이 2회 이상 (선택지·짧은 반복 대사) → 동일값 전부 일괄 치환
  word  : 식별자 이름(＿ソース派 등에서 ＿/「」 제거)이 자유 텍스트 안에 substring 으로 등장
          → 용어 번역 지정. 강조/초안 보조용. (식별자 자체는 원문 유지)

적용 대상은 자유 텍스트(free)만. 플래그/쿠폰 등 식별자엔 적용하지 않는다.
"""
from __future__ import annotations
from collections import Counter
from typing import Dict, Any, List

from . import schema, textcodec


# 화자 후보에서 제외할 합성 라벨(실제 캐릭터 이름이 아님)
_SYNTHETIC_SPEAKERS = {
    "랜덤 PC", "선택 PC", "비선택 PC", "지정 PC", "선택된 PC", "PC",
}


def _clean_term(s: str) -> str:
    s = (s or "").strip().strip("\\n").strip()
    if s.startswith("＿"):
        s = s[1:]
    s = s.strip("「」 ")
    return s


_STRUCT_CH = set("_[]＿（）()<>０１２３４５６７８９0123456789")


def _is_structural_id(s: str) -> bool:
    """扉の番人_回答_[3] 처럼 구조(언더바/괄호/숫자)를 담은 내부 식별자성 이름.
    플레이어에게 안 보이고 번역 시 깨지기 쉬워 용어 후보에서 뺀다."""
    return any(c in _STRUCT_CH for c in s)


def _free_values(proj: Dict[str, Any]) -> List[str]:
    """모든 자유 텍스트의 표시형(디코드) 값."""
    out = []
    for f in proj["files"].values():
        for u in f["units"]:
            if u["kind"] == "free" and not u.get("control"):
                out.append(textcodec.decode(u["jp"]))
    return out


def _free_index(proj: Dict[str, Any]):
    """[(rel, sid, disp)] — 위치 추적용 자유 텍스트 인덱스."""
    idx = []
    for rel, f in proj["files"].items():
        for u in f["units"]:
            if u["kind"] == "free" and not u.get("control"):
                idx.append((rel, u["id"], textcodec.decode(u["jp"])))
    return idx


def _identifier_names(proj: Dict[str, Any]) -> set:
    """식별자(엔티티) 이름 집합(정리형). 용어가 식별자와 겹치는지 표시용."""
    out = set()
    for g in proj.get("glossary", {}).values():
        t = _clean_term(g.get("jp", ""))
        if t:
            out.add(t)
    return out


def _occurrences(index, jp: str, exact: bool, cap: int = 80):
    """용어가 등장하는 자유 텍스트 위치 목록 [{rel, sid, preview}]."""
    jp_s = jp.strip()
    out = []
    for rel, sid, disp in index:
        hit = (disp.strip() == jp_s) if exact else (jp in disp)
        if hit:
            prev = disp.replace("\n", " ").strip()
            out.append({"rel": rel, "sid": sid, "preview": prev[:60]})
            if len(out) >= cap:
                break
    return out


def detect(proj: Dict[str, Any]) -> Dict[str, List[dict]]:
    """exact / word / manual 용어 후보를 감지 + 각 용어의 등장 위치(occurrences) 부착.
    proj['terms'] 의 기존 번역과 proj['terms_manual'] 의 수동 추가어를 병합."""
    saved = proj.get("terms", {})
    manual = proj.get("terms_manual", [])   # [{jp, ko}]
    free_vals = _free_values(proj)
    index = _free_index(proj)
    ids = _identifier_names(proj)

    def entry(jp, count, exact):
        return {
            "jp": jp, "count": count, "ko": saved.get(jp, ""),
            "is_identifier": _clean_term(jp) in ids,
            "occurrences": _occurrences(index, jp, exact=exact),
        }

    # ── exact: 동일 자유텍스트 값 2회+ ──
    cnt = Counter(v.strip() for v in free_vals if v.strip())
    exact = [entry(v, c, True) for v, c in cnt.most_common()
             if c >= 2 and len(v) <= 30]

    # ── word: 식별자/캐릭터 이름 중 자유텍스트에 등장 (구조적 내부식별자는 제외) ──
    cand = set()
    for g in proj.get("glossary", {}).values():
        t = _clean_term(g.get("jp", ""))
        if len(t) >= 2 and not _is_structural_id(t):
            cand.add(t)
    for f in proj["files"].values():
        for u in f["units"]:
            sp = (u.get("speaker") or "").strip()
            if len(sp) >= 2 and sp not in _SYNTHETIC_SPEAKERS \
                    and not sp.endswith("PC") and not _is_structural_id(sp):
                cand.add(sp)
    joined = "\n".join(free_vals)
    words = [entry(t, joined.count(t), False) for t in cand if joined.count(t) >= 1]
    words.sort(key=lambda x: -x["count"])

    # ── manual: 사용자가 직접 추가한 단어/문장 ──
    auto_jp = {e["jp"] for e in exact} | {w["jp"] for w in words}
    man = []
    for m in manual:
        jp = (m.get("jp") or "").strip()
        if not jp:
            continue
        e = entry(jp, len(_occurrences(index, jp, exact=False)), False)
        e["ko"] = m.get("ko", "") or saved.get(jp, "")
        man.append(e)

    return {"exact": exact, "word": words, "manual": man}


def add_manual(proj: Dict[str, Any], jp: str, ko: str = "") -> dict:
    """용어집에 단어/문장 수동 추가. 등장 위치를 찾아 함께 반환."""
    jp = (jp or "").strip()
    lst = proj.setdefault("terms_manual", [])
    found = next((m for m in lst if m.get("jp") == jp), None)
    if found is None:
        found = {"jp": jp, "ko": ko}
        lst.append(found)
    else:
        if ko:
            found["ko"] = ko
    if ko:
        proj.setdefault("terms", {})[jp] = ko
    return {
        "jp": jp, "ko": found.get("ko", ""), "is_identifier": False,
        "count": len(_occurrences(_free_index(proj), jp, exact=False)),
        "occurrences": _occurrences(_free_index(proj), jp, exact=False),
    }


def remove_manual(proj: Dict[str, Any], jp: str) -> None:
    lst = proj.get("terms_manual", [])
    proj["terms_manual"] = [m for m in lst if m.get("jp") != jp]


def apply_exact(proj: Dict[str, Any], jp: str, ko: str) -> int:
    """exact 용어: 동일 자유텍스트 값 전부에 ko 를 일괄 적용. 적용 건수 반환."""
    proj.setdefault("terms", {})[jp] = ko
    ko_raw = textcodec.encode(ko)
    n = 0
    for f in proj["files"].values():
        for u in f["units"]:
            if u["kind"] == "free" and textcodec.decode(u["jp"]).strip() == jp.strip():
                u["ko"] = ko_raw
                n += 1
    return n


def set_word(proj: Dict[str, Any], jp: str, ko: str) -> None:
    proj.setdefault("terms", {})[jp] = ko


def apply_words_to_drafts(proj: Dict[str, Any], only_untranslated: bool = True) -> int:
    """word 용어들을 자유 텍스트에 substring 치환해 초안(ko) 생성. 변경 건수 반환.
    이미 번역된 유닛은 기본적으로 건드리지 않는다."""
    terms = {k: v for k, v in proj.get("terms", {}).items() if v}
    # 긴 용어 먼저 치환(부분겹침 방지)
    items = sorted(terms.items(), key=lambda kv: -len(kv[0]))
    n = 0
    for f in proj["files"].values():
        for u in f["units"]:
            if u["kind"] != "free" or u.get("control"):
                continue
            if only_untranslated and u.get("ko"):
                continue
            disp = textcodec.decode(u["jp"])
            new = disp
            for tj, tk in items:
                if tj and tj in new:
                    new = new.replace(tj, tk)
            if new != disp:
                u["ko"] = textcodec.encode(new)
                n += 1
    return n

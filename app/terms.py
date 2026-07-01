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
import re
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


# $PC\人物描写\髪の色$ / %..% = 게임이 실행 시 값(쿠폰·PC속성 등)으로 치환하는 변수 참조.
# 번역 대상이 아니므로(건드리면 깨짐) 용어·식별자·초안치환에서 제외한다.
_VAR_RE = re.compile(r"\$[^$\n]*\$|%[^%\n]*%")


def _is_variable_ref(s: str) -> bool:
    """(exact 값용) 문자열이 사실상 변수 참조($..$ / %..%)만으로 이뤄졌는지.
    토큰이 섞인 정상 문장(반복 대사)은 제외 대상이 아니므로 False."""
    if not s:
        return False
    rest = _VAR_RE.sub("", s).strip().strip("「」 \\n")
    return not rest and bool(_VAR_RE.search(s))


def _is_system_name(s: str) -> bool:
    """(word/식별자 이름 후보용) 쿠폰·PC속성 경로(PC\\人物描写\\目の色, PC\\三人称,
    進行度\\... 등 백슬래시 계층 이름) 또는 변수 참조. 이름 자체가 시스템 식별자라
    캐릭터명/용어 후보에서 제외한다."""
    if not s:
        return False
    return "\\" in s or _is_variable_ref(s)


def _protect_vars(text: str):
    """치환 보호: $..$ / %..% 구간을 임시 placeholder 로 빼둔다. (masked, holds) 반환."""
    holds: List[str] = []

    def _repl(m: "re.Match") -> str:
        holds.append(m.group(0))
        return f"\x00{len(holds) - 1}\x00"

    return _VAR_RE.sub(_repl, text), holds


def _restore_vars(text: str, holds: List[str]) -> str:
    for i, v in enumerate(holds):
        text = text.replace(f"\x00{i}\x00", v)
    return text


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
        if t and not _is_system_name(t):
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
             if c >= 2 and len(v) <= 30 and not _is_variable_ref(v)]

    # ── word: 식별자/캐릭터 이름 중 자유텍스트에 등장 (구조적 내부식별자는 제외) ──
    cand = set()
    for g in proj.get("glossary", {}).values():
        t = _clean_term(g.get("jp", ""))
        if len(t) >= 2 and not _is_structural_id(t) and not _is_system_name(t):
            cand.add(t)
    for f in proj["files"].values():
        for u in f["units"]:
            sp = (u.get("speaker") or "").strip()
            if len(sp) >= 2 and sp not in _SYNTHETIC_SPEAKERS \
                    and not sp.endswith("PC") and not _is_structural_id(sp) \
                    and not _is_system_name(sp):
                cand.add(sp)
    # 실제 '표시 텍스트'에 등장하는 것만 용어로 센다(같은 문자열이 표시 텍스트면 남긴다):
    #  · 변수 참조($..$ / %..%) 내부는 제외 — 토큰 안 substring(二人称 등)이 용어로 잡히는 것 방지
    #  · 그 후에도 백슬래시가 남는 값(パッケージ\… 같은 시스템 경로)은 표시 텍스트가 아니므로 제외
    disp_vals = []
    for v in free_vals:
        v2 = _VAR_RE.sub("", v)
        if "\\" not in v2:
            disp_vals.append(v2)
    joined = "\n".join(disp_vals)
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
            masked, holds = _protect_vars(disp)   # $..$ / %..% 안은 치환에서 보호(쿠폰·변수 참조 보존)
            new = masked
            for tj, tk in items:
                if tj and tj in new:
                    new = new.replace(tj, tk)
            new = _restore_vars(new, holds)
            if new != disp:
                u["ko"] = textcodec.encode(new)
                n += 1
    return n

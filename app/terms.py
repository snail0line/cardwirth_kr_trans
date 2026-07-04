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
import json
import os
import re
from collections import Counter
from typing import Dict, Any, List

from . import schema, textcodec

# ── 공용 용어집 (모든 시나리오 공통 — リューン=륜 같은 세계관 단어) ──────────
# projects/ 아래 로컬 저장(배포 안 됨). 프로젝트별 use_global_terms 로 on/off.
_GLOBAL_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "projects", "global_terms.json"))


def load_global() -> Dict[str, str]:
    try:
        with open(_GLOBAL_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return {k: v for k, v in d.items() if k and v}
    except (OSError, ValueError):
        return {}


def set_global(jp: str, ko: str) -> Dict[str, str]:
    """공용 용어 추가/수정. ko 빈값 = 삭제. 갱신된 전체 맵 반환."""
    jp = (jp or "").strip()
    ko = (ko or "").strip()
    d = load_global()
    if jp:
        if ko:
            d[jp] = ko
        else:
            d.pop(jp, None)
    os.makedirs(os.path.dirname(_GLOBAL_PATH), exist_ok=True)
    with open(_GLOBAL_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    return d


def _write_global(d: Dict[str, str]) -> None:
    os.makedirs(os.path.dirname(_GLOBAL_PATH), exist_ok=True)
    with open(_GLOBAL_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def export_global(path: str) -> int:
    """공용 용어집을 JSON 파일로 저장(공유용). 반환: 용어 수."""
    d = load_global()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    return len(d)


def inspect_import(path: str) -> Dict[str, int]:
    """가져올 파일 검사(적용 안 함). {total, new, conflict, same}."""
    with open(path, encoding="utf-8-sig") as f:
        d = json.load(f)
    if not isinstance(d, dict):
        raise ValueError("JSON 형식이 다릅니다 — {\"단어\": \"번역\"} 맵이어야 합니다")
    d = {str(k).strip(): str(v).strip() for k, v in d.items()
         if str(k).strip() and str(v).strip()}
    cur = load_global()
    new = sum(1 for k in d if k not in cur)
    conflict = sum(1 for k, v in d.items() if k in cur and cur[k] != v)
    same = len(d) - new - conflict
    return {"total": len(d), "new": new, "conflict": conflict, "same": same}


def import_global(path: str, overwrite: bool = False) -> Dict[str, int]:
    """가져온 파일을 내 공용 용어집에 병합. overwrite=False 면 새 단어만 추가.
    반환: {added, updated}."""
    with open(path, encoding="utf-8-sig") as f:
        d = json.load(f)
    d = {str(k).strip(): str(v).strip() for k, v in d.items()
         if str(k).strip() and str(v).strip()}
    cur = load_global()
    added = updated = 0
    for k, v in d.items():
        if k not in cur:
            cur[k] = v
            added += 1
        elif overwrite and cur[k] != v:
            cur[k] = v
            updated += 1
    _write_global(cur)
    return {"added": added, "updated": updated}


def global_enabled(proj: Dict[str, Any]) -> bool:
    return bool(proj.get("use_global_terms", True))


def effective_terms(proj: Dict[str, Any]) -> Dict[str, str]:
    """초안 생성 등에 실제 적용할 용어 = 공용(켜져 있으면) + 프로젝트(우선)."""
    out = dict(load_global()) if global_enabled(proj) else {}
    out.update({k: v for k, v in (proj.get("terms") or {}).items() if (v or "").strip()})
    return out


def global_list(proj: Dict[str, Any]) -> List[dict]:
    """공용 용어 목록 + 현재 시나리오 등장 횟수·위치. [{jp, ko, count, occurrences}]"""
    joined = "\n".join(_free_values(proj))
    index = _free_index(proj)
    return [{"jp": jp, "ko": ko, "count": joined.count(jp),
             "occurrences": _occurrences(index, jp, exact=False)}
            for jp, ko in sorted(load_global().items())]


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
    """[(rel, sid, disp, field, ko)] — 위치 추적용 자유 텍스트 인덱스.
    field 는 "#text"(본문 문장) / "@name"(선택지 버튼 라벨) 구분용. ko = 번역문(표시형)."""
    idx = []
    for rel, f in proj["files"].items():
        for u in f["units"]:
            if u["kind"] == "free" and not u.get("control"):
                idx.append((rel, u["id"], textcodec.decode(u["jp"]), u["field"],
                            textcodec.decode_field(u["field"], u.get("ko", ""))))
    return idx


# 「」『』 안의 짧은 인용어 = 고유명사/아이템명 신호 (예: 「鬼杜若」（おにかきつばた）)
_QUOTED_RE = re.compile(r"[「『]([^「」『』\n]{2,12})[」』]")
# 인용어 후보 탈락 조건: 문장부호/공백(=문장), 제어코드(&R/#Y 등 색·특수 지시)
_TERM_NOISE_RE = re.compile(r"[。！？!?、\s　]|&[A-Za-z]|#[0-9A-Za-z]")


def _mine_quoted_terms(free_vals: List[str]) -> set:
    """자유 텍스트에서 「」『』 인용 단어를 채굴해 word 후보로. 2회+ 등장만.
    식별자·화자에 안 잡히는 본문 속 고유명사(鬼杜若 등)를 건지는 경로."""
    cnt: Counter = Counter()
    for v in free_vals:
        for m in _QUOTED_RE.findall(_VAR_RE.sub("", v)):
            if not _TERM_NOISE_RE.search(m):
                cnt[m] += 1
    return {t for t, c in cnt.items() if c >= 2}


# 빈출어 채굴: 가타카나 연속 3자+ / 한자 연속 2자+ / 한자+호칭(さん·ちゃん·くん).
# 목표 예시(2026-07-04 사용자 지정): 半熟·醤油·親父(한자), マヨラー·マヨネーズ(가타카나),
# 娘さん(호칭). 様·殿은 貴様·同様 오탐이 나와 호칭 규칙에서 제외(親父 등 본체는 한자 규칙이 잡음).
_KATA_RE = re.compile(r"[ァ-ヴー]{3,}")
_KANJI_RE = re.compile(r"[一-龥]{2,}")
_HONOR_RE = re.compile(r"[一-龥]{1,4}(?:さん|ちゃん|くん)")
_MINE_CAP = 200          # 대형 시나리오에서 후보 폭주 방지 (빈도순 상위만)


def _mine_frequent_terms(free_vals: List[str], min_units: int = 3) -> set:
    """여러 유닛에 반복 등장하는 연속어를 단어 후보로 채굴.
    같은 유닛 안 중복은 1로 세고(유닛 수 기준), 가타카나·한자 연속어는
    min_units 유닛+, 호칭 붙은 인물어는 2유닛+ 면 후보. 일반어/고유명사는
    기계적으로 구분하지 않는다 — 빈도순 정렬로 노출하고 선택은 사용자 몫."""
    cnt: Counter = Counter()
    honor: set = set()
    for v in free_vals:
        v2 = _VAR_RE.sub("", v)
        hon = set(_HONOR_RE.findall(v2))
        honor |= hon
        for m in set(_KATA_RE.findall(v2)) | set(_KANJI_RE.findall(v2)) | hon:
            cnt[m] += 1
    picked = [(t, c) for t, c in cnt.items()
              if c >= (2 if t in honor else min_units)]
    picked.sort(key=lambda x: -x[1])
    return {t for t, _c in picked[:_MINE_CAP]}


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
    for rel, sid, disp, _field, ko in index:
        hit = (disp.strip() == jp_s) if exact else (jp in disp)
        if hit:
            prev = disp.replace("\n", " ").strip()
            out.append({"rel": rel, "sid": sid, "preview": prev[:60],
                        "ko": ko.replace("\n", " ").strip()[:100]})
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
    gl = load_global() if global_enabled(proj) else {}

    def entry(jp, count, exact):
        return {
            "jp": jp, "count": count, "ko": saved.get(jp, ""),
            "global_ko": gl.get(jp.strip(), ""),   # 공용 용어 번역(프로젝트 미입력 시 적용됨)
            "is_identifier": _clean_term(jp) in ids,
            "occurrences": _occurrences(index, jp, exact=exact),
        }

    # ── exact: 동일 자유텍스트 값 2회+ ──
    # 값별로 어디에 쓰였는지(#text=본문 문장 / @name=선택지 버튼 라벨) 집계해
    # UI 가 "문장/선택지" 라벨을 달 수 있게 한다. 둘 다면 둘 다 담긴다.
    field_kinds: Dict[str, set] = {}
    for _rel, _sid, disp, field, _ko in index:
        v = disp.strip()
        if v:
            field_kinds.setdefault(v, set()).add(
                "choice" if field.startswith("@") else "text")
    cnt = Counter(v.strip() for v in free_vals if v.strip())
    exact = []
    for v, c in cnt.most_common():
        if c >= 2 and len(v) <= 30 and not _is_variable_ref(v):
            e = entry(v, c, True)
            e["kinds"] = sorted(field_kinds.get(v, set()))
            exact.append(e)

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
                    and not _is_system_name(sp) \
                    and not any(c in sp for c in " 　\t"):
                cand.add(sp)     # 공백 포함 = 이름이 아니라 문장(화자 오탐 방어)
    # 공용 용어 중 이 시나리오 본문에 실제 등장하는 것도 후보로 (적용 상태 확인용)
    for t in gl:
        if len(t) >= 2:
            cand.add(t)
    # 본문 속 「」『』 인용어 — 식별자/화자 어디에도 없는 고유명사를 채굴
    mined = set()
    for t in _mine_quoted_terms(free_vals):
        if not _is_structural_id(t) and not _is_system_name(t):
            mined.add(t)
    # 본문 빈출어(가타카나·한자 연속어·호칭 인물어) — 半熟/醤油/娘さん 류
    mined |= _mine_frequent_terms(free_vals)
    mined -= cand
    # 실제 '표시 텍스트'에 등장하는 것만 용어로 센다(같은 문자열이 표시 텍스트면 남긴다):
    #  · 변수 참조($..$ / %..%) 내부는 제외 — 토큰 안 substring(二人称 등)이 용어로 잡히는 것 방지
    #  · 그 후에도 백슬래시가 남는 값(パッケージ\… 같은 시스템 경로)은 표시 텍스트가 아니므로 제외
    disp_vals = []
    for v in free_vals:
        v2 = _VAR_RE.sub("", v)
        if "\\" not in v2:
            disp_vals.append(v2)
    joined = "\n".join(disp_vals)
    # 채굴 조각이 항상 더 긴 후보 안에서만 등장하면 제외 — ミューゼル卿만 쓰이는데
    # 가타카나 조각 ミューゼル 이 따로 잡히는 것 방지. (醤油처럼 단독 등장이 있으면
    # 醤油派 와 별개로 유지. 긴 후보 등장을 마스킹한 뒤 남은 단독 등장으로 판정)
    allc = cand | mined
    for t in sorted(mined, key=len):
        masked = joined
        for t2 in allc:
            if t2 is not t and t2 != t and t in t2:
                masked = masked.replace(t2, "\x00")
        if t not in masked:
            mined.discard(t)
    cand |= mined
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
    """exact 용어: 동일 자유텍스트 값 전부에 ko 를 일괄 적용. 적용 건수 반환.
    완성된 번역(가나 없음 또는 명시 완료)은 덮어쓰지 않는다 — 빈칸·부분 번역만."""
    from . import extract
    proj.setdefault("terms", {})[jp] = ko
    n = 0
    for f in proj["files"].values():
        for u in f["units"]:
            if u["kind"] != "free" \
                    or textcodec.decode_field(u["field"], u["jp"]).strip() != jp.strip():
                continue
            cur = textcodec.decode_field(u["field"], u.get("ko", ""))
            if cur and (u.get("force_done")
                        or not extract.is_partial_ko(
                            textcodec.decode_field(u["field"], u["jp"]), cur)):
                continue                    # 완료 번역 보존
            # #text 만 이스케이프, 속성(@name)은 raw
            u["ko"] = textcodec.encode_field(u["field"], ko)
            n += 1
    return n


def set_word(proj: Dict[str, Any], jp: str, ko: str) -> None:
    proj.setdefault("terms", {})[jp] = ko


def apply_word_to_existing(proj: Dict[str, Any], jp: str, ko: str) -> int:
    """단어 용어의 번역 입력 시, 번역칸(ko)에 "아직 남아 있는 원문 단어"를 즉시 치환.

    대상 = ko 가 있고 그 안에 jp 단어가 그대로 남은 유닛(🈁 부분 번역의 잔재).
    완성된 한국어 번역에는 원문 단어가 남아 있지 않으므로 자연히 건드리지 않고,
    명시 완료(force_done)·읽기전용(control)은 보호한다. 빈칸은 초안 생성 몫."""
    jp = (jp or "").strip()
    ko = (ko or "").strip()
    if not jp or not ko:
        return 0
    n = 0
    for f in proj["files"].values():
        for u in f["units"]:
            if u["kind"] != "free" or u.get("control") or u.get("force_done"):
                continue
            cur = textcodec.decode_field(u["field"], u.get("ko", ""))
            if cur and jp in cur:
                u["ko"] = textcodec.encode_field(u["field"], cur.replace(jp, ko))
                n += 1
    return n


def reapply_terms_to_existing(proj: Dict[str, Any], dry: bool = False) -> int:
    """모든 유효 용어(공용+프로젝트)를 "번역칸에 남아 있는 원문 단어"에 일괄 치환.

    공용 용어집 도입 전에 만든 혼합 초안/부분 번역의 잔존 원문 소급 적용용.
    완성 한국어 번역에는 원문 단어가 없으므로 자연히 안 건드리고,
    명시 완료(force_done)·읽기전용(control)은 보호. dry=True 면 대상 수만 센다."""
    items = sorted(effective_terms(proj).items(), key=lambda kv: -len(kv[0]))
    if not items:
        return 0
    n = 0
    for f in proj["files"].values():
        for u in f["units"]:
            if u["kind"] != "free" or u.get("control") or u.get("force_done"):
                continue
            cur = textcodec.decode_field(u["field"], u.get("ko", ""))
            if not cur:
                continue
            masked, holds = _protect_vars(cur)   # $..$ / %..% 보호
            new = masked
            for tj, tk in items:
                if tj in new:
                    new = new.replace(tj, tk)
            new = _restore_vars(new, holds)
            if new != cur:
                n += 1
                if not dry:
                    u["ko"] = textcodec.encode_field(u["field"], new)
    return n


def term_mismatches(proj: Dict[str, Any], cap: int = 300) -> List[dict]:
    """용어 불일치 검사: 원문에 용어가 있는데 번역문에 그 한국어 표기가 없는
    완성 번역 목록 — 공용 용어집 도입 전의 "옛 표기" 발견용.

    원문 단어가 번역문에 그대로 남은 것(부분 번역)은 재적용 대상이므로 제외.
    무시 목록(proj["term_check_ignores"] = {"rows": ["rel|sid|용어"], "terms": [용어]})에
    든 것도 제외 — 오탐(以上 의 문법적 쓰임 등)을 치우는 용도.
    반환: [{rel, sid, term, term_ko, jp, ko}] (문장·용어당 1행)."""
    terms = effective_terms(proj)
    ig = proj.get("term_check_ignores") or {}
    ig_rows = set(ig.get("rows") or [])
    ig_terms = set(ig.get("terms") or [])
    for t in ig_terms:
        terms.pop(t, None)
    if not terms:
        return []
    out: List[dict] = []
    for rel, f in proj["files"].items():
        for u in f["units"]:
            if u["kind"] != "free" or u.get("control"):
                continue
            ko = textcodec.decode_field(u["field"], u.get("ko", ""))
            if not ko.strip():
                continue
            jp = textcodec.decode_field(u["field"], u["jp"])
            flat_jp = jp.replace("\n", " ").strip()
            flat_ko = ko.replace("\n", " ").strip()
            # 긴 용어부터 검사하고 매칭된 자리는 마스킹 — 依頼人 이 걸린 자리에서
            # 부분 문자열 依頼 가 또 걸리는 중복 방지 (긴 용어만 보고)
            work = jp
            for tj, tk in sorted(terms.items(), key=lambda kv: -len(kv[0])):
                if tj not in work:
                    continue
                hit = tk not in ko and tj not in ko \
                    and f"{rel}|{u['id']}|{tj}" not in ig_rows
                work = work.replace(tj, "\x00" * len(tj))
                if hit:
                    # 발췌는 용어 등장 위치를 중심으로 (앞부분만 자르면 용어가 안 보임)
                    i = flat_jp.find(tj)
                    s = max(0, i - 18)
                    ex = flat_jp[s:s + 70]
                    if s > 0:
                        ex = "…" + ex
                    if s + 70 < len(flat_jp):
                        ex += "…"
                    out.append({
                        "rel": rel, "sid": u["id"], "term": tj, "term_ko": tk,
                        "jp": ex, "ko": flat_ko[:70],
                    })
                    if len(out) >= cap:
                        return out
    return out


def apply_words_to_drafts(proj: Dict[str, Any], only_untranslated: bool = True) -> int:
    """word 용어들을 자유 텍스트에 substring 치환해 초안(ko) 생성. 변경 건수 반환.
    이미 번역된 유닛은 기본적으로 건드리지 않는다. 공용 용어집(켜져 있으면) 포함."""
    terms = effective_terms(proj)
    # 긴 용어 먼저 치환(부분겹침 방지)
    items = sorted(terms.items(), key=lambda kv: -len(kv[0]))
    n = 0
    for f in proj["files"].values():
        for u in f["units"]:
            if u["kind"] != "free" or u.get("control"):
                continue
            if only_untranslated and u.get("ko"):
                continue
            disp = textcodec.decode_field(u["field"], u["jp"])
            masked, holds = _protect_vars(disp)   # $..$ / %..% 안은 치환에서 보호(쿠폰·변수 참조 보존)
            new = masked
            for tj, tk in items:
                if tj and tj in new:
                    new = new.replace(tj, tk)
            new = _restore_vars(new, holds)
            if new != disp:
                u["ko"] = textcodec.encode_field(u["field"], new)   # #text 만 이스케이프, 속성은 raw
                n += 1
    return n

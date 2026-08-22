# -*- coding: utf-8 -*-
"""한국어 조사 보정 — 받침 판별 + 조사 쌍표 + 최장일치. 순수 함수, stdlib only.

왜 필요한가: 자동번역은 용어집 단어를 placeholder(안정 음차 인명)나 DeepL glossary 로 넣는데,
그 자리에 사용자 한국어 용어를 되돌리면 placeholder 기준으로 붙어 있던 조사가 어긋난다
(예: 「히카루를」 → 「륜를」). 받침은 유니코드 계산으로 정확히 알 수 있으므로,
**용어 경계 바로 뒤의 조사**(A등급)는 자동으로 고치고, 그 밖의 자리는 제안만 한다.

등급
  A  치환 자리 — 경계를 아는 곳. 자동 수정 (fix_after_terms).
  B  이름표 — 용어집 한국어 값과 어간이 일치. 기본 선택(단, 더 긴 이름의 앞머리일 수 있으면 해제).
  C  문서 훑기 — 그 밖. 문서 안 쓰임(어간 단독 등장·서로 다른 조사 2개 이상)이 있으면
     제안하지 않고, 사전(app/dict/korean-surface.txt)에 있는 어절이면 낱말로 보고 포기.

기조: 원문에 없는 조사를 새로 넣지 않는다 — 있는 조사를 맞는 형태로 바꿀 뿐.
"""
from __future__ import annotations
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

_HANGUL_BASE = 0xAC00
_HANGUL_LAST = 0xD7A3
_RIEUL = 8          # 종성 인덱스 8 = ㄹ


def jongseong(ch: str) -> int:
    """한글 음절의 종성 인덱스(0=받침 없음, 1~27). 한글 음절이 아니면 -1."""
    if not ch:
        return -1
    cp = ord(ch[-1])
    if _HANGUL_BASE <= cp <= _HANGUL_LAST:
        return (cp - _HANGUL_BASE) % 28
    return -1


@dataclass(frozen=True)
class Pair:
    id: str
    jong: str            # 받침 있을 때
    nojong: str          # 받침 없을 때
    rieul: str = ""      # ㄹ 받침 예외형(으로/로)
    risky: str = ""      # 위험한 수정 방향: 'toJong' | 'toNoJong' | ''
    name_tail: bool = False   # 이름 뒤에 잘 붙어 오탐이 많은 쌍
    default_on: bool = False  # C등급에서 기본 선택


# 조사 쌍표 13쌍. risky = 그 방향으로 고치면 낱말을 깨뜨릴 확률이 큰 쪽
# (예: '이' 받침형은 "X이다/X이고"처럼 조사가 아닐 수 있어 toJong 이 위험).
PAIRS: Tuple[Pair, ...] = (
    Pair("을/를", "을", "를", risky="toJong", default_on=True),
    Pair("은/는", "은", "는", risky="toJong"),
    Pair("이/가", "이", "가", risky="toJong"),
    Pair("과/와", "과", "와", risky="toNoJong"),
    Pair("으로/로", "으로", "로", rieul="로", risky="toJong"),
    Pair("이라/라", "이라", "라", risky="toJong", name_tail=True),
    Pair("이랑/랑", "이랑", "랑", risky="toJong", name_tail=True),
    Pair("이나/나", "이나", "나", risky="toJong", name_tail=True),
    Pair("이든/든", "이든", "든", risky="toJong", name_tail=True),
    Pair("이며/며", "이며", "며", risky="toJong", name_tail=True),
    Pair("이야/야", "이야", "야", risky="toJong", name_tail=True),
    Pair("아/야", "아", "야", risky="toJong"),
    Pair("이여/여", "이여", "여", risky="toJong", name_tail=True),
)
_PAIR_BY_ID = {p.id: p for p in PAIRS}

# 표면형 → (쌍, 받침형인가). 긴 형태부터 보므로 '이라' 가 '라' 보다 먼저 걸린다.
_SURFACES: List[Tuple[str, Pair, bool]] = sorted(
    [(p.jong, p, True) for p in PAIRS] + [(p.nojong, p, False) for p in PAIRS]
    + [(p.rieul, p, False) for p in PAIRS if p.rieul and p.rieul != p.nojong],
    key=lambda t: -len(t[0]))

# 이라/라 뒤에만 허용하는 꼬리 1자(「X이라고」「X이라며」). 다른 쌍에 허용하면
# 「나오이고」(이다+고) 를 「나오가고」로 망가뜨린다.
_TAILS = frozenset("고는며서도만")
_TAIL_PAIR = "이라/라"

_TAIL_PUNCT = re.compile(r"[.,!?;:…·。，、)\"'”’」』】\]}）]+$")
_LEAD_BRACKET = re.compile(r"^[(\"'“‘「『【\[{（<]+")
_TRAIL_BRACKET = re.compile(r"[)\"'”’」』】\]}）>]+$")
_WORD = re.compile(r"\S+")


def correct_form(pair: Pair, jong_idx: int) -> str:
    """어간의 종성 인덱스에 맞는 조사 형태."""
    if jong_idx <= 0:
        return pair.nojong
    if jong_idx == _RIEUL and pair.rieul:
        return pair.rieul
    return pair.jong


def _match_surface(core: str):
    """core 끝에서 조사 표면형을 최장일치로 찾는다. (form, pair, tailed) 또는 None."""
    for form, pair, _ in _SURFACES:
        if len(core) > len(form) and core.endswith(form):
            return form, pair, False
    # 이라/라 한정 꼬리 1자 허용
    if len(core) >= 2 and core[-1] in _TAILS:
        stem = core[:-1]
        p = _PAIR_BY_ID[_TAIL_PAIR]
        for form in (p.jong, p.nojong):
            if len(stem) > len(form) and stem.endswith(form):
                return form, p, True
    return None


@dataclass
class Fix:
    base: str            # 어간(괄호 벗긴 것)
    frm: str             # 현재 조사
    to: str              # 맞는 조사
    pair_id: str
    direction: str       # 'toJong' | 'toNoJong'
    risky: bool
    tailed: bool
    start: int           # 어절 안에서 조사가 시작하는 오프셋
    end: int             # 조사 끝 오프셋(배타)


def analyze_word(word: str, dictionary: Optional["Dictionary"] = None) -> Optional[Fix]:
    """어절 하나를 보고 조사 불일치가 있으면 Fix, 아니면 None.
    사전이 주어지면 '어간+조사' 또는 어절 전체가 표제어일 때 낱말로 보고 포기한다."""
    core = _TAIL_PUNCT.sub("", word)
    core = _TRAIL_BRACKET.sub("", core)
    hit = _match_surface(core)
    if not hit:
        return None
    form, pair, tailed = hit
    tail_len = 1 if tailed else 0
    base_end = len(core) - len(form) - tail_len
    base = core[:base_end]
    base = _TRAIL_BRACKET.sub("", _LEAD_BRACKET.sub("", base))   # (유나)을 / 「유나」를
    if not base:
        return None
    j = jongseong(base[-1])
    if j < 0:
        return None                 # 어간 끝이 한글 음절이 아니면 받침을 알 수 없다
    if dictionary is not None and (dictionary.has(base + form) or dictionary.has(core)):
        return None                 # 낱말(가을·사이·나라…)이지 조사가 아니다
    want = correct_form(pair, j)
    if want == form:
        return None
    direction = "toJong" if want == pair.jong else "toNoJong"
    return Fix(base=base, frm=form, to=want, pair_id=pair.id, direction=direction,
               risky=(pair.risky == direction), tailed=tailed,
               start=base_end, end=base_end + len(form))


# ── A등급: 용어 경계 뒤 조사 자동 수정 ──────────────────────────────────────

def _particle_after(text: str, pos: int):
    """text[pos:] 가 조사 표면형(+이라/라 꼬리)으로 시작하고 그 뒤가 어절 경계면
    (form, pair, tailed) 반환. 아니면 None."""
    rest = text[pos:]
    m = _WORD.match(rest)
    run = m.group(0) if m else ""
    run = _TAIL_PUNCT.sub("", _TRAIL_BRACKET.sub("", run))
    if not run:
        return None
    for form, pair, _ in _SURFACES:
        if run == form:
            return form, pair, False
    if len(run) >= 2 and run[-1] in _TAILS:
        p = _PAIR_BY_ID[_TAIL_PAIR]
        if run[:-1] in (p.jong, p.nojong):
            return run[:-1], p, True
    return None


def fix_after_terms(text: str, terms: Iterable[str]) -> str:
    """text 안의 각 용어 등장 자리 바로 뒤 조사를 용어의 받침에 맞춘다.
    용어 끝이 한글 음절이 아니면(변수·영문) 손대지 않는다. 긴 용어부터 처리해
    짧은 용어가 긴 용어의 일부로 두 번 걸리지 않게 한다."""
    if not text:
        return text
    done: List[Tuple[int, int]] = []   # 이미 손댄 용어 구간
    for term in sorted({t for t in terms if t}, key=len, reverse=True):
        j = jongseong(term[-1])
        if j < 0:
            continue
        i = 0
        while True:
            i = text.find(term, i)
            if i < 0:
                break
            end = i + len(term)
            if any(a <= i < b for a, b in done):
                i = end
                continue
            hit = _particle_after(text, end)
            if hit:
                form, pair, _ = hit
                want = correct_form(pair, j)
                if want != form:
                    text = text[:end] + want + text[end + len(form):]
                    delta = len(want) - len(form)
                    if delta:           # 뒤쪽 구간 오프셋 보정(으로↔로 처럼 길이가 달라질 때)
                        done = [(a + delta, b + delta) if a >= end else (a, b) for a, b in done]
            done.append((i, end))
            i = end
    return text


# ── B/C등급: 문서 훑기 제안 ────────────────────────────────────────────────

def build_evidence(texts: Iterable[str]) -> Dict[str, object]:
    """문서 자체를 근거 자료로: 단독 등장 어절 집합 + 어간→붙은 조사 집합."""
    words: Set[str] = set()
    stems: Dict[str, Set[str]] = {}
    for t in texts:
        for m in _WORD.finditer(t or ""):
            w = _TAIL_PUNCT.sub("", _TRAIL_BRACKET.sub("", m.group(0)))
            w = _LEAD_BRACKET.sub("", w)
            if not w:
                continue
            words.add(w)
            hit = _match_surface(w)
            if hit:
                form, _, tailed = hit
                base = w[:len(w) - len(form) - (1 if tailed else 0)]
                if base:
                    stems.setdefault(base, set()).add(form)
    return {"words": words, "stems": stems}


def _has_evidence(ev: Optional[Dict[str, object]], base: str) -> bool:
    if not ev:
        return False
    if base in ev["words"]:          # 어간이 그대로(조사 없이) 등장 → 낱말
        return True
    return len(ev["stems"].get(base, ())) >= 2   # 서로 다른 조사 2개 이상과 결합


def _is_name_prefix(base: str, names: Set[str]) -> bool:
    return any(n != base and n.startswith(base) for n in names)


def suggest(text: str, names: Optional[Set[str]] = None,
            dictionary: Optional["Dictionary"] = None,
            evidence: Optional[Dict[str, object]] = None,
            scan_all: bool = False) -> List[dict]:
    """text 의 어절을 훑어 조사 제안 목록을 만든다.
    names(이름표, NFC) 에 어간이 있으면 B등급, 그 밖은 scan_all 일 때만 C등급.
    반환: [{grade, base, from, to, pair, risky, preselected, start, end}] (text 오프셋)."""
    names = {unicodedata.normalize("NFC", n) for n in (names or set()) if n}
    out: List[dict] = []
    for m in _WORD.finditer(text or ""):
        fix = analyze_word(m.group(0), dictionary)
        if not fix:
            continue
        base = unicodedata.normalize("NFC", fix.base)
        if base in names:
            grade = "B"
            pre = not fix.tailed and not _is_name_prefix(base, names)
        else:
            if not scan_all:
                continue
            if _has_evidence(evidence, fix.base):
                continue
            grade = "C"
            pre = not fix.risky
        out.append({"grade": grade, "base": fix.base, "from": fix.frm, "to": fix.to,
                    "pair": fix.pair_id, "risky": fix.risky, "preselected": pre,
                    "start": m.start() + fix.start, "end": m.start() + fix.end})
    return out


def apply_fixes(text: str, fixes: List[dict]) -> str:
    """suggest() 결과 중 고른 것을 적용(뒤에서부터 치환해 오프셋 유지)."""
    for f in sorted(fixes, key=lambda x: -x["start"]):
        text = text[:f["start"]] + f["to"] + text[f["end"]:]
    return text


# ── 사전 가드 ───────────────────────────────────────────────────────────────

DICT_PATH = os.path.join(os.path.dirname(__file__), "dict", "korean-surface.txt")


class Dictionary:
    """표준국어대사전 표층형 목록(app/dict/korean-surface.txt, CC BY-SA 2.0 KR).
    처음 has() 를 부를 때 읽는다. 파일이 없으면 가드만 꺼지고(has 는 항상 False) 기능은 동작."""

    def __init__(self, path: str = DICT_PATH):
        self.path = path
        self._words: Optional[Set[str]] = None
        self.available = False

    def _load(self) -> None:
        self._words = set()
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    w = line.strip()
                    if w:
                        self._words.add(w)
            self.available = bool(self._words)
        except OSError:
            self.available = False

    def has(self, word: str) -> bool:
        if self._words is None:
            self._load()
        return unicodedata.normalize("NFC", word) in self._words

    @property
    def count(self) -> int:
        if self._words is None:
            self._load()
        return len(self._words)


_DICT: Optional[Dictionary] = None


def dictionary() -> Dictionary:
    global _DICT
    if _DICT is None:
        _DICT = Dictionary()
    return _DICT

# -*- coding: utf-8 -*-
"""
이벤트 콘텐츠 흐름을 따라가 각 대사(<Text>)의 '도달 조건'을 정확히 계산한다.

CardWirthPy 엔진 모델(src.zip cw/content.py·event.py 확인):
- <ContentsLine> 안 카드들은 순차 실행. 카드의 다음(get_children)은:
    · ContentsLine 안에서 다음 형제가 있으면 그 형제 1개
    · 없으면(라인 끝) 그 카드의 <Contents> 자식들
- 카드의 name = '직전 분기의 어느 출구로 도달했는지'.
    · ○ = 분기 성립, × = 불성립, 숫자 = 값 분기, "Default" = 그 외
- <Branch>: 결과에 맞는 name 의 자식으로 이동. 맞는 자식 없으면 그 경로 종료(IDX_TREEEND).
- 비분기 카드: name 무시하고 무조건 다음으로.
- <Link type="Start" link="X"> : <Start name="X"> 라인으로 점프(폴스루 없음).
- <Call type="Package"> : 다른 파일 호출 후 복귀 → 파일 내 흐름상 통과.

각 대사의 조건은 그 대사에 이르는 모든 경로 조건의 논리합(OR), 한 경로는 논리곱(AND).
=> clause = frozenset(조건문자열),  대사조건 = set(clause)  (DNF)
"""
from __future__ import annotations
import xml.etree.ElementTree as ET
from typing import Dict, List, Set, FrozenSet, Tuple

_TARGET_WHO = {"Random": "누군가", "Selected": "선택 PC", "Unselected": "비선택 PC",
               "Valued": "지정 PC", "Party": "누군가", "Npc": "NPC"}
_COUPON_LABEL = {
    "♀": "여성", "♂": "남성", "貧乳": "빈유", "虚乳": "절벽",
    "巨乳": "거유", "美形": "미형", "老人": "노인", "子供": "아이",
}
_MAX_CLAUSES = 48  # 경로 폭발 방지


def _clean_coupon(s: str) -> str:
    s = (s or "").strip().strip("\\n").strip()
    if s.startswith("＿"):
        s = s[1:]
    return s.strip("「」 ")


def _name_of(card: ET.Element) -> str:
    if card.tag == "ContentsLine":
        return (card[0].get("name", "") if len(card) else "")
    return card.get("name", "")


_KIND_KO = {
    "coupon": "쿠폰", "flag": "플래그", "step": "스텝", "random": "랜덤",
    "ability": "능력 판정", "level": "레벨 판정", "partynumber": "인원 수",
    "select": "선택지", "cast": "동행 NPC", "beast": "소환수",
    "area": "현재 지역", "isbattle": "전투 중", "gossip": "소문",
}


def _branch_who_what(card: ET.Element):
    """(kind, who, what) — 분기 대상·종류. who=대상 라벨, what=쿠폰/플래그/스텝 이름."""
    t = (card.get("type") or "").lower()
    if t == "coupon":
        coup = _clean_coupon(card.get("coupon", ""))
        return ("coupon", _TARGET_WHO.get(card.get("targets", ""), ""),
                _COUPON_LABEL.get(coup, coup))
    if t == "flag":
        return ("flag", "", card.get("flag") or "")
    if t in ("step", "multistep"):
        return ("step", "", card.get("step") or "")
    if t == "random":
        return ("random", "", (card.get("percent", "") or "") + "%")
    if t == "gossip":
        return ("gossip", "", card.get("gossip") or "")
    return (t or "branch", "", "")


def _edge_cond(card: ET.Element, child_name: str):
    """분기 card → 자식(child_name) 도달 조건을 구조화 튜플로.
    (kind, who, what, pol). pol ∈ have/not/true/false/yes/no/else/'=값'."""
    kind, who, what = _branch_who_what(card)
    invert = (card.get("invert") == "True")
    if child_name in ("○", "×"):
        success = (child_name == "○")
        if invert:
            success = not success
        if kind == "coupon":
            pol = "have" if success else "not"
        elif kind == "flag":
            pol = "true" if success else "false"
        else:
            pol = "yes" if success else "no"
    elif child_name == "Default":
        pol = "else"
    else:
        pol = "=" + child_name
    return (kind, who, what, pol)


def _is_branch(card: ET.Element) -> bool:
    return card.tag == "Branch"


def compute_file_conditions(root: ET.Element) -> Dict[int, dict]:
    """파일 루트 → {id(Text요소): {"must":[...], "any":[[...],...]}} 매핑.
    must = 모든 경로 공통(AND) 조건, any = 경로마다 갈리는 부분(OR; 각 항목은 AND 묶음)."""
    text_conditions: Dict[int, dict] = {}
    for events in root.iter("Events"):
        for event in events.findall("Event"):
            _process_event(event, text_conditions)
    return text_conditions


def _process_event(event: ET.Element, out: Dict[int, List[str]]) -> None:
    # Start 이름 → ContentsLine (Link/Call 점프 대상)
    trees: Dict[str, ET.Element] = {}
    lines: List[ET.Element] = []
    for cl in event.iter("ContentsLine"):
        lines.append(cl)
        if len(cl) and cl[0].tag == "Start":
            nm = cl[0].get("name")
            if nm and nm not in trees:
                trees[nm] = cl
    if not lines:
        return

    # 부모/인덱스 맵 (형제 이동용)
    parent: Dict[int, ET.Element] = {}
    for p in event.iter():
        for c in p:
            parent[id(c)] = p

    # 카드별 도달 조건(DNF) — id(card) -> set of frozenset
    reach: Dict[int, Set[FrozenSet[str]]] = {}

    def card_of(el: ET.Element) -> ET.Element:
        """el 의 컨테이너 안 직계 카드(=Talk/Branch/Link 등) 자신."""
        return el

    def successors(card: ET.Element) -> List[Tuple[ET.Element, str]]:
        """(다음 카드, 조건라벨 or '') 목록. Link 점프 포함."""
        # Link type=Start → 그 Start 라인의 첫 카드로 점프
        if card.tag == "Link" and card.get("type") == "Start":
            tgt = trees.get(card.get("link", ""))
            if tgt is not None and len(tgt):
                return [(tgt[0], None)]
            return []
        # 다음 후보: 라인 내 다음 형제 1개, 없으면 자기 <Contents> 자식들
        par = parent.get(id(card))
        cands: List[ET.Element] = []
        if par is not None and par.tag == "ContentsLine":
            idx = next((k for k, c in enumerate(par) if c is card), None)
            if idx is not None and idx + 1 < len(par):
                cands = [par[idx + 1]]
        if not cands:
            cont = card.find("Contents")
            if cont is not None:
                cands = list(cont)
        # 분기면 결과(name)별 조건 튜플, 비분기면 무조건(None)
        res = []
        if _is_branch(card):
            for c in cands:
                nm = _name_of(c)
                if nm in ("○", "×", "Default") or _isnum(nm):
                    res.append((c, _edge_cond(card, nm)))
                # 분기인데 매칭 안 되는 name → 그 출구는 막힘(경로 종료)
        else:
            for c in cands:
                res.append((c, None))
        return res

    def entry_card(line: ET.Element) -> ET.Element:
        return line[0] if len(line) else line

    # 시드: 이벤트의 첫 ContentsLine (메인 진입). 나머지는 Link 로만 도달.
    seed = lines[0]
    start = entry_card(seed)
    reach.setdefault(id(start), set()).add(frozenset())
    elem_by_id = {id(start): start}
    worklist = [start]
    while worklist:
        card = worklist.pop()
        clauses = reach.get(id(card), set())
        for nxt, cond in successors(card):
            if nxt is None:
                continue
            elem_by_id[id(nxt)] = nxt
            if cond is not None:
                newcl = {c | {cond} for c in clauses}
            else:
                newcl = set(clauses)
            cur = reach.setdefault(id(nxt), set())
            before = len(cur)
            cur |= newcl
            if len(cur) > _MAX_CLAUSES:
                # 너무 많으면 공통만 유지(과근사) — 폭발 방지
                common = frozenset.intersection(*cur) if cur else frozenset()
                cur.clear()
                cur.add(common)
            if len(cur) != before:           # 변경됐으면 다시 전파
                worklist.append(nxt)

    # 각 Talk(카드) 의 조건 → 그 안의 모든 Text 에 부여
    for cid, clauses in reach.items():
        card = elem_by_id.get(cid)
        if card is None or card.tag != "Talk":
            continue
        info = _summarize(clauses)
        if not info["must"] and not info["any"]:
            continue
        for txt in card.iter("Text"):
            out[id(txt)] = info


def _isnum(s: str) -> bool:
    try:
        int(s)
        return True
    except Exception:
        return False


def _summarize(clauses: Set[FrozenSet[tuple]]) -> dict:
    """DNF → {"must":[공통 AND 조건], "any":[[갈리는 AND 묶음],...]}.
    조건은 [kind, who, what, pol] 배열(표시 포맷·그룹화는 프런트가 담당)."""
    clauses = {c for c in clauses}
    if not clauses or clauses == {frozenset()}:
        return {"must": [], "any": []}
    common = frozenset.intersection(*clauses) if clauses else frozenset()
    must = [list(c) for c in sorted(common)]
    # 단일 경로면 갈리는 부분이 곧 must 에 흡수됨
    if len(clauses) == 1:
        only = next(iter(clauses))
        return {"must": [list(c) for c in sorted(only)], "any": []}
    # 여러 경로: 공통 외 나머지를 경로별 묶음으로
    anyc = []
    seen = set()
    for c in clauses:
        rest = tuple(sorted(c - common))
        if rest and rest not in seen:
            seen.add(rest)
            anyc.append([list(x) for x in rest])
    return {"must": must, "any": anyc}

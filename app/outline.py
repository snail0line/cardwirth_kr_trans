# -*- coding: utf-8 -*-
"""
이벤트 콘텐츠를 진행(트리) 순서대로 들여쓰기한 아웃라인 생성 — CWXEditor 의
'어디 나갔다가(패키지 콜/링크) 들어왔다가' 보기와 같은 흐름을 한 파일 안에서 표시.

각 카드 = 한 줄. 들여쓰기 depth = 콘텐츠 트리 중첩(분기 등).
대사(Talk) 줄은 번역 유닛 id(sid) 를 달아 두어 프런트가 그 자리에서 번역하게 한다.
패키지 콜/링크 줄은 대상 파일(rel)을 달아 클릭 이동 가능.
"""
from __future__ import annotations
import xml.etree.ElementTree as ET
from typing import Dict, List

from . import xmlio, context, textcodec

# 카드로 취급할 태그(이 외 Dialogs/Property/RequiredCoupons 등은 구조용 → 무시)
_CARD_TAGS = {
    "Start", "Talk", "Branch", "Link", "Call", "Change", "Effect", "Sound",
    "PlayBgm", "Wait", "Elapse", "Set", "End", "Get", "Lose", "Show", "Hide",
    "Cast", "Reverse", "Redisplay", "Substitute", "Battle", "Check", "Talk2",
}

_TARGET_WHO = {"Random": "파티 중 누군가", "Selected": "선택 PC",
               "Unselected": "비선택 PC", "Valued": "지정 PC", "Party": "파티 전원"}


def _clean(s: str) -> str:
    s = (s or "").strip().strip("\\n").strip()
    if s.startswith("＿"):
        s = s[1:]
    return s.strip("「」 ")


def _talk_preview(card: ET.Element) -> str:
    for t in card.iter("Text"):
        disp = textcodec.decode(t.text or "")
        disp = disp.replace("\n", " ").strip()
        if disp:
            return disp[:40]
    return ""


def _describe(card: ET.Element, resolve: Dict) -> dict:
    """카드 → {kind, desc, target_rel?, target_name?}. resolve: (종류,id)->(rel,name)."""
    tag = card.tag
    t = card.get("type")
    if tag == "Start":
        return {"kind": "start", "desc": card.get("name", "") or "(시작)"}
    if tag in ("Talk", "Talk2"):
        return {"kind": "talk", "desc": ""}
    if tag == "Branch":
        if t == "Coupon":
            who = _TARGET_WHO.get(card.get("targets", ""), "")
            coup = _clean(card.get("coupon", ""))
            return {"kind": "branch",
                    "desc": f"「{coup}」 칭호 분기" + (f" ({who})" if who else "")}
        if t == "Flag":
            return {"kind": "branch", "desc": f"플래그 「{card.get('flag','')}」 분기"}
        if t in ("Step", "MultiStep"):
            return {"kind": "branch", "desc": f"스텝 「{card.get('step','')}」 분기"}
        return {"kind": "branch", "desc": f"{t or ''} 분기"}
    if tag == "Call":
        if t == "Package":
            rel, name = resolve.get(("Package", (card.get("call") or "").strip()), (None, card.get("call")))
            return {"kind": "call", "desc": f"패키지 「{name}」 호출", "target_rel": rel}
        if t == "Start":
            return {"kind": "call", "desc": f"스타트 「{card.get('call','')}」 호출(복귀)"}
        return {"kind": "call", "desc": "호출"}
    if tag == "Link":
        if t == "Package":
            rel, name = resolve.get(("Package", (card.get("link") or "").strip()), (None, card.get("link")))
            return {"kind": "link", "desc": f"패키지 「{name}」로 이동", "target_rel": rel}
        if t == "Start":
            return {"kind": "link", "desc": f"스타트 「{card.get('link','')}」로 점프(파일 내)"}
        return {"kind": "link", "desc": "이동"}
    if tag == "Change" and t == "Area":
        rel, name = resolve.get(("Area", (card.get("id") or "").strip()), (None, card.get("id")))
        return {"kind": "change", "desc": f"에리어 「{name}」로 이동", "target_rel": rel}
    if tag == "End":
        return {"kind": "end", "desc": "이벤트 종료"}
    if tag in ("PlayBgm",) or (tag == "Effect" and t in ("PlayBgm", "Bgm")):
        return {"kind": "misc", "desc": "BGM"}
    if tag == "Sound" or (tag == "Effect" and t == "Sound"):
        return {"kind": "misc", "desc": "효과음"}
    if tag in ("Wait", "Elapse"):
        return {"kind": "misc", "desc": "대기"}
    if tag == "Set":
        return {"kind": "misc", "desc": f"{t or ''} 설정"}
    return {"kind": "misc", "desc": tag}


def build_outline(root: ET.Element, resolve: Dict[tuple, tuple]) -> List[dict]:
    """파일 루트 → 카드 줄 목록(진행/트리 순서, depth 포함).
    대사 줄엔 unit_ids(번역 유닛 sid) 부여."""
    # Text요소 → 유닛 sid 매핑(번역칸 연결용)
    text_sid: Dict[int, int] = {}
    for sid, el, _anc, slot in xmlio.iter_slots(root):
        if slot.kind == "free" and slot.tag == "Text" and slot.field == "#text":
            text_sid[id(el)] = sid

    out: List[dict] = []

    def walk(container: ET.Element, depth: int):
        for child in container:
            if child.tag == "ContentsLine":
                walk(child, depth)
                continue
            if child.tag not in _CARD_TAGS:
                continue
            entry = _describe(child, resolve)
            entry["depth"] = depth
            if entry["kind"] == "talk":
                sids = [text_sid[id(t)] for t in child.iter("Text") if id(t) in text_sid]
                entry["unit_ids"] = sids
                entry["preview"] = _talk_preview(child)
                if not sids:
                    continue  # 번역할 텍스트 없는 Talk 은 생략
            out.append(entry)
            cont = child.find("Contents")
            if cont is not None:
                walk(cont, depth + 1)

    for events in root.iter("Events"):
        for event in events.findall("Event"):
            cont = event.find("Contents")
            if cont is not None:
                walk(cont, 0)
    return out


def build_resolve(scenario_dir: str) -> Dict[tuple, tuple]:
    """시나리오 전체에서 (종류, id) → (rel, 표시이름) 맵. Call/Link/Change 대상 해석용."""
    import os
    resolve: Dict[tuple, tuple] = {}
    for rel in xmlio.find_xml_files(scenario_dir):
        try:
            root = ET.parse(os.path.join(scenario_dir, rel)).getroot()
        except Exception:
            continue
        if root.tag in ("Package", "Area", "Battle"):
            pid = (root.findtext("Property/Id") or "").strip()
            name = (root.findtext("Property/Name") or "").strip() \
                or os.path.splitext(os.path.basename(rel))[0]
            if pid:
                resolve[(root.tag, pid)] = (rel, name)
    return resolve

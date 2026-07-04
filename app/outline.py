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


class NameDisplay:
    """흐름 보기/흐름 패널의 이름 라벨 번역 표시 (툴 안에서만 — export 무관).

    우선순위: ①정식 번역(식별자 glossary ko / 씬 Name 유닛 ko — export 에도 반영되는 것)
             ②proj["tool_names"] 의 툴 전용 표시명
             ③용어집(terms) 번역 — ＿접두사 뗀 이름이 단어 용어로 번역돼 있으면 사용
               (예: 단어 사전에서 マヨネーズ派→마요네즈파 → ＿マヨネーズ派 쿠폰 라벨에 적용)
             ④원문."""

    def __init__(self, proj):
        self.tool = (proj or {}).get("tool_names", {}) or {}
        self.terms = {k.strip(): v for k, v in ((proj or {}).get("terms") or {}).items() if v}
        self.gl = {}      # (etype, jp) -> ko
        self.scene = {}   # rel -> 번역된 씬(Area/Package/Battle) 이름
        if not proj:
            return
        for g in proj.get("glossary", {}).values():
            if g.get("ko"):
                self.gl[(g["etype"], (g["jp"] or "").strip())] = g["ko"]
        for rel, f in proj.get("files", {}).items():
            for u in f["units"]:
                if u["kind"] == "free" and u["tag"] == "Name" \
                        and u.get("parent") == "Property" and u.get("ko"):
                    ko = textcodec.decode_field(u["field"], u["ko"]).strip()
                    if ko:
                        self.scene[rel] = ko
                    break

    def name(self, raw, etype=None) -> str:
        raw_s = (raw or "").strip()
        if etype and (etype, raw_s) in self.gl:
            return self.gl[(etype, raw_s)]
        if raw_s in self.tool:
            return self.tool[raw_s]
        c = _clean(raw_s)      # ＿접두사·「」 뗀 이름으로 용어집(단어) 번역 조회
        if c in self.terms:
            return self.terms[c]
        return raw_s

    def scene_name(self, rel, raw) -> str:
        if rel and rel in self.scene:
            return self.scene[rel]
        raw_s = (raw or "").strip()
        return self.tool.get(raw_s) or self.terms.get(raw_s) or (raw or "")


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


def _describe(card: ET.Element, resolve: Dict, nd: NameDisplay) -> dict:
    """카드 → {kind, desc, target_rel?, name?}. resolve: (종류,id)->(rel,name).
    이름이 붙는 줄엔 name(원문)을 함께 실어 프런트가 툴 전용 표시명을 편집하게 한다.
    desc 의 이름 부분은 nd 로 번역 표시(툴 안에서만 — export 무관)."""
    tag = card.tag
    t = card.get("type")
    if tag == "Start":
        raw = card.get("name", "")
        return {"kind": "start", "desc": nd.name(raw) or "(시작)", "name": raw}
    if tag in ("Talk", "Talk2"):
        return {"kind": "talk", "desc": ""}
    if tag == "Branch":
        if t == "Coupon":
            who = _TARGET_WHO.get(card.get("targets", ""), "")
            raw = card.get("coupon", "")
            coup = _clean(nd.name(raw, "Coupon"))
            return {"kind": "branch", "name": raw,
                    "desc": f"「{coup}」 칭호 분기" + (f" ({who})" if who else "")}
        if t == "Flag":
            raw = card.get("flag", "")
            return {"kind": "branch", "name": raw,
                    "desc": f"플래그 「{nd.name(raw, 'Flag')}」 분기"}
        if t in ("Step", "MultiStep"):
            raw = card.get("step", "")
            return {"kind": "branch", "name": raw,
                    "desc": f"스텝 「{nd.name(raw, 'Step')}」 분기"}
        return {"kind": "branch", "desc": f"{t or ''} 분기"}
    if tag == "Call":
        if t == "Package":
            rel, name = resolve.get(("Package", (card.get("call") or "").strip()), (None, card.get("call")))
            return {"kind": "call", "name": name,
                    "desc": f"패키지 「{nd.scene_name(rel, name)}」 호출", "target_rel": rel}
        if t == "Start":
            raw = card.get("call", "")
            return {"kind": "call", "name": raw,
                    "desc": f"스타트 「{nd.name(raw)}」 호출(복귀)"}
        return {"kind": "call", "desc": "호출"}
    if tag == "Link":
        if t == "Package":
            rel, name = resolve.get(("Package", (card.get("link") or "").strip()), (None, card.get("link")))
            return {"kind": "link", "name": name,
                    "desc": f"패키지 「{nd.scene_name(rel, name)}」로 이동", "target_rel": rel}
        if t == "Start":
            raw = card.get("link", "")
            return {"kind": "link", "name": raw,
                    "desc": f"스타트 「{nd.name(raw)}」로 점프(파일 내)"}
        return {"kind": "link", "desc": "이동"}
    if tag == "Change" and t == "Area":
        rel, name = resolve.get(("Area", (card.get("id") or "").strip()), (None, card.get("id")))
        return {"kind": "change", "name": name,
                "desc": f"에리어 「{nd.scene_name(rel, name)}」로 이동", "target_rel": rel}
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


def build_outline(root: ET.Element, resolve: Dict[tuple, tuple],
                  nd: NameDisplay | None = None,
                  content_rels: set | None = None) -> List[dict]:
    """파일 루트 → 카드 줄 목록(진행/트리 순서, depth 포함).
    대사 줄엔 unit_ids(번역 유닛 sid) 부여. nd = 이름 라벨 번역 표시(없으면 원문).
    content_rels 를 주면 번역할 게 없는 로직 전용 파일로의 호출/이동 줄은 숨긴다."""
    if nd is None:
        nd = NameDisplay(None)
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
            entry = _describe(child, resolve, nd)
            entry["depth"] = depth
            if entry.get("name"):
                # 편집칸 프리필용 — 현재 툴 전용 표시명(없으면 프런트가 원문 사용)
                entry["tool_ko"] = nd.tool.get(entry["name"].strip(), "")
            if entry["kind"] == "talk":
                sids = [text_sid[id(t)] for t in child.iter("Text") if id(t) in text_sid]
                entry["unit_ids"] = sids
                entry["preview"] = _talk_preview(child)
                if not sids:
                    continue  # 번역할 텍스트 없는 Talk 은 생략
            # 로직 전용 파일(번역 유닛 없음 — SYSTEM_… 패키지 등)로의 호출/이동은
            # 번역할 게 없으므로 줄 자체를 숨긴다 (하위 콘텐츠는 계속 따라간다)
            logic_only = (content_rels is not None
                          and entry.get("target_rel")
                          and entry["target_rel"] not in content_rels)
            if entry["kind"] != "misc" and not logic_only:
                # misc(BGM/효과음/대기/플래그 설정/Get·Lose 등)는 번역 문맥에 무의미한
                # 로직 잡동사니라 표시하지 않는다. 하위 콘텐츠는 계속 따라간다.
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

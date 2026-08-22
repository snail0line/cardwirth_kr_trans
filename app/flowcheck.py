# -*- coding: utf-8 -*-
"""시나리오 흐름 구조 검사 — 끊어진 점프·미참조 라벨·닿지 않는 씬.

번역 툴이므로 저장·내보내기를 막지 않는다(원작 시나리오의 결함일 수 있다). 다만 번역 중
Start/Link/Call 라벨(ENT_LINK)을 같이 번역하는 시나리오에서는 정의부·참조부 불일치가
곧 게임 깨짐이므로, 내보내기 전에 눈으로 확인할 수 있게 목록으로 올린다.

검사 항목
  error  같은 Event 안 <Link/Call type="Start"> 가 가리키는 <Start name> 이 없음
  error  <Call/Link type="Package"> 대상 Id 의 Package/Battle 파일이 없음
  error  <Change type="Area"> 대상 Id 의 Area 파일이 없음
  warn   어디서도 참조되지 않는 <Start name> 라벨(이벤트 진입 라인은 제외)
  warn   Summary StartAreaId 에서 Call/Link/Change 로 닿지 않는 Area/Package/Battle

파일 간 그래프 규칙은 flow.py 와 같다(Link type=Start 는 파일 내부 점프).
반환 형태는 issues.py 가 그대로 실어 나른다: {level, rel, where, message}.
"""
from __future__ import annotations
import os
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from . import xmlio

SCENE_TAGS = {"Area", "Package", "Battle"}


def _is_label_start(el: ET.Element) -> bool:
    """ContentsLine 첫 카드인 <Start name> 라벨. <Start type="Battle"> 는 전투 개시 카드."""
    return el.tag == "Start" and not el.get("type") and bool(el.get("name"))


def _jump_target(el: ET.Element) -> Optional[str]:
    """<Link/Call type="Start"> 의 대상 라벨 이름."""
    if el.tag not in ("Link", "Call") or el.get("type") != "Start":
        return None
    return (el.get("link") or el.get("call") or "").strip() or None


def check_roots(roots: Dict[str, ET.Element]) -> List[dict]:
    """rel → 루트 요소 맵을 검사. 파일을 읽지 않으므로 테스트에서 문자열 XML 로 바로 쓴다."""
    out: List[dict] = []
    area_to_rel: Dict[str, str] = {}
    pkg_to_rel: Dict[str, str] = {}
    battle_to_rel: Dict[str, str] = {}      # Package 와 Battle 은 Id 공간이 따로다(둘 다 1,2,3…)
    start_area = None
    for rel, root in roots.items():
        if root.tag == "Summary":
            sa = root.findtext("Property/StartAreaId")
            if sa and sa.strip():
                start_area = sa.strip()
        elif root.tag == "Area":
            aid = (root.findtext("Property/Id") or "").strip()
            if aid:
                area_to_rel[aid] = rel
        elif root.tag == "Package":
            pid = (root.findtext("Property/Id") or "").strip()
            if pid:
                pkg_to_rel[pid] = rel
        elif root.tag == "Battle":
            bid = (root.findtext("Property/Id") or "").strip()
            if bid:
                battle_to_rel[bid] = rel

    edges: Dict[str, set] = {}
    for rel, root in roots.items():
        if root.tag not in SCENE_TAGS:
            continue
        edges.setdefault(rel, set())
        # ① 파일 내부 라벨 점프 — Event 단위
        for event in root.iter("Event"):
            defined: Dict[str, int] = {}
            entry: Optional[str] = None
            for cl in event.iter("ContentsLine"):
                if len(cl) and _is_label_start(cl[0]):
                    nm = cl[0].get("name").strip()
                    if entry is None:
                        entry = nm
                    defined[nm] = defined.get(nm, 0)
            referenced = set()
            for el in event.iter():
                tgt = _jump_target(el)
                if tgt is None:
                    continue
                referenced.add(tgt)
                if tgt not in defined:
                    out.append({"level": "error", "rel": rel, "where": tgt,
                                "message": f"<{el.tag} type=\"Start\"> 가 가리키는 <Start name=\"{tgt}\"> 가 이 이벤트에 없음"})
            for nm in defined:
                if nm != entry and nm not in referenced:
                    out.append({"level": "warn", "rel": rel, "where": nm,
                                "message": f"<Start name=\"{nm}\"> 를 참조하는 Link/Call 이 없음(닿지 않는 라인)"})
        # ② 파일 간 참조
        for el in root.iter():
            t = el.get("type")
            if el.tag in ("Call", "Link") and t == "Package":
                pid = (el.get("call") or el.get("link") or "").strip()
                dst = pkg_to_rel.get(pid)
                if dst is None:
                    out.append({"level": "error", "rel": rel, "where": pid,
                                "message": f"<{el.tag} type=\"Package\"> 대상 Id {pid or '(빈 값)'} 의 패키지 파일이 없음"})
                elif dst != rel:
                    edges[rel].add(dst)
            elif el.tag == "Change" and t == "Area":
                aid = (el.get("id") or "").strip()
                dst = area_to_rel.get(aid)
                if dst is None:
                    out.append({"level": "error", "rel": rel, "where": aid,
                                "message": f"<Change type=\"Area\"> 대상 Id {aid or '(빈 값)'} 의 에어리어 파일이 없음"})
                elif dst != rel:
                    edges[rel].add(dst)
            elif el.tag == "Start" and t == "Battle":
                bid = (el.get("id") or "").strip()
                dst = battle_to_rel.get(bid)
                if dst is None:
                    out.append({"level": "error", "rel": rel, "where": bid,
                                "message": f"<Start type=\"Battle\"> 대상 Id {bid or '(빈 값)'} 의 전투 파일이 없음"})
                elif dst != rel:
                    edges[rel].add(dst)

    # 같은 자리의 같은 메시지는 한 번만(Link 가 두 번 있어도 고칠 곳은 하나)
    uniq: Dict[tuple, dict] = {}
    for i in out:
        uniq.setdefault((i["level"], i["rel"], i["where"], i["message"]), i)
    out = list(uniq.values())

    # ③ 시작 에어리어에서의 도달성
    start_rel = area_to_rel.get(start_area) if start_area else None
    if start_area and start_rel is None:
        out.append({"level": "error", "rel": "Summary.xml", "where": start_area,
                    "message": f"Summary StartAreaId {start_area} 의 에어리어 파일이 없음"})
    if start_rel:
        seen = set()
        stack = [start_rel]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(edges.get(cur, ()))
        for rel in edges:
            if rel not in seen:
                out.append({"level": "warn", "rel": rel, "where": "",
                            "message": "시작 에어리어에서 Call/Link/Change 로 닿지 않는 씬"})
    return out


def check_scenario(scenario_dir: str) -> List[dict]:
    """시나리오 폴더의 XML 을 읽어 검사. 폴더가 없으면 빈 목록(열리지 않은 프로젝트)."""
    if not scenario_dir or not os.path.isdir(scenario_dir):
        return []
    roots: Dict[str, ET.Element] = {}
    for rel in xmlio.find_xml_files(scenario_dir):
        try:
            roots[rel] = ET.parse(os.path.join(scenario_dir, rel)).getroot()
        except Exception:
            continue        # 깨진 XML 은 extract 단계에서 이미 걸린다
    return check_roots(roots)

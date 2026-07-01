# -*- coding: utf-8 -*-
"""시나리오 XML 폴더 → 번역 프로젝트(dict) 추출."""
from __future__ import annotations
import os
from typing import Dict, Any

from . import xmlio, schema, context, flowcond

GSEP = "\x1f"  # glossary key 구분자


def gkey(etype: str, jp: str) -> str:
    return f"{etype}{GSEP}{jp}"


def _nearest(ancestors, tag):
    """ancestors(루트→부모 순) 중 가장 가까운 해당 tag 요소."""
    for a in reversed(ancestors):
        if a.tag == tag:
            return a
    return None


def extract_project(scenario_dir: str) -> Dict[str, Any]:
    scenario_dir = os.path.abspath(scenario_dir)
    proj: Dict[str, Any] = {
        "scenario_dir": scenario_dir,
        "glossary": {},   # gkey -> {etype, jp, ko}
        "files": {},      # rel -> {units:[...]}
    }
    glossary = proj["glossary"]

    for rel in xmlio.find_xml_files(scenario_dir):
        tree = xmlio.parse_file(os.path.join(scenario_dir, rel))
        root = tree.getroot()
        # 이벤트 흐름을 따라가 각 대사의 '도달 조건'(쿠폰 분기 등)을 정확히 계산
        fcond = flowcond.compute_file_conditions(root)
        units = []
        talk_group = {}   # id(Talk요소) -> 그룹번호 (말투 변형 묶음, 파일 단위)
        for sid, el, ancestors, slot in xmlio.iter_slots(root):
            if slot.kind == "entity":
                k = gkey(slot.etype, slot.value)
                if k not in glossary:
                    glossary[k] = {"etype": slot.etype, "jp": slot.value, "ko": ""}
                units.append({
                    "id": sid, "field": slot.field, "tag": slot.tag,
                    "parent": slot.parent, "kind": "entity",
                    "etype": slot.etype, "jp": slot.value, "gkey": k,
                })
            else:
                u = {
                    "id": sid, "field": slot.field, "tag": slot.tag,
                    "parent": slot.parent, "kind": "free",
                    "jp": slot.value, "ko": "",
                    "control": schema.is_control_label(slot.value),
                }
                # 대사 컨텍스트: 화자 / 분기조건(파벌·플래그·스텝) / 말투
                sp = ""
                if slot.field == "#text" and slot.tag == "Text":
                    sp = context.speaker_of(ancestors, el)
                    if sp:
                        u["speaker"] = sp
                    info = fcond.get(id(el))
                    if info:
                        if info.get("must"):
                            u["conditions"] = info["must"]
                        if info.get("any"):
                            u["cond_alt"] = info["any"]
                    tone = context.tone_of(ancestors, el)
                    if tone:
                        u["tone"] = tone
                    # 메시지창에 이미지(화자 그림/사진)가 뜨면 텍스트 폭이 좁아진다
                    # (게임 자동 줄바꿈: 그림 없음 43단위 → 그림 있으면 33단위).
                    # 판별 = 부모 <Talk> 의 path 속성이 비어있지 않은지.
                    talk = _nearest(ancestors, "Talk")
                    if talk is not None and (talk.get("path") or "").strip():
                        u["img"] = True
                # 말투 변형 묶기 — 두 가지 구조 지원:
                # (A) <Talk type="Dialog"> 안 여러 <Dialog> (쿠폰 :○○口調 분기) → 같은 Talk 로 묶기
                #     (구조: Talk > Dialogs > Dialog > Text — 중간 Dialogs 래퍼 있음)
                # (B) 口調 분기 <Branch type="MultiStep" step="…口調"> 아래 name=0..N 별도 <Talk> 들
                #     → 같은 Branch 로 묶기 (각 Talk 가 한 말투)
                if _nearest(ancestors, "Dialog") is not None:
                    talk = _nearest(ancestors, "Talk")
                    if talk is not None:
                        u["group"] = talk_group.setdefault(id(talk), len(talk_group) + 1)
                elif slot.tag == "Text":
                    br = _nearest(ancestors, "Branch")
                    if br is not None and br.get("type") == "MultiStep" \
                            and "口調" in (br.get("step") or ""):
                        u["group"] = talk_group.setdefault(id(br), len(talk_group) + 1)
                # 분류: 대사 / 나레이션 / 선택지 / 설명 / 제목(label) / 내부명(sysname)
                if slot.field != "#text":
                    u["cat"] = "choice"
                elif slot.tag == "Text":
                    u["cat"] = "dialogue" if sp else "narration"
                elif slot.tag == "Description":
                    u["cat"] = "desc"
                elif slot.tag == "Name":
                    root_tag = ancestors[0].tag if ancestors else ""
                    parent_tag = ancestors[-1].tag if ancestors else ""
                    # Package/Area/Battle 의 최상위 Property/Name = 내부 이벤트명(플레이어 비노출)
                    if parent_tag == "Property" and root_tag in ("Package", "Area", "Battle"):
                        u["cat"] = "sysname"
                    else:
                        u["cat"] = "label"
                else:
                    u["cat"] = "label"
                units.append(u)
        # 멤버가 1개뿐인 그룹은 묶을 필요 없음 → group 키 제거(단독 유닛으로 표시)
        gcount: Dict[int, int] = {}
        for u in units:
            if u.get("group") is not None:
                gcount[u["group"]] = gcount.get(u["group"], 0) + 1
        for u in units:
            if u.get("group") is not None and gcount[u["group"]] < 2:
                u.pop("group", None)
        if units:
            proj["files"][rel] = {"units": units}
    return proj


def project_stats(proj: Dict[str, Any]) -> Dict[str, int]:
    free_total = free_done = 0
    for f in proj["files"].values():
        for u in f["units"]:
            if u["kind"] == "free":
                free_total += 1
                if u.get("ko"):
                    free_done += 1
    ent_total = len(proj["glossary"])
    ent_done = sum(1 for g in proj["glossary"].values() if g.get("ko"))
    return {
        "free_total": free_total, "free_done": free_done,
        "entity_total": ent_total, "entity_done": ent_done,
        "files": len(proj["files"]),
    }

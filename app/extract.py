# -*- coding: utf-8 -*-
"""시나리오 XML 폴더 → 번역 프로젝트(dict) 추출."""
from __future__ import annotations
import os
import re
from typing import Dict, Any

from . import xmlio, schema, context, flowcond

# %상태변수% 표시 참조 (예: %02/食事済？%)
_DISPVAR = re.compile(r"%([^%\n]+)%")

# 가나(히라가나/가타카나/반각 가타카나) — 번역문에 남아 있으면 부분 번역
_KANA = re.compile(r"[ぁ-ゖァ-ヺｦ-ﾝ]")


def is_partial_ko(jp: str, ko: str) -> bool:
    """ko 에 가나가 남아 있으면 부분 번역(용어 치환 초안 등) — 완료로 세지 않는다.
    단 ko == jp(원문 그대로 완료 처리)는 의도적 유지로 보고 완료로 인정한다."""
    return bool(ko) and ko != jp and bool(_KANA.search(ko))

GSEP = "\x1f"  # glossary key 구분자


def gkey(etype: str, jp: str) -> str:
    return f"{etype}{GSEP}{jp}"


def _nearest(ancestors, tag):
    """ancestors(루트→부모 순) 중 가장 가까운 해당 tag 요소."""
    for a in reversed(ancestors):
        if a.tag == tag:
            return a
    return None


def _collect_display_vars(scenario_dir: str, rels) -> set:
    """전 파일에서 %이름% 표시 참조를 수집. 여기 등장하는 상태변수의 표시값(True/False/
    Value)만 번역 대상 — 나머지 변수의 표시값은 로직 전용이라 플레이어에게 안 보인다."""
    names = set()
    for rel in rels:
        try:
            with open(os.path.join(scenario_dir, rel), encoding="utf-8") as f:
                names.update(_DISPVAR.findall(f.read()))
        except (OSError, UnicodeDecodeError):
            pass
    return names


def _collect_cast_names(roots) -> set:
    """시나리오의 CastCard 실명 집합 — 대사 첫 줄 이름표 판정은 이 이름과
    정확히 일치할 때만 인정한다(자유 휴리스틱은 지문 첫 줄 오탐이 많아 폐지)."""
    names = set()
    for root in roots.values():
        if root.tag == "CastCard":
            nm = (root.findtext("Property/Name") or "").strip()
            if nm:
                names.add(nm)
        for cc in root.iter("CastCard"):        # 에어리어/배틀에 임베드된 카드 포함
            nm = (cc.findtext("Property/Name") or "").strip()
            if nm:
                names.add(nm)
    return names


def extract_project(scenario_dir: str) -> Dict[str, Any]:
    scenario_dir = os.path.abspath(scenario_dir)
    proj: Dict[str, Any] = {
        "scenario_dir": scenario_dir,
        "glossary": {},   # gkey -> {etype, jp, ko}
        "files": {},      # rel -> {units:[...]}
    }
    glossary = proj["glossary"]
    rels = xmlio.find_xml_files(scenario_dir)
    display_vars = _collect_display_vars(scenario_dir, rels)
    roots = {}
    for rel in rels:
        roots[rel] = xmlio.parse_file(os.path.join(scenario_dir, rel)).getroot()
    cast_names = _collect_cast_names(roots)

    for rel in rels:
        root = roots[rel]
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
                # 플래그/스텝 표시값: %이름% 으로 실제 표시되는 변수만 번역 대상.
                # (슬롯 sid 는 그대로 소비되므로 repack/dupchoice 와 정합 유지)
                vname = ""
                if (slot.tag, slot.parent) in schema.FREE_VALUE_TAGS:
                    holder = ancestors[-1] if ancestors else None
                    vname = (holder.findtext("Name") or "").strip() if holder is not None else ""
                    if vname not in display_vars:
                        continue
                u = {
                    "id": sid, "field": slot.field, "tag": slot.tag,
                    "parent": slot.parent, "kind": "free",
                    "jp": slot.value, "ko": "",
                    "control": schema.is_control_label(slot.value)
                    or schema.is_tokens_only(slot.value),   # 코드/치환자뿐 → 읽기전용
                }
                if vname:
                    u["varname"] = vname                    # 표시값 → 사용처 점프용
                refs = sorted(set(_DISPVAR.findall(slot.value)))
                if refs:
                    u["varrefs"] = refs                     # %변수% 참조 → 정의 점프용
                # 대사 컨텍스트: 화자 / 분기조건(파벌·플래그·스텝) / 말투
                sp = ""
                if slot.field == "#text" and slot.tag == "Text":
                    sp = context.speaker_of(ancestors, el, cast_names)
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
                    # 초상화가 뜨는 조건 = path(NPC 그림)가 있거나,
                    # type="Dialog"/target 지정(선택·랜덤 PC 발화 → PC 카드 초상화)인 경우.
                    # (path 없는 나레이션·본문내장 이름만 있는 Message 는 그림 없음 → 43)
                    talk = _nearest(ancestors, "Talk")
                    if talk is not None:
                        _tgt = (talk.get("targetm") or talk.get("targetf")
                                or talk.get("target") or "")
                        if (talk.get("path") or "").strip() \
                                or talk.get("type") == "Dialog" or _tgt:
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
                    root_tag = ancestors[0].tag if ancestors else ""
                    u["cat"] = "scndesc" if root_tag == "Summary" else "desc"
                elif (slot.tag, slot.parent) in schema.FREE_VALUE_TAGS:
                    u["cat"] = "varvalue"           # 플래그/스텝 표시값 (%상태변수% 로 표시)
                elif slot.tag == "Name":
                    root_tag = ancestors[0].tag if ancestors else ""
                    parent_tag = ancestors[-1].tag if ancestors else ""
                    # Package/Area/Battle "자체"의 Property/Name(루트 직속, len==2)만
                    # 내부 이벤트명(플레이어 비노출) = sysname. 같은 파일이라도 더 깊은
                    # Property/Name(Area>MenuCards>MenuCard>Property>Name 등)은 게임에
                    # 표시되는 카드 이름이므로 번역 대상(label)이다.
                    if parent_tag == "Property" and root_tag in ("Package", "Area", "Battle") \
                            and len(ancestors) == 2:
                        u["cat"] = "sysname"
                    elif parent_tag == "Property" and root_tag == "Summary" \
                            and len(ancestors) == 2:
                        u["cat"] = "scnname"        # 시나리오 제목 (선택 화면에 표시)
                    else:
                        u["cat"] = "label"
                else:
                    u["cat"] = "label"
                if u["cat"] == "sysname":
                    continue    # 내부명(에어리어/배틀/패키지 자체 이름)은 플레이어 비노출
                                # (디버거·플레이 로그 전용) — 번역툴에 아예 노출하지 않음
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
                if u.get("ko") and (u.get("force_done")
                                    or not is_partial_ko(u["jp"], u["ko"])):
                    free_done += 1          # 가나 남은 부분 번역은 미완(명시 완료 제외)
    # 엔티티 진행률 — 링크(Link/Start/Call = 화면 비노출 흐름 라벨)는 분리해서 센다.
    # 링크는 번역 '가능'하되 플레이어 진행률에는 안 넣는다(편집기 가독성용 선택 항목).
    ent_total = ent_done = link_total = link_done = 0
    for g in proj["glossary"].values():
        done = bool(g.get("ko"))
        if g.get("etype") == schema.ENT_LINK:
            link_total += 1
            link_done += done
        else:
            ent_total += 1
            ent_done += done
    return {
        "free_total": free_total, "free_done": free_done,
        "entity_total": ent_total, "entity_done": ent_done,
        "link_total": link_total, "link_done": link_done,
        "files": len(proj["files"]),
    }

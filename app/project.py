# -*- coding: utf-8 -*-
"""번역 프로젝트 영속화 (JSON) + 재추출 머지."""
from __future__ import annotations
import os
import json
from typing import Dict, Any

from . import extract, textcodec

PROJECTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "projects"))


def _migrate_attr_ko(proj: Dict[str, Any]) -> Dict[str, Any]:
    """구버전 버그 복구: 속성(@…) 슬롯 ko 에도 CardWirth 이스케이프가 걸려 백슬래시가
    이중화됐다(선택지의 $PC\\…$ 토큰이 게임에서 깨짐). @ 슬롯 ko 를 한 번 decode 해 raw 로
    되돌린다. 백슬래시 없는 정상값엔 무해(idempotent). 프로젝트당 1회(_attr_ko_fixed)."""
    if proj.get("_attr_ko_fixed"):
        return proj
    for f in proj.get("files", {}).values():
        for u in f.get("units", []):
            if u.get("kind") == "free" and u.get("field") != "#text" and u.get("ko"):
                u["ko"] = textcodec.decode(u["ko"])
    proj["_attr_ko_fixed"] = True
    return proj


def _safe_name(scenario_dir: str) -> str:
    base = os.path.basename(os.path.normpath(scenario_dir)) or "project"
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in base)


def project_path(scenario_dir: str) -> str:
    return os.path.join(PROJECTS_DIR, _safe_name(scenario_dir) + ".json")


def save(proj: Dict[str, Any]) -> str:
    os.makedirs(PROJECTS_DIR, exist_ok=True)
    p = project_path(proj["scenario_dir"])
    with open(p, "w", encoding="utf-8") as f:
        json.dump(proj, f, ensure_ascii=False, indent=1)
    return p


def load(scenario_dir: str) -> Dict[str, Any] | None:
    p = project_path(scenario_dir)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return _migrate_attr_ko(json.load(f))


_LAST = os.path.join(PROJECTS_DIR, ".last_scenario")


def save_last(scenario_dir: str) -> None:
    os.makedirs(PROJECTS_DIR, exist_ok=True)
    with open(_LAST, "w", encoding="utf-8") as f:
        f.write(scenario_dir)


def load_last() -> str | None:
    try:
        with open(_LAST, encoding="utf-8") as f:
            d = f.read().strip()
        return d if d and os.path.isdir(d) else None
    except OSError:
        return None


def open_or_extract(scenario_dir: str) -> Dict[str, Any]:
    """기존 저장 프로젝트가 있으면 재추출 결과와 머지(번역 보존), 없으면 새로 추출."""
    fresh = extract.extract_project(scenario_dir)
    old = load(scenario_dir)
    if old is None:
        return fresh
    return merge(old, fresh)


def merge(old: Dict[str, Any], fresh: Dict[str, Any]) -> Dict[str, Any]:
    """원본 시나리오가 바뀌어 재추출했을 때, 기존 번역을 키 기준으로 옮긴다."""
    # 용어집(terms) 보존
    if old.get("terms"):
        fresh["terms"] = dict(old["terms"])
    # 수동 추가 용어 보존
    if old.get("terms_manual"):
        fresh["terms_manual"] = list(old["terms_manual"])
    # 글로서리: 같은 gkey 의 ko 보존
    for k, g in fresh["glossary"].items():
        if k in old.get("glossary", {}) and old["glossary"][k].get("ko"):
            g["ko"] = old["glossary"][k]["ko"]
    # 자유 유닛: (파일, jp) 기준으로 ko 보존 (id 가 흔들려도 원문 매칭)
    old_free = {}
    for rel, f in old.get("files", {}).items():
        for u in f["units"]:
            if u["kind"] == "free" and u.get("ko"):
                old_free.setdefault(rel, {})[(u["field"], u["jp"])] = u["ko"]
    for rel, f in fresh["files"].items():
        m = old_free.get(rel, {})
        for u in f["units"]:
            if u["kind"] == "free":
                ko = m.get((u["field"], u["jp"]))
                if ko:
                    u["ko"] = ko
    return fresh

# -*- coding: utf-8 -*-
"""번역 프로젝트 + 원본 XML 폴더 → 한글 시나리오 폴더 산출."""
from __future__ import annotations
import os
import shutil
from typing import Dict, Any

from . import xmlio


def _resolve_value(unit: Dict[str, Any], glossary: Dict[str, Any]) -> str:
    """유닛에 적용할 최종 값. 번역이 비면 원문(JP) 유지."""
    if unit["kind"] == "entity":
        ko = glossary.get(unit["gkey"], {}).get("ko", "")
    else:
        ko = unit.get("ko", "")
    return ko if ko else unit["jp"]


def repack_project(proj: Dict[str, Any], out_dir: str,
                   copy_assets: bool = True) -> Dict[str, int]:
    """proj 의 번역을 적용해 out_dir 에 완전한 시나리오를 만든다."""
    scenario_dir = proj["scenario_dir"]
    glossary = proj.get("glossary", {})
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    applied = 0
    xml_rels = set(proj["files"].keys())

    # 1) 번역 XML 기록
    for rel, fdata in proj["files"].items():
        tree = xmlio.parse_file(os.path.join(scenario_dir, rel))
        by_id = {u["id"]: u for u in fdata["units"]}
        for sid, el, _anc, slot in xmlio.iter_slots(tree.getroot()):
            u = by_id.get(sid)
            if u is None:
                continue
            val = _resolve_value(u, glossary)
            if val != slot.value:
                applied += 1
            xmlio.apply_slot(el, slot, val)
        xmlio.write_tree(tree, os.path.join(out_dir, rel))

    # 2) 번역 대상이 아닌 XML(유닛 0개) + 에셋(Material 등) 그대로 복사
    copied = 0
    if copy_assets:
        for root, _dirs, files in os.walk(scenario_dir):
            for name in files:
                src = os.path.join(root, name)
                rel = os.path.relpath(src, scenario_dir).replace(os.sep, "/")
                if rel in xml_rels:
                    continue  # 위에서 기록함
                dst = os.path.join(out_dir, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                copied += 1

    return {"xml_files": len(xml_rels), "applied": applied, "copied_assets": copied}

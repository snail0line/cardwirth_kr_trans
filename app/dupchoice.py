# -*- coding: utf-8 -*-
"""같은 선택지 그룹(같은 <Contents> 아래 형제 메뉴 옵션) 안에서 서로 다른 원문(jp)이
같은 번역(ko)으로 겹쳐 선택지 구실을 못 하는 경우를 찾는다.

CardWirth 선택지는 텍스트(@name 키코드)로 분기를 매칭하므로, 한 메뉴에 같은 한국어가
둘 이상 있으면 게임이 구분하지 못한다(뒤 항목이 사실상 도달 불가). 예: 刀→"칼",
ナイフ→"칼". 자동 수정은 오역 위험이 있어 하지 않고 '알림'만 한다.

XML 을 다시 파싱해 메뉴 그룹을 잡는다 — iter_slots 의 slot_id 순서는 추출(extract.py)과
동일하므로 proj 유닛과 1:1 대응한다. 각 그룹에서 원문은 다른데 번역이 겹치는 항목만
보고한다(원문까지 같으면 애초에 같은 선택지라 문제 아님).
"""
from __future__ import annotations
import os
from typing import Dict, Any, List

from . import xmlio


def _nearest(ancestors, tag):
    """ancestors(루트→부모 순) 중 가장 가까운 해당 tag 요소."""
    for a in reversed(ancestors):
        if a.tag == tag:
            return a
    return None


def find_dup_choices(proj: Dict[str, Any], scope: str = "all",
                     cur_rel: str = "", cap: int = 500) -> List[dict]:
    """같은 메뉴에서 ko 가 겹치는 선택지 묶음 목록. scope: 'all'|'file'(cur_rel 만).
    반환: [{rel, ko, count, items:[{sid, jp}]}] — 파일 순."""
    sdir = proj.get("scenario_dir")
    out: List[dict] = []
    for rel, f in proj["files"].items():
        if scope == "file" and rel != cur_rel:
            continue
        path = os.path.join(sdir, rel) if sdir else None
        if not path or not os.path.isfile(path):
            continue                            # XML 캐시 없으면(닫힘 등) 건너뜀
        try:
            root = xmlio.parse_file(path).getroot()
        except Exception:
            continue
        by_id = {u["id"]: u for u in f["units"]}
        # 메뉴(가장 가까운 Contents)별로 선택지 sid 묶기
        groups: Dict[int, List[int]] = {}
        for sid, el, ancestors, slot in xmlio.iter_slots(root):
            if slot.field == "#text":           # 선택지(@name)만 대상
                continue
            u = by_id.get(sid)
            if not u or u.get("cat") != "choice" or u.get("control"):
                continue
            cont = _nearest(ancestors, "Contents")
            key = id(cont) if cont is not None else -sid
            groups.setdefault(key, []).append(sid)
        # 각 그룹에서 번역(ko) 중복(원문은 다른데) 찾기
        for sids in groups.values():
            if len(sids) < 2:
                continue
            byko: Dict[str, List[int]] = {}
            for sid in sids:
                ko = (by_id[sid].get("ko") or "").strip()
                if ko:                          # 미번역은 제외
                    byko.setdefault(ko, []).append(sid)
            for ko, dups in byko.items():
                if len(dups) < 2:
                    continue
                jps = {(by_id[s].get("jp") or "").strip() for s in dups}
                if len(jps) < 2:                # 원문까지 동일 → 진짜 같은 선택지, 문제 아님
                    continue
                out.append({
                    "rel": rel, "ko": ko[:60], "count": len(dups),
                    "items": [{"sid": s, "jp": (by_id[s].get("jp") or "").strip()[:40]}
                              for s in dups],
                })
                if len(out) >= cap:
                    return out
    return out

# -*- coding: utf-8 -*-
"""
시나리오 진행 흐름 그래프(플로우차트) 생성.

노드 = 파일(Area / Package / Battle = 하나의 '씬')
엣지 = Link(type=Start, link="X") → <Start name="X"> 를 가진 파일
       Change(type=Area, id=N)   → Id=N 인 Area 파일
시작 = Summary 의 StartAreaId 가 가리키는 Area
"""
from __future__ import annotations
import os
import xml.etree.ElementTree as ET
from . import xmlio

SCENE_TAGS = {"Area", "Package", "Battle"}  # 노드로 삼을 루트 태그


def _disp_name(root: ET.Element, rel: str) -> str:
    name = root.findtext("Property/Name") or root.findtext("Name") or ""
    name = (name or "").strip()
    return name or os.path.splitext(os.path.basename(rel))[0]


def _reduce_to_content(nodes, edges, edge_order, edge_kind, keep, start_rel):
    """content 없는 노드를 제거하되, 그 노드를 '건너뛰어' 앞뒤 content 노드를 직접 연결.
    호출 순서(edge_order)·종류(edge_kind)는 src 를 떠난 출발 엣지의 것을 물려준다.
    keep = 남길 rel 집합(+시작 노드). 반환: (nodes, edge_list, edge_order, edge_kind)."""
    keep = set(keep)
    if start_rel:
        keep.add(start_rel)
    adj = {}
    for s, d in edges:
        adj.setdefault(s, []).append((d, edge_order.get((s, d), 0), edge_kind.get((s, d), "call")))

    def reach_kept(src):
        """src 에서 도달하는 kept 노드 → 그 노드로 이끈 src 출발 엣지의 (최소순서, 종류)."""
        res = {}
        for first, o, k in adj.get(src, []):
            seen, stack = set(), [first]
            while stack:
                n = stack.pop()
                if n in seen:
                    continue
                seen.add(n)
                if n in keep:
                    if n not in res or o < res[n][0]:
                        res[n] = (o, k)
                else:
                    stack.extend(d for d, _, _ in adj.get(n, []))
        return res

    new_nodes = {r: n for r, n in nodes.items() if r in keep}
    new_edges, new_order, new_kind = [], {}, {}
    for src in new_nodes:
        for dst, (o, k) in reach_kept(src).items():
            if dst != src:
                new_edges.append((src, dst))
                new_order[(src, dst)] = o
                new_kind[(src, dst)] = k
    return new_nodes, new_edges, new_order, new_kind


def build_flow(scenario_dir: str, content_rels=None) -> dict:
    scenario_dir = os.path.abspath(scenario_dir)
    rels = xmlio.find_xml_files(scenario_dir)

    roots = {}            # rel -> (root, tag)
    area_to_file = {}     # area id(str) -> rel
    pkg_to_file = {}      # package id(str) -> rel (Call/Link type=Package 대상)
    summary_start_area = None

    for rel in rels:
        try:
            root = ET.parse(os.path.join(scenario_dir, rel)).getroot()
        except Exception:
            continue
        roots[rel] = root
        tag = root.tag
        if tag == "Summary":
            sa = root.findtext("Property/StartAreaId")
            if sa:
                summary_start_area = sa.strip()
        if tag == "Area":
            aid = root.findtext("Property/Id")
            if aid:
                area_to_file[aid.strip()] = rel
        if tag in ("Package", "Battle"):
            pid = root.findtext("Property/Id")
            if pid:
                pkg_to_file[pid.strip()] = rel

    # 노드: 씬 파일만
    nodes = {}  # rel -> {label, kind}
    for rel, root in roots.items():
        if root.tag in SCENE_TAGS:
            nodes[rel] = {"label": _disp_name(root, rel), "kind": root.tag}

    # 엣지: 문서 순서대로 1패스 → 호출/이동 순서(edge_order)·종류(edge_kind) 기록
    #   call = 패키지 호출(끝나면 복귀) / link = 이동(복귀X) / change = 에리어 이동
    edges = {}        # (src,dst) -> set(labels)
    edge_order = {}   # (src,dst) -> src 내 첫 등장 순서(호출 차례)
    edge_kind = {}    # (src,dst) -> "call"|"link"|"change"
    for rel, root in roots.items():
        if rel not in nodes:
            continue
        seq = 0
        for el in root.iter():
            tgt = None
            kind = None
            t = el.get("type")
            if el.tag == "Call" and t == "Package":
                tgt = pkg_to_file.get((el.get("call") or "").strip()); kind = "call"
            elif el.tag == "Link" and t == "Package":
                tgt = pkg_to_file.get((el.get("link") or "").strip()); kind = "link"
            # 주의: Link type="Start" 는 '파일 내부' 점프(その１/その２ 등 로컬 라벨)이므로
            #       파일 간 엣지로 쓰지 않는다(전역 매핑하면 가짜 연결 발생).
            elif el.tag == "Change" and t == "Area":
                tgt = area_to_file.get((el.get("id") or "").strip()); kind = "change"
            else:
                continue
            if tgt and tgt in nodes and tgt != rel:
                key = (rel, tgt)
                edges.setdefault(key, set())
                if kind == "change":
                    edges[key].add("이동")
                if key not in edge_order:
                    edge_order[key] = seq
                    edge_kind[key] = kind
                seq += 1

    start_rel = area_to_file.get(summary_start_area) if summary_start_area else None

    edge_list = list(edges.keys())
    # 내용 있는 노드만(+시작) 으로 축약, 로직 노드는 건너뛰어 연결
    if content_rels is not None:
        nodes, edge_list, edge_order, edge_kind = _reduce_to_content(
            nodes, edge_list, edge_order, edge_kind, content_rels, start_rel)

    # rel -> node id (n0..)
    order = list(nodes.keys())
    nid = {rel: f"n{i}" for i, rel in enumerate(order)}

    return {
        "nodes": nodes, "edges": edge_list, "edge_order": edge_order,
        "edge_kind": edge_kind, "nid": nid, "start_rel": start_rel,
    }


def _mm_label(s: str) -> str:
    """mermaid 노드 라벨 안전화."""
    s = (s or "").replace('"', "'").replace("[", "(").replace("]", ")")
    s = s.replace("{", "(").replace("}", ")").replace("|", "/").replace("\n", " ")
    return s[:40]


_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def _seq_mark(n: int) -> str:
    """1→① … 20→⑳, 그 이상은 (n)."""
    return _CIRCLED[n - 1] if 1 <= n <= len(_CIRCLED) else f"({n})"


def to_mermaid(flow: dict) -> dict:
    """flow → mermaid 정의 문자열(flowchart TD) + (노드id→rel) 맵.
    엣지 = Area↔Package 호출/이동(패키지는 Call type=Package call=Id 로 호출).
    같은 출발지의 호출은 진행 순서대로 ①②③… 라벨을 붙여 '어떤 순서로 빠져나가는지' 표시."""
    nid = flow["nid"]
    nodes = flow["nodes"]
    edge_order = flow.get("edge_order", {})
    edge_kind = flow.get("edge_kind", {})
    lines = ["flowchart TD"]
    id2rel = {}
    for rel, n in nodes.items():
        i = nid[rel]
        id2rel[i] = rel
        shape_l, shape_r = ("([", "])") if n["kind"] == "Area" else ("[", "]")
        lines.append(f'  {i}{shape_l}"{_mm_label(n["label"])}"{shape_r}')
    # 출발지별로 호출 순서(edge_order) 에 따라 ①②③… 번호 매김
    by_src = {}
    for src, dst in flow["edges"]:
        by_src.setdefault(src, []).append(dst)
    edge_i = 0          # mermaid 엣지 인덱스(선언 순서)
    ret_idx = []        # 점선 복귀 화살표 인덱스 → 연하게 스타일
    for src, dsts in by_src.items():
        dsts.sort(key=lambda d: edge_order.get((src, d), 0))
        multi = len(dsts) > 1
        for k, dst in enumerate(dsts, 1):
            if multi:
                lines.append(f'  {nid[src]} -->|{_seq_mark(k)}| {nid[dst]}')
            else:
                lines.append(f"  {nid[src]} --> {nid[dst]}")
            edge_i += 1
            # 패키지 '호출'(call)이고 대상이 Package 면 끝나고 호출자로 복귀 → 점선으로 '들어옴'.
            # (에리어 이동/Change·Link 는 복귀 아님)
            if edge_kind.get((src, dst)) == "call" and nodes.get(dst, {}).get("kind") == "Package":
                lines.append(f"  {nid[dst]} -.->|복귀| {nid[src]}")
                ret_idx.append(edge_i)
                edge_i += 1
    # 시작 노드 강조
    if flow.get("start_rel") and flow["start_rel"] in nid:
        s = nid[flow["start_rel"]]
        lines.append(f"  style {s} fill:#dbeafe,stroke:#2563eb,stroke-width:2px")
    # 복귀 화살표는 연한 회색으로
    if ret_idx:
        idx = ",".join(str(i) for i in ret_idx)
        lines.append(f"  linkStyle {idx} stroke:#c4b5fd,stroke-width:1px")
    return {"mermaid": "\n".join(lines), "id2rel": id2rel,
            "start": nid.get(flow.get("start_rel"))}

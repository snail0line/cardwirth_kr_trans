# -*- coding: utf-8 -*-
"""
CardWirthPy XML 입출력 + 번역 슬롯 문서순서 순회.

extract 와 repack 이 **동일한 순회**를 공유해야 슬롯 id(문서순서 인덱스)가 일치한다.
"""
from __future__ import annotations
import os
import io
import glob
import xml.etree.ElementTree as ET
from typing import Iterator, Tuple, Optional

from . import schema


XML_DECL = '<?xml version="1.0"?>\n'  # CardWirthPy 원본 스타일(인코딩 속성 없음, UTF-8)


def find_xml_files(scenario_dir: str) -> list[str]:
    """시나리오 폴더의 모든 .xml 을 상대경로(슬래시 통일)로 반환."""
    out = []
    for fp in glob.glob(os.path.join(scenario_dir, "**", "*.xml"), recursive=True):
        rel = os.path.relpath(fp, scenario_dir).replace(os.sep, "/")
        out.append(rel)
    out.sort()
    return out


def parse_file(path: str) -> ET.ElementTree:
    return ET.parse(path)


def iter_slots(root: ET.Element) -> Iterator[Tuple[int, ET.Element, list, schema.Slot]]:
    """문서 순서(pre-order)로 (slot_id, element, ancestors, Slot) 를 yield.
    ancestors = 루트부터 부모까지 요소 리스트(컨텍스트: 화자/분기조건/말투 추출용).
    한 요소 안에서는 #text 먼저, 그 다음 속성을 파일 순서대로."""
    seq = 0

    def walk(el: ET.Element, ancestors: list):
        nonlocal seq
        parent_tag = ancestors[-1].tag if ancestors else None
        s = schema.slot_for_text(el.tag, parent_tag, el.text)
        if s is not None:
            yield seq, el, ancestors, s
            seq += 1
        for attr, val in el.attrib.items():
            s = schema.slot_for_attr(el.tag, attr, val)
            if s is not None:
                yield seq, el, ancestors, s
                seq += 1
        child_anc = ancestors + [el]
        for child in el:
            yield from walk(child, child_anc)

    yield from walk(root, [])


def apply_slot(el: ET.Element, slot: schema.Slot, value: str) -> None:
    """슬롯에 번역값을 써넣는다."""
    if slot.field == "#text":
        el.text = value
    else:
        attr = slot.field[1:]
        el.set(attr, value)


def serialize(tree: ET.ElementTree) -> bytes:
    """CardWirthPy 원본 스타일(선언부 직접)로 직렬화."""
    body = ET.tostring(tree.getroot(), encoding="unicode")
    return (XML_DECL + body).encode("utf-8")


def write_tree(tree: ET.ElementTree, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(serialize(tree))

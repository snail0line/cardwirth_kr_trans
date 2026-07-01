# -*- coding: utf-8 -*-
"""
일괄 들여오기/내보내기 — 번역기(스프레드시트 등) 돌리기용.

내보내기: 모든 자유 텍스트를 CSV 로 (file, id, jp, ko). jp 는 사람이 읽기 좋게 디코드.
가져오기: 같은 CSV 를 읽어 (file, id) 매칭으로 ko 를 채운다.
  - ko 가 비었으면 건너뜀(기존 유지)
  - ko 가 jp 와 같으면 미번역으로 보고 비움
CSV 는 UTF-8 BOM(Excel 호환) + 표준 따옴표 처리(줄바꿈 포함 셀 OK).
"""
from __future__ import annotations
import csv
import io
from typing import Dict, Any, Tuple

from . import textcodec

HEADER = ["file", "id", "jp", "ko"]


def export_csv(proj: Dict[str, Any], path: str, only_untranslated: bool = False) -> int:
    """자유 텍스트를 CSV 로 내보냄. 반환: 행 수."""
    rows = 0
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for rel, fd in proj["files"].items():
            for u in fd["units"]:
                if u["kind"] != "free" or u.get("control"):
                    continue
                if u.get("cat") == "sysname":   # 내부명(플레이어 비노출) 제외
                    continue
                ko = textcodec.decode_field(u["field"], u.get("ko", ""))
                if only_untranslated and ko:
                    continue
                w.writerow([rel, u["id"], textcodec.decode_field(u["field"], u["jp"]), ko])
                rows += 1
    return rows


def import_csv(proj: Dict[str, Any], path: str) -> Dict[str, int]:
    """CSV 를 읽어 ko 적용. 반환: {applied, skipped, unmatched, rows}."""
    # (file,id) -> unit 인덱스
    index: Dict[Tuple[str, str], Any] = {}
    for rel, fd in proj["files"].items():
        for u in fd["units"]:
            if u["kind"] == "free":
                index[(rel, str(u["id"]))] = u

    applied = skipped = unmatched = rows = 0
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            rows += 1
            rel = (row.get("file") or "").strip()
            uid = (row.get("id") or "").strip()
            ko = row.get("ko")
            ko = "" if ko is None else ko
            u = index.get((rel, uid))
            if u is None:
                unmatched += 1
                continue
            jp = textcodec.decode_field(u["field"], u["jp"])
            new = "" if (ko.strip() == "" or ko == jp) else ko
            cur = textcodec.decode_field(u["field"], u.get("ko", ""))
            if new == cur:
                skipped += 1
                continue
            u["ko"] = textcodec.encode_field(u["field"], new)
            applied += 1
    return {"applied": applied, "skipped": skipped, "unmatched": unmatched, "rows": rows}

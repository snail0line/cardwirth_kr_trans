# -*- coding: utf-8 -*-
"""번역문이 게임 메시지창(8줄 기준)을 넘겨 잘리는 대사 목록.

미리보기(web/app.js `wrapForGame`)와 같은 strlen 고정 그리드 계산을 서버에서 재현해
전 파일(또는 현재 파일)을 스캔한다. 번역(ko)이 있는 메시지창 텍스트(대사/나레이션)만
검사한다 — 원문(jp)은 원작자가 이미 창에 맞췄다고 보고 제외. 결과 클릭 → 그 문장으로
점프(app.js `jumpTo`). 판정 상수·문자폭은 app.js 와 동일하게 유지할 것.
"""
from __future__ import annotations
import re
from typing import Dict, Any, List

from . import textcodec

LINE_UNITS = 43       # 일반 메시지 한 줄 폭(strlen)
LINE_UNITS_IMG = 33   # 화자 그림/PC 카드가 뜨는 메시지 (그림 폭만큼 좁음)
WRAP_ROWS = 8         # 넘침 판정 기준 줄 수(넘으면 잘림/페이지 넘어감)

_CTRL = re.compile(r"&[A-Za-z]")        # 색·제어코드(게임에 안 보임, 폭 0)
_MSG_CATS = ("dialogue", "narration")   # 메시지창에 뜨는 텍스트만 (선택지·설명·제목 제외)


def _char_units(ch: str) -> int:
    c = ord(ch)
    if c == 0x3000:              # 전각 공백(들여쓰기)
        return 2
    if c <= 0x2ff:              # ASCII·라틴 → 반각
        return 1
    if 0xff61 <= c <= 0xff9f:   # 반각 가타카나
        return 1
    return 2                    # 한글·일본어·한자·전각기호


def wrap_rows(text: str, units: int) -> int:
    """text 를 게임처럼 units 폭으로 접었을 때의 줄 수(app.js wrapForGame 과 동일).
    명시적 \\n 은 그대로 유지하고, 각 줄이 폭을 넘으면 접어서 줄 수를 늘린다."""
    text = _CTRL.sub("", text)
    rows = 0
    for raw in text.split("\n"):
        rows += 1                       # 이 구간은 최소 1줄
        w = 0
        started = False
        for ch in raw:
            cw = _char_units(ch)
            if w + cw > units and started:
                rows += 1               # 폭 초과 → 다음 줄로 접힘
                w = 0
                started = False
            w += cw
            started = True
    return rows


def tidy_text(text: str) -> str:
    """문단(빈 줄 구분 블록) 안 수동 줄바꿈을 없애 게임 자동 줄바꿈에 맡긴다(app.js tidyText 와 동일).
    빈 줄 문단 경계는 유지, 이어지는 줄은 앞뒤 공백(전각 포함) 제거 후 한 칸 띄어 이음,
    끝의 빈 줄(마지막이 엔터)은 제거해 넘침을 완화한다."""
    out: List[str] = []
    cur: List[str] = []

    def flush():
        if not cur:
            return
        first = cur[0].rstrip()                       # 첫 줄 들여쓰기 유지, 우측 공백만 제거
        rest = [ln.strip() for ln in cur[1:]]         # 이어지는 줄은 앞뒤 공백 제거
        out.append(" ".join([first] + rest))
        cur.clear()

    for ln in (text or "").split("\n"):
        if ln.strip() == "":
            flush()
            out.append("")
        else:
            cur.append(ln)
    flush()
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def tidy_overflow(proj: Dict[str, Any], scope: str = "all", cur_rel: str = "") -> Dict[str, Any]:
    """넘치는(8줄 초과) 번역 대사를 정돈해 저장 대상 proj 를 갱신. 반환: {tidied, still_over}.
    실제로 줄 수가 준 유닛만 손대고, 정돈해도 여전히 넘치는 수도 함께 돌려준다."""
    tidied = 0
    still_over = 0
    for rel, f in proj["files"].items():
        if scope == "file" and rel != cur_rel:
            continue
        for u in f["units"]:
            if u["kind"] != "free" or u.get("control"):
                continue
            if u.get("cat") not in _MSG_CATS:
                continue
            ko = textcodec.decode_field(u["field"], u.get("ko", ""))
            if not ko.strip():
                continue
            units = LINE_UNITS_IMG if u.get("img") else LINE_UNITS
            if wrap_rows(ko, units) <= WRAP_ROWS:
                continue
            new = tidy_text(ko)
            if new != ko:
                u["ko"] = textcodec.encode_field(u["field"], new)
                tidied += 1
                ko = new
            if wrap_rows(ko, units) > WRAP_ROWS:
                still_over += 1
    return {"tidied": tidied, "still_over": still_over}


def find_overflow(proj: Dict[str, Any], scope: str = "all",
                  cur_rel: str = "", cap: int = 500) -> List[dict]:
    """8줄을 넘겨 잘리는 번역 대사 목록. scope: 'all'|'file'(cur_rel 만).
    반환: [{rel,sid,cat,speaker,rows,over,img,ko}] — 넘침 큰 순."""
    out: List[dict] = []
    for rel, f in proj["files"].items():
        if scope == "file" and rel != cur_rel:
            continue
        for u in f["units"]:
            if u["kind"] != "free" or u.get("control"):
                continue
            if u.get("cat") not in _MSG_CATS:
                continue
            ko = textcodec.decode(u.get("ko", ""))
            if not ko.strip():          # 번역된 대사만
                continue
            units = LINE_UNITS_IMG if u.get("img") else LINE_UNITS
            rows = wrap_rows(ko, units)
            if rows <= WRAP_ROWS:
                continue
            out.append({
                "rel": rel, "sid": u["id"], "cat": u.get("cat"),
                "speaker": u.get("speaker"),
                "rows": rows, "over": rows - WRAP_ROWS,
                "img": bool(u.get("img")),
                "ko": ko.replace("\n", " ").strip()[:100],
            })
            if len(out) >= cap:
                out.sort(key=lambda r: r["rows"], reverse=True)
                return out
    out.sort(key=lambda r: r["rows"], reverse=True)
    return out

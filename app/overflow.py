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


def tidy_trailing(text: str) -> str:
    """끝의 빈 줄만 제거 — '간단 정돈'. 줄바꿈(레이아웃)은 일절 건드리지 않는다."""
    lines = (text or "").split("\n")
    while lines and lines[-1].strip() == "":
        lines.pop()
    return "\n".join(lines)


def _needs_rewrap(jp: str, ko: str, units: int) -> bool:
    """번역이 원문보다 줄 수가 많고, 번역 최대 줄폭이 원문 최대 줄폭 수준에
    머무는 경우 — 자동번역이 원문의 좁은 줄폭을 따라 재줄바꿈한 흔적.
    (원문이 게임 폭보다 충분히 좁을 때만 — 재줄바꿈으로 얻는 게 있어야 한다)"""
    def _widths(text):
        return [sum(_char_units(c) for c in _CTRL.sub("", ln))
                for ln in text.split("\n") if ln.strip()]
    if len(ko.split("\n")) <= len(jp.split("\n")):
        return False
    jw, kw = _widths(jp), _widths(ko)
    if not jw or not kw:
        return False
    return max(jw) < units * 0.9 and max(kw) <= max(max(jw) + 2, units * 0.7)


def _jp_gap(jp: str) -> int:
    """원문 텍스트 줄 사이 빈 줄 수(더블 스페이싱)의 최빈값."""
    gaps: List[int] = []
    gap = None
    for ln in jp.split("\n"):
        if ln.strip():
            if gap is not None:
                gaps.append(gap)
            gap = 0
        elif gap is not None:
            gap += 1
    return max(set(gaps), key=gaps.count) if gaps else 0


def merge_matching_leads(jp: str, ko: str, units: int) -> str:
    """원문이 줄마다 다른 들여쓰기(레이아웃)를 가질 때: 자동번역이 한 원문 줄을
    같은 들여쓰기의 연속 줄로 쪼갠 것을 다시 합쳐, 번역의 들여쓰기 구성이
    원문과 정확히 일치할 때만 채택한다. 합친 줄이 게임 폭을 넘으면 병합 안 함."""
    from . import azure_mt as az     # 함수 내 임포트 (모듈 순환 방지)

    def parse(text):
        lead_blank, entries = 0, []
        for ln in text.split("\n"):
            if ln.strip():
                entries.append(az._split_lead(ln))
            elif not entries:
                lead_blank += 1
        return lead_blank, entries

    _lb, jp_e = parse(jp)
    lead_blank, ko_e = parse(ko)
    jp_leads = [l for l, _ in jp_e]
    if len(ko_e) <= len(jp_leads):
        return ko
    merged: List[tuple] = []
    for lead, body in ko_e:
        if merged and merged[-1][0] == lead:
            cand = merged[-1][1] + " " + body.strip()
            if sum(_char_units(c) for c in _CTRL.sub("", lead + cand)) <= units:
                merged[-1] = (lead, cand)
                continue
        merged.append((lead, body.rstrip()))
    if [l for l, _ in merged] != jp_leads:
        return ko                    # 원문 줄 구성과 안 맞으면 손대지 않는다
    sep = _jp_gap(jp)
    out = [""] * lead_blank
    for i, (lead, body) in enumerate(merged):
        out.append(lead + body)
        if i < len(merged) - 1:
            out.extend([""] * sep)
    return "\n".join(out)


def flatten_text(ko: str) -> str:
    """넘침 최후 수단: 모든 줄머리 들여쓰기(전각공백)와 빈 줄을 걷어내고
    한 문단으로 합쳐 게임 자동 줄바꿈에 맡긴다. 색상코드(&R 등)는 유지."""
    texts = [ln.strip() for ln in (ko or "").split("\n") if ln.strip()]
    return " ".join(texts)


def rewrap_narrow(jp: str, ko: str, units: int) -> str:
    """잘게 쪼개진 번역을 게임 폭(units)으로 다시 접는다.

    본문 줄들을 이어붙여 azure_mt._wrap 으로 재줄바꿈하고, 들여쓰기(줄머리)와
    원문의 줄 간격(더블 스페이싱 = 줄 사이 빈 줄 수 최빈값)을 재현한다."""
    from . import azure_mt as az     # 함수 내 임포트 (모듈 순환 방지)
    ko_lines = ko.split("\n")
    texts = [ln for ln in ko_lines if ln.strip()]
    if len(texts) < 2:
        return ko
    lead_blank = 0                   # 선행 빈 줄 보존
    for ln in ko_lines:
        if ln.strip():
            break
        lead_blank += 1
    lead0, first_body = az._split_lead(texts[0])
    lead_cont = az._split_lead(texts[1])[0]
    if "　" in lead_cont:
        lead_cont = lead_cont.replace(" ", "").replace("\t", "")
    # 한국어는 단어 사이 공백이 필요 — 줄들을 한 칸 띄워 이어붙인다
    body = " ".join([first_body.rstrip()] + [t.strip() for t in texts[1:]])
    wrapped = az._wrap(body, units, lead0, lead_cont)
    sep = _jp_gap(jp)   # 원문 더블 스페이싱 재현
    out = [""] * lead_blank
    for i, wl in enumerate(wrapped):
        out.append(wl)
        if i < len(wrapped) - 1:
            out.extend([""] * sep)
    return "\n".join(out)


def tidy_overflow(proj: Dict[str, Any], scope: str = "all", cur_rel: str = "",
                  mode: str = "full") -> Dict[str, Any]:
    """넘치는(8줄 초과) 번역 대사를 정돈해 저장 대상 proj 를 갱신. 반환: {tidied, still_over}.
    실제로 줄 수가 준 유닛만 손대고, 정돈해도 여전히 넘치는 수도 함께 돌려준다.
    mode: "full"=문단 안 수동 줄바꿈 제거+끝 빈 줄 제거(상세) / "simple"=끝 빈 줄만(간단).
    상세 모드는 8줄 초과 외에 "원문보다 잘게 쪼개진 대사"(_needs_rewrap)도 정돈한다."""
    tidy = tidy_text if mode == "full" else tidy_trailing
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
            over = wrap_rows(ko, units) > WRAP_ROWS
            if mode == "full":
                jp = textcodec.decode_field(u["field"], u["jp"])
                narrow = _needs_rewrap(jp, ko, units)
                lead_merge = merge_matching_leads(jp, ko, units)
                if not over and not narrow and lead_merge == ko:
                    continue
                # 후보를 온건한 순서로: ①들여쓰기 병합(원문 구성 복원)
                # ②게임 폭 재줄바꿈 ③문단 합치기 ④(넘침 한정) 전부 걷어내고 합치기.
                # 8줄 안에 들어오는 가장 온건한 후보를 채택, 없으면 접힘 최소인 것.
                cand = []
                if lead_merge != ko:
                    cand.append(lead_merge)
                if narrow:
                    cand.append(rewrap_narrow(jp, ko, units))
                cand.append(tidy_text(ko))
                if over:
                    cand.append(flatten_text(ko))
                score = lambda t: (wrap_rows(t, units), len(t.split("\n")))
                new = next((t for t in cand
                            if score(t) < score(ko) and wrap_rows(t, units) <= WRAP_ROWS),
                           None)
                if new is None:
                    new = min(cand, key=score)
                    if score(new) >= score(ko):
                        new = ko                  # 개선 없으면 그대로
            else:
                if not over:
                    continue
                new = tidy_trailing(ko)
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

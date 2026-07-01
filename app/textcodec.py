# -*- coding: utf-8 -*-
"""
CardWirth 텍스트 이스케이프 ↔ 사람이 읽는 형태 변환.

CardWirth(encodewrap)는 저장 시  '\\' → '\\\\' ,  개행 → '\\n'  으로 인코딩한다.
에디터에서는 '\\n' 을 실제 줄바꿈으로 보여주고(decode), 사용자가 줄바꿈으로 입력한
한국어를 다시 '\\n' 으로 되돌려(encode) 저장한다.
"""
from __future__ import annotations


def decode(s: str) -> str:
    """저장형(CardWirth) → 표시형(실제 줄바꿈)."""
    if not s:
        return s or ""
    out = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            nx = s[i + 1]
            if nx == "n":
                out.append("\n"); i += 2; continue
            if nx == "\\":
                out.append("\\"); i += 2; continue
        out.append(c)
        i += 1
    return "".join(out)


def encode(s: str) -> str:
    """표시형 → 저장형(CardWirth). 백슬래시 먼저 이스케이프 후 개행 치환."""
    if not s:
        return s or ""
    s = s.replace("\\", "\\\\")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("\n", "\\n")
    return s


# CardWirth encodewrap(\\·\n 이스케이프)은 요소 본문(#text)에만 적용된다.
# 속성 값(@name 선택지 라벨 등)은 raw 저장이라 이스케이프하면 안 된다(백슬래시 이중화 → 토큰 깨짐).
def decode_field(field: str, s: str) -> str:
    return decode(s) if field == "#text" else (s or "")


def encode_field(field: str, s: str) -> str:
    return encode(s) if field == "#text" else (s or "")

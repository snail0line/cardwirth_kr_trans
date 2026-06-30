# -*- coding: utf-8 -*-
"""
CardWirthPy XML 의 번역 대상 분류 규칙.

두 부류:
  - free   : occurrence 별 독립 번역 (대사/설명/제목/선택지 라벨)
  - entity : 이름으로 참조되는 식별자 (Flag/Step/Coupon/Gossip/Scenario/KeyCode/Link)
             고유 원문 1개당 1번역, 정의부+모든 참조처에 동일 적용 → 시나리오 깨짐 방지

분류는 (요소 tag, 부모 tag, 속성명) 컨텍스트로 결정한다.
"""
from __future__ import annotations
import re
from typing import List, NamedTuple, Optional


# ── 엔티티 종류(namespace) ───────────────────────────────────────────────
ENT_FLAG = "Flag"
ENT_STEP = "Step"
ENT_COUPON = "Coupon"
ENT_GOSSIP = "Gossip"
ENT_SCENARIO = "Scenario"
ENT_KEYCODE = "KeyCode"
ENT_LINK = "Link"


# ── 엔티티 정의부: 요소 텍스트(#text) ──────────────────────────────────────
# (요소 tag, 부모 tag 또는 None) -> 엔티티 종류
ENTITY_TEXT_DEF = {
    ("Name", "Flag"): ENT_FLAG,
    ("Name", "Step"): ENT_STEP,
    ("Coupon", None): ENT_COUPON,
    ("RequiredCoupons", None): ENT_COUPON,
    ("KeyCode", None): ENT_KEYCODE,
    ("KeyCodes", None): ENT_KEYCODE,
    ("Scenario", None): ENT_SCENARIO,
    # 이벤트 콘텐츠에서 엔티티명이 '요소 텍스트'로 참조되는 형태.
    # (Summary 의 <Flag>/<Step> 컨테이너는 직접 텍스트가 비어 있어 매칭 안 됨)
    ("Flag", None): ENT_FLAG,
    ("Step", None): ENT_STEP,
    ("Gossip", None): ENT_GOSSIP,
}

# ── 엔티티 참조부/정의부: 속성 ─────────────────────────────────────────────
# 속성명 -> 엔티티 종류 (어느 요소든)
ENTITY_ATTR = {
    "flag": ENT_FLAG,
    "step": ENT_STEP,
    "coupon": ENT_COUPON,
    "gossip": ENT_GOSSIP,
    "scenario": ENT_SCENARIO,
    "keycode": ENT_KEYCODE,
    "link": ENT_LINK,
}
# Link 타깃 앵커: <Start name="..."> 의 name 속성은 Link 엔티티 정의
ENTITY_ATTR_BY_TAG = {
    ("Start", "name"): ENT_LINK,
}

# ── 자유 텍스트: 요소 텍스트(#text) ────────────────────────────────────────
# 항상 자유 텍스트인 tag
# (Value = 스텝 값 라벨. 플래그/스텝과 같은 내부 로직 라벨이라 번역 대상에서 제외 — 사용자 결정)
FREE_TEXT_TAGS = {"Text", "Description"}
# 컨텍스트로 자유 텍스트가 되는 tag: <Name> (부모가 Flag/Step 이 아니면 제목류)
FREE_NAME_TAG = "Name"

# ── 자유 텍스트: 속성 ──────────────────────────────────────────────────────
# 선택지/메뉴 버튼 라벨. Start@name 은 위 ENTITY 로 빠지므로 제외.
FREE_ATTR = {"name"}

# 비텍스트 라벨 = 제어기호 / 분기 케이스 키.
# @name 의 값이 여기 해당하면 번역 대상이 아니므로 추출에서 제외한다.
#   - 시스템 버튼/기호: ＯＫ ○ × △ Ｙｅｓ Ｎｏ Default ...
#   - 분기 케이스 키: 순수 숫자(스텝값 인덱스), 전각숫자
CONTROL_LABELS = {
    "", "ＯＫ", "OK", "○", "×", "△", "▽", "→", "←", "↑", "↓", "□", "■",
    "ＴＲＵＥ", "ＦＡＬＳＥ", "TRUE", "FALSE",
    "Ｙｅｓ", "Ｎｏ", "Yes", "No", "Default", "ＤＥＦＡＵＬＴ",
}
_FULLWIDTH_DIGITS = "０１２３４５６７８９"


# CWXEditor/CardWirthPy 가 미사용 슬롯에 자동으로 채우는 더미 값.
#  예: 'Ｓｔｅｐ - 3', 'Step - 9', 'Ｆｌａｇ - 1' → 번역 대상 아님
_FILLER_RE = re.compile(r"^(?:Ｓｔｅｐ|Step|Ｆｌａｇ|Flag)\s*[-－]\s*[0-9０-９]+$")


def is_filler_value(value: str) -> bool:
    return bool(_FILLER_RE.match((value or "").strip()))


def is_nontext_label(value: str) -> bool:
    """@name 값이 번역 대상 아닌(제어기호/분기 케이스 키) 라벨인지."""
    v = (value or "").strip()
    if v in CONTROL_LABELS:
        return True
    # 순수 숫자(반각/전각) = 분기 케이스 키
    if v and all(c.isdigit() or c in _FULLWIDTH_DIGITS for c in v):
        return True
    return False

# 절대 제외(파일 경로/이미지 등)
SKIP_ATTRS = {"path", "imagepath"}
SKIP_TAGS = {"ImagePath"}


class Slot(NamedTuple):
    """문서 순서상의 한 번역 슬롯."""
    field: str            # "#text" 또는 "@<attr>"
    tag: str              # 요소 tag
    parent: Optional[str] # 부모 tag
    kind: str             # "free" | "entity"
    etype: Optional[str]  # entity 일 때 종류
    value: str            # 원문(JP) 텍스트


def _norm_text(s: Optional[str]) -> str:
    return s if s is not None else ""


def slot_for_text(tag: str, parent: Optional[str], text: Optional[str]) -> Optional[Slot]:
    """요소 텍스트(#text)에 대한 슬롯 분류."""
    val = _norm_text(text).strip()
    if not val:
        return None
    if tag in SKIP_TAGS:
        return None
    # 엔티티 정의부 (텍스트)
    et = ENTITY_TEXT_DEF.get((tag, parent)) or ENTITY_TEXT_DEF.get((tag, None))
    if et:
        return Slot("#text", tag, parent, "entity", et, _norm_text(text))
    # 자동생성 더미값(Ｓｔｅｐ - N 등)은 번역 대상 아님
    if is_filler_value(val):
        return None
    # 자유 텍스트
    if tag in FREE_TEXT_TAGS:
        return Slot("#text", tag, parent, "free", None, _norm_text(text))
    if tag == FREE_NAME_TAG and parent not in ("Flag", "Step"):
        return Slot("#text", tag, parent, "free", None, _norm_text(text))
    return None


def slot_for_attr(tag: str, attr: str, value: str) -> Optional[Slot]:
    """속성 값에 대한 슬롯 분류."""
    if value is None or value == "":
        return None
    a = attr.lower()
    if a in SKIP_ATTRS:
        return None
    # 엔티티 앵커 (Start@name 등)
    et = ENTITY_ATTR_BY_TAG.get((tag, attr))
    if et:
        return Slot(f"@{attr}", tag, None, "entity", et, value)
    # 엔티티 참조 속성
    et = ENTITY_ATTR.get(a)
    if et:
        return Slot(f"@{attr}", tag, None, "entity", et, value)
    # 자유 텍스트 속성(선택지 라벨) — 단, 제어기호/분기 케이스 키(숫자/○×/Default 등)는 제외
    if a in FREE_ATTR:
        if is_nontext_label(value):
            return None
        return Slot(f"@{attr}", tag, None, "free", None, value)
    return None


def is_control_label(value: str) -> bool:
    return value.strip() in CONTROL_LABELS

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
}
# <Start name>(정의) ↔ <Link link>/<Call call>(참조) = 라인 간 점프 라벨.
# 이름 매칭으로 연결되므로 ENT_LINK 엔티티로 다룬다(고유 원문 1개당 1번역 →
# 정의부+참조부 동시 적용 = 매칭 유지). The Cave 등 식별자까지 번역하는 시나리오 지원
# (2026-07-22 — 2026-07-04 "비노출이라 스킵" 결정 번복: 매칭만 유지되면 번역 허용).
# ※ type="Package" 의 link/call 값은 대상 패키지 Id(숫자)라 번역 대상이 아님 → 숫자면 스킵.
LINK_ATTRS = {("Start", "name"), ("Link", "link"), ("Call", "call"),
              ("Link", "call"), ("Call", "link")}

# ── 자유 텍스트: 요소 텍스트(#text) ────────────────────────────────────────
# 항상 자유 텍스트인 tag
FREE_TEXT_TAGS = {"Text", "Description"}
# 플래그/스텝의 "표시값" — %상태변수% 로 메시지에 삽입돼 플레이어에게 보이는 텍스트일 수
# 있어 번역 대상(2026-07-04 사용자 결정으로 포함 전환. 예: Flag False 값에 문장을 넣고
# %02/食事済？% 로 표시하는 시나리오). 로직 식별자는 Name 이라 표시값 번역은 안전.
# ＴＲＵＥ/숫자 같은 제어성 라벨은 is_nontext_label 로 걸러 노이즈를 줄인다.
# ⚠ 슬롯 생성은 무조건(상태 없는 규칙 — sid 정합성), "%이름% 으로 실제 표시되는
# 변수인지" 필터는 extract.py 가 유닛 등록 단계에서 한다(표시 안 되는 변수의 값은
# 로직 전용이라 번역 대상이 아님 — 사용자 설계).
FREE_VALUE_TAGS = {("True", "Flag"), ("False", "Flag"), ("Value", "Step")}
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

# 제어코드/치환자/변수 — 이것들(과 공백)뿐인 텍스트는 번역할 내용이 없다.
#  예: "&B\n　%02/食事済？%" (상태변수 표시 전용 메시지)
# raw XML 의 #text 는 줄바꿈이 CardWirth 이스케이프(백슬래시+n 두 글자)라 그것도 걷어낸다.
_TOKEN_RE = re.compile(r"\\n|&[A-Za-z]|#[0-9A-Za-z]|\$[^$\n]*\$|%[^%\n]*%")


def is_tokens_only(value: str) -> bool:
    return not _TOKEN_RE.sub("", value or "").strip()


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
    # (제어코드/치환자뿐인 텍스트도 슬롯은 만든다 — extract 가 control 표시하고
    #  UI 가 읽기전용 + 변수 정의로 점프하는 링크를 붙인다)
    # 자유 텍스트
    if tag in FREE_TEXT_TAGS:
        return Slot("#text", tag, parent, "free", None, _norm_text(text))
    if tag == FREE_NAME_TAG and parent not in ("Flag", "Step"):
        return Slot("#text", tag, parent, "free", None, _norm_text(text))
    # 플래그/스텝 표시값 — 제어성 라벨(ＴＲＵＥ/숫자/기호)은 제외
    if (tag, parent) in FREE_VALUE_TAGS and not is_nontext_label(val):
        return Slot("#text", tag, parent, "free", None, _norm_text(text))
    return None


def slot_for_attr(tag: str, attr: str, value: str) -> Optional[Slot]:
    """속성 값에 대한 슬롯 분류."""
    if value is None or value == "":
        return None
    a = attr.lower()
    if a in SKIP_ATTRS:
        return None
    # Link/Start/Call 점프 라벨 → ENT_LINK 엔티티. 단 type="Package" 의 숫자 Id 는
    # 로직 참조라 제외(is_nontext_label 이 순수 숫자를 걸러 준다).
    if (tag, a) in LINK_ATTRS:
        if is_nontext_label(value):
            return None
        return Slot(f"@{attr}", tag, None, "entity", ENT_LINK, value)
    if a == "link":
        return None   # 그 밖의 @link(대상 참조)는 번역 대상 아님
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

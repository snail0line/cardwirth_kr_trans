# -*- coding: utf-8 -*-
"""대사(<Text>)의 번역 컨텍스트 추출: 화자 / 분기 조건(쿠폰·플래그·스텝) / 말투.

CardWirth 대사 구조:
  - <Talk type="Message" path="..."><Text>...</Text></Talk>          (단일 화자 대사)
  - <Talk type="Dialog"><Dialogs><Dialog><RequiredCoupons>＿「尊大」</RequiredCoupons>
        <Text>...</Text></Dialog>...</Talk>                            (말투별 변형)
  - 위가 <Branch type="Coupon" coupon="＿○○派"> 등으로 감싸여 파벌/조건별로 갈림
"""
from __future__ import annotations
import os as _os

# 표준 말투(口調) 쿠폰 → 읽기 쉬운 라벨. 변형 표기(＿「尊大」 / ＿尊大 모두 매칭)
_TONE = {
    "尊大": "거만", "粗雑": "거침", "老人": "노인", "子供": "아이",
    "慇懃": "공손", "女語": "여성", "男語": "남성", "丁寧": "정중",
    "乱暴": "난폭", "famille": "여성", "ですます": "정중", "ぼく": "소년",
    "尊大ぶり": "거만", "中性": "중성", "方言": "사투리",
}

# 동적 화자 토큰(?? 접두)
_DYN_SPEAKER = {
    "??Selected": "선택된 PC", "??Random": "랜덤 PC", "??Unselected": "비선택 PC",
    "??Valued": "지정 PC",
}


def _clean_coupon(s: str) -> str:
    """＿「尊大」\\n → 尊大,  ＿ソース派 → ソース派"""
    s = (s or "").strip().strip("\\n").strip()
    if s.startswith("＿"):
        s = s[1:]
    s = s.strip("「」")
    return s


_TARGET = {"Random": "랜덤 PC", "Selected": "선택 PC", "Unselected": "비선택 PC",
           "Valued": "지정 PC"}


def _embedded_name(el) -> str:
    """Message 대사 본문의 첫 줄이 화자 이름인 경우 추출.
    형식: "親父\\n「おはよう…」" → 첫 줄(짧음) + 다음 줄이 「 로 시작하면 그 첫 줄이 이름.
    초상화 파일명(CAST_012_ 등)보다 실제 이름이 우선."""
    txt = (el.text or "").replace("\\n", "\n")
    lines = [ln.strip() for ln in txt.split("\n") if ln.strip()]
    if len(lines) >= 2 and len(lines[0]) <= 12 \
            and lines[0][0] not in "「#＃" and lines[1].startswith("「"):
        return lines[0]
    return ""


def speaker_of(ancestors, el) -> str:
    """가장 가까운 <Talk> 조상의 화자.
    - Message 본문 첫 줄이 이름 형식이면 그 이름(실제 캐릭터명 우선)
    - path(화자 이미지)가 있으면 그 이름(NPC 초상화)
    - 없고 Dialog형/target 지정이면 PC 발화(targetm 으로 랜덤/선택 PC)
    - 둘 다 없으면 나레이션('')"""
    for a in reversed(ancestors):
        if a.tag != "Talk":
            continue
        if a.get("type") == "Message":
            nm = _embedded_name(el)
            if nm:
                return nm
        path = a.get("path") or ""
        if path:
            base = _os.path.basename(path.replace("\\", "/"))
            if base in _DYN_SPEAKER:
                return _DYN_SPEAKER[base]
            if base.startswith("??"):
                return base[2:] or base
            base = _os.path.splitext(base)[0]
            for pre in ("Cast_", "cast_"):
                if base.startswith(pre):
                    base = base[len(pre):]
            return base
        # path 없음: Dialog형(말투 변형) 또는 target 지정이면 PC 발화
        tgt = a.get("targetm") or a.get("targetf") or a.get("target") or ""
        if a.get("type") == "Dialog" or tgt:
            return _TARGET.get(tgt, "PC")
        return ""
    return ""


def tone_of(ancestors, el) -> str:
    """대사가 <Dialog> 안의 말투 변형이면, 그 RequiredCoupons → 말투 라벨."""
    parent = ancestors[-1] if ancestors else None
    if parent is None or parent.tag != "Dialog":
        return ""
    rc = parent.find("RequiredCoupons")
    if rc is None or not (rc.text or "").strip():
        return ""
    raw = _clean_coupon(rc.text)
    return _TONE.get(raw, raw)

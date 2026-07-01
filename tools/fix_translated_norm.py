# -*- coding: utf-8 -*-
"""이미 번역된 프로젝트(JSON)의 ko 텍스트를 정규화 규칙으로 소급 보정한다.

app/deepl.py 후처리가 강화되기 전에 만들어진 번역 초안에는 두 가지 흔적이 남는다.
  1) 말줄임표: 전각 '…' 가 ASCII '...' 로 바뀐 것 → '…' 로 복원
  2) 줄머리 들여쓰기 오배치: 원문 `　#U…`(들여쓰기+치환코드)가 `#U　는`처럼 코드와 조사
     사이에 전각공백이 끼워진 것 → `　#U는` 으로 스왑(들여쓰기를 코드 앞으로 복원)

파이프라인(app/deepl.py) 은 이제 이 둘을 발생 단계에서 막으므로, 이 스크립트는
"기존 데이터 소급 보정" 전용이다. 저장 포맷은 app/project.py 와 동일(ensure_ascii=False,
indent=1). 실행 전 원본을 .bak 로 백업한다.

사용:
  python tools/fix_translated_norm.py <project.json> [...]   # 특정 파일
  python tools/fix_translated_norm.py --all                  # projects/*.json 전체
  옵션: --dry (미저장, 리포트만)
"""
from __future__ import annotations
import os
import re
import sys
import glob
import json
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app import deepl  # _restore_ellipsis 재사용(파이프라인과 동일 규칙)

_PROJECTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "projects"))

# 줄머리(문자열 시작 또는 인코딩 개행 '\n' 직후) 의 `#코드 + 전각공백` 을
# `전각공백 + #코드` 로 되돌린다. 저장 문자열에서 개행은 리터럴 '\'+'n' 두 글자.
_SPACE_BUG = re.compile(r"(\\n|^)(#[0-9A-Za-z])(　+)")


def _fix_space(ko: str) -> str:
    return _SPACE_BUG.sub(lambda m: m.group(1) + m.group(3) + m.group(2), ko)


def fix_project(path: str, dry: bool = False) -> dict:
    with open(path, encoding="utf-8") as f:
        proj = json.load(f)
    n_ell = n_sp = n_unit = 0
    for fd in proj.get("files", {}).values():
        for u in fd.get("units", []):
            if u.get("kind") != "free":
                continue
            ko = u.get("ko", "")
            if not ko:
                continue
            new = deepl._restore_ellipsis(u.get("jp", ""), ko)   # 1) 말줄임표
            if new != ko:
                n_ell += 1
            after = _fix_space(new)                               # 2) 들여쓰기 스왑
            if after != new:
                n_sp += 1
            if after != ko:
                n_unit += 1
                u["ko"] = after
    if not dry and n_unit:
        bak = path + ".bak"
        if not os.path.exists(bak):
            shutil.copy2(path, bak)              # 원본 바이트 그대로 백업(최초 1회)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(proj, f, ensure_ascii=False, indent=1)
    return {"file": os.path.basename(path), "units_changed": n_unit,
            "ellipsis": n_ell, "space_bug": n_sp, "saved": (not dry and bool(n_unit))}


def main(argv):
    dry = "--dry" in argv
    args = [a for a in argv if not a.startswith("--")]
    if "--all" in argv:
        paths = sorted(glob.glob(os.path.join(_PROJECTS, "*.json")))
    else:
        paths = args
    if not paths:
        print(__doc__)
        return 1
    for p in paths:
        r = fix_project(p, dry=dry)
        print(f"[{'DRY' if dry else 'FIX'}] {r['file']}: "
              f"유닛 {r['units_changed']} 변경 (말줄임표 {r['ellipsis']}, 들여쓰기 {r['space_bug']})"
              f"{' — 저장' if r['saved'] else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

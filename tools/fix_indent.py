# -*- coding: utf-8 -*-
"""
이미 DeepL 초벌이 들어간 프로젝트 JSON 의 DeepL 후처리 복구.

DeepL 이 망가뜨리는 두 가지를 원문(jp) 기준으로 되돌린다(번역 텍스트 자체는 유지):
  1) 줄머리 전각공백(U+3000) 들여쓰기 → 반각/삭제된 것 복원 (app/deepl._restore_indent)
  2) $...$ 변수 참조 안쪽 번역(예: $PC\\一人称$→$PC\\1인칭$) → 원문으로 복원 (_restore_vars)

사용:
  python tools/fix_indent.py projects/어떤시나리오.json            # 백업 후 제자리 수정
  python tools/fix_indent.py projects/어떤시나리오.json --dry-run   # 바뀔 개수만 출력
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import deepl, textcodec


def main() -> None:
    ap = argparse.ArgumentParser(description="프로젝트 JSON 줄머리 전각공백 들여쓰기 복구")
    ap.add_argument("json_path", help="복구할 프로젝트 JSON")
    ap.add_argument("--dry-run", action="store_true", help="저장 없이 바뀔 개수만 출력")
    args = ap.parse_args()

    with open(args.json_path, "r", encoding="utf-8") as f:
        proj = json.load(f)

    total = changed = skipped = 0
    for fd in proj["files"].values():
        for u in fd["units"]:
            if u.get("kind") != "free" or not u.get("ko"):
                continue
            total += 1
            jp = textcodec.decode(u["jp"])
            ko = textcodec.decode(u["ko"])
            fixed = ko
            if jp.count("\n") == ko.count("\n"):
                fixed = deepl._restore_indent(jp, fixed)   # 줄 구조 같을 때만 들여쓰기 복원
            else:
                skipped += 1
            fixed = deepl._restore_vars(jp, fixed)         # $...$ 변수는 줄 구조와 무관하게 복원
            if fixed != ko:
                changed += 1
                if not args.dry_run:
                    u["ko"] = textcodec.encode(fixed)

    print(f"free·ko 유닛 {total}개 · 복구 대상 {changed}개 · 들여쓰기 보류(줄구조 불일치) {skipped}개")
    if args.dry_run:
        return
    if not changed:
        print("바꿀 게 없습니다.")
        return

    backup = args.json_path + ".bak_before_indentfix"
    if not os.path.exists(backup):
        shutil.copy2(args.json_path, backup)
        print(f"백업: {backup}")
    with open(args.json_path, "w", encoding="utf-8") as f:
        json.dump(proj, f, ensure_ascii=False, indent=1)   # app/project.py 저장 포맷과 동일
    print(f"저장: {args.json_path}  (복구 {changed}개)")


if __name__ == "__main__":
    main()

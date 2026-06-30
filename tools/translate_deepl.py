# -*- coding: utf-8 -*-
"""
DeepL 로 일괄 CSV(file,id,jp,ko) 의 빈 ko 를 자동 번역(JA→KO).

에디터에서 "CSV 내보내기" 한 파일을 이 스크립트로 돌려 ko 를 채운 뒤,
다시 에디터에서 "CSV 가져오기" 하면 된다. (웹앱의 "DeepL 초안" 과 동일 엔진)

사용:
  python tools/translate_deepl.py 내보낸.csv
  python tools/translate_deepl.py 내보낸.csv -o 번역됨.csv
  python tools/translate_deepl.py 내보낸.csv --limit 20      # 앞 20개만(테스트)
  python tools/translate_deepl.py 내보낸.csv --all           # 이미 채워진 ko 도 다시 번역
  python tools/translate_deepl.py 내보낸.csv --dry-run        # 호출 안 하고 대상 개수만
  python tools/translate_deepl.py 내보낸.csv --free           # 무료 엔드포인트 강제

API 키: 환경변수 DEEPL_API_KEY 또는 tools/.deepl_key(.txt) 파일. (app/deepl.py 가 로드)
"""
from __future__ import annotations
import argparse
import csv
import os
import sys

try:                                    # 콘솔이 cp932 여도 한국어 로그가 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import deepl


def main() -> None:
    ap = argparse.ArgumentParser(description="DeepL 로 CSV ko 일괄 번역")
    ap.add_argument("csv_in", help="에디터에서 내보낸 CSV")
    ap.add_argument("-o", "--out", help="출력 CSV (생략 시 입력파일 옆 *_ko.csv)")
    ap.add_argument("--all", action="store_true", help="이미 채워진 ko 도 다시 번역")
    ap.add_argument("--limit", type=int, default=0, help="번역할 최대 개수(테스트용)")
    ap.add_argument("--dry-run", action="store_true", help="API 호출 없이 대상 개수만 출력")
    ap.add_argument("--free", dest="force", action="store_const", const="free",
                    default="auto", help="무료 엔드포인트 강제(키 :fx 자동판별 무시)")
    ap.add_argument("--pro", dest="force", action="store_const", const="pro",
                    help="Pro 엔드포인트 강제")
    args = ap.parse_args()

    with open(args.csv_in, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit("빈 CSV 입니다.")

    targets = []  # 번역할 행 인덱스
    for i, r in enumerate(rows):
        jp = (r.get("jp") or "")
        ko = (r.get("ko") or "").strip()
        if not jp.strip():
            continue
        if ko and not args.all:
            continue
        targets.append(i)
    if args.limit > 0:
        targets = targets[: args.limit]

    uniq = list(dict.fromkeys(rows[i]["jp"] for i in targets))
    print(f"행 {len(rows)}개 · 번역 대상 {len(targets)}개 · 고유 텍스트 {len(uniq)}개")
    if args.dry_run:
        return
    if not uniq:
        print("번역할 게 없습니다.")
        return

    def prog(done, total):
        print(f"  {done}/{total} 완료")

    try:
        trans = deepl.translate_texts(uniq, force=args.force, progress=prog)
    except deepl.DeepLError as e:
        sys.exit(f"DeepL 오류: {e}")

    for i in targets:
        rows[i]["ko"] = trans.get(rows[i]["jp"], rows[i].get("ko", ""))

    out_path = args.out or (os.path.splitext(args.csv_in)[0] + "_ko.csv")
    fields = ["file", "id", "jp", "ko"]
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"저장: {out_path}  (번역 {len(targets)}행)")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
DeepL vs Azure Translator 번역 품질 A/B 비교 (JA→KO).

같은 일본어 원문 샘플을 두 엔진에 보내고, 나란히 비교할 수 있는 CSV 를 만든다.
후처리 정규화(app/deepl.py 의 _restore_*)는 양쪽에 동일하게 적용되므로 순수 엔진 차이만 보인다.

입력: 프로젝트 JSON(projects/*.json) 또는 에디터 내보내기 CSV(file,id,jp,ko)
출력: _export_test/compare_deepl_azure.csv (열: jp, deepl, azure)

사용:
  python tools/compare_deepl_azure.py projects/무덤에피는꽃_wsn.json
  python tools/compare_deepl_azure.py 내보낸.csv --limit 100
  python tools/compare_deepl_azure.py projects/foo.json --dry-run   # 호출 없이 대상만 집계

API 키: tools/.deepl_key, tools/.azure_key (각 모듈이 로드)
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import sys

try:                                    # 콘솔이 cp932 여도 한국어 로그가 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import deepl, azure_mt

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DEFAULT = os.path.join(_ROOT, "_export_test", "compare_deepl_azure.csv")


def _load_jp(path: str) -> list:
    """프로젝트 JSON 또는 CSV 에서 일본어 원문 목록(중복 제거, 원래 순서)을 뽑는다."""
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as f:
            proj = json.load(f)
        targets = deepl._collect_targets(proj, overwrite=True)   # 이미 번역된 칸도 포함
        jps = [jp for _, jp in targets]
    else:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            jps = [(r.get("jp") or "") for r in csv.DictReader(f)]
    return list(dict.fromkeys(j for j in jps if j.strip()))


def _sample(items: list, n: int) -> list:
    """전체에서 고르게 n개 추출(등간격) — 재현 가능하고 파일 전반을 커버한다."""
    if n <= 0 or n >= len(items):
        return items
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def main() -> None:
    ap = argparse.ArgumentParser(description="DeepL vs Azure JA→KO 비교 CSV 생성")
    ap.add_argument("src", help="프로젝트 JSON(projects/*.json) 또는 내보내기 CSV")
    ap.add_argument("-o", "--out", default=_OUT_DEFAULT, help="출력 CSV 경로")
    ap.add_argument("--limit", type=int, default=50, help="비교할 문장 수(고르게 샘플, 기본 50)")
    ap.add_argument("--dry-run", action="store_true", help="API 호출 없이 대상 개수·글자수만")
    args = ap.parse_args()

    jps = _load_jp(args.src)
    if not jps:
        sys.exit("일본어 원문이 없습니다.")
    sample = _sample(jps, args.limit)
    chars = sum(len(j) for j in sample)
    print(f"전체 고유 문장 {len(jps)}개 → 샘플 {len(sample)}개 · {chars}자 (엔진당)")
    if args.dry_run:
        return

    def prog(name):
        return lambda done, total: print(f"  [{name}] {done}/{total}")

    try:
        ko_deepl = deepl.translate_texts(sample, progress=prog("DeepL"))
    except deepl.DeepLError as e:
        sys.exit(f"DeepL 오류: {e}")
    try:
        # 비교 목적이므로 복원 실패해도 훼손된 Azure 출력을 그대로 본다 (DeepL 폴백/스킵 없음)
        ko_azure = azure_mt.translate_texts(sample, progress=prog("Azure"), fallback="keep")
    except azure_mt.AzureError as e:
        sys.exit(f"Azure 오류: {e}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["jp", "deepl", "azure"])
        for jp in sample:
            w.writerow([jp, ko_deepl.get(jp, ""), ko_azure.get(jp, "")])
    print(f"저장: {args.out}  ({len(sample)}행 — 엑셀에서 열어 나란히 비교)")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""문제 목록 단일 채널 — 흩어진 검사 결과를 한 모양으로 모은다.

지금까지 자동번역 복원 실패(mt_failed)·넘침(overflow)·선택지 중복번역(dupchoice)·
용어 불일치(term_check)가 각각 다른 API·다른 모양으로 프런트에 갔다. 새 검사기를
붙일 때마다 프런트를 고쳐야 했으므로, 여기서 `Issue` 한 형태로 통일한다.

  level   'error' | 'warn'
  kind    'mt_failed' | 'overflow' | 'dup_choice' | 'term' | 'josa' | 'flow'
  rel/sid 점프 좌표 (sid 없으면 파일만)
  message 사람이 읽는 한 줄

기존 API(/api/mt_failed 등)는 그대로 둔다 — 이 모듈은 읽기 전용 집계다.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional

from . import azure_mt, overflow, dupchoice, terms, textcodec, josa, flowcheck

KIND_LABEL = {
    "flow": "흐름 구조", "dup_choice": "선택지 중복번역", "mt_failed": "자동번역 복원 실패",
    "overflow": "메시지창 넘침", "term": "용어 불일치", "josa": "조사 보정",
}
# 표시 순서 — 치명적인 것부터
KIND_ORDER = ("flow", "dup_choice", "mt_failed", "overflow", "term", "josa")


@dataclass
class Issue:
    level: str
    kind: str
    rel: str
    message: str
    sid: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["kind_label"] = KIND_LABEL.get(self.kind, self.kind)
        return d


def _in_scope(scope: str, rel: str, cur_rel: str) -> bool:
    return scope != "file" or rel == cur_rel


def collect(proj: Dict[str, Any], scope: str = "all", cur_rel: str = "",
            josa_all: bool = False, cap_per_kind: int = 300) -> List[dict]:
    """모든 검사기를 돌려 Issue 목록(dict)을 만든다. 종류별 cap_per_kind 상한."""
    out: List[Issue] = []

    # 흐름 구조 (파일 단위 좌표)
    for r in flowcheck.check_scenario(proj.get("scenario_dir") or ""):
        if _in_scope(scope, r["rel"], cur_rel):
            out.append(Issue(r["level"], "flow", r["rel"], r["message"],
                             extra={"where": r.get("where", "")}))

    for r in dupchoice.find_dup_choices(proj, scope, cur_rel, cap=cap_per_kind):
        first = r["items"][0]["sid"] if r.get("items") else None
        out.append(Issue("error", "dup_choice", r["rel"],
                         f"번역 “{r['ko']}” ×{r['count']} — 원문이 다른데 번역이 같아 선택지 구분 불가",
                         sid=first, extra={"items": r["items"]}))

    for r in azure_mt.failed_units(proj, cap=cap_per_kind):
        if _in_scope(scope, r["rel"], cur_rel):
            out.append(Issue("warn", "mt_failed", r["rel"],
                             f"복원 실패로 빈 칸: {r['jp']}", sid=r["sid"],
                             extra={"cat": r.get("cat")}))

    for r in overflow.find_overflow(proj, scope, cur_rel, cap=cap_per_kind):
        out.append(Issue("warn", "overflow", r["rel"],
                         f"{r['rows']}줄 (+{r['over']}) — {r['ko']}", sid=r["sid"],
                         extra={"cat": r.get("cat"), "speaker": r.get("speaker")}))

    for r in terms.term_mismatches(proj, cap=cap_per_kind):
        if _in_scope(scope, r["rel"], cur_rel):
            out.append(Issue("warn", "term", r["rel"],
                             f"{r['term']}→{r['term_ko']} 표기가 번역문에 없음: {r['ko']}",
                             sid=r["sid"], extra={"term": r["term"]}))

    out.extend(josa_issues(proj, scope, cur_rel, scan_all=josa_all, cap=cap_per_kind))

    order = {k: i for i, k in enumerate(KIND_ORDER)}
    out.sort(key=lambda i: (order.get(i.kind, 99), 0 if i.level == "error" else 1, i.rel))
    return [i.to_dict() for i in out]


def josa_issues(proj: Dict[str, Any], scope: str = "all", cur_rel: str = "",
                scan_all: bool = False, cap: int = 300) -> List[Issue]:
    """번역문(ko)의 조사 제안을 Issue 로. B등급(용어집 이름표)은 항상, C등급은 scan_all 일 때만."""
    names = {v.strip() for v in terms.effective_terms(proj).values() if (v or "").strip()}
    dic = josa.dictionary()
    texts: List[str] = []
    units = []
    for rel, f in proj["files"].items():
        for u in f["units"]:
            if u["kind"] != "free" or u.get("control"):
                continue
            ko = textcodec.decode_field(u["field"], u.get("ko", ""))
            if not ko.strip():
                continue
            texts.append(ko)
            if _in_scope(scope, rel, cur_rel):
                units.append((rel, u, ko))
    evidence = josa.build_evidence(texts) if scan_all else None
    out: List[Issue] = []
    for rel, u, ko in units:
        for s in josa.suggest(ko, names=names, dictionary=dic, evidence=evidence,
                              scan_all=scan_all):
            tag = "이름표" if s["grade"] == "B" else "문서 훑기"
            if s["risky"]:
                tag += " · 조심"
            out.append(Issue("warn", "josa", rel,
                             f"[{tag}] {s['base']}{s['from']} → {s['base']}{s['to']}",
                             sid=u["id"], extra={**s, "ko": ko[:80]}))
            if len(out) >= cap:
                return out
    return out

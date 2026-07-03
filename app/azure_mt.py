# -*- coding: utf-8 -*-
"""
Azure Translator(F0 무료 티어) JA→KO 번역 — DeepL 보완용.

키는 깃에 안 올라가는 tools/.azure_key 에 저장한다(.gitignore: *azure_key*).
  1줄: API 키, 2줄: 리소스 지역(예: koreacentral)
환경변수 AZURE_TRANSLATOR_KEY / AZURE_TRANSLATOR_REGION 이 있으면 그쪽이 우선.

Azure 는 DeepL 과 달리 $...$ 변수·#X 치환코드를 번역해 깨뜨린다. translate="no"
스팬으로 얼리면 토큰은 보존되지만 어순·조사가 붕괴하므로("말할 수 $PC\二人称$있나요"),
변수를 카타카나 이름(ミナ 등)으로 치환해 자연스러운 문장으로 번역시킨 뒤 음차된
이름을 원 토큰으로 되치환한다. 이름이 번역에서 생략되면(복원 실패) 기본은 빈 칸으로
남겨 이후 DeepL 초안(빈 칸만 채움)이 흡수하게 한다 — 몰래 DeepL 쿼터를 쓰지 않는다.
&X 색상코드는 단어가 아니므로 textType=html + <span translate="no"> 로 보호한다.
후처리(따옴표 억제·들여쓰기·$변수$·색상코드 공백·말줄임표 복원)는 deepl.py 의
_restore_* 를 그대로 태워, 어느 엔진을 쓰든 같은 정규화 기조의 출력이 나오게 한다.
"""
from __future__ import annotations
import datetime
import html
import json
import os
import re
import time
import urllib.request
import urllib.error
from typing import Dict, List, Callable, Optional

from . import deepl, textcodec

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_KEY_DIR = os.path.join(_ROOT, "tools")
_KEY_CANDIDATES = (".azure_key", ".azure_key.txt", "azure_key.txt")
_ENDPOINT = ("https://api.cognitive.microsofttranslator.com/translate"
             "?api-version=3.0&from=ja&to=ko&textType=html")
BATCH = 40          # Azure 한도는 요청당 1000건/5만자 — deepl.py 와 맞춰 40
RETRY = 3
LIMIT = 2_000_000   # F0 무료 티어 월 한도(자)

# Azure 는 DeepL 처럼 사용량 조회 API 가 없다(포털 메트릭 또는 AD 인증 관리 API 뿐).
# 이 툴이 키를 쓰는 유일한 창구이므로, 보낸 글자수를 로컬 파일에 월 단위로 자체 집계한다.
_USAGE_PATH = os.path.join(_KEY_DIR, ".azure_usage.json")


class AzureError(Exception):
    pass


def load_key() -> tuple:
    """(키, 지역) 반환. 없으면 ("", "")."""
    key = os.environ.get("AZURE_TRANSLATOR_KEY", "").strip()
    region = os.environ.get("AZURE_TRANSLATOR_REGION", "").strip()
    if key and region:
        return key, region
    for fn in _KEY_CANDIDATES:
        fp = os.path.join(_KEY_DIR, fn)
        if os.path.isfile(fp):
            with open(fp, "r", encoding="utf-8-sig") as f:
                # 'AZURE_TRANSLATOR_KEY=...' 처럼 .env 복붙 형태도 허용 (deepl.py 와 동일 규칙)
                lines = [deepl._parse_key_line(ln) for ln in f.read().splitlines() if ln.strip()]
            if lines:
                return lines[0], (lines[1] if len(lines) > 1 else region or "koreacentral")
    return key, region


def save_key(key: str, region: str) -> None:
    key = deepl._parse_key_line(key)
    region = deepl._parse_key_line(region) or "koreacentral"
    os.makedirs(_KEY_DIR, exist_ok=True)
    with open(os.path.join(_KEY_DIR, ".azure_key"), "w", encoding="utf-8") as f:
        f.write(key + "\n" + region + "\n")


def key_status() -> Dict[str, object]:
    """키 노출 없이 상태만. {set, region}."""
    k, r = load_key()
    return {"set": bool(k), "region": r or None}


def _read_usage() -> Dict[str, object]:
    month = datetime.date.today().strftime("%Y-%m")
    try:
        with open(_USAGE_PATH, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    if d.get("month") != month:                     # 월 바뀌면 리셋(Azure 도 월 단위 리셋)
        d = {"month": month, "chars": 0}
    return d


def _add_usage(chars: int) -> None:
    d = _read_usage()
    d["chars"] = int(d.get("chars", 0)) + chars
    try:
        with open(_USAGE_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except OSError:
        pass                                        # 집계 실패가 번역을 막으면 안 됨


def usage() -> Dict[str, int]:
    """이 툴에서 보낸 분량 기준 자체 집계. 반환: {count, limit, remaining}."""
    d = _read_usage()
    count = int(d.get("chars", 0))
    return {"count": count, "limit": LIMIT, "remaining": max(0, LIMIT - count)}


def _call(key: str, region: str, texts: List[str]) -> List[str]:
    body = json.dumps([{"Text": t} for t in texts]).encode("utf-8")
    req = urllib.request.Request(_ENDPOINT, data=body, method="POST")
    req.add_header("Ocp-Apim-Subscription-Key", key)
    req.add_header("Ocp-Apim-Subscription-Region", region)
    req.add_header("Content-Type", "application/json")
    last = None
    for attempt in range(RETRY):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            _add_usage(sum(len(t) for t in texts))  # 성공분만 집계(마크업 포함=보수적)
            return [item["translations"][0]["text"] for item in payload]
        except urllib.error.HTTPError as e:
            body_txt = e.read().decode("utf-8", "replace")
            if e.code == 429 or e.code >= 500:      # rate limit / 일시 오류 → 재시도
                last = f"HTTP {e.code}: {body_txt}"
                time.sleep(2 * (attempt + 1))
                continue
            raise AzureError(f"HTTP {e.code}: {body_txt}")
        except urllib.error.URLError as e:
            last = str(e)
            time.sleep(2 * (attempt + 1))
    raise AzureError(f"재시도 실패: {last}")


# 스팬 보호 대상: &X 색상코드만 (단어가 아니라 이름 치환이 불가능한 토큰).
_PROTECT = re.compile(r"&[rgbywopld]", re.I)
_TAG = re.compile(r"</?span[^>]*>")

# 이름 치환 대상: $...$ 변수 참조, #X 치환코드(캐릭터 이름 등).
_NAMEPAT = re.compile(r"\$[^$\n]*\$|#[0-9A-Za-z]")
# 치환용 이름 풀: (일본어, 허용 한국어 음차). 일반명사와 안 겹치고(ユリ=백합 오번역 사례)
# 어두가 유성음/모음이라 음차 표기가 흔들리지 않는 이름만 쓴다.
_NAMES = (("ミナ", ("미나",)), ("エマ", ("에마", "엠마")), ("ナオ", ("나오",)),
          ("リンネ", ("린네",)), ("アンナ", ("안나",)), ("サキ", ("사키",)))


def _mask_names(src: str) -> tuple:
    """변수/치환코드 → 이름. 동일 토큰은 동일 이름. 반환 (치환문, [(일본어, 음차들, 원토큰)]).

    원문에 이미 등장하는 이름은 쓰지 않는다 — 진짜 그 이름의 캐릭터가 있는 문장이면
    되치환 때 캐릭터 이름까지 변수로 오염되기 때문. 치환·복원이 문장 단위라
    다른 문장에 나오는 이름과는 충돌하지 않는다."""
    seen: Dict[str, str] = {}
    used = []
    avail = [n for n in _NAMES if n[0] not in src]

    def rep(m):
        tok = m.group()
        if tok not in seen:
            if len(seen) >= len(avail):         # 이름 풀 소진(변수 종류 과다/충돌) — 그대로 둠
                return tok
            jp, kos = avail[len(seen)]
            seen[tok] = jp
            used.append((jp, kos, tok))
        return seen[tok]

    return _NAMEPAT.sub(rep, src), used


def _unmask_names(dst: str, used) -> tuple:
    """번역문의 음차된 이름 → 원 토큰. 이름이 하나라도 생략됐으면 ok=False (폴백 대상)."""
    ok = True
    for jp, kos, tok in used:
        hit = False
        for ko in tuple(kos) + (jp,):           # 음차 또는 일본어 그대로 남은 경우
            if ko in dst:
                dst = dst.replace(ko, tok)
                hit = True
        if not hit:
            ok = False
    return dst, ok


def _mask(line: str) -> str:
    """보호 토큰을 <span translate="no"> 로 감싸고 나머지는 HTML 이스케이프."""
    out, last = [], 0
    for m in _PROTECT.finditer(line):
        out.append(html.escape(line[last:m.start()]))
        out.append('<span translate="no">' + html.escape(m.group()) + "</span>")
        last = m.end()
    out.append(html.escape(line[last:]))
    return "".join(out)


def _unmask(text: str) -> str:
    return html.unescape(_TAG.sub("", text))


def _fix_line(src_line: str, dst_line: str) -> str:
    """Azure 특유의 괄호 훼손을 줄 단위로 복원.
    · 【】 를 반각 [] 로 바꾸는 것 → 원문에 【】 있고 개수가 맞으면 되돌림
    · 줄 끝의 닫는 괄호(」』】)를 떨어뜨리는 것 → 원문 줄이 그 괄호로 끝나면 다시 붙임"""
    if "【" in src_line and "【" not in dst_line and dst_line.count("[") == src_line.count("【"):
        dst_line = dst_line.replace("[", "【")
    if "】" in src_line and "】" not in dst_line and dst_line.count("]") == src_line.count("】"):
        dst_line = dst_line.replace("]", "】")
    s, d = src_line.rstrip(), dst_line.rstrip()
    for cl in "」』】":
        if s.endswith(cl) and not d.endswith(cl) and d.count(cl) < src_line.count(cl):
            return d + cl
    return dst_line


def translate_texts(texts: List[str], key: Optional[str] = None, region: Optional[str] = None,
                    progress: Optional[Callable[[int, int], None]] = None,
                    fallback: str = "skip") -> Dict[str, str]:
    """텍스트 목록 JA→KO 번역. 중복 제거 후 한 번씩만 호출. 반환: {원문: 번역}.

    Azure 는 DeepL 의 preserve_formatting 같은 개행 보존 옵션이 없어, 여러 줄을 한 번에
    보내면 빈 줄이 사라지고 줄 구조가 뭉개진다(CardWirth 는 줄 배치가 곧 레이아웃).
    그래서 줄 단위로 쪼개 번역하고 원문 줄 구조 그대로 재조립한다.

    변수/치환코드는 이름 치환(_mask_names)으로 보내고, 번역에서 이름이 생략돼
    복원에 실패한 문장은 fallback 에 따라 처리한다:
      · "skip"  (기본): 결과에서 제외 → 초안이 빈 칸으로 남아 이후 DeepL 초안이 채운다.
                사용자 모르게 DeepL 쿼터를 쓰지 않기 위한 기본값.
      · "keep" : 훼손된 Azure 출력을 그대로 반환 (비교/디버깅용).
      · "deepl": DeepL 로 즉시 재번역 (쿼터 소모 — 명시적으로 요청할 때만)."""
    if not key:
        key, region = load_key()
    if not key:
        raise AzureError("Azure 키가 없습니다. tools/.azure_key (1줄 키, 2줄 지역)를 만드세요.")
    if not region:
        raise AzureError("Azure 지역이 없습니다. tools/.azure_key 2번째 줄에 지역(예: koreacentral)을 적으세요.")
    uniq = list(dict.fromkeys(t for t in texts if t and t.strip()))
    masked = {t: _mask_names(t) for t in uniq}      # 원문 → (이름 치환문, 사용한 이름들)
    lines = list(dict.fromkeys(
        ln for t in uniq for ln in masked[t][0].split("\n") if ln.strip()))
    trans: Dict[str, str] = {}
    for s in range(0, len(lines), BATCH):
        chunk = lines[s: s + BATCH]
        res = _call(key, region, [_mask(ln) for ln in chunk])
        if len(res) != len(chunk):
            raise AzureError(f"응답 개수 불일치: 요청 {len(chunk)} vs 응답 {len(res)}")
        trans.update(zip(chunk, (_unmask(r) for r in res)))
        if progress:
            progress(min(s + BATCH, len(lines)), len(lines))
    out: Dict[str, str] = {}
    failed: List[str] = []
    for src in uniq:
        msrc, used = masked[src]
        dst = "\n".join(trans.get(ln, ln) for ln in msrc.split("\n"))  # 빈 줄은 그대로 보존
        dst, ok = _unmask_names(dst, used)          # 음차된 이름 → 원 토큰
        dst = deepl._restore_quotes(src, dst)       # 원문에 없는 '' "" 억제 / 「」『』 복원
        dst = deepl._restore_indent(src, dst)       # 줄머리 전각공백 들여쓰기 복원
        dst = deepl._restore_vars(src, dst)         # $...$ 변수 참조 원문 복원
        dst = deepl._restore_color_space(src, dst)  # 색상코드 뒤 덧붙은 반각공백 제거
        dst = deepl._restore_ellipsis(src, dst)     # ASCII '...' → 전각 '…' 복원
        # 괄호 복원은 반드시 _restore_quotes(따옴표→「」 환원) 뒤에 — 앞이면 」가 이중으로 붙는다
        dst = "\n".join(_fix_line(s_ln, d_ln)
                        for s_ln, d_ln in zip(src.split("\n"), dst.split("\n")))
        out[src] = dst
        if not ok:
            failed.append(src)
    if failed:
        if fallback == "deepl":
            try:
                out.update(deepl.translate_texts(failed))
            except deepl.DeepLError:                # DeepL 불가 → 빈 칸으로 남김
                for t in failed:
                    out.pop(t, None)
        elif fallback == "skip":
            for t in failed:
                out.pop(t, None)
    return out


def draft_units(proj, rel: Optional[str] = None, overwrite: bool = False) -> Dict[str, int]:
    """proj 의 자유 텍스트를 Azure 초안으로 채운다. deepl.draft_units 와 동일 규약.
    복원 실패 문장은 빈 칸으로 남긴다(이후 DeepL 초안 실행 시 빈 칸만 채우므로 그쪽으로 흡수).
    반환: {translated, chars, unique, skipped}."""
    targets = deepl._collect_targets(proj, rel, overwrite)
    if not targets:
        return {"translated": 0, "chars": 0, "unique": 0, "skipped": 0}
    uniq_jp = list(dict.fromkeys(jp for _, jp in targets))
    trans = translate_texts(uniq_jp)                        # fallback="skip"
    n = 0
    for u, jp in targets:
        dst = trans.get(jp)
        if dst is None:
            continue
        u["ko"] = textcodec.encode_field(u["field"], dst)   # 속성은 raw 저장(백슬래시 이중화 방지)
        n += 1
    return {"translated": n, "chars": sum(len(j) for j in uniq_jp),
            "unique": len(uniq_jp), "skipped": len(uniq_jp) - len(trans)}

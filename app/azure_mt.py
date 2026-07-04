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


# 스팬 보호 대상: &X 색상코드 + #X 이모지 글리프(스킨 Font 이미지로 렌더링되는
# 특수문자 — a b d e f g h j k l n o p q s w x z, 대소문자 무관. 치환코드
# m/u/r/i/c/y/t 와 겹치지 않게 설계돼 있다). 단어가 아니므로 이름 치환 불가.
_PROTECT = re.compile(r"&[rgbywopld]|#[abdefghjklnopqswxz0-9]", re.I)
_TAG = re.compile(r"</?span[^>]*>")
# 이모지 글리프 보존 검증용 (스팬 보호가 번역 중 유실되면 복원 실패로 처리)
_EMOJI = re.compile(r"#[abdefghjklnopqswxz0-9]", re.I)

# 이름 치환 대상: $...$ 변수 참조, %...% 상태 변수, #X 치환코드(멤버/화자/여관 등).
_NAMEPAT = re.compile(r"\$[^$\n]*\$|%[^%\n]*%|#[MURICYTmuricyt]")
# 인명 치환 풀: (일본어, 허용 한국어 음차). 일반명사와 안 겹치고(ユリ=백합 오번역 사례)
# 음차 표기가 흔들리지 않는 이름만. 남녀 공용 이름 위주 — 여성형 이름(ミナ/エマ)을
# 쓰면 영어 피벗이 없는 소유격을 "her→그녀"로 지어내는 편향이 생긴다.
_NAMES = (("ヒカル", ("히카루",)), ("マコト", ("마코토",)), ("アキラ", ("아키라",)),
          ("ナオ", ("나오",)), ("カオル", ("카오루",)), ("ツバサ", ("츠바사", "쓰바사")))
# 코드 의미별 치환어 — CWXEditor 상태변수 정의 기준. 인명이 아닌 코드는 보통명사로
# 바꿔야 번역이 자연스럽다(#Y=여관 이름을 인명으로 바꾸면 "여관으로 돌아가"가 안 나옴).
_KIND_WORDS = {
    "Y": (("宿", ("여관", "숙소")),),            # 여관 이름
    "T": (("チーム", ("팀",)),),                 # 팀 이름
    "C": (("カード", ("카드",)),),               # 선택 카드 이름
    # #M/#U/#R/#I(멤버/화자 이름)는 인명 풀 사용. メンバー(멤버) 치환을 실측한 결과
    # 보통명사라 엔진이 "멤버들"(복수화 — 개수검증을 통과하는 오염)·"직원"(의역 — 스킵)
    # 으로 변형해서 고유명사 치환보다 나빴다. 런타임 값도 실제 인명이라 의미상 정확.
}


def mask_glossary(src: str, glossary: Dict[str, str], taken: Optional[set] = None) -> tuple:
    """용어집 단어(원문→한국어)를 안정 음차 이름으로 마스킹. DeepL/Azure 공용.
    반환 (치환문, [(이름, 음차들, 사용자 한국어 번역, 개수)]). 되치환은 _unmask_names.
    문장형 용어(12자 초과·개행 포함)는 제외. 긴 용어부터 치환(부분 중복 대비)."""
    taken = taken if taken is not None else set()
    used = []
    masked = src
    for term in sorted(glossary, key=len, reverse=True):
        ko = (glossary[term] or "").strip()
        if not ko or len(term) > 12 or "\n" in term or term not in masked:
            continue
        got = None
        for jp, kos in _NAMES:
            if jp in src or jp in taken:
                continue
            got = (jp, kos)
            break
        if got is None:
            break                               # 이름 풀 소진 — 남은 용어는 원문대로
        taken.add(got[0])
        n = masked.count(term)
        masked = masked.replace(term, got[0])
        used.append((got[0], got[1], ko, n))
    return masked, used


def unmask_glossary(dst: str, used) -> str:
    """번역문의 음차 이름 → 사용자 한국어 번역 (best-effort — DeepL 경로용)."""
    d, _ok = _unmask_names(dst, used)
    return d


def _mask_names(src: str, glossary: Optional[Dict[str, str]] = None) -> tuple:
    """변수/치환코드/용어 → 이름. 동일 토큰은 동일 이름.
    반환 (치환문, [(일본어, 음차들, 되치환값, 개수)]).

    glossary(용어집: 원문→한국어)가 주어지면 그 단어도 이름으로 마스킹하고,
    되치환 때 원문 토큰이 아니라 "사용자의 한국어 번역"을 넣는다
    (예: リューン→ヒカル→번역→"륜"). 문장형 용어(12자 초과·개행 포함)는 제외.

    원문에 이미 등장하는 이름은 쓰지 않는다 — 진짜 그 이름의 캐릭터가 있는 문장이면
    되치환 때 캐릭터 이름까지 변수로 오염되기 때문. 치환·복원이 문장 단위라
    다른 문장에 나오는 이름과는 충돌하지 않는다."""
    seen: Dict[str, str] = {}
    used = []
    counts: Dict[str, int] = {}
    taken = set()

    def pick(tok):
        """토큰 의미에 맞는 치환어 선택 — 코드별 보통명사 우선, 없으면 인명 풀."""
        cands = _KIND_WORDS.get(tok[1].upper(), ()) if tok.startswith("#") else ()
        for jp, kos in tuple(cands) + _NAMES:
            if jp in src or jp in taken:        # 원문 등장/이미 사용 → 다음 후보
                continue
            taken.add(jp)
            return jp, kos
        return None                             # 풀 소진 — 토큰 그대로 둠

    masked = src
    if glossary:
        masked, used_g = mask_glossary(src, glossary, taken)
        used.extend(used_g)

    def rep(m):
        tok = m.group()
        if tok not in seen:
            got = pick(tok)
            if got is None:
                return tok
            seen[tok] = got[0]
            used.append((got[0], got[1], tok))
        counts[tok] = counts.get(tok, 0) + 1
        return seen[tok]

    masked = _NAMEPAT.sub(rep, masked)
    return masked, [e if len(e) == 4 else (e[0], e[1], e[2], counts.get(e[2], 0))
                    for e in used]


def _unmask_names(dst: str, used) -> tuple:
    """번역문의 음차된 이름 → 원 토큰. ok=False 조건 (폴백/스킵 대상):
    · 이름이 번역에서 생략됨 (주어 생략 등)
    · 되치환 후 토큰 개수가 원문과 다름 — 엔진이 이름을 반복/증식시킨 오염
      (예: #Y 1개가 번역문에 2개로 복제되는 케이스)"""
    ok = True
    for jp, kos, tok, n_src in used:
        hit = False
        for ko in tuple(kos) + (jp,):           # 음차 또는 일본어 그대로 남은 경우
            if ko in dst:
                dst = dst.replace(ko, tok)
                hit = True
        if not hit or dst.count(tok) != n_src:
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


# 문장 종결로 취급하는 줄 끝 문자 — 이걸로 안 끝나는 줄은 다음 줄과 같은 문장이
# 중간에서 줄바꿈된 것으로 보고 이어 붙여 번역한다("いくら/でも" 분단 방지).
_SENT_END = tuple("。．.！？…‼⁉」』】)）!?")
# 빈 줄을 '건너서도' 문장이 이어진다고 볼 단서 — 조사/쉼표로 끝나면 명백한 문장 중간.
# (더블 스페이싱 대응. 명사로 끝나는 줄은 목록 항목일 수 있어 빈 줄에서 끊는다.)
_CONT_END = tuple("、，をはがのにへとでもや")


# 줄머리 분리는 공백/들여쓰기 + &색상코드까지만. deepl._LEADRUN 과 달리 #X 는 포함하지
# 않는다 — #X 는 이름 치환 대상인 문장 내용이라, 떼어내면 병합 문장에서 유실되고
# 재줄바꿈 들여쓰기 패턴으로 복제된다(#Y 이중 출현 버그).
_LEAD = re.compile(r"^(?:&[0-9A-Za-z]|[ \t　])*")


def _split_lead(line: str) -> tuple:
    """줄머리의 색상코드/들여쓰기 run 과 본문을 분리."""
    m = _LEAD.match(line)
    return m.group(0), line[m.end():]


def _tokenize(text: str) -> list:
    """줄 목록 → [("raw", 줄)] 또는 [("grp", (줄들, 줄사이 빈줄 수))] 토큰열.

    문장 종결로 끝나지 않는 줄은 다음 줄과 한 grp 로 묶는다. 작가가 문장 중간
    줄바꿈에 더해 줄 사이에 빈 줄(더블 스페이싱)을 끼우기도 하므로, 문장이
    미완결이면 빈 줄을 건너서 계속 병합하고 그 간격(gaps)을 기억해 재현한다.
    코드/공백뿐인 줄(&B 단독 등)은 그룹에 넣지 않고 raw 로 보존한다."""
    tokens, buf, gaps, pending = [], [], [], []

    def flush():
        nonlocal buf, gaps
        if buf:
            tokens.append(("grp", (buf, gaps)))
            buf, gaps = [], []

    for ln in text.split("\n"):
        if not ln.strip():                      # 진짜 빈 줄 — 그룹 내부 간격일 수 있음
            if buf:
                pending.append(ln)
            else:
                tokens.append(("raw", ln))
            continue
        body = _split_lead(ln)[1].strip()
        if not body or _NAMEPAT.fullmatch(body):
            # 코드 단독 줄(&B)·토큰 단독 줄(#I 화자 캡션) — 문장이 아니므로 그룹을 끊고
            # 그대로 보존한다. (빈 줄과 달리 gap 으로 흡수하면 내용이 유실된다)
            flush()
            tokens.extend(("raw", p) for p in pending)
            pending = []
            tokens.append(("raw", ln))
            continue
        if buf and pending and not buf[-1].rstrip().endswith(_CONT_END):
            # 빈 줄을 건너는 병합은 조사/쉼표로 끝날 때만 — 목록 항목 오병합 방지
            flush()
            tokens.extend(("raw", p) for p in pending)
            pending = []
        if buf:
            gaps.append(len(pending)); pending = []
        buf.append(ln)
        if ln.rstrip().endswith(_SENT_END):
            flush()
    flush()
    for ln in pending:                  # 그룹이 끝난 뒤 남은 빈/코드 줄
        tokens.append(("raw", ln))
    return tokens


def _grp_body(lines: List[str]) -> str:
    """grp 의 번역 원문: 줄머리 코드/들여쓰기를 뗀 본문을 이어 붙인다(일본어는 무공백 연결)."""
    return "".join(_split_lead(ln)[1].rstrip() for ln in lines)


def _display_width(s: str) -> int:
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _wrap(body: str, width: int, lead0: str, lead_cont: str) -> List[str]:
    """번역문을 표시폭 width 안에서 어절 단위로 줄바꿈. 첫 줄은 lead0,
    이후 줄은 lead_cont(원문 연속 줄의 들여쓰기 패턴)를 붙인다."""
    out: List[str] = []
    cur, lead = lead0, lead0
    for word in body.split(" "):
        while word:                                 # 한 어절이 폭을 넘으면 강제 분절
            cand = cur + (" " if cur != lead else "") + word if cur != lead else cur + word
            if _display_width(cand) <= width:
                cur = cand
                word = ""
            elif cur == lead:                       # 빈 줄인데도 안 들어감 → 글자 단위로 자름
                k = len(word)
                while k > 1 and _display_width(cur + word[:k]) > width:
                    k -= 1
                cur += word[:k]
                word = word[k:]
                out.append(cur); lead = lead_cont; cur = lead
            else:
                out.append(cur); lead = lead_cont; cur = lead
    if cur != lead or not out:
        out.append(cur)
    return out


def translate_texts(texts: List[str], key: Optional[str] = None, region: Optional[str] = None,
                    progress: Optional[Callable[[int, int], None]] = None,
                    fallback: str = "skip",
                    glossary: Optional[Dict[str, str]] = None) -> Dict[str, str]:
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
    toks = {t: _tokenize(t) for t in uniq}
    # 번역 단위 = grp 본문(문장 중간 줄바꿈을 이어 붙인 것). 동일 본문은 한 번만.
    bodies: List[str] = []
    for t in uniq:
        for kind, v in toks[t]:
            if kind == "grp":
                b = _grp_body(v[0])
                if b.strip():
                    bodies.append(b)
    bodies = list(dict.fromkeys(bodies))
    masked_bodies = {b: _mask_names(b, glossary) for b in bodies}     # 본문 → (이름 치환문, 이름들)
    send = [masked_bodies[b][0] for b in bodies]
    trans_raw: Dict[str, str] = {}
    for s in range(0, len(send), BATCH):
        chunk = send[s: s + BATCH]
        res = _call(key, region, [_mask(x) for x in chunk])
        if len(res) != len(chunk):
            raise AzureError(f"응답 개수 불일치: 요청 {len(chunk)} vs 응답 {len(res)}")
        trans_raw.update(zip(chunk, (_unmask(r) for r in res)))
        if progress:
            progress(min(s + BATCH, len(send)), len(send))
    trans: Dict[str, tuple] = {}                            # 본문 → (번역, 복원성공)
    for b in bodies:
        mb, used = masked_bodies[b]
        d, ok = _unmask_names(trans_raw.get(mb, mb), used)  # 음차된 이름 → 원 토큰
        # 이모지 글리프(#e 등) 보존 검증 — 스팬 보호가 유실/증식되면 실패 처리
        if sorted(t.lower() for t in _EMOJI.findall(b)) \
                != sorted(t.lower() for t in _EMOJI.findall(d)):
            ok = False
        trans[b] = (d, ok)
    out: Dict[str, str] = {}
    failed: List[str] = []
    for src in uniq:
        pieces: List[str] = []
        ok_all = True
        for kind, v in toks[src]:
            if kind == "raw":                       # 빈 줄/코드 단독 줄 — 그대로 보존
                pieces.append(v)
                continue
            g_lines, g_gaps = v
            body = _grp_body(g_lines)
            if not body.strip():
                pieces.extend(g_lines)
                continue
            d, ok = trans.get(body, (body, True))
            ok_all = ok_all and ok
            # 따옴표→괄호 환원을 grp(병합 문장) 범위에서 먼저 — Azure 가 「」 를
            # 곧은따옴표로 바꾸는데, 문장 단위여야 짝 판정이 정확하다(전체 텍스트
            # 단위로 하면 다른 문단의 따옴표와 짝지어져 「 유실/」 이중이 생긴다).
            d = deepl._restore_quotes(body, d)
            # 환원기가 지어낸 초과 괄호 제거 — 여는 「만 있는 문장(닫는 짝은 다른
            # 문장에 있음)에 따옴표 쌍이 오면 」가 창작되므로, 원문 개수를 넘는
            # 경계 괄호는 걷어낸다.
            for br in "「」『』":
                while d.count(br) > body.count(br):
                    if d.rstrip().endswith(br):
                        d = d.rstrip()[:-1]
                    elif d.startswith(br):
                        d = d[1:]
                    else:
                        break
            # 남은 짝 안 맞는 괄호 복원. 따옴표가 아직 있으면(원문 자체에 따옴표가
            # 있는 경우) 보류 — 이후 전체 _restore_quotes/_fix_line 에 맡긴다.
            if not any(q in d for q in "“”‘’\"'"):
                for op, cl in (("「", "」"), ("『", "』"), ("（", "）")):
                    if body.startswith(op) and not d.startswith(op) and d.count(op) < body.count(op):
                        d = op + d
                    if body.rstrip().endswith(cl) and not d.rstrip().endswith(cl) \
                            and d.count(cl) < body.count(cl):
                        d = d.rstrip() + cl
            lead0 = _split_lead(g_lines[0])[0]
            if len(g_lines) == 1:                   # 한 줄 문장 — 레이아웃 유지
                pieces.append(lead0 + d)
            else:                                   # 합쳐 번역한 문장 — 원문 폭 안에서 재줄바꿈
                width = max(_display_width(ln) for ln in g_lines)
                lead_cont = _split_lead(g_lines[1])[0]
                # 연속 줄 들여쓰기에 전각공백이 있으면 곁들여진 반각공백은 제거 —
                # 원문의 일본어 글자 정렬용 반각(예: "　 数日")이 재줄바꿈된 모든
                # 연속 줄에 퍼지는 것을 막는다. 반각만으로 들여쓴 원문은 그대로 둔다.
                if "　" in lead_cont:
                    lead_cont = lead_cont.replace(" ", "").replace("\t", "")
                wrapped = _wrap(d, width, lead0, lead_cont)
                # 원문 줄 사이 간격(더블 스페이싱 등)을 최빈값으로 재현
                sep = max(set(g_gaps), key=g_gaps.count) if g_gaps else 0
                for i, wl in enumerate(wrapped):
                    pieces.append(wl)
                    if i < len(wrapped) - 1:
                        pieces.extend([""] * sep)
        dst = "\n".join(pieces)
        dst = deepl._restore_quotes(src, dst)       # 원문에 없는 '' "" 억제 / 「」『』 복원
        # deepl._restore_indent 는 쓰지 않는다 — 그쪽 _LEADRUN 은 #X 를 줄머리 코드로
        # 취급해 원문 줄머리 "　#Y" 를 통째로 이식, #Y 가 이중으로 붙는다. 들여쓰기는
        # 위 재조립(lead0/lead_cont)이 이미 원문 기준으로 처리했다.
        dst = deepl._restore_vars(src, dst)         # $...$ 변수 참조 원문 복원
        dst = deepl._restore_color_space(src, dst)  # 색상코드 뒤 덧붙은 반각공백 제거
        dst = deepl._restore_ellipsis(src, dst)     # ASCII '...' → 전각 '…' 복원
        # 괄호 복원은 _restore_quotes 뒤에, 그리고 줄 수가 유지된 경우에만 줄 단위 적용
        s_lines, d_lines = src.split("\n"), dst.split("\n")
        if len(s_lines) == len(d_lines):
            dst = "\n".join(_fix_line(a, b) for a, b in zip(s_lines, d_lines))
        out[src] = dst
        if not ok_all:
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
    # 용어집(번역이 입력된 단어)을 MT 에 강제 적용 — リューン→륜 같은 고정 표기
    terms = {jp: ko for jp, ko in (proj.get("terms") or {}).items() if (ko or "").strip()}
    trans = translate_texts(uniq_jp, glossary=terms or None)   # fallback="skip"
    n = 0
    for u, jp in targets:
        dst = trans.get(jp)
        if dst is None:
            u["mt_failed"] = True                           # 복원 실패 — 경고 패널/점프 표적
            continue
        u["ko"] = textcodec.encode_field(u["field"], dst)   # 속성은 raw 저장(백슬래시 이중화 방지)
        u.pop("mt_failed", None)
        n += 1
    return {"translated": n, "chars": sum(len(j) for j in uniq_jp),
            "unique": len(uniq_jp), "skipped": len(uniq_jp) - len(trans)}


def failed_units(proj, cap: int = 200) -> list:
    """복원 실패로 빈 칸으로 남은 유닛 목록(번역되면 자동 제외). 경고 패널/점프용."""
    out = []
    for rel, f in proj["files"].items():
        for u in f["units"]:
            if u["kind"] != "free" or not u.get("mt_failed") or u.get("ko"):
                continue
            jp = textcodec.decode_field(u["field"], u["jp"])
            out.append({"rel": rel, "sid": u["id"], "cat": u.get("cat"),
                        "jp": jp.replace("\n", " ").strip()[:100]})
            if len(out) >= cap:
                return out
    return out

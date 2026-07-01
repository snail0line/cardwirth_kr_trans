# -*- coding: utf-8 -*-
"""
DeepL 자동 번역 — 키 저장/로드 + 일괄 번역 + 시나리오 초안 생성.

스크립트(tools/translate_deepl.py)와 웹앱(server.py)이 함께 쓴다.
키는 깃에 안 올라가는 tools/.deepl_key 에 저장한다(.gitignore: *deepl_key*).
무료 키(":fx" 로 끝남)는 api-free, 그 외는 api(Pro) 엔드포인트를 자동 선택한다.
줄바꿈은 preserve_formatting 으로 보존하고, 동일 일본어는 한 번만 번역해 쿼터를 아낀다.
"""
from __future__ import annotations
import json
import os
import re
import time
import urllib.parse
import urllib.request
import urllib.error
from typing import Dict, List, Any, Callable, Optional

from . import textcodec

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_KEY_DIR = os.path.join(_ROOT, "tools")
_KEY_CANDIDATES = (".deepl_key", ".deepl_key.txt", "deepl_key.txt")
BATCH = 40          # DeepL 권장 최대 50, 여유 두고 40
RETRY = 3


class DeepLError(Exception):
    pass


def _parse_key_line(line: str) -> str:
    """키 한 줄 정리. 'ApiKey=...' 형태(유니티 번역기 설정 복붙)면 = 뒷부분을 키로."""
    line = (line or "").strip()
    if "=" in line:
        line = line.split("=", 1)[1].strip()
    return line


def load_key() -> str:
    key = os.environ.get("DEEPL_API_KEY", "").strip()
    if key:
        return key
    for fn in _KEY_CANDIDATES:
        fp = os.path.join(_KEY_DIR, fn)
        if os.path.isfile(fp):
            with open(fp, "r", encoding="utf-8-sig") as f:
                k = _parse_key_line(f.readline())
            if k:
                return k
    return ""


def save_key(key: str) -> None:
    key = _parse_key_line(key)
    os.makedirs(_KEY_DIR, exist_ok=True)
    with open(os.path.join(_KEY_DIR, ".deepl_key"), "w", encoding="utf-8") as f:
        f.write(key + "\n")


def key_status() -> Dict[str, Any]:
    """키 노출 없이 상태만. {set, free}."""
    k = load_key()
    return {"set": bool(k), "free": (k.endswith(":fx") if k else None)}


def endpoint(key: str, force: str = "auto") -> str:
    if force == "free":
        free = True
    elif force == "pro":
        free = False
    else:                               # auto: 무료 키는 항상 ":fx" 로 끝남
        free = key.endswith(":fx")
    return "https://api-free.deepl.com/v2/translate" if free else "https://api.deepl.com/v2/translate"


def _call(url: str, key: str, texts: List[str]) -> List[str]:
    params = [("target_lang", "KO"), ("source_lang", "JA"), ("preserve_formatting", "1")]
    params += [("text", t) for t in texts]
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"DeepL-Auth-Key {key}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    last = None
    for attempt in range(RETRY):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return [t["text"] for t in payload["translations"]]
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code == 429 or e.code >= 500:        # rate limit / 일시 오류 → 재시도
                last = f"HTTP {e.code}: {body}"
                time.sleep(2 * (attempt + 1))
                continue
            raise DeepLError(f"HTTP {e.code}: {body}")
        except urllib.error.URLError as e:
            last = str(e)
            time.sleep(2 * (attempt + 1))
    raise DeepLError(f"재시도 실패: {last}")


# 따옴표류: 스마트(“ ” ‘ ’) + 곧은(" ')
_QALL = "“”‘’\"'"
# 색상코드: & + 색 글자(r/g/b/y/w/o/p/l/d), 대소문자. get_fontcolour / app.js FONT_COLORS 와 일치.
_COLOR = re.compile(r"&[rgbywopld]", re.I)


def _restore_quotes(src: str, dst: str) -> str:
    """DeepL 이 원문에 없는 '' \"\" 를 넣거나 대사 괄호 「」『』 를 따옴표로 바꾸는 걸 정규화.

    번역 기조: '원문에 '' \"\" 가 없으면 번역문에도 넣지 않는다'.
      · 원문에 따옴표류가 이미 있으면 → 손대지 않음(유지).
      · 원문에 「」/『』 가 있으면 → 그 괄호를 복원(바깥 따옴표쌍→괄호, 안쪽 덧붙은 따옴표 제거).
      · 원문에 괄호도 따옴표도 없으면 → 번역문의 따옴표류를 전부 제거.
    (이 프로젝트 일회성 데이터 보정과 동일 규칙. overflow.py 등과 무관.)"""
    if any(c in _QALL for c in src):            # 원문에 따옴표류 있음 → 유지
        return dst
    if not any(c in _QALL for c in dst):
        return dst
    bt = ("『", "』") if "『" in src else (("「", "」") if "「" in src else None)
    if bt is None:                              # 원문에 괄호·따옴표 전무 → 따옴표 제거
        return "".join(c for c in dst if c not in _QALL)
    if any(c in "「『" for c in dst):            # 번역문에 괄호가 이미 있음 → 덧붙은 따옴표만 제거
        return "".join(c for c in dst if c not in _QALL)
    idxs = [i for i, c in enumerate(dst) if c in _QALL]
    if len(idxs) < 2:
        return "".join(c for c in dst if c not in _QALL)
    first, last = idxs[0], idxs[-1]             # 바깥쌍=원문 괄호, 그 사이 따옴표=제거
    res = []
    for i, c in enumerate(dst):
        if i == first:
            res.append(bt[0])
        elif i == last:
            res.append(bt[1])
        elif c in _QALL:
            continue
        else:
            res.append(c)
    return "".join(res)


def _restore_color_space(src: str, dst: str) -> str:
    """색상코드(&X) 바로 뒤의 반각공백을 원문 기준으로 정렬한다.

    DeepL 이 `&B大通り`(공백 없음)를 `&B 대로`처럼 색상코드 뒤에 공백을 끼워 글자 배치를
    어긋나게 하는 걸 막는다. 원문에도 그 자리에 공백이 있으면(원작자 의도) 그대로 둔다.
    색상코드 순서로 정렬 비교하고, 개수가 어긋나면(매핑 불가) 손대지 않는다."""
    jf = [src[m.end():m.end() + 1] == " " for m in _COLOR.finditer(src)]
    km = list(_COLOR.finditer(dst))
    if not any(dst[m.end():m.end() + 1] == " " for m in km):
        return dst
    if len(jf) != len(km):
        return dst
    out, last = [], 0
    for i, m in enumerate(km):
        out.append(dst[last:m.end()])
        j = m.end()
        k = j
        while k < len(dst) and dst[k] == " ":
            k += 1
        last = k if (k > j and not jf[i]) else j   # 원문에 공백 없으면 제거, 있으면 유지
    out.append(dst[last:])
    return "".join(out)


# 줄머리의 (제어코드*)(공백*) 를 분리. 제어코드 = & 또는 # + 영숫자 1글자(색·치환코드).
_LEAD = re.compile(r"^((?:[&#][0-9A-Za-z])*)([ \t　]*)(.*)$")

# CardWirth 변수 참조: $...$ (예: $PC\一人称$). 안쪽은 식별자라 절대 번역하면 안 됨.
_VAR = re.compile(r"\$[^$\n]*\$")


def _restore_vars(src: str, dst: str) -> str:
    """DeepL 이 $...$ 변수 참조(예: $PC\\一人称$) 안의 일본어를 번역해 깨뜨리는 걸 복원한다.

    $PC\\一人称$ → $PC\\1인칭$ 처럼 안쪽이 번역되면 게임이 변수를 못 찾아 글이 깨진다.
    DeepL 은 $ 구분자와 그 개수·순서는 보존하므로, 원문의 $...$ 들을 순서대로
    번역문의 $...$ 자리에 그대로 되돌린다(개수가 같을 때만 — 다르면 매핑 불가라 보류)."""
    src_vars = _VAR.findall(src)
    if not src_vars:
        return dst
    dst_hits = list(_VAR.finditer(dst))
    if len(dst_hits) != len(src_vars):
        return dst
    out, last = [], 0
    for span, m in zip(src_vars, dst_hits):
        out.append(dst[last:m.start()]); out.append(span); last = m.end()
    out.append(dst[last:])
    return "".join(out)


def _restore_indent(src: str, dst: str) -> str:
    """DeepL 이 줄머리 전각공백(U+3000) 들여쓰기를 일반공백으로 바꾸거나 지우는 걸
    원문 기준으로 복원한다.

    CardWirth 메시지는 각 줄을 전각공백으로 들여쓰는데, DeepL 은 맨 첫 줄을 빼면
    줄머리 U+3000 을 반각공백으로 normalize 하거나 아예 삭제해 레이아웃이 깨진다.
    preserve_formatting 으로 개행 구조(개행 수)는 보존되므로, 개행 수가 같을 때만
    줄 단위로 원문의 줄머리 공백을 그대로 옮긴다(제어코드는 번역문 것을 유지)."""
    if src.count("\n") != dst.count("\n"):
        return dst                      # 줄 구조가 어긋나면 위치 정렬이 깨지므로 손대지 않음
    out = []
    for s_line, d_line in zip(src.split("\n"), dst.split("\n")):
        s_ws = _LEAD.match(s_line).group(2)
        if "　" not in s_ws:            # 원문 줄머리에 전각 들여쓰기가 없으면 그대로 둠
            out.append(d_line)
            continue
        d_codes, _d_ws, d_rest = _LEAD.match(d_line).groups()
        out.append(d_codes + s_ws + d_rest)
    return "\n".join(out)


def translate_texts(texts: List[str], key: Optional[str] = None, force: str = "auto",
                    progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, str]:
    """텍스트 목록 JA→KO 번역. 중복 제거 후 한 번씩만 호출. 반환: {원문: 번역}."""
    key = key or load_key()
    if not key:
        raise DeepLError("DeepL 키가 없습니다.")
    url = endpoint(key, force)
    uniq = list(dict.fromkeys(t for t in texts if t and t.strip()))
    out: Dict[str, str] = {}
    for s in range(0, len(uniq), BATCH):
        chunk = uniq[s: s + BATCH]
        res = _call(url, key, chunk)
        if len(res) != len(chunk):
            raise DeepLError(f"응답 개수 불일치: 요청 {len(chunk)} vs 응답 {len(res)}")
        for src, dst in zip(chunk, res):
            dst = _restore_quotes(src, dst)         # 원문에 없는 '' "" 억제 / 「」『』 복원
            dst = _restore_indent(src, dst)         # 줄머리 전각공백 들여쓰기 복원
            dst = _restore_vars(src, dst)           # $...$ 변수 참조 원문 복원
            dst = _restore_color_space(src, dst)    # 색상코드 뒤 덧붙은 반각공백 제거
            out[src] = dst
        if progress:
            progress(min(s + BATCH, len(uniq)), len(uniq))
    return out


def usage(key: Optional[str] = None, force: str = "auto") -> Dict[str, int]:
    """DeepL 사용량 조회. 반환: {count, limit, remaining}."""
    key = key or load_key()
    if not key:
        raise DeepLError("DeepL 키가 없습니다.")
    base = endpoint(key, force).rsplit("/v2/", 1)[0]
    req = urllib.request.Request(base + "/v2/usage")
    req.add_header("Authorization", f"DeepL-Auth-Key {key}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            d = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise DeepLError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}")
    except urllib.error.URLError as e:
        raise DeepLError(str(e))
    count = int(d.get("character_count", 0))
    limit = int(d.get("character_limit", 0))
    return {"count": count, "limit": limit, "remaining": max(0, limit - count)}


def draft_units(proj: Dict[str, Any], rel: Optional[str] = None,
                overwrite: bool = False, force: str = "auto") -> Dict[str, int]:
    """proj 의 자유 텍스트(제어/내부명 제외)를 DeepL 초안으로 채운다.
    rel 지정 시 그 파일만, overwrite=False 면 빈 ko 만 번역. 반환: {translated, chars, unique}."""
    targets = []  # (unit, jp_decoded)
    for r, fd in proj["files"].items():
        if rel and r != rel:
            continue
        for u in fd["units"]:
            if u["kind"] != "free" or u.get("control"):
                continue
            if u.get("cat") == "sysname":
                continue
            # #text 만 CardWirth 이스케이프, 속성(@name 선택지)은 raw — encode_field 대칭
            jp = textcodec.decode_field(u["field"], u["jp"])
            if not jp.strip():
                continue
            ko = textcodec.decode_field(u["field"], u.get("ko", ""))
            if ko and not overwrite:
                continue
            targets.append((u, jp))
    if not targets:
        return {"translated": 0, "chars": 0, "unique": 0}
    uniq_jp = list(dict.fromkeys(jp for _, jp in targets))
    trans = translate_texts(uniq_jp, force=force)
    n = 0
    for u, jp in targets:
        dst = trans.get(jp)
        if dst is None:
            continue
        u["ko"] = textcodec.encode_field(u["field"], dst)   # 속성은 raw 저장(백슬래시 이중화 방지)
        n += 1
    return {"translated": n, "chars": sum(len(j) for j in uniq_jp), "unique": len(uniq_jp)}

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


def _restore_brackets(src: str, dst: str) -> str:
    """DeepL 이 일본어 대사 괄호 「」 를 “ ”(U+201C/U+201D)로 바꾸므로 되돌린다.
    원문에 「 또는 」 가 있던 문장에만 적용해 일반 따옴표 오변환을 막는다."""
    if "「" in src or "」" in src:
        dst = dst.replace("“", "「").replace("”", "」")
    return dst


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
            out[src] = _restore_brackets(src, dst)
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
            jp = textcodec.decode(u["jp"])
            if not jp.strip():
                continue
            ko = textcodec.decode(u.get("ko", ""))
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
        u["ko"] = textcodec.encode(dst)
        n += 1
    return {"translated": n, "chars": sum(len(j) for j in uniq_jp), "unique": len(uniq_jp)}

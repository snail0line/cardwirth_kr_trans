# -*- coding: utf-8 -*-
"""
.wsn (CardWirthPy 패키지 시나리오) 지원.

.wsn = XML 시나리오 폴더(Summary.xml + Package/ + Material/ …)를 담은 ZIP.
열기: 안정된 캐시 폴더에 풀어 일반 XML 폴더처럼 다룬다.
내보내기: 번역된 폴더를 다시 .wsn(ZIP)으로 압축.

.wsm/.wid (구 CardWirth 1.x 바이너리)는 별도 변환기가 필요해 여기서 다루지 않는다.
"""
from __future__ import annotations
import os
import zipfile
import hashlib


def is_wsn(path: str) -> bool:
    return os.path.isfile(path) and path.lower().endswith(".wsn") and zipfile.is_zipfile(path)


def _summary_root(names):
    """ZIP 안에서 Summary.xml 이 들어있는 공통 루트 접두(없으면 '')."""
    for n in names:
        base = n.replace("\\", "/")
        if base.endswith("Summary.xml"):
            return base[: -len("Summary.xml")]
    return ""


def unpack_wsn(wsn_path: str, cache_base: str) -> str:
    """.wsn 을 캐시 폴더에 풀고, Summary.xml 이 있는 시나리오 루트 경로를 반환.
    같은 .wsn(경로+크기+mtime) 은 같은 폴더에 재사용."""
    st = os.stat(wsn_path)
    key = f"{os.path.abspath(wsn_path)}|{st.st_size}|{int(st.st_mtime)}"
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    name = os.path.splitext(os.path.basename(wsn_path))[0]
    dest = os.path.join(cache_base, f"{name}_{h}")
    with zipfile.ZipFile(wsn_path) as z:
        root_prefix = _summary_root(z.namelist())
        if not os.path.isdir(dest):
            z.extractall(dest)
    scen_root = os.path.join(dest, root_prefix.replace("/", os.sep)) if root_prefix else dest
    return os.path.normpath(scen_root)


def pack_wsn(src_dir: str, wsn_path: str) -> int:
    """src_dir(번역된 시나리오 폴더)를 .wsn(ZIP)으로 압축. 반환: 엔트리 수."""
    src_dir = os.path.abspath(src_dir)
    n = 0
    with zipfile.ZipFile(wsn_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(src_dir):
            for fn in files:
                full = os.path.join(root, fn)
                arc = os.path.relpath(full, src_dir).replace(os.sep, "/")
                z.write(full, arc)
                n += 1
    return n

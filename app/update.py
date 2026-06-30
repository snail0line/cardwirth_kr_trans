# -*- coding: utf-8 -*-
"""
자동 업데이트 — GitHub 공개 레포에서 최신 버전 확인 + 코드 파일 갱신(git 불필요).

실행 중 서버가 GitHub zip 을 받아 코드 파일만 덮어쓴다.
사용자 데이터(projects/, tools/.deepl_key, test_scenario/)는 레포 zip 에 없으므로
건드리지 않는다. .py 는 실행 중에도 잠기지 않으니 별도 updater 없이 가능하고,
덮어쓰면 서버의 자동 리로더(app/*.py mtime 감시)가 알아서 재시작한다.
"""
from __future__ import annotations
import io
import os
import shutil
import zipfile
import urllib.request
import urllib.error

REPO = "snail0line/cardwirth_kr_trans"
BRANCH = "main"
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_VERSION_FILE = os.path.join(_ROOT, "VERSION")
RAW_VERSION = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/VERSION"
ZIP_URL = f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}"

# zip 에서 받아 덮어쓸 최상위 항목(이외는 무시 → 사용자 데이터 보존).
# 파일 단위로 복사하므로, zip 에 없는 로컬 파일(tools/.deepl_key 등)은 삭제되지 않는다.
_UPDATE_PATHS = ("app", "web", "tools", "README.md", "SCENARIO_ANALYSIS.md",
                 "run.bat", "VERSION", ".gitignore")
_BACKUP_PATHS = ("app", "web")   # 롤백용 백업(코드만)


def local_version() -> str:
    try:
        with open(_VERSION_FILE, encoding="utf-8") as f:
            return f.read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def _vt(s: str):
    parts = []
    for p in (s or "0").strip().split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def remote_version(timeout: int = 8):
    try:
        with urllib.request.urlopen(RAW_VERSION, timeout=timeout) as r:
            return r.read().decode("utf-8").strip()
    except (urllib.error.URLError, OSError):
        return None


def check() -> dict:
    cur = local_version()
    latest = remote_version()
    if latest is None:
        return {"current": cur, "latest": None, "behind": False, "error": "원격 버전 확인 실패"}
    return {"current": cur, "latest": latest, "behind": _vt(latest) > _vt(cur)}


def _backup() -> str:
    bdir = os.path.join(_ROOT, "projects", "_update_backup")
    if os.path.isdir(bdir):
        shutil.rmtree(bdir, ignore_errors=True)
    for p in _BACKUP_PATHS:
        src = os.path.join(_ROOT, p)
        if not os.path.exists(src):
            continue
        shutil.copytree(src, os.path.join(bdir, p))
    return bdir


def apply(timeout: int = 120) -> dict:
    """GitHub zip 다운로드 → 코드 파일 덮어쓰기. 반환: {updated_to, files, backup}."""
    try:
        with urllib.request.urlopen(ZIP_URL, timeout=timeout) as r:
            data = r.read()
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"다운로드 실패: {e}")

    zf = zipfile.ZipFile(io.BytesIO(data))
    names = zf.namelist()
    if not names:
        raise RuntimeError("빈 zip")
    prefix = names[0].split("/")[0] + "/"     # 예: cardwirth_kr_trans-main/
    try:
        new_ver = zf.read(prefix + "VERSION").decode("utf-8").strip()
    except KeyError:
        new_ver = remote_version() or "?"

    backup = _backup()                         # 롤백용
    updated = 0
    for name in names:
        if name.endswith("/"):
            continue
        rel = name[len(prefix):]
        if not rel or rel.split("/")[0] not in _UPDATE_PATHS:
            continue
        dest = os.path.join(_ROOT, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with zf.open(name) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
        updated += 1
    if updated == 0:
        raise RuntimeError("교체된 파일이 없습니다(zip 구조 확인 필요)")
    return {"updated_to": new_ver, "files": updated, "backup": os.path.relpath(backup, _ROOT)}

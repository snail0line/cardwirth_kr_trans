# -*- coding: utf-8 -*-
"""
CardWirth 한글화 — 로컬 웹 에디터 (stdlib only).

실행:  python -m app.server   →  http://127.0.0.1:8765
"""
from __future__ import annotations
import os
import sys
import json
import shutil
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import project, repack, extract, textcodec, flow, terms, outline, bulkio, wsn, deepl, azure_mt, search, overflow, dupchoice, update

WEB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web"))
TOOLS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools"))
HOST, PORT = "127.0.0.1", 8765

# ── #X 이모지 글리프 (게임 줄바꿈 미리보기용) ──
# CardWirthPy 스킨의 Resource/Image/Font 이미지를 그대로 서빙한다 (cw/setting.py 매핑).
# CardWirthPy 위치는 환경변수 CWPY_DIR 또는 tools/.cwpy_path (한 줄, 깃 제외) 로 지정.
_GLYPH_NAMES = {"a": "ANGRY", "b": "CLUB", "d": "DIAMOND", "e": "EASY", "f": "FLY",
                "g": "GRIEVE", "h": "HEART", "j": "JACK", "k": "KISS", "l": "LAUGH",
                "n": "NIKO", "o": "ONSEN", "p": "PUZZLE", "q": "QUICK", "s": "SPADE",
                "w": "WORRY", "x": "X", "z": "ZAP"}
_FONT_DIR_CACHE = [None]        # [경로 또는 ""] — 최초 1회 탐색


def _glyph_font_dir() -> str:
    if _FONT_DIR_CACHE[0] is not None:
        return _FONT_DIR_CACHE[0]
    roots = []
    if os.environ.get("CWPY_DIR"):
        roots.append(os.environ["CWPY_DIR"])
    try:
        with open(os.path.join(TOOLS_DIR, ".cwpy_path"), encoding="utf-8-sig") as f:
            p = f.readline().strip()
        if p:
            roots.append(p)
    except OSError:
        pass
    found = ""
    for root in roots:
        if os.path.basename(os.path.normpath(root)).lower() == "font" and os.path.isdir(root):
            found = root                        # Font 폴더 직접 지정도 허용
            break
        skinroot = os.path.join(root, "Data", "Skin")
        if not os.path.isdir(skinroot):
            continue
        for skin in sorted(os.listdir(skinroot)):
            d = os.path.join(skinroot, skin, "Resource", "Image", "Font")
            if os.path.isdir(d) and any(f.lower().endswith(".png") for f in os.listdir(d)):
                found = d
                break
        if found:
            break
    _FONT_DIR_CACHE[0] = found
    return found

# 단일 사용자 로컬 툴 → 전역 현재 프로젝트
STATE = {"proj": None}


# 네이티브 선택 다이얼로그(별도 프로세스). 창을 데스크톱 최상단으로 끌어올린다.
def _picker_code(kind: str) -> str:
    if kind == "file":     # .wsn 패키지 파일 선택
        call = ("p=filedialog.askopenfilename(title='CardWirth .wsn package', parent=r,"
                "filetypes=[('CardWirth 패키지','*.wsn'),('모든 파일','*.*')])\n")
    elif kind == "save":   # 번역 결과 저장 위치(.wsn=패키지 / 확장자 없으면 폴더). 기본값은 env 로 전달
        call = ("p=filedialog.asksaveasfilename("
                "title='번역 결과 저장 — 파일명이 .wsn 이면 패키지, 확장자 없으면 폴더', parent=r,"
                " initialdir=os.environ.get('CW_INITDIR',''),"
                " initialfile=os.environ.get('CW_INITFILE',''),"
                " filetypes=[('CardWirth 패키지 (.wsn)','*.wsn'),('폴더로 저장','*')])\n")
    else:                  # 시나리오 XML 폴더 선택
        call = "p=filedialog.askdirectory(title='CardWirth scenario XML folder', parent=r)\n"
    return (
        "import os\n"
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "r=tk.Tk()\n"
        "r.withdraw()\n"
        "r.update_idletasks()\n"
        "r.attributes('-topmost', True)\n"
        "r.lift()\n"
        "r.focus_force()\n"
        + call +
        "import sys\n"
        # 콘솔 코드페이지(cp932 등)와 무관하게 경로를 UTF-8 바이트로 출력
        "sys.stdout.buffer.write((p or '').encode('utf-8'))\n"
    )


def _pick_folder_dialog(kind: str = "dir", initfile: str = "", initdir: str = "") -> dict:
    """사용자 데스크톱에 네이티브 선택 다이얼로그를 띄운다. kind: 'dir'|'file'|'save'.
    save 모드의 기본 파일명/폴더는 initfile/initdir 로 전달(환경변수 경유, 이스케이프 회피).
    서버가 사용자의 인터랙티브 세션에서 실행 중이어야 창이 보인다.
    반환: {path, error}."""
    import subprocess
    env = dict(os.environ)
    env["CW_INITFILE"] = initfile or ""
    env["CW_INITDIR"] = initdir or ""
    try:
        # text=False(바이트)로 받아 UTF-8 로 직접 디코드 (cp932 자동디코딩 크래시 방지)
        out = subprocess.run([sys.executable, "-c", _picker_code(kind)],
                             capture_output=True, timeout=600, env=env)
        path = (out.stdout or b"").decode("utf-8", "replace").strip()
        err = (out.stderr or b"").decode("utf-8", "replace").strip()
        if not path and err:
            return {"path": "", "error": err.splitlines()[-1][:200]}
        return {"path": path, "error": ""}
    except Exception as e:
        return {"path": "", "error": str(e)[:200]}


def _drives():
    import string
    return [f"{d}:/" for d in string.ascii_uppercase if os.path.exists(f"{d}:/")]


def _listdir(path: str) -> dict:
    """브라우저 폴더 탐색용. path 비면 드라이브 목록, 아니면 하위 폴더 목록."""
    path = (path or "").strip().strip('"')
    if not path:
        return {"path": "", "parent": None,
                "dirs": [{"name": d, "path": d} for d in _drives()],
                "is_scenario": False}
    try:
        path = os.path.abspath(path)
        parent = os.path.dirname(path)
        if parent == path:  # 드라이브 루트 → 위로 가면 드라이브 목록
            parent = ""
        dirs = []
        for name in sorted(os.listdir(path), key=lambda s: s.lower()):
            fp = os.path.join(path, name)
            try:
                if os.path.isdir(fp):
                    dirs.append({"name": name, "path": fp})
            except OSError:
                pass
        is_scn = os.path.isfile(os.path.join(path, "Summary.xml"))
        return {"path": path, "parent": parent, "dirs": dirs, "is_scenario": is_scn}
    except (OSError, PermissionError) as e:
        return {"path": path, "parent": os.path.dirname(path), "dirs": [],
                "is_scenario": False, "error": str(e)}


def _stats():
    p = STATE["proj"]
    return extract.project_stats(p) if p else {}


def _file_summaries():
    p = STATE["proj"]
    if not p:
        return []
    out = []
    for rel, f in p["files"].items():
        free = [u for u in f["units"] if u["kind"] == "free"]
        done = sum(1 for u in free
                   if u.get("ko") and (u.get("force_done")
                                       or not extract.is_partial_ko(u["jp"], u["ko"])))
        # 실제 번역 내용(내부명 sysname 제외) 유무
        content = sum(1 for u in free if u.get("cat") != "sysname")
        out.append({"rel": rel, "free_total": len(free), "free_done": done,
                    "content": content})
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 콘솔 소음 억제
        pass

    # ── 응답 헬퍼 ──
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype):
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    # ── GET ──
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            return self._file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")
        if u.path.startswith("/static/"):
            name = u.path[len("/static/"):]
            fp = os.path.join(WEB_DIR, name)
            if os.path.isfile(fp):
                ctype = "text/javascript" if name.endswith(".js") else \
                        "text/css" if name.endswith(".css") else "application/octet-stream"
                return self._file(fp, ctype + "; charset=utf-8")
            return self._json({"error": "not found"}, 404)
        if u.path == "/api/listdir":
            return self._json(_listdir(q.get("path", [""])[0]))

        if u.path == "/api/state":
            p = STATE["proj"]
            return self._json({
                "open": bool(p),
                "scenario_dir": p["scenario_dir"] if p else None,
                "src_wsn": p.get("src_wsn") if p else None,
                "stats": _stats(),
                "files": _file_summaries(),
                "deepl": deepl.key_status(),
                "azure": azure_mt.key_status(),
                "version": update.local_version(),
            })
        if u.path == "/api/file":
            p = STATE["proj"]; rel = q.get("rel", [""])[0]
            if not p or rel not in p["files"]:
                return self._json({"error": "no file"}, 404)
            # 자유 텍스트만, 표시용으로 \n→실제 줄바꿈 디코드해서 전달
            from collections import Counter
            dup_cnt = Counter((un["field"], un["jp"])
                              for fd in p["files"].values()
                              for un in fd["units"] if un["kind"] == "free")
            units = []
            for un in p["files"][rel]["units"]:
                if un["kind"] != "free":
                    continue
                d = dict(un)
                d["jp"] = textcodec.decode_field(un["field"], un["jp"])
                d["ko"] = textcodec.decode_field(un["field"], un.get("ko", ""))
                n_dup = dup_cnt[(un["field"], un["jp"])]
                if n_dup > 1:
                    d["dups"] = n_dup       # 동일 원문 총 개수 (배지 표시용)
                if extract.is_partial_ko(un["jp"], un.get("ko", ""))                         and not un.get("force_done"):
                    d["partial"] = True     # 가나 잔존 = 부분 번역 (명시 완료 제외)
                units.append(d)
            return self._json({"rel": rel, "units": units})
        if u.path == "/api/search":
            p = STATE["proj"]
            if not p:
                return self._json({"error": "no project"}, 404)
            query = q.get("q", [""])[0]
            scope = q.get("scope", ["both"])[0]
            inc_ctrl = q.get("ctrl", ["0"])[0] == "1"
            return self._json({"results": search.search_units(p, query, scope,
                                                              include_control=inc_ctrl)})
        if u.path == "/api/overflow":
            p = STATE["proj"]
            if not p:
                return self._json({"error": "no project"}, 404)
            scope = q.get("scope", ["all"])[0]
            cur_rel = q.get("rel", [""])[0]
            return self._json({"results": overflow.find_overflow(p, scope, cur_rel)})
        if u.path == "/api/dup_choices":
            p = STATE["proj"]
            if not p:
                return self._json({"error": "no project"}, 404)
            scope = q.get("scope", ["all"])[0]
            cur_rel = q.get("rel", [""])[0]
            return self._json({"results": dupchoice.find_dup_choices(p, scope, cur_rel)})
        if u.path == "/api/outline":
            import xml.etree.ElementTree as ET
            p = STATE["proj"]; rel = q.get("rel", [""])[0]
            if not p or rel not in p["files"]:
                return self._json({"error": "no file"}, 404)
            resolve = STATE.get("resolve")
            if resolve is None:
                resolve = outline.build_resolve(p["scenario_dir"])
                STATE["resolve"] = resolve
            try:
                root = ET.parse(os.path.join(p["scenario_dir"], rel)).getroot()
            except Exception as e:
                return self._json({"error": str(e)}, 500)
            nd = outline.NameDisplay(p)
            content = {r2 for r2, fd in p["files"].items()
                       if any(un["kind"] == "free" and un.get("cat") != "sysname"
                              for un in fd["units"])}
            return self._json({"rel": rel,
                               "outline": outline.build_outline(root, resolve, nd,
                                                                content_rels=content)})
        if u.path == "/api/flow":
            p = STATE["proj"]
            if not p:
                return self._json({"error": "no project"}, 404)
            show_all = q.get("all", ["0"])[0] == "1"
            content_rels = None
            if not show_all:
                content_rels = {
                    rel for rel, fd in p["files"].items()
                    if any(un["kind"] == "free" and un.get("cat") != "sysname"
                           for un in fd["units"])
                }
            f = flow.build_flow(p["scenario_dir"], content_rels=content_rels)
            # 노드 라벨에 표시명(정식 번역/툴 전용 이름) 적용 — 원문은 id2name 으로 전달
            nd = outline.NameDisplay(p)
            orig = {rel: n["label"] for rel, n in f["nodes"].items()}
            for rel, n in f["nodes"].items():
                n["label"] = nd.scene_name(rel, n["label"])
            # 패키지 호출(Call type=Package) 엣지로 Area↔Package 실제 흐름을 그린다
            mm = flow.to_mermaid(f)
            mm["id2name"] = {f["nid"][rel]: orig[rel] for rel in f["nodes"]}
            mm["id2tool"] = {f["nid"][rel]: nd.tool.get(orig[rel].strip(), "")
                             for rel in f["nodes"]}
            return self._json(mm)

        if u.path == "/api/update_check":
            return self._json(update.check())

        if u.path == "/api/deepl_usage":
            try:
                return self._json({"ok": True, **deepl.usage()})
            except deepl.DeepLError as e:
                return self._json({"error": str(e)}, 502)

        if u.path == "/api/azure_usage":
            return self._json({"ok": True, **azure_mt.usage()})

        if u.path == "/api/fontglyph":
            c = (q.get("c", [""])[0] or "").lower()
            d = _glyph_font_dir()
            name = _GLYPH_NAMES.get(c)
            if d and name:
                fp = os.path.join(d, name + ".png")
                if os.path.isfile(fp):
                    return self._file(fp, "image/png")
            return self._json({"error": "no glyph"}, 404)

        if u.path == "/api/dup_where":
            p = STATE["proj"]
            if not p:
                return self._json({"error": "no project"}, 404)
            rel = q.get("rel", [""])[0]
            uid = int(q.get("id", ["0"])[0])
            src = next((x for x in p["files"].get(rel, {}).get("units", [])
                        if x["id"] == uid and x["kind"] == "free"), None)
            if src is None:
                return self._json({"error": "no unit"}, 404)
            key = (src["field"], src["jp"])
            out = []
            for rel2, f2 in p["files"].items():
                for u2 in f2["units"]:
                    if u2["kind"] == "free" and (u2["field"], u2["jp"]) == key:
                        out.append({"rel": rel2, "sid": u2["id"],
                                    "cat": u2.get("cat"),
                                    "done": bool(u2.get("ko")),
                                    "me": rel2 == rel and u2["id"] == uid})
            return self._json({"results": out})

        if u.path == "/api/mt_failed":
            p = STATE["proj"]
            if not p:
                return self._json({"error": "no project"}, 404)
            return self._json({"results": azure_mt.failed_units(p)})

        if u.path == "/api/deepl_count":
            p = STATE["proj"]
            if not p:
                return self._json({"error": "no project"}, 404)
            overwrite = q.get("overwrite", ["0"])[0] in ("1", "true", "True")
            cur_rel = q.get("rel", [""])[0]
            file_cnt = deepl.count_chars(p, cur_rel, overwrite) if cur_rel else None
            all_cnt = deepl.count_chars(p, None, overwrite)
            return self._json({"ok": True, "file": file_cnt, "all": all_cnt})

        if u.path == "/api/terms":
            p = STATE["proj"]
            if not p:
                return self._json({"error": "no project"}, 404)
            return self._json(terms.detect(p))

        if u.path == "/api/glossary":
            p = STATE["proj"]
            if not p:
                return self._json({"error": "no project"}, 404)
            items = [{"gkey": k, **g} for k, g in p["glossary"].items()]
            items.sort(key=lambda x: (x["etype"], x["jp"]))
            return self._json({"glossary": items})
        return self._json({"error": "not found"}, 404)

    # ── POST ──
    def do_POST(self):
        u = urlparse(self.path)
        try:
            data = self._body()
        except Exception as e:
            return self._json({"error": f"bad json: {e}"}, 400)

        if u.path == "/api/pick_folder":
            return self._json(_pick_folder_dialog(
                data.get("kind", "dir"), data.get("initfile", ""), data.get("initdir", "")))

        if u.path == "/api/open":
            d = data.get("scenario_dir", "").strip().strip('"')
            # 폴더인데 Summary.xml 없이 .wsn 패키지가 하나만 있으면 그걸 연다(변칙 배치 대응)
            if os.path.isdir(d) and not os.path.isfile(os.path.join(d, "Summary.xml")):
                wsns = [f for f in os.listdir(d) if f.lower().endswith(".wsn")
                        and os.path.isfile(os.path.join(d, f))]
                if len(wsns) == 1:
                    d = os.path.join(d, wsns[0])
            src_wsn = None
            if wsn.is_wsn(d):
                # .wsn(패키지) → 캐시에 풀어 XML 폴더처럼 사용
                src_wsn = os.path.abspath(d)
                try:
                    cache = os.path.join(project.PROJECTS_DIR, "_wsn")
                    os.makedirs(cache, exist_ok=True)
                    d = wsn.unpack_wsn(src_wsn, cache)
                except Exception as e:
                    return self._json({"error": f".wsn 풀기 실패: {e}"}, 500)
            if not os.path.isdir(d):
                return self._json({"error": f"폴더/.wsn 없음: {d}"}, 400)
            STATE["proj"] = project.open_or_extract(d)
            STATE["proj"]["src_wsn"] = src_wsn   # .wsn 으로 열었으면 내보낼 때 기본 .wsn
            STATE["resolve"] = None  # 새 시나리오 → 아웃라인 해석 맵 캐시 무효화
            project.save(STATE["proj"])
            project.save_last(src_wsn or d)  # 자동 리로드 후 복원용(.wsn 우선)
            return self._json({"ok": True, "scenario_dir": d, "src_wsn": src_wsn,
                               "stats": _stats(), "files": _file_summaries()})

        p = STATE["proj"]
        if u.path == "/api/set":
            if not p:
                return self._json({"error": "no project"}, 400)
            kind = data.get("kind")
            ko = data.get("ko", "")
            propagated = 0
            stale = 0
            if kind == "free":
                rel, uid = data["rel"], data["id"]
                src_unit = None
                old_disp = ""
                for unit in p["files"][rel]["units"]:
                    if unit["id"] == uid and unit["kind"] == "free":
                        old_disp = textcodec.decode_field(unit["field"], unit.get("ko", ""))
                        # #text 만 CardWirth 이스케이프(\\·\n), 속성(@name 선택지 등)은 raw 저장
                        unit["ko"] = textcodec.encode_field(unit["field"], ko)
                        # [완료로 표시]의 명시 완료 — 가나가 남아도 완료로 인정
                        if ko and data.get("force_done"):
                            unit["force_done"] = True
                        else:
                            unit.pop("force_done", None)
                        src_unit = unit
                        break
                # 동일 원문 자동 전파 — 캐스트카드 설명이 에어리어 메뉴카드에 복사되는
                # 구조 등, 같은 (field, jp) 의 "미번역" 칸을 같은 번역으로 채운다.
                # 이미 번역된 칸은 건드리지 않는다(문맥별로 다르게 고친 것 보호).
                if src_unit is not None and ko.strip():
                    key = (src_unit["field"], src_unit["jp"])
                    for f2 in p["files"].values():
                        for u2 in f2["units"]:
                            if u2 is src_unit or u2["kind"] != "free" \
                                    or u2.get("ko") or u2.get("control"):
                                continue
                            if (u2["field"], u2["jp"]) == key:
                                u2["ko"] = textcodec.encode_field(u2["field"], ko)
                                u2.pop("mt_failed", None)
                                propagated += 1
                # 수정(재번역) 감지: 같은 원문 칸 중 "수정 전과 같은 번역"이 몇 곳인지
                # 알려준다 — 프런트가 확인 후 /api/set_stale 로 함께 갱신할 수 있게.
                if src_unit is not None and old_disp and ko.strip() and old_disp != ko:
                    key = (src_unit["field"], src_unit["jp"])
                    for f2 in p["files"].values():
                        for u2 in f2["units"]:
                            if u2 is src_unit or u2["kind"] != "free" or u2.get("control"):
                                continue
                            if (u2["field"], u2["jp"]) == key \
                                    and textcodec.decode_field(u2["field"], u2.get("ko", "")) == old_disp:
                                stale += 1
            elif kind == "entity":
                gk = data["gkey"]
                if gk in p["glossary"]:
                    p["glossary"][gk]["ko"] = ko
            else:
                return self._json({"error": "bad kind"}, 400)
            return self._json({"ok": True, "stats": _stats(), "propagated": propagated,
                               "stale": stale})

        if u.path == "/api/set_stale":
            # 동일 원문 칸 중 "수정 전과 같은 번역"만 새 번역으로 갱신.
            # 문맥에 맞게 직접 다르게 번역해 둔 칸은 값이 달라서 자연히 보호된다.
            if not p:
                return self._json({"error": "no project"}, 400)
            rel, uid = data.get("rel"), data.get("id")
            old_ko = data.get("old_ko") or ""
            ko = data.get("ko") or ""
            src = next((x for x in p["files"].get(rel, {}).get("units", [])
                        if x["id"] == uid and x["kind"] == "free"), None)
            if src is None or not old_ko or not ko:
                return self._json({"error": "bad request"}, 400)
            key = (src["field"], src["jp"])
            n = 0
            for f2 in p["files"].values():
                for u2 in f2["units"]:
                    if u2 is src or u2["kind"] != "free" or u2.get("control"):
                        continue
                    if (u2["field"], u2["jp"]) == key \
                            and textcodec.decode_field(u2["field"], u2.get("ko", "")) == old_ko:
                        u2["ko"] = textcodec.encode_field(u2["field"], ko)
                        u2.pop("mt_failed", None)
                        n += 1
            return self._json({"ok": True, "applied": n, "stats": _stats()})

        if u.path == "/api/term":
            if not p:
                return self._json({"error": "no project"}, 400)
            jp, ko, kind = data.get("jp", ""), data.get("ko", ""), data.get("kind")
            applied = 0
            if kind == "exact":
                applied = terms.apply_exact(p, jp, ko)
            else:
                terms.set_word(p, jp, ko)
                if kind == "manual":
                    terms.add_manual(p, jp, ko)  # 수동 용어 번역 갱신
                if ko:
                    # 부분 번역(🈁)에 남아 있는 원문 단어를 즉시 치환
                    applied = terms.apply_word_to_existing(p, jp, ko)
            return self._json({"ok": True, "applied": applied, "stats": _stats()})

        if u.path == "/api/term_add":
            if not p:
                return self._json({"error": "no project"}, 400)
            jp = (data.get("jp") or "").strip()
            if not jp:
                return self._json({"error": "단어/문장을 입력하세요"}, 400)
            term = terms.add_manual(p, jp, data.get("ko", ""))
            project.save(p)
            return self._json({"ok": True, "term": term})

        if u.path == "/api/term_remove":
            if not p:
                return self._json({"error": "no project"}, 400)
            terms.remove_manual(p, (data.get("jp") or "").strip())
            project.save(p)
            return self._json({"ok": True})

        if u.path == "/api/reset":
            # 번역을 원문 상태로 초기화. scope="file"(rel 필수) | "all"(식별자 포함).
            # 용어집(terms)·수동 용어·툴 표시 이름은 유지. 직전 상태는 .bak_reset 백업.
            if not p:
                return self._json({"error": "no project"}, 400)
            scope = data.get("scope")
            rel = (data.get("rel") or "").strip()
            if scope not in ("file", "all") or (scope == "file" and rel not in p["files"]):
                return self._json({"error": "bad scope/rel"}, 400)
            pp = project.project_path(p["scenario_dir"])
            if os.path.isfile(pp):
                shutil.copyfile(pp, pp + ".bak_reset")      # 실수 대비 1회 백업
            n = 0
            for r2, fd in p["files"].items():
                if scope == "file" and r2 != rel:
                    continue
                for u2 in fd["units"]:
                    if u2["kind"] != "free":
                        continue
                    if u2.get("ko"):
                        n += 1
                    u2["ko"] = ""
                    u2.pop("force_done", None)
                    u2.pop("mt_failed", None)
            if scope == "all":
                for g in p["glossary"].values():
                    if g.get("ko"):
                        n += 1
                    g["ko"] = ""
            project.save(p)
            return self._json({"ok": True, "cleared": n, "stats": _stats()})

        if u.path == "/api/tool_name":
            # 툴 전용 표시 이름(흐름 패널/흐름 보기 라벨 번역) — export 에 안 들어감
            if not p:
                return self._json({"error": "no project"}, 400)
            name = (data.get("name") or "").strip()
            ko = (data.get("ko") or "").strip()
            if not name:
                return self._json({"error": "이름이 비었습니다"}, 400)
            tn = p.setdefault("tool_names", {})
            if ko and ko != name:
                tn[name] = ko
            else:
                tn.pop(name, None)      # 빈 값/원문 그대로 = 표시명 제거(원문으로)
            project.save(p)
            return self._json({"ok": True})

        if u.path == "/api/apply_terms":
            if not p:
                return self._json({"error": "no project"}, 400)
            only_unt = data.get("only_untranslated", True)
            n = terms.apply_words_to_drafts(p, only_untranslated=only_unt)
            return self._json({"ok": True, "drafted": n, "stats": _stats()})

        if u.path == "/api/overflow_tidy":
            if not p:
                return self._json({"error": "no project"}, 400)
            scope = data.get("scope", "all")
            cur_rel = data.get("rel", "")
            mode = data.get("mode", "full")     # "full"=상세 정돈 / "simple"=끝 빈 줄만
            res = overflow.tidy_overflow(p, scope, cur_rel, mode=mode)
            project.save(p)
            return self._json({"ok": True, **res, "stats": _stats()})

        if u.path == "/api/bulk_export":
            if not p:
                return self._json({"error": "no project"}, 400)
            path = (data.get("path") or "").strip().strip('"')
            if not path:
                return self._json({"error": "내보낼 파일 경로 필요"}, 400)
            try:
                n = bulkio.export_csv(p, path, only_untranslated=data.get("only_untranslated", False))
            except Exception as e:
                return self._json({"error": str(e)}, 500)
            return self._json({"ok": True, "rows": n, "path": path})

        if u.path == "/api/bulk_import":
            if not p:
                return self._json({"error": "no project"}, 400)
            path = (data.get("path") or "").strip().strip('"')
            if not os.path.isfile(path):
                return self._json({"error": f"파일 없음: {path}"}, 400)
            try:
                res = bulkio.import_csv(p, path)
            except Exception as e:
                return self._json({"error": str(e)}, 500)
            project.save(p)
            return self._json({"ok": True, "result": res, "stats": _stats()})

        if u.path == "/api/deepl_key":
            key = (data.get("key") or "").strip()
            if not key:
                return self._json({"error": "키를 입력하세요"}, 400)
            try:
                deepl.save_key(key)
            except Exception as e:
                return self._json({"error": str(e)}, 500)
            return self._json({"ok": True, **deepl.key_status()})

        if u.path == "/api/deepl_draft":
            if not p:
                return self._json({"error": "no project"}, 400)
            rel = data.get("rel") or None      # 없으면 전체
            if rel and rel not in p["files"]:
                return self._json({"error": f"파일 없음: {rel}"}, 404)
            try:
                res = deepl.draft_units(p, rel=rel, overwrite=bool(data.get("overwrite")))
            except deepl.DeepLError as e:
                return self._json({"error": str(e)}, 502)
            except Exception as e:
                return self._json({"error": str(e)}, 500)
            project.save(p)
            return self._json({"ok": True, "result": res, "stats": _stats()})

        if u.path == "/api/azure_key":
            key = (data.get("key") or "").strip()
            region = (data.get("region") or "").strip()
            if not key:
                return self._json({"error": "키를 입력하세요"}, 400)
            try:
                azure_mt.save_key(key, region)
            except Exception as e:
                return self._json({"error": str(e)}, 500)
            return self._json({"ok": True, **azure_mt.key_status()})

        if u.path == "/api/azure_draft":
            if not p:
                return self._json({"error": "no project"}, 400)
            rel = data.get("rel") or None      # 없으면 전체
            if rel and rel not in p["files"]:
                return self._json({"error": f"파일 없음: {rel}"}, 404)
            try:
                res = azure_mt.draft_units(p, rel=rel, overwrite=bool(data.get("overwrite")))
            except azure_mt.AzureError as e:
                return self._json({"error": str(e)}, 502)
            except Exception as e:
                return self._json({"error": str(e)}, 500)
            project.save(p)
            return self._json({"ok": True, "result": res, "stats": _stats(),
                               "failed": azure_mt.failed_units(p)})

        if u.path == "/api/update_apply":
            try:
                res = update.apply()
            except Exception as e:
                return self._json({"error": str(e)}, 500)
            # app/*.py 가 바뀌었으면 자동 리로더가 곧 서버를 재시작한다.
            return self._json({"ok": True, **res})

        if u.path == "/api/save":
            if not p:
                return self._json({"error": "no project"}, 400)
            return self._json({"ok": True, "path": project.save(p)})

        if u.path == "/api/export":
            if not p:
                return self._json({"error": "no project"}, 400)
            out = data.get("out_dir", "").strip().strip('"')
            if not out:
                return self._json({"error": "out_dir 필요"}, 400)
            project.save(p)
            # 출력 경로가 .wsn 이면 폴더로 repack 후 ZIP(.wsn)으로 압축
            if out.lower().endswith(".wsn"):
                tmp = out[:-4] + "_folder"
                r = repack.repack_project(p, tmp)
                entries = wsn.pack_wsn(tmp, out)
                shutil.rmtree(tmp, ignore_errors=True)   # 압축용 임시 폴더 정리(.wsn 만 남김)
                return self._json({"ok": True, "out_dir": os.path.abspath(out),
                                   "result": r, "wsn": True, "entries": entries})
            r = repack.repack_project(p, out)
            return self._json({"ok": True, "out_dir": os.path.abspath(out), "result": r})

        return self._json({"error": "not found"}, 404)


def _start_reloader():
    """app/*.py 변경 감지 시 서버를 자동 재시작(개발 편의). 브라우저는 다시 안 엶."""
    import threading
    import time
    import glob
    watch = glob.glob(os.path.join(os.path.dirname(__file__), "*.py"))

    def loop():
        mt = {p: os.path.getmtime(p) for p in watch if os.path.exists(p)}
        while True:
            time.sleep(1)
            for p in list(mt):
                try:
                    m = os.path.getmtime(p)
                except OSError:
                    continue
                if m != mt[p]:
                    print(f"[reload] {os.path.basename(p)} 변경 감지 → 재시작")
                    os.environ["CWKR_NOBROWSER"] = "1"  # 재시작 시 브라우저 재오픈 안 함
                    os.execv(sys.executable, [sys.executable, "-m", "app.server"])
    threading.Thread(target=loop, daemon=True).start()


def main():
    # 콘솔 코드페이지(cp932/cp949 등)와 무관하게 한글 출력이 크래시나지 않도록 utf-8 강제
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # 직전에 열었던 시나리오 자동 복원(리로드 후에도 이어서)
    last = project.load_last()
    if last:
        try:
            src_wsn = None
            d = last
            if wsn.is_wsn(last):
                src_wsn = os.path.abspath(last)
                cache = os.path.join(project.PROJECTS_DIR, "_wsn")
                os.makedirs(cache, exist_ok=True)
                d = wsn.unpack_wsn(src_wsn, cache)
            STATE["proj"] = project.open_or_extract(d)
            STATE["proj"]["src_wsn"] = src_wsn
            print(f"[복원] 직전 시나리오: {last}")
        except Exception:
            pass

    _start_reloader()

    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"CardWirth 한글화 에디터 실행 중 → {url}")
    print("코드 자동 리로드 켜짐. 종료: Ctrl+C")
    if not os.environ.get("CWKR_NOBROWSER"):
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n종료")


if __name__ == "__main__":
    main()

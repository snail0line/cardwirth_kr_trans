# -*- coding: utf-8 -*-
"""
CardWirth 한글화 — 로컬 웹 에디터 (stdlib only).

실행:  python -m app.server   →  http://127.0.0.1:8765
"""
from __future__ import annotations
import os
import sys
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import project, repack, extract, textcodec, flow, terms, outline, bulkio, wsn, deepl

WEB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web"))
HOST, PORT = "127.0.0.1", 8765

# 단일 사용자 로컬 툴 → 전역 현재 프로젝트
STATE = {"proj": None}


# 네이티브 선택 다이얼로그(별도 프로세스). 창을 데스크톱 최상단으로 끌어올린다.
def _picker_code(kind: str) -> str:
    if kind == "file":     # .wsn 패키지 파일 선택
        call = ("p=filedialog.askopenfilename(title='CardWirth .wsn package', parent=r,"
                "filetypes=[('CardWirth 패키지','*.wsn'),('모든 파일','*.*')])\n")
    else:                  # 시나리오 XML 폴더 선택
        call = "p=filedialog.askdirectory(title='CardWirth scenario XML folder', parent=r)\n"
    return (
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


def _pick_folder_dialog(kind: str = "dir") -> dict:
    """사용자 데스크톱에 네이티브 선택 다이얼로그를 띄운다. kind: 'dir'|'file'.
    서버가 사용자의 인터랙티브 세션에서 실행 중이어야 창이 보인다.
    반환: {path, error}."""
    import subprocess
    try:
        # text=False(바이트)로 받아 UTF-8 로 직접 디코드 (cp932 자동디코딩 크래시 방지)
        out = subprocess.run([sys.executable, "-c", _picker_code(kind)],
                             capture_output=True, timeout=600)
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
        done = sum(1 for u in free if u.get("ko"))
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
            })
        if u.path == "/api/file":
            p = STATE["proj"]; rel = q.get("rel", [""])[0]
            if not p or rel not in p["files"]:
                return self._json({"error": "no file"}, 404)
            # 자유 텍스트만, 표시용으로 \n→실제 줄바꿈 디코드해서 전달
            units = []
            for un in p["files"][rel]["units"]:
                if un["kind"] != "free":
                    continue
                d = dict(un)
                d["jp"] = textcodec.decode(un["jp"])
                d["ko"] = textcodec.decode(un.get("ko", ""))
                units.append(d)
            return self._json({"rel": rel, "units": units})
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
            return self._json({"rel": rel, "outline": outline.build_outline(root, resolve)})
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
            # 패키지 호출(Call type=Package) 엣지로 Area↔Package 실제 흐름을 그린다
            return self._json(flow.to_mermaid(f))

        if u.path == "/api/deepl_usage":
            try:
                return self._json({"ok": True, **deepl.usage()})
            except deepl.DeepLError as e:
                return self._json({"error": str(e)}, 502)

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
            return self._json(_pick_folder_dialog(data.get("kind", "dir")))

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
            if kind == "free":
                rel, uid = data["rel"], data["id"]
                ko_raw = textcodec.encode(ko)  # 줄바꿈 → \n 저장형
                for unit in p["files"][rel]["units"]:
                    if unit["id"] == uid and unit["kind"] == "free":
                        unit["ko"] = ko_raw
                        break
            elif kind == "entity":
                gk = data["gkey"]
                if gk in p["glossary"]:
                    p["glossary"][gk]["ko"] = ko
            else:
                return self._json({"error": "bad kind"}, 400)
            return self._json({"ok": True, "stats": _stats()})

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

        if u.path == "/api/apply_terms":
            if not p:
                return self._json({"error": "no project"}, 400)
            only_unt = data.get("only_untranslated", True)
            n = terms.apply_words_to_drafts(p, only_untranslated=only_unt)
            return self._json({"ok": True, "drafted": n, "stats": _stats()})

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

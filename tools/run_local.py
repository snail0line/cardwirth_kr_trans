# -*- coding: utf-8 -*-
r"""웹툴 로컬 실행 — GPT 번역 엔진을 붙여서 띄운다. 배포 안 함(.gitignore).

app/server.py 와 web/ 은 배포본에 포함되는 파일이라 손대지 않는다. 대신 이 런처가
서버를 import 한 뒤 핸들러를 감싸서(monkeypatch) GPT 경로만 얹는다.

  · POST /api/gpt_draft   : 현재 프로젝트(또는 rel 파일 하나)를 GPT 초안으로 채움
  · GET  /api/gpt_status  : 키·모델·이번 달 사용액
  · GET  /  ·  /index.html: 원본 HTML 에 GPT 버튼 스크립트를 주입해서 내보냄

그래서 이 스크립트로 띄웠을 때만 GPT 버튼이 보이고, run.bat 으로 띄우면 배포본과
완전히 동일하게 동작한다.

  python tools\run_local.py

기존 DeepL/Azure 기능은 그대로다. 서버가 원래 하던 코드 자동 리로드도 유지하되,
재시작 대상을 app.server 가 아니라 이 런처로 바꾼다(안 그러면 리로드 후 GPT 가 사라진다).
"""
from __future__ import annotations
import glob
import json
import os
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from app import server, project, ds_mt                     # noqa: E402

# 브라우저에 주입할 조각. 기존 "초안" 버튼 옆에 GPT 버튼을 새로 만든다.
# 원본 app.js 의 흐름(curEngine/runDraft)에 끼어들지 않고 독립 버튼으로 두는 편이
# 배포본 코드가 바뀌어도 덜 깨진다.
_INJECT = """
<style>
  #gptBar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;
          padding:8px 10px;margin:8px 0;border:1px solid #e5e7eb;border-radius:8px;
          background:#f9fafb;font-size:13px}
  #gptBar b{color:#111827}
  #gptBar button{padding:5px 12px;border:1px solid #d1d5db;border-radius:6px;
                 background:#fff;cursor:pointer}
  #gptBar button:hover:not(:disabled){border-color:#2563eb;color:#2563eb}
  #gptBar button:disabled{opacity:.5;cursor:default}
  #gptStat{color:#6b7280}
</style>
<script>
(function () {
  function mk() {
    if (document.getElementById("gptBar")) return true;
    // DeepL 초안 버튼이 있는 영역 뒤에 붙인다.
    var anchor = document.querySelector("#deeplDraftAll");
    if (!anchor) return false;
    var host = anchor.closest("section, div") || anchor.parentElement;
    var bar = document.createElement("div");
    bar.id = "gptBar";
    bar.innerHTML =
      '<b>GPT</b>' +
      '<button id="gptDraftFile">이 파일 초안</button>' +
      '<button id="gptDraftAll">전체 초안</button>' +
      '<label><input type="checkbox" id="gptOverwrite"> 기존 번역도 덮어쓰기</label>' +
      '<span id="gptStat">…</span>';
    host.parentNode.insertBefore(bar, host.nextSibling);

    function stat(t) { document.getElementById("gptStat").textContent = t; }
    function busy(b) {
      ["gptDraftFile", "gptDraftAll"].forEach(function (i) {
        document.getElementById(i).disabled = b;
      });
    }
    function refresh() {
      fetch("/api/gpt_status").then(function (r) { return r.json(); }).then(function (s) {
        stat(s.set ? (s.model + " · 이번 달 $" + (s.cost || 0).toFixed(4))
                   : "키 없음 (tools/.deepseek_key)");
      }).catch(function () { stat("상태 조회 실패"); });
    }
    function draft(all) {
      var rel = all ? "" : (window.CUR_REL || "");
      if (!all && !rel) { stat("파일을 먼저 여세요"); return; }
      busy(true); stat("번역 중…");
      fetch("/api/gpt_draft", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rel: rel,
          overwrite: document.getElementById("gptOverwrite").checked
        })
      }).then(function (r) { return r.json(); }).then(function (d) {
        busy(false);
        if (d.error) { stat("실패: " + d.error); return; }
        var r = d.result || {};
        stat(r.translated + "칸 번역 · $" + (r.cost || 0).toFixed(4) +
             (r.skipped ? " · 실패 " + r.skipped + "건" : ""));
        if (typeof window.reloadAll === "function") window.reloadAll();
        else location.reload();
      }).catch(function (e) { busy(false); stat("실패: " + e); });
    }
    document.getElementById("gptDraftAll").onclick = function () { draft(true); };
    document.getElementById("gptDraftFile").onclick = function () { draft(false); };
    refresh();
    return true;
  }
  // app.js 가 DOM 을 그린 뒤에 붙어야 해서 잠깐 폴링한다.
  var n = 0;
  var t = setInterval(function () { if (mk() || ++n > 60) clearInterval(t); }, 250);
})();
</script>
"""

_orig_get = server.Handler.do_GET
_orig_post = server.Handler.do_POST


def _do_GET(self):
    from urllib.parse import urlparse
    u = urlparse(self.path)
    if u.path == "/api/gpt_status":
        st = ds_mt.key_status()
        return self._json({**st, **{"cost": ds_mt.usage()["cost"]}})
    if u.path in ("/", "/index.html"):
        try:
            with open(os.path.join(server.WEB_DIR, "index.html"), encoding="utf-8") as f:
                html = f.read()
        except OSError as e:
            return self._json({"error": str(e)}, 500)
        html = (html.replace("</body>", _INJECT + "</body>") if "</body>" in html
                else html + _INJECT)
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        return
    return _orig_get(self)


def _do_POST(self):
    from urllib.parse import urlparse
    u = urlparse(self.path)
    if u.path != "/api/gpt_draft":
        return _orig_post(self)
    try:
        data = self._body()
    except Exception as e:
        return self._json({"error": f"bad json: {e}"}, 400)
    p = server.STATE["proj"]
    if not p:
        return self._json({"error": "no project"}, 400)
    rel = data.get("rel") or None                 # 없으면 전체
    if rel and rel not in p["files"]:
        return self._json({"error": f"파일 없음: {rel}"}, 404)
    try:
        res = ds_mt.draft_units(p, rel=rel, overwrite=bool(data.get("overwrite")))
    except ds_mt.DeepSeekError as e:
        return self._json({"error": str(e)}, 502)
    except Exception as e:
        return self._json({"error": str(e)}, 500)
    project.save(p)
    return self._json({"ok": True, "result": res, "stats": server._stats(),
                       "failed": ds_mt.failed_units(p)})


def _reloader():
    """원본 리로더는 app.server 로 재시작해서 이 패치를 날린다. 이 런처로 되살린다."""
    watch = glob.glob(os.path.join(_ROOT, "app", "*.py")) + [os.path.abspath(__file__)]

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
                    os.environ["CWKR_NOBROWSER"] = "1"
                    os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)])
    threading.Thread(target=loop, daemon=True).start()


def main():
    server.Handler.do_GET = _do_GET
    server.Handler.do_POST = _do_POST
    server._start_reloader = _reloader
    st = ds_mt.key_status()
    print(f"[local] GPT 엔진 연결 — 모델 {st['model']} · 키 "
          f"{'있음' if st['set'] else '없음'}")
    print("[local] 이 창으로 띄운 동안만 GPT 버튼이 보입니다 (run.bat 은 배포본과 동일)")
    server.main()


if __name__ == "__main__":
    main()

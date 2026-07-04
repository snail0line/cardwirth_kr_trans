"use strict";
const $ = (s) => document.querySelector(s);

// ── 전역 커스텀 툴팁 ──
// 모든 title 속성(정적/동적)을 가로채 스타일된 말풍선(#globaltip)으로 표시한다.
// title 은 발견 즉시 data-tip 으로 옮겨 브라우저 기본 툴팁을 억제. \n = 줄바꿈.
(() => {
  const tip = document.createElement("div");
  tip.id = "globaltip";
  document.addEventListener("DOMContentLoaded", () => document.body.appendChild(tip));
  let target = null, timer = null;
  const hide = () => { clearTimeout(timer); target = null; tip.style.display = "none"; };
  document.addEventListener("mouseover", (e) => {
    const t = e.target.closest("[title], [data-tip]");
    if (!t) return;
    if (t.hasAttribute("title")) {          // 갱신된 title 도 매번 반영
      t.dataset.tip = t.getAttribute("title");
      t.removeAttribute("title");
    }
    if (t === target || !t.dataset.tip) return;
    clearTimeout(timer);
    target = t;
    timer = setTimeout(() => {
      if (target !== t || !document.contains(t)) return;
      tip.textContent = t.dataset.tip;
      tip.style.display = "block";
      const r = t.getBoundingClientRect();
      let x = r.left, y = r.bottom + 8;
      x = Math.max(4, Math.min(x, window.innerWidth - tip.offsetWidth - 8));
      if (y + tip.offsetHeight > window.innerHeight - 8) y = r.top - tip.offsetHeight - 8;
      tip.style.left = x + "px";
      tip.style.top = Math.max(4, y) + "px";
    }, 350);
  });
  document.addEventListener("mouseout", (e) => {
    if (target && !target.contains(e.relatedTarget)) hide();
  });
  document.addEventListener("click", hide, true);
  document.addEventListener("scroll", hide, true);
})();
const api = async (path, opts) => (await fetch(path, opts)).json();
const post = (path, body) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

let STATE = { open: false, files: [], curRel: null };

// ── 게임 내 줄바꿈 미리보기 ──
// CardWirthPy(AtWS) 렌더러는 픽셀이 아니라 strlen 고정 그리드로 줄바꿈한다.
//   strlen: 반각(ASCII)=1, 전각(한글·일본어·한자·전각기호)=2 (util.get_strlen)
//   색·제어코드(&X)는 폭 0. 선두 전각공백(들여쓰기)도 포함해서 셈.
//   한 줄 한계 = 43 단위(일반) / 33 단위(화자 그림 있을 때). 세로 = 창에 약 7줄.
const LINE_UNITS = 43;      // 일반 메시지 자동 줄바꿈 한계(strlen)
const LINE_UNITS_IMG = 33;  // 화자 그림/사진 있는 메시지 (그림 폭만큼 좁음, 32+1)
const WRAP_ROWS = 7;        // 넘침 판정 기준 줄 수 — 8줄째부터 잘림(창 180px/줄 22px)
// 카드 해설창(CastCard/ItemCard/SkillCard) — cardinfo.py + util.txtwrap mode=1.
// wx 다이얼로그라 메시지창과 별개: 폭 37단위·9줄·13px, 색코드/7줄컷 없음(있는 그대로 표시).
const CARD_UNITS = 37;
const CARD_ROWS = 9;

function charUnits(ch) {
  const c = ch.codePointAt(0);
  if (c === 0x3000) return 2;                 // 전각 공백(들여쓰기)
  if (c <= 0x2ff) return 1;                   // ASCII·라틴 → 반각
  if (c >= 0xff61 && c <= 0xff9f) return 1;   // 반각 가타카나
  return 2;                                   // 한글·일본어·한자·전각기호
}

// CardWirthPy 폰트 색코드(&X) → 색 (cw/sprite/message.py get_fontcolour). 소문자만 유효.
// b 는 파랑이 아니라 시안(0,255,255). o/p/l/d 는 1.50+. &w·미정의 코드는 기본색으로 리셋.
const FONT_COLORS = {
  r: "#ff0000", g: "#00ff00", b: "#00ffff", y: "#ffff00", w: "#ffffff",
  o: "#ffa500", p: "#cc88ff", l: "#a9a9a9", d: "#696969",
};

// 텍스트를 게임처럼 strlen 한계(units)로 접어 줄 배열로 반환. 각 줄은 {color,text} 런 배열.
// &X 색코드는 폭 0(줄바꿈 계산에서 제외)이며, 색은 줄바꿈·명시적 \n 을 넘어 유지된다.
// #X 이모지 글리프(스킨 Resource/Image/Font, cw/setting.py 매핑) — 유니코드 근사.
// 게임은 현재 폰트색을 곱연산 틴트하므로(BLEND_RGBA_MULT) 기호형 글리프엔 런 색이 그대로 먹는다.
// 폭은 게임과 동일하게 전각 1글자(2단위) 취급. 대소문자 무관.
const FONT_GLYPHS = {
  a: "💢", b: "♣", d: "♦", e: "☺", f: "🪰", g: "😢", h: "♥", j: "🃏", k: "💋",
  l: "😆", n: "🙂", o: "♨", p: "🧩", q: "💨", s: "♠", w: "😟", x: "✖", z: "⚡",
};

// 스킨 글리프 이미지 캐시 — 서버(/api/fontglyph)에서 실제 스킨 PNG 를 받아,
// 게임과 같은 곱연산(BLEND_RGBA_MULT)으로 현재 폰트색을 틴트해 표시한다.
// 이미지를 못 찾으면(CardWirthPy 경로 미설정 등) 유니코드 근사(FONT_GLYPHS)로 폴백.
const GLYPH_IMGS = {};
function loadGlyph(letter) {
  if (!(letter in GLYPH_IMGS)) {
    GLYPH_IMGS[letter] = new Promise((res) => {
      const img = new Image();
      img.onload = () => res(img);
      img.onerror = () => res(null);
      img.src = "/api/fontglyph?c=" + letter;
    });
  }
  return GLYPH_IMGS[letter];
}
function glyphEl(letter, color) {
  const holder = document.createElement("span");
  holder.className = "gp-glyph";
  holder.textContent = FONT_GLYPHS[letter] || "#" + letter;   // 로드 전/실패 폴백
  loadGlyph(letter).then((img) => {
    if (!img) return;
    // 1) 마젠타(#FF00FF) 컬러키 → 투명 (classic 리소스 투명색 규약)
    const base = document.createElement("canvas");
    base.width = img.width; base.height = img.height;
    const bg = base.getContext("2d");
    bg.drawImage(img, 0, 0);
    const px = bg.getImageData(0, 0, base.width, base.height);
    const d = px.data;
    for (let k = 0; k < d.length; k += 4) {
      if (d[k] === 255 && d[k + 1] === 0 && d[k + 2] === 255) d[k + 3] = 0;
    }
    bg.putImageData(px, 0, 0);
    // 2) 색 곱연산 틴트 (BLEND_RGBA_MULT) 후 알파 복원
    const cv = document.createElement("canvas");
    cv.width = base.width; cv.height = base.height;
    const g = cv.getContext("2d");
    g.drawImage(base, 0, 0);
    g.globalCompositeOperation = "multiply";
    g.fillStyle = color || "#ffffff";            // 기본 폰트색 = 흰색 → 원본 그대로
    g.fillRect(0, 0, cv.width, cv.height);
    g.globalCompositeOperation = "destination-in";
    g.drawImage(base, 0, 0);
    cv.className = "gp-glyph";
    cv.title = "#" + letter;
    if (holder.isConnected) holder.replaceWith(cv);
  });
  return holder;
}

function wrapForGameRuns(text, units) {
  const lines = [];
  let cur = [], color = "", w = 0;
  const push = (ch) => {
    const last = cur[cur.length - 1];
    if (last && !last.glyph && last.color === color) last.text += ch;   // 글리프 run 에는 병합 금지
    else cur.push({ color, text: ch });
  };
  const newline = () => { lines.push(cur); cur = []; w = 0; };
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === "\n") { newline(); continue; }
    if (ch === "&" && /[A-Za-z]/.test(text[i + 1] || "")) {   // 색코드(폭 0)
      color = FONT_COLORS[text[++i].toLowerCase()] || "";     // 미정의·&w → 기본색
      continue;
    }
    if (ch === "#" && FONT_GLYPHS[(text[i + 1] || "").toLowerCase()]) {  // 이모지 글리프(전각 폭)
      if (w + 2 > units && w > 0) newline();
      cur.push({ glyph: text[++i].toLowerCase(), color });   // 스킨 이미지로 렌더(색상 틴트)
      w += 2;
      continue;
    }
    const cw = charUnits(ch);
    if (w + cw > units && w > 0) newline();
    push(ch); w += cw;
  }
  lines.push(cur);                                            // 마지막(빈) 줄
  return lines;
}

// 카드 해설용 평문 줄바꿈 — cw/util.txtwrap mode=1 재현(wx 다이얼로그).
// 엔진 규칙: ①다음 글자가 반각(줄 끝 개행 포함)이면 폭 +1 허용 — 전각 19자 줄(38단위)이
//   안 접히는 이유. ②행두 금지 문자(WRAP_HANG)는 줄 끝에 매달아 넘겨쓰기(ぶら下げ).
const WRAP_HANG = "｡|､|，|、|。|．|）|」|』|〕|｝|】";   // util.WRAPS_CHARS
function wrapPlain(text, units) {
  const out = [];
  for (const raw of text.split("\n")) {
    let line = "", w = 0;
    const chars = [...raw];
    for (let i = 0; i < chars.length; i++) {
      const ch = chars[i];
      const cw = charUnits(ch);
      if (w + cw > units && line !== "") {
        const next = chars[i + 1];
        const bonus = (next === undefined || charUnits(next) === 1) ? 1 : 0;  // 다음이 반각/줄끝
        if (!(WRAP_HANG.includes(ch) || w + cw <= units + bonus)) {
          out.push(line); line = ""; w = 0;
        }
      }
      line += ch; w += cw;
    }
    out.push(line);
  }
  return out;
}

// 정돈 — 문단(빈 줄로 구분되는 블록) 안의 수동 줄바꿈을 없애 게임 자동 줄바꿈에 맡긴다.
// 강제 개행은 줄 수를 늘리기만 하므로, 이어붙이면 세로 줄 수가 최소가 된다(넘침 완화).
// 규칙: 빈 줄(문단 경계)은 그대로 두고, 한 문단의 이어지는 줄은 앞쪽 들여쓰기(전각공백 포함)를
// 떼고 한 칸 띄어 이어붙인다. 각 문단 첫 줄의 들여쓰기는 유지한다.
function tidyText(text) {
  const out = [];
  let cur = [];
  const flush = () => {
    if (!cur.length) return;
    const first = cur[0].replace(/\s+$/, "");                 // 첫 줄 들여쓰기 유지, 우측 공백만 제거
    const rest = cur.slice(1)
      .map((l) => l.replace(/^\s+/, "").replace(/\s+$/, "")); // 이어지는 줄은 앞뒤 공백 제거
    out.push([first, ...rest].join(" "));
    cur = [];
  };
  for (const ln of String(text).split("\n")) {
    if (ln.trim() === "") { flush(); out.push(""); }          // 빈 줄 = 문단 경계 유지
    else cur.push(ln);
  }
  flush();
  while (out.length && out[out.length - 1] === "") out.pop();  // 끝의 빈 줄(마지막 엔터) 제거 → 넘침 완화
  return out.join("\n");
}

// 치환자(변수·이름 코드) — 게임 실행 시 값으로 치환된다(message.py _rpl_specialstr).
// 에디터엔 그 상태가 없으니 사용자가 값을 넣어 미리볼 수 있게 한다. 값은 세션 전역 공유.
const SUBST = {};                                        // 토큰 → 대체 텍스트
const SUBST_RE = /(\$[^$\n]+\$|%[^%\n]+%|#[MURICYTmuricyt])/g;   // $..$ / %..% 변수, #x 이름코드(이모지 글리프 #e 등 제외)
const SHARP_LABEL = {                                    // #코드 뜻
  "#m": "선택 캐릭터명", "#u": "비선택 캐릭터명", "#r": "랜덤 캐릭터명",
  "#i": "화자명", "#c": "사용 카드명", "#y": "숙소 이름", "#t": "파티 이름",
};
function findSubstTokens(text) {
  const seen = [];
  const m = text.match(SUBST_RE);
  if (m) m.forEach((t) => { if (!seen.includes(t)) seen.push(t); });
  return seen;
}
function applySubst(text) {
  return text.replace(SUBST_RE, (t) => (SUBST[t] ? SUBST[t] : t));   // 값 없으면 토큰 그대로
}

// 가나가 남은 번역 = 부분 번역(용어 치환 초안 등) — 완료로 치지 않는다.
// 단 ko === jp(원문 그대로 완료)는 의도적 유지로 완료 인정 (extract.is_partial_ko 와 동일)
const KANA_RE = /[ぁ-ゖァ-ヺｦ-ﾝ]/;
function isPartial(u) {
  return !!u.ko && u.ko !== u.jp && KANA_RE.test(u.ko) && !u.force_done;
}
// 완료 판정 — 번역 있음 + (가나 없음 or 명시 완료[force_done])
function isDone(u) {
  return !!u.ko && !isPartial(u);
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 1800);
}

function renderProgress(stats) {
  if (!stats || !stats.free_total) { $("#progress").textContent = "—"; return; }
  $("#progress").textContent = `번역 ${stats.free_done}/${stats.free_total} · 파일 ${stats.files}`;
}

function renderFileList() {
  const box = $("#fileList");
  box.innerHTML = "";
  const hideEmpty = $("#hideEmpty").checked;
  const files = STATE.files.filter((f) => !hideEmpty || (f.content ?? f.free_total) > 0);
  $("#fileCount").textContent = files.length ? `(${files.length}${hideEmpty && files.length < STATE.files.length ? "/" + STATE.files.length : ""})` : "";
  files.forEach((f) => {
    const div = document.createElement("div");
    div.className = "fileitem" + (f.rel === STATE.curRel ? " active" : "");
    const full = f.free_total > 0 && f.free_done === f.free_total;
    div.innerHTML = `<span class="nm" title="${f.rel}">${f.rel}</span>
      <span class="ct ${full ? "full" : ""}">${f.free_done}/${f.free_total}</span>`;
    div.onclick = () => openFile(f.rel);
    box.appendChild(div);
  });
}

async function refreshState() {
  const s = await api("/api/state");
  STATE.open = s.open;
  STATE.files = s.files || [];
  STATE.srcWsn = s.src_wsn || null;
  renderProgress(s.stats);
  if (s.version && $("#appVer")) $("#appVer").textContent = " v" + s.version;
  if (s.open) {
    $("#scenDir").value = s.src_wsn || s.scenario_dir;
    $("#filterbar").style.display = "flex";
  }
  renderFileList();
}

// ── 자동 업데이트 ──
async function checkUpdate() {
  try {
    const r = await api("/api/update_check");
    if (r && r.behind && r.latest) {
      $("#updateMsg").textContent = `🆕 새 버전 v${r.latest} 가 나왔어요 (현재 v${r.current})`;
      $("#updateBtn").disabled = false;
      $("#updateBar").style.display = "flex";
    }
  } catch (e) { /* 오프라인 등 — 조용히 무시 */ }
}
async function applyUpdate() {
  if (!confirm("최신 버전으로 업데이트할까요?\n코드 파일만 교체되고 번역 진행상황·DeepL 키·시나리오는 그대로 유지됩니다.\n완료 후 서버가 자동 재시작됩니다.")) return;
  $("#updateBtn").disabled = true;
  $("#updateMsg").textContent = "업데이트 중… (다운로드·교체, 수십 초)";
  const r = await post("/api/update_apply");
  if (r.error) {
    $("#updateMsg").textContent = "업데이트 오류: " + r.error;
    $("#updateBtn").disabled = false;
    return;
  }
  $("#updateMsg").textContent = `✅ v${r.updated_to} 로 업데이트됨 (파일 ${r.files}개) · 서버 재시작 중… 잠시 후 자동 새로고침`;
  setTimeout(() => location.reload(), 4500);
}

// ── 네이티브 Windows 선택 다이얼로그 (폴더 / .wsn 파일) ──
async function pickAndOpen(kind) {
  toast(kind === "file" ? ".wsn 파일 선택창을 여는 중…" : "폴더 선택창을 여는 중…");
  const r = await post("/api/pick_folder", { kind: kind || "dir" });
  if (r.error) return toast("선택창 오류: " + r.error + " (터미널에서 직접 서버를 실행했는지 확인)");
  if (!r.path) return toast("취소됨");
  $("#scenDir").value = r.path;
  openScenario();
}

async function openScenario() {
  const dir = $("#scenDir").value.trim();
  if (!dir) return toast("폴더 경로를 입력하세요");
  toast("여는 중…");
  const r = await post("/api/open", { scenario_dir: dir });
  if (r.error) return toast("오류: " + r.error);
  STATE.curRel = null;
  await refreshState();
  $("#viewTitle").textContent = "파일을 선택하세요 (" + r.files.length + "개)";
  $("#units").innerHTML = "";
  toast("열림");
}

function unitVisible(u) {
  if ($("#hideDone").checked && isDone(u)) return false;
  // %상태변수% 를 표시하는 메시지는 control(읽기전용)이라도 맥락 확인용으로 항상 표시
  if ($("#hideControl").checked && u.control && !(u.varrefs && u.varrefs.length)) return false;
  return true;
}

let VIEW = "list"; // "list" | "flow"

async function openFile(rel) {
  STATE.curRel = rel;
  renderFileList();
  const r = await api("/api/file?rel=" + encodeURIComponent(rel));
  $("#viewTitle").textContent = rel;
  STATE.curUnits = (r.units || []).filter((u) => u.kind === "free");
  STATE.unitById = {};
  STATE.curUnits.forEach((u) => { STATE.unitById[u.id] = u; });
  if (VIEW === "flow") return renderFlowView(rel);
  renderListView(rel);
}

function renderListView(rel) {
  const box = $("#units");
  box.innerHTML = "";
  const shown = STATE.curUnits.filter(unitVisible);
  if (!shown.length) {
    box.innerHTML = `<div class="empty">표시할 번역 텍스트가 없습니다.</div>`;
    return;
  }
  // 말투 변형(같은 group) 은 한 묶음으로
  let i = 0;
  while (i < shown.length) {
    const u = shown[i];
    if (u.group != null) {
      const grp = [u];
      let j = i + 1;
      while (j < shown.length && shown[j].group === u.group) { grp.push(shown[j]); j++; }
      box.appendChild(toneGroupEl(rel, grp));
      i = j;
    } else {
      box.appendChild(freeUnitEl(rel, u));
      i++;
    }
  }
}

// 흐름 보기: 이벤트 진행 순서(패키지 콜/링크/분기 포함) 타임라인
const OL_ICON = { start: "▶", talk: "💬", branch: "❖", call: "»", link: "↪", change: "⇒", end: "■", misc: "·" };
// 흐름 보기 내비게이션 스택: 호출로 들어갈 때마다 프레임을 쌓아, 중첩 호출에서
// 돌아와도 바깥 호출원을 잃지 않는다. 프레임 = {from, calls, idx, target}
let FLOWSTACK = [];
// 흐름 보기 모드: "file" = 파일 이동 + 호출원/다음 배너, "linear" = 호출 인라인 펼침
let FLOWMODE = localStorage.getItem("flowmode") || "file";

// 일렬 모드: rel 의 아웃라인에 패키지 호출 대상 파일의 아웃라인을 진행 순서대로
// 재귀로 이어붙인다. 같은 패키지는 첫 호출에서만 펼치고(expanded), 재호출 지점은
// "앞에서 이미 펼쳐짐" 표시만 남긴다 — 같은 내용이 여러 번 보여 헷갈리는 것 방지.
// visited = 현재 경로(순환 차단), 깊이 8 제한. maps[rel] = 유닛 id 맵.
async function buildLinearOutline(rel, depth, visited, maps, out, expanded) {
  const r = await api("/api/outline?rel=" + encodeURIComponent(rel));
  if (r.error || !r.outline) return;
  if (!maps[rel]) {
    const fr = await api("/api/file?rel=" + encodeURIComponent(rel));
    const m = {};
    (fr.units || []).forEach((u) => { m[u.id] = u; });
    maps[rel] = m;
  }
  for (const e of r.outline) {
    e.src_rel = rel;
    e.depth = (e.depth || 0) + depth;
    out.push(e);
    if (e.kind === "call" && e.target_rel && depth < 8) {
      if (visited.has(e.target_rel) || expanded.has(e.target_rel)) {
        e.repeat = true;                // 이미 위에서 펼쳐진 패키지의 재호출
      } else {
        e.inlined = true;               // 호출 줄 바로 아래에 내용이 펼쳐짐
        expanded.add(e.target_rel);
        visited.add(e.target_rel);
        await buildLinearOutline(e.target_rel, e.depth + 1, visited, maps, out, expanded);
        visited.delete(e.target_rel);
      }
    }
  }
}

async function renderFlowView(rel) {
  const box = $("#units");
  box.innerHTML = `<div class="empty">흐름 불러오는 중…</div>`;
  const maps = { [rel]: STATE.unitById };
  let outlineList;
  if (FLOWMODE === "linear") {
    outlineList = [];
    await buildLinearOutline(rel, 0, new Set([rel]), maps, outlineList, new Set());
  } else {
    const r = await api("/api/outline?rel=" + encodeURIComponent(rel));
    if (r.error || !r.outline) { box.innerHTML = `<div class="empty">흐름 정보 없음</div>`; return; }
    outlineList = r.outline;
    outlineList.forEach((e) => { e.src_rel = rel; });
  }
  box.innerHTML = "";
  const wrap = document.createElement("div");
  wrap.className = "outline";

  // 모드 전환 바
  const modeBar = document.createElement("div");
  modeBar.className = "ol-modebar";
  const modeLab = document.createElement("label");
  const modeCb = document.createElement("input");
  modeCb.type = "checkbox";
  modeCb.checked = FLOWMODE === "linear";
  modeCb.onchange = () => {
    FLOWMODE = modeCb.checked ? "linear" : "file";
    localStorage.setItem("flowmode", FLOWMODE);
    FLOWSTACK = [];
    renderFlowView(rel);
  };
  modeLab.appendChild(modeCb);
  modeLab.appendChild(document.createTextNode(
    " 🧵 일렬로 쭉 보기 — 패키지 호출 내용을 진행 순서대로 그 자리에 펼침"));
  modeBar.appendChild(modeLab);
  wrap.appendChild(modeBar);

  // 말투 변형(口調 분기)이 별도 Talk 로 흩어진 경우(구조 B)도 한 묶음으로 —
  // 연속된 talk 항목의 유닛이 같은 파일 + 같은 group 이면 하나의 말투 그룹으로 병합.
  const entries = [];
  outlineList.forEach((e) => {
    if (e.kind === "talk") {
      const m = maps[e.src_rel] || {};
      const ids = (e.unit_ids || []).map((id) => m[id]).filter(Boolean);
      if (!ids.length) return;
      const g = ids[0].group != null && ids.every((u) => u.group === ids[0].group)
        ? ids[0].group : null;
      const last = entries[entries.length - 1];
      if (g != null && last && last.kind === "talk" && last.group === g
          && last.src_rel === e.src_rel) {
        last.units.push(...ids);            // 같은 말투 그룹 → 앞 항목에 병합
        return;
      }
      entries.push({ kind: "talk", depth: e.depth, units: ids, group: g, src_rel: e.src_rel });
    } else {
      entries.push(e);
    }
  });
  // 파일 모드: 호출로 들어온 파일이면 호출원·다음 순서 배너 (상단 + 하단 ⏭)
  // 스택 최상단 프레임만 이 파일에 해당할 때 표시. 복귀는 pop → 바깥 호출원 배너가 살아난다.
  const top = FLOWSTACK[FLOWSTACK.length - 1];
  const navBar = (bottom) => {
    if (FLOWMODE === "linear" || !top || top.target !== rel) return null;
    // 호출원이 같은 패키지를 (조건 분기 가지마다) 연달아 호출하는 경우가 있어,
    // "다음"은 지금 파일이 아닌 첫 호출까지 건너뛴다
    let ni = top.idx + 1;
    while (top.calls[ni] && top.calls[ni].target_rel === rel) ni++;
    const next = top.calls[ni];
    const bar = document.createElement("div");
    bar.className = "ol-navbar";
    const backName = top.from.split(/[\\/]/).pop().replace(/\.xml$/i, "");
    const goBack = () => { FLOWSTACK.pop(); openFile(top.from); };
    if (!bottom) {
      const back = document.createElement("span");
      back.className = "ol-navlink";
      back.textContent = "↩ 호출원: " + backName;
      back.title = "클릭 → " + top.from + " (이 파일을 호출한 곳으로 복귀)";
      back.onclick = goBack;
      bar.appendChild(back);
    }
    if (next) {
      const nx = document.createElement("span");
      nx.className = "ol-navlink ol-navnext";
      nx.textContent = "⏭ 다음: " + next.desc.replace(/ 호출$/, "");
      nx.title = "클릭 → " + next.target_rel;
      nx.onclick = () => {
        top.idx = ni;
        top.target = next.target_rel;
        openFile(next.target_rel);
      };
      bar.appendChild(nx);
    } else if (bottom) {
      // 마지막 호출 안내는 다 읽고 내려온 하단에만 (상단은 ↩ 호출원 링크로 충분)
      const nx = document.createElement("span");
      nx.className = "ol-navlink ol-navnext";
      nx.textContent = `↩ 여기가 마지막 — 「${backName}」(으)로 돌아가세요`;
      nx.title = "클릭 → " + top.from + " (호출원으로 복귀)";
      nx.onclick = goBack;
      bar.appendChild(nx);
    }
    return bar;
  };
  const topBar = navBar(false);
  if (topBar) wrap.appendChild(topBar);

  entries.forEach((e) => {
    const indent = Math.min(e.depth || 0, 12) * 18;
    if (e.kind === "talk") {
      const ids = e.units;
      const row = document.createElement("div");
      row.className = "ol-talk";
      row.style.marginLeft = indent + "px";
      // 말투 변형이면 묶음, 아니면 단일 (유닛은 자기 파일(src_rel)로 저장)
      if (ids.length > 1 && ids[0].group != null) row.appendChild(toneGroupEl(e.src_rel, ids));
      else ids.forEach((u) => row.appendChild(freeUnitEl(e.src_rel, u)));
      wrap.appendChild(row);
    } else {
      const row = document.createElement("div");
      row.className = "ol-mark ol-" + e.kind;
      row.style.marginLeft = indent + "px";
      row.innerHTML = `<span class="ol-ic">${OL_ICON[e.kind] || "·"}</span> <span class="ol-desc"></span>`;
      row.querySelector(".ol-desc").textContent = e.desc;
      if (e.repeat) {
        // 일렬 모드: 이미 위에서 펼친 패키지의 재호출 — 내용 중복 없이 표시만
        row.querySelector(".ol-desc").textContent = e.desc + " — ↑ 앞에서 이미 펼쳐짐";
        row.title = e.target_rel;
      } else if (e.inlined) {
        // 일렬 모드: 내용이 바로 아래 펼쳐져 있으므로 이동 없음 — 구간 머리 역할
        row.classList.add("ol-inlined");
        row.title = "아래에 펼쳐져 있음 · " + e.target_rel;
      } else if (e.target_rel) {
        row.classList.add("ol-jump");
        row.title = "클릭 → " + e.target_rel;
        row.onclick = () => {
          if (FLOWMODE !== "linear" && e.kind === "call") {
            // 호출 = 끝나면 이 파일로 복귀. 다른 파일을 헤매다 왔으면 스택을 이 파일
            // 기준으로 정리한 뒤 프레임을 쌓는다 (중첩 호출도 복귀 경로 유지).
            while (FLOWSTACK.length && FLOWSTACK[FLOWSTACK.length - 1].target !== rel)
              FLOWSTACK.pop();
            const calls = entries.filter((x) => x.kind === "call" && x.target_rel);
            FLOWSTACK.push({ from: rel, calls, idx: calls.indexOf(e), target: e.target_rel });
          } else if (e.kind !== "call") {
            FLOWSTACK = [];    // 이동(Link/Change)은 복귀 없음
          }
          openFile(e.target_rel);
        };
      }
      // 이름 붙은 줄(칭호/플래그/스텝/스타트/패키지/에리어) — 툴 전용 표시명 편집
      if (e.name) {
        row.title = (row.title ? row.title + " · " : "") + "원문: " + e.name;
        const ed = document.createElement("button");
        ed.className = "ol-edit";
        ed.textContent = "✏";
        ed.title = "툴에서만 보일 이름을 입력합니다.\n내보내기에는 들어가지 않고, 비우면 원문으로 돌아갑니다";
        ed.onclick = (ev) => {
          ev.stopPropagation();
          if (row.querySelector(".ol-editbox")) return;
          const inp = document.createElement("input");
          inp.type = "text"; inp.className = "ol-editbox";
          inp.placeholder = e.name;
          inp.value = e.tool_ko || e.name;   // 일부만 고쳐 쓸 수 있게 현재값/원문 프리필
          inp.onclick = (x) => x.stopPropagation();
          let cancelled = false;
          const save = async () => {
            if (cancelled) return;
            cancelled = true;                       // blur+Enter 중복 저장 방지
            const v = inp.value.trim();
            if (v === (e.tool_ko || e.name)) { inp.remove(); return; }  // 변경 없음
            const r2 = await post("/api/tool_name", { name: e.name, ko: v });
            if (r2.error) return toast(r2.error);
            toast("표시 이름 저장 (툴에서만 보임)");
            renderFlowView(rel);
          };
          inp.onblur = save;                        // 포커스 아웃 = 자동 저장
          inp.onkeydown = (x) => {
            if (x.key === "Escape") { cancelled = true; inp.remove(); }
            else if (x.key === "Enter") inp.blur();
          };
          ed.after(inp);
          inp.focus();
        };
        row.appendChild(ed);
      }
      wrap.appendChild(row);
    }
  });
  const botBar = navBar(true);
  if (botBar) wrap.appendChild(botBar);
  box.appendChild(wrap);
}

function setView(v) {
  VIEW = v;
  $("#viewList").classList.toggle("active", v === "list");
  $("#viewFlow").classList.toggle("active", v === "flow");
  if (STATE.curRel) openFile(STATE.curRel);
}

function esc(s) { return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }

// ── 조건 포맷/그룹화 ──
const COND_KIND = { coupon: "쿠폰", flag: "플래그", step: "스텝", random: "랜덤", select: "선택지", partynumber: "인원 수", gossip: "소문", ability: "능력 판정", level: "레벨 판정", cast: "동행 NPC", beast: "소환수", area: "지역", isbattle: "전투" };
const COND_POL = { have: "보유", not: "미보유", true: "참", false: "거짓", yes: "성립", no: "불성립", else: "그 외" };
function polWord(p) { return COND_POL[p] || (p && p[0] === "=" ? p : ""); }
// [kind,who,what,pol] 목록 → 같은 (kind·대상·극성) 끼리 묶어 읽기 쉬운 문자열 배열
function groupConds(list) {
  const groups = new Map(), order = [];
  (list || []).forEach(([kind, who, what, pol]) => {
    const key = kind + "|" + who + "|" + pol;
    if (!groups.has(key)) { groups.set(key, { kind, who, pol, whats: [] }); order.push(key); }
    if (what) groups.get(key).whats.push(what);
  });
  return order.map((k) => {
    const g = groups.get(k), pw = polWord(g.pol), whats = g.whats.join("/");
    if (g.kind === "coupon") return (g.who ? g.who + " " : "") + whats + (pw ? " " + pw : "");
    const base = COND_KIND[g.kind] || g.kind;
    if (whats) return base + " " + whats + (pw ? " " + pw : "");
    return base + (pw && pw !== "성립" ? " " + pw : "");
  });
}
function condBadges(list) {
  return groupConds(list).map((c) => `<span class="badge cond">${esc(c)}</span>`).join("");
}

// 조건 분기(OR): 접이식. 여러 경로 중 하나로 도달하는 경우를 정확히 표시
function condAltEl(u) {
  if (!u.cond_alt || !u.cond_alt.length) return null;
  const wrap = document.createElement("div");
  wrap.className = "condalt";
  const tog = document.createElement("span");
  tog.className = "condalt-tog";
  tog.textContent = `▸ 분기 조건 ${u.cond_alt.length}가지 중 하나`;
  const body = document.createElement("div");
  body.className = "condalt-body";
  body.style.display = "none";
  u.cond_alt.forEach((clause) => {
    const row = document.createElement("div");
    row.className = "condalt-row";
    row.innerHTML = condBadges(clause) || '<span class="cond-muted">(조건 없음)</span>';
    body.appendChild(row);
  });
  tog.onclick = (e) => {
    e.stopPropagation();
    const open = body.style.display === "none";
    body.style.display = open ? "block" : "none";
    tog.textContent = (open ? "▾" : "▸") + ` 분기 조건 ${u.cond_alt.length}가지 중 하나`;
  };
  wrap.appendChild(tog); wrap.appendChild(body);
  return wrap;
}

// 말투 변형 묶음: 기본 접힘(대표 1줄), 펼치면 톤별 번역칸
function toneGroupEl(rel, grp) {
  const wrap = document.createElement("div");
  wrap.className = "tonegroup";
  const head = grp[0];
  const done = grp.filter((u) => u.ko).length;
  const spk = head.speaker ? `<span class="badge spk">🗣 ${esc(head.speaker)}</span>` : "";
  const conds = condBadges(head.conditions);
  const bar = document.createElement("div");
  bar.className = "tg-head";
  bar.innerHTML = `<span class="tg-tog">▸</span>${spk}${conds}
    <span class="badge tone">말투 ${grp.length}종</span>
    <span class="tg-prog ${done === grp.length ? "full" : ""}">${done}/${grp.length}</span>
    <span class="tg-rep"></span>`;
  bar.querySelector(".tg-rep").textContent = head.jp.replace(/\s+/g, " ").slice(0, 60);
  const alt = condAltEl(head);
  const body = document.createElement("div");
  body.className = "tg-body";
  body.style.display = "none";
  grp.forEach((u) => body.appendChild(freeUnitEl(rel, u, true)));
  bar.onclick = () => {
    const open = body.style.display === "none";
    body.style.display = open ? "flex" : "none";
    bar.querySelector(".tg-tog").textContent = open ? "▾" : "▸";
  };
  wrap.appendChild(bar);
  if (alt) wrap.appendChild(alt);
  wrap.appendChild(body);
  return wrap;
}

function freeUnitEl(rel, u, skipAlt) {
  const el = document.createElement("div");
  el.className = "unit" + (isDone(u) ? " done" : "") + (u.control ? " control" : "");
  el.dataset.sid = u.id;
  el.dataset.rel = rel;   // 일렬 모드에서 같은 유닛의 다른 펼침 사본 동기화용
  const CAT = { dialogue: "대사", narration: "나레이션", choice: "선택지", label: "카드 이름", desc: "카드 설명", scnname: "시나리오 제목", scndesc: "시나리오 설명", sysname: "내부명", varvalue: "변수값" };
  const catBadge = u.cat ? `<span class="badge cat-${u.cat}">${CAT[u.cat] || u.cat}</span>` : "";
  const left = document.createElement("div");
  const spk = u.speaker ? `<span class="badge spk">🗣 ${esc(u.speaker)}</span>` : "";
  const conds = condBadges(u.conditions);
  const tone = u.tone ? `<span class="badge tone">말투 ${esc(u.tone)}</span>` : "";
  const ctrl = u.control ? '<span class="badge">제어기호</span>' : "";
  const imgB = u.img ? '<span class="badge img" title="그림이 떠서 한 줄 폭이 좁음 (43→33단위)">🖼 그림·33</span>' : "";
  left.innerHTML = `<div class="meta">${catBadge}${spk}${conds}${tone}${ctrl}${imgB}</div>
    <div class="jp"></div>`;
  // %상태변수% 상호 점프 — 참조하는 쪽은 정의(Summary.xml)로, 표시값은 사용처로
  const meta = left.querySelector(".meta");
  (u.varrefs || []).forEach((name) => {
    const b = document.createElement("span");
    b.className = "badge varjump";
    b.textContent = `%${name}% 정의↗`;
    b.title = "Summary.xml 의 이 상태변수 표시값(True/False)으로 이동";
    b.onclick = () => jumpToVarDef(name);
    meta.appendChild(b);
  });
  if (isPartial(u)) {
    const b = document.createElement("span");
    b.className = "badge partial";
    b.textContent = "🈁 일본어 남음";
    b.title = "번역문에 가나가 남아 있어 완료로 세지 않습니다.\n(용어 치환 초안 등 부분 번역 상태)";
    meta.appendChild(b);
  }
  if (u.dups > 1) {
    const b = document.createElement("span");
    b.className = "badge dup";
    b.textContent = `동일 원문 ×${u.dups}`;
    b.title = "클릭하면 같은 원문의 위치 목록을 보여줍니다.\n번역하면 미번역 동일 원문에 자동 적용됩니다";
    let listEl = null;
    b.onclick = async () => {
      if (listEl) { listEl.remove(); listEl = null; return; }
      const r = await api(`/api/dup_where?rel=${encodeURIComponent(rel)}&id=${u.id}`);
      listEl = document.createElement("div");
      listEl.className = "dup-where";
      (r.results || []).forEach((m) => {
        const row = document.createElement("div");
        row.className = "dup-where-row" + (m.me ? " me" : "");
        row.textContent = `${m.me ? "▶ " : ""}${m.rel}  ${m.done ? "✓ 번역됨" : "미번역"}`;
        if (!m.me) row.onclick = () => jumpTo(m.rel, m.sid);
        listEl.appendChild(row);
      });
      meta.parentElement.insertBefore(listEl, meta.nextSibling);
    };
    meta.appendChild(b);
  }
  if (u.cat === "varvalue" && u.varname) {
    const nameB = document.createElement("span");
    nameB.className = "badge ent";
    nameB.textContent = `%${u.varname}%`;
    nameB.title = "이 텍스트가 표시값으로 들어가는 상태변수";
    meta.appendChild(nameB);
    const flagB = document.createElement("span");
    const kind = u.tag === "True" ? "true" : u.tag === "False" ? "false" : "step";
    flagB.className = "badge varflag-" + kind;
    flagB.textContent = u.tag === "True" ? "TRUE 값" : u.tag === "False" ? "FALSE 값" : "스텝 값";
    flagB.title = u.tag === "Value"
      ? `스텝 %${u.varname}% 의 값 라벨`
      : `%${u.varname}% 가 ${u.tag.toUpperCase()} 일 때 표시되는 텍스트`;
    meta.appendChild(flagB);
    const b = document.createElement("span");
    b.className = "badge varjump";
    b.textContent = "사용처↗";
    b.title = `%${u.varname}% 가 표시되는 대사로 이동`;
    b.onclick = () => jumpToVarUsage(u.varname);
    meta.appendChild(b);
  }
  if (!skipAlt) {
    const alt = condAltEl(u);
    if (alt) left.querySelector(".meta").appendChild(alt);
  }
  left.querySelector(".jp").textContent = u.jp;
  const right = document.createElement("div");
  const ta = document.createElement("textarea");
  // 원문을 미리 넣어 둔다 → 줄바꿈/띄어쓰기 그대로 두고 일본어만 한국어로 고쳐 쓰기
  ta.value = u.ko || u.jp;
  ta.placeholder = "여기에서 일본어만 한국어로 고쳐 쓰세요";
  if (u.control) {
    ta.disabled = true;                 // 제어기호/치환자뿐 — 번역할 내용 없음(읽기전용)
    ta.title = "제어코드·치환자뿐인 텍스트라 번역하지 않습니다";
  }
  // 입력창은 내용 전체가 보이는 높이로 자동 고정 (드래그 리사이즈 불필요).
  // 기본 크기는 줄 수(rows) — 접힌 그룹 등 숨김 상태에서도 정확하다.
  // 화면에 보일 때는 scrollHeight 로 보정(자동 줄바꿈으로 넘치는 경우 커버).
  const fitRows = () => {
    ta.rows = Math.max(3, (ta.value.match(/\n/g) || []).length + 2);
  };
  const autoGrow = () => {
    fitRows();
    if (!ta.clientHeight) return;       // 숨김 상태 — rows 크기가 그대로 쓰임
    ta.style.height = "auto";
    ta.style.height = (ta.scrollHeight + 2) + "px";
  };
  fitRows();
  ta.addEventListener("input", autoGrow);
  ta.addEventListener("focus", autoGrow);   // 접힘 해제 후 첫 포커스에서 보정
  requestAnimationFrame(autoGrow);

  // ko 변경을 서버에 반영 (onblur·되돌리기 공용)
  let markDoneBtn = null;   // [완료로 표시] — 완료 상태에 따라 표시/숨김
  const commit = async (newKo, force = false) => {
    if (newKo === (u.ko || "") && force === !!u.force_done) return;
    const prevKo = u.ko || "";
    u.ko = newKo;
    u.force_done = force && !!newKo;    // 일반 편집은 명시 완료 해제
    el.classList.toggle("done", isDone(u));
    if (markDoneBtn) markDoneBtn.style.display = isDone(u) ? "none" : "";
    const res = await post("/api/set", { kind: "free", rel, id: u.id, ko: newKo, force_done: u.force_done });
    renderProgress(res.stats);
    if (res.propagated) toast(`동일 원문 ${res.propagated}곳에 함께 적용했어요`);
    api("/api/state").then((s) => { STATE.files = s.files || []; renderFileList(); });
    // 일렬 모드: 같은 패키지가 여러 번 펼쳐져 있으면 다른 사본의 화면도 즉시 갱신
    document.querySelectorAll(`.unit[data-sid="${u.id}"]`).forEach((other) => {
      if (other === el || other.dataset.rel !== rel) return;
      const t2 = other.querySelector("textarea");
      if (t2) t2.value = newKo || u.jp;
      other.classList.toggle("done", isDone(u));
    });
    // 수정(재번역) 시: 동일 원문 칸 중 "수정 전과 같은 번역"이 있으면 함께 고칠지 확인
    if (res.stale && newKo && prevKo && prevKo !== newKo) {
      const yes = await askConfirm(
        `동일 원문 ${res.stale}곳이 수정 전과 같은 번역입니다.\n함께 고칠까요?\n\n(다르게 번역해 둔 칸은 건드리지 않습니다)`,
        "네, 함께 고칩니다");
      if (yes) {
        const r2 = await post("/api/set_stale", { rel, id: u.id, old_ko: prevKo, ko: newKo });
        if (r2.error) toast(r2.error);
        else {
          toast(`동일 원문 ${r2.applied}곳 함께 수정했어요`);
          renderProgress(r2.stats);
        }
      }
    }
  };

  ta.onblur = () => {
    let val = ta.value;
    if (val === "") { val = u.jp; ta.value = u.jp; }   // 비우면 원문 복원
    commit(val === u.jp ? "" : val);                   // 원문 그대로면 미번역으로 취급
  };

  // 게임 창 미리보기 — 메시지창(대사/나레이션)에만. 카드 설명(CastCard/ItemCard/SkillCard)은
  // centering_y=True(card.py) 라 7줄 초과해도 안 잘리고 폭도 달라서 미리보기를 붙이지 않는다.
  const isMsg = u.cat === "dialogue" || u.cat === "narration";
  const isCard = u.cat === "desc" || u.cat === "scndesc";   // 카드 해설(CastCard/ItemCard/SkillCard) = 별도 미리보기
  const preview = document.createElement("div");
  preview.className = "game-preview";
  const limit = u.img ? LINE_UNITS_IMG : LINE_UNITS;   // 그림 있으면 33, 없으면 43
  if (u.img) preview.classList.add("gp-img");          // 이미지 폭만큼 본문이 오른쪽에서 시작
  let tidyBtn = null;   // 아래 unit-bar 에서 생성. 넘칠 때만 보이도록 미리보기가 토글.
  const refreshPreview = () => {
    const lines = wrapForGameRuns(applySubst(ta.value), limit);   // 치환자 값 반영해 렌더
    if (tidyBtn) tidyBtn.style.display = lines.length > WRAP_ROWS ? "" : "none";
    preview.innerHTML = "";
    lines.forEach((runs, i) => {
      if (i === WRAP_ROWS) {                       // 7줄 다음에 잘림선(게임에선 여기까지만 보임)
        const cut = document.createElement("div");
        cut.className = "gp-cut";
        cut.dataset.label = `${WRAP_ROWS}줄 초과`;
        preview.appendChild(cut);
      }
      const d = document.createElement("div");
      d.className = "gp-line" + (i >= WRAP_ROWS ? " gp-over" : "");
      if (!runs.length) {
        d.textContent = " ";                     // 빈 줄도 높이 유지
      } else {
        runs.forEach((run) => {
          if (run.glyph) {
            d.appendChild(glyphEl(run.glyph, run.color));
          } else if (run.color) {
            const sp = document.createElement("span");
            sp.style.color = run.color;
            sp.textContent = run.text;
            d.appendChild(sp);
          } else {
            d.appendChild(document.createTextNode(run.text));
          }
        });
      }
      preview.appendChild(d);
    });
  };
  // 치환자 입력 바 — 이 메시지에 있는 토큰별 입력칸(값은 전역 SUBST 로 메시지 간 공유)
  const substBar = document.createElement("div");
  substBar.className = "subst-bar";
  const buildSubstBar = () => {
    const toks = findSubstTokens(ta.value);
    substBar.innerHTML = "";
    if (!toks.length) { substBar.style.display = "none"; return; }
    substBar.style.display = "flex";
    const title = document.createElement("span");
    title.className = "subst-title"; title.textContent = "치환자:";
    substBar.appendChild(title);
    toks.forEach((t) => {
      const item = document.createElement("label");
      item.className = "subst-item";
      const key = document.createElement("span");
      key.className = "subst-key"; key.textContent = t;
      const inp = document.createElement("input");
      inp.type = "text"; inp.value = SUBST[t] || "";
      inp.placeholder = SHARP_LABEL[t.toLowerCase()] || "값 입력";
      inp.oninput = () => { SUBST[t] = inp.value; refreshPreview(); };
      item.appendChild(key); item.appendChild(inp);
      substBar.appendChild(item);
    });
  };
  if (isMsg) {
    ta.addEventListener("input", () => { buildSubstBar(); refreshPreview(); });
    ta.addEventListener("focus", () => { buildSubstBar(); refreshPreview(); preview.classList.add("gp-show"); });
    // 치환자 입력칸으로 포커스가 옮겨가도 미리보기 유지, right 영역 밖으로 나가면 숨김
    right.addEventListener("focusout", (e) => {
      if (!right.contains(e.relatedTarget)) {
        preview.classList.remove("gp-show");
        substBar.style.display = "none";
      }
    });
  }

  // 카드 해설 미리보기 — 카드 설명창(37단위·9줄, 색코드/치환 해석·7줄컷 없음)
  const cardPrev = document.createElement("div");
  cardPrev.className = "card-preview";
  const refreshCard = () => {
    const lines = wrapPlain(ta.value, CARD_UNITS);
    cardPrev.innerHTML = "";
    lines.forEach((ln, i) => {
      if (i === CARD_ROWS) {                        // 9줄 = 카드창에 보이는 범위 경계
        const cut = document.createElement("div");
        cut.className = "cp-cut";
        cut.dataset.label = `${CARD_ROWS}줄`;
        cardPrev.appendChild(cut);
      }
      const d = document.createElement("div");
      d.className = "cp-line" + (i >= CARD_ROWS ? " cp-over" : "");
      d.textContent = ln || " ";
      cardPrev.appendChild(d);
    });
  };
  if (isCard) {
    ta.addEventListener("input", refreshCard);
    ta.addEventListener("focus", () => { refreshCard(); cardPrev.classList.add("gp-show"); });
    ta.addEventListener("blur", () => { cardPrev.classList.remove("gp-show"); });
  }

  // 메시지별 "원문으로 되돌리기" — 초안/번역을 버리고 원문(jp)으로 리셋해 재번역 대상으로
  const bar = document.createElement("div");
  bar.className = "unit-bar";
  const reset = document.createElement("button");
  reset.type = "button";
  reset.className = "unit-reset";
  reset.textContent = "↺ 원문으로";
  reset.title = "이 메시지의 번역/초안을 버리고 원문으로 되돌립니다 (재번역 대상이 됩니다)";
  reset.onclick = () => {
    if (u.ko && !confirm("이 메시지를 원문으로 되돌릴까요?\n현재 번역/초안은 사라집니다.")) return;
    ta.value = u.jp;
    commit("");
  };
  bar.appendChild(reset);

  // [완료로 표시] — 원문 그대로가 정답인 문장(「～～♪」, %상태변수% 표시 메시지 등)을
  // 번역 완료로 처리. 입력칸의 blur 규칙("원문과 같으면 미번역")을 우회해 ko 에 명시 저장.
  markDoneBtn = document.createElement("button");
  markDoneBtn.type = "button";
  markDoneBtn.className = "unit-reset";
  markDoneBtn.textContent = "✓ 완료로 표시";
  markDoneBtn.title = "이 내용 그대로 번역 완료로 표시합니다 — 원문 유지(♪ 등)나 일본어가 남은 부분 번역도 확정할 수 있습니다 (되돌리기 = ↺ 원문으로)";
  markDoneBtn.onclick = () => commit(ta.value || u.jp, true);
  if (isDone(u)) markDoneBtn.style.display = "none";
  bar.appendChild(markDoneBtn);

  // "정돈" — 문단 안 수동 줄바꿈을 없애 7줄 넘침을 완화. 메시지창에서 넘칠 때만 노출.
  if (isMsg) {
    tidyBtn = document.createElement("button");
    tidyBtn.type = "button";
    tidyBtn.className = "unit-tidy";
    tidyBtn.textContent = "⤵ 정돈";
    tidyBtn.title = `문단 안 수동 줄바꿈을 없애 게임 자동 줄바꿈에 맡깁니다 (${WRAP_ROWS}줄 넘침 완화). 빈 줄 문단 구분은 유지됩니다.`;
    tidyBtn.style.display = "none";
    tidyBtn.onclick = () => {
      const next = tidyText(ta.value);
      if (next === ta.value) { toast("이미 정돈된 상태예요"); return; }
      ta.value = next;
      buildSubstBar();
      refreshPreview();
      commit(next);
      toast("정돈했어요 — 게임 자동 줄바꿈 기준으로 이어붙였습니다");
    };
    bar.appendChild(tidyBtn);
  }

  right.appendChild(bar);
  right.appendChild(ta);
  if (isMsg) { right.appendChild(substBar); right.appendChild(preview); }
  else if (isCard) right.appendChild(cardPrev);
  el.appendChild(left); el.appendChild(right);
  return el;
}

// ── 용어집 ──
async function showTerms() {
  if (!STATE.open) return toast("먼저 시나리오를 여세요");
  $("#terms").style.display = "flex";
  await reloadTerms();
}
// 공용 용어 변경 후 열려 있는 화면들 갱신 (용어집 모달 + 공용 용어집 패널)
function refreshGlobalViews() {
  if (STATE.open && $("#terms").style.display !== "none") reloadTerms();
  if ($("#gterms").style.display !== "none") loadGTerms();
}

async function reloadTerms() {
  if (!STATE.open) return;
  const r = await api("/api/terms");
  $("#globalOn").checked = !!r.global_on;
  renderGlobalList($("#termsGlobal"), r.global || []);
  renderTermList($("#termsManual"), r.manual || [], "manual");
  renderTermList($("#termsExact"), r.exact || [], "exact");
  renderTermList($("#termsWord"), r.word || [], "word");
}

// 용어 등장 위치(📍) 버튼 + 펼침 목록 — 일반/공용 용어 공용
function occurrenceParts(occurrences) {
  const btn = document.createElement("button");
  btn.className = "term-occbtn";
  btn.textContent = `📍 ${(occurrences || []).length}`;
  btn.title = "등장 위치 보기";
  const box = document.createElement("div");
  box.className = "term-occ";
  box.style.display = "none";
  (occurrences || []).forEach((o) => {
    const orow = document.createElement("div");
    orow.className = "occ-row";
    orow.innerHTML = `<span class="occ-file"></span><span class="occ-prev"></span>`;
    orow.querySelector(".occ-file").textContent = o.rel.split(/[\\/]/).pop();
    orow.querySelector(".occ-prev").textContent = o.preview;
    orow.title = o.ko ? "번역: " + o.ko : "(미번역)";
    orow.onclick = () => {
      closeTerms();
      $("#gterms").style.display = "none";
      jumpTo(o.rel, o.sid);
    };
    box.appendChild(orow);
  });
  btn.onclick = () => {
    box.style.display = box.style.display === "none" ? "block" : "none";
  };
  return { btn, box };
}

// 공용 용어(모든 시나리오 공통) 목록 — 번역 비우면 삭제.
// 이 시나리오에 안 나오는(0회) 용어는 기본 숨김 — 토글로 펼쳐서 관리.
function renderGlobalList(host, list) {
  host.innerHTML = "";
  if (!list.length) {
    host.innerHTML = `<div class="empty">없음 — 용어 줄의 🌐 버튼으로 자주 쓰는 단어를 등록하세요</div>`;
    return;
  }
  const used = list.filter((t) => t.count > 0);
  const unused = list.filter((t) => !t.count);
  const render = (t) => renderGlobalRow(host, t);
  used.forEach(render);
  if (!used.length) {
    const d = document.createElement("div");
    d.className = "empty";
    d.textContent = "이 시나리오에 등장하는 공용 용어가 없습니다";
    host.appendChild(d);
  }
  if (unused.length) {
    const tog = document.createElement("div");
    tog.className = "gt-unused-toggle";
    tog.textContent = `이 시나리오 미등장 ${unused.length}개 — 전체 관리에서 보기 ↗`;
    tog.onclick = showGTerms;
    host.appendChild(tog);
  }
}

function renderGlobalRow(host, t) {
    const row = document.createElement("div");
    row.className = "term-row done";
    const head = document.createElement("div");
    head.className = "term-head";
    const jp = document.createElement("span");
    jp.className = "term-jp";
    jp.innerHTML = `<span class="term-cnt" title="이 시나리오 등장 횟수">${t.count}</span>`;
    jp.appendChild(document.createTextNode(t.jp));
    const inp = document.createElement("input");
    inp.type = "text"; inp.value = t.ko || ""; inp.placeholder = "번역 (비우면 삭제)";
    inp.onblur = async () => {
      if (inp.value === (t.ko || "")) return;
      await post("/api/global_term", { jp: t.jp, ko: inp.value.trim() });
      toast(inp.value.trim() ? "공용 용어 수정됨" : "공용 용어 삭제됨");
      refreshGlobalViews();
    };
    const del = document.createElement("button");
    del.className = "term-del"; del.textContent = "✕"; del.title = "공용 용어에서 삭제";
    del.onclick = async () => {
      await post("/api/global_term", { jp: t.jp, ko: "" });
      refreshGlobalViews();
    };
    const occ = occurrenceParts(t.occurrences);
    head.appendChild(jp); head.appendChild(inp); head.appendChild(occ.btn); head.appendChild(del);
    row.appendChild(head);
    row.appendChild(occ.box);
    host.appendChild(row);
    return row;
}
function closeTerms() { $("#terms").style.display = "none"; }

function renderTermList(host, list, kind) {
  host.innerHTML = "";
  if (!list.length) { host.innerHTML = `<div class="empty">없음</div>`; return; }
  list.forEach((t) => {
    const row = document.createElement("div");
    row.className = "term-row" + (t.ko ? " done" : "");
    // 1줄: 횟수 · 원문 · (식별자 배지) · 번역칸 · 위치토글 · (수동:삭제)
    const head = document.createElement("div");
    head.className = "term-head";
    const jp = document.createElement("span");
    jp.className = "term-jp";
    jp.innerHTML = `<span class="term-cnt">${t.count}</span>`;
    // 반복 문장: 본문 문장인지 선택지 버튼 라벨인지 표시 (둘 다 쓰이면 둘 다)
    (t.kinds || []).forEach((k) => {
      jp.innerHTML += k === "choice"
        ? `<span class="term-kindbadge choice" title="이벤트 선택지 버튼 라벨로 쓰이는 텍스트">선택지</span>`
        : `<span class="term-kindbadge" title="메시지 본문/설명 문장">문장</span>`;
    });
    if (t.is_identifier) jp.innerHTML += `<span class="term-idbadge" title="식별자이기도 함.\n식별자 자체는 원문 유지, 자유 텍스트에서만 치환됩니다">식별자</span>`;
    jp.appendChild(document.createTextNode(t.jp.replace(/\n/g, "⏎")));   // 줄바꿈 시각화
    const cp = document.createElement("button");
    cp.className = "term-copy";
    cp.textContent = "📋";
    cp.title = "원문 복사";
    cp.onclick = async () => {
      try { await navigator.clipboard.writeText(t.jp); toast("원문 복사됨"); }
      catch (err) { toast("복사 실패 — 브라우저가 클립보드 접근을 막았습니다"); }
    };
    const inp = document.createElement("input");
    inp.type = "text"; inp.value = t.ko || ""; inp.placeholder = "번역";
    if (t.global_ko && !t.ko) {
      // 프로젝트 번역이 없으면 공용 용어 번역이 적용됨을 표시
      inp.placeholder = "공용: " + t.global_ko;
      inp.title = `공용 용어집의 "${t.global_ko}" 가 적용됩니다.\n여기 입력하면 이 시나리오에서는 그 번역이 우선합니다.`;
    }
    if (kind === "exact" && t.jp.includes("\n")) {
      // 한 줄 입력이라 원문의 줄바꿈을 살릴 수 없음 — 본문 번역 + 자동 전파를 권장
      inp.placeholder = "⚠ 원문에 줄바꿈(⏎) 있음";
      inp.title = "여기에 적으면 줄바꿈 없이 한 줄로 적용됩니다.\n"
        + "줄바꿈을 살리려면 📍 위치에서 본문으로 이동해 번역하세요 — "
        + "저장하면 동일 원문 전체에 줄바꿈째 자동 전파됩니다.";
    }
    inp.onblur = async () => {
      if (inp.value === (t.ko || "")) return;
      t.ko = inp.value;
      row.classList.toggle("done", !!t.ko);
      const res = await post("/api/term", { kind, jp: t.jp, ko: inp.value });
      if (res.applied) toast(kind === "exact"
        ? `${res.applied}곳 일괄 적용`
        : `부분 번역 ${res.applied}곳의 남은 원문 단어를 치환했어요`);
      if (res.stats) renderProgress(res.stats);
      if (STATE.curRel) openFile(STATE.curRel);
    };
    const occ = occurrenceParts(t.occurrences);
    const occBtn = occ.btn;
    // 🌐 공용 용어집 등록 — 자주 나오는 단어를 모든 시나리오 공통으로
    const gbtn = document.createElement("button");
    gbtn.className = "term-copy";
    gbtn.textContent = "🌐";
    gbtn.title = "이 단어를 공용 용어집에 등록합니다 (모든 시나리오 공통 적용).\n번역칸에 값이 있어야 합니다.";
    gbtn.onclick = async () => {
      const ko = inp.value.trim() || t.ko || "";
      if (!ko) return toast("먼저 번역을 입력하세요");
      await post("/api/global_term", { jp: t.jp, ko });
      toast(`공용 용어집에 등록: ${t.jp} → ${ko}`);
      reloadTerms();
    };
    head.appendChild(jp); head.appendChild(cp); head.appendChild(gbtn);
    head.appendChild(inp); head.appendChild(occBtn);
    if (kind === "manual") {
      const del = document.createElement("button");
      del.className = "term-del"; del.textContent = "✕"; del.title = "삭제";
      del.onclick = async () => { await post("/api/term_remove", { jp: t.jp }); reloadTerms(); };
      head.appendChild(del);
    }
    row.appendChild(head);
    row.appendChild(occ.box);   // 펼침: 등장 위치(파일·문장) 목록 → 클릭 이동
    host.appendChild(row);
  });
}

// 특정 파일의 특정 문장(sid)으로 이동 + 강조
// %상태변수% 정의(Summary.xml 표시값)로 이동
async function jumpToVarDef(name) {
  const r = await api(`/api/file?rel=${encodeURIComponent("Summary.xml")}`);
  const hits = (r.units || []).filter((x) => x.varname === name);
  if (!hits.length) return toast(`Summary.xml 에서 %${name}% 표시값을 못 찾았습니다`);
  jumpTo("Summary.xml", hits[0].id);
}
// %상태변수% 사용처(그 변수가 표시되는 대사)로 이동
async function jumpToVarUsage(name) {
  const r = await api(`/api/search?q=${encodeURIComponent(`%${name}%`)}&scope=jp&ctrl=1`);
  const hits = (r.results || []).filter((m) => m.rel !== "Summary.xml");
  if (!hits.length) return toast(`%${name}% 사용처를 못 찾았습니다`);
  jumpTo(hits[0].rel, hits[0].sid);
}
async function jumpTo(rel, sid) {
  if (VIEW === "flow") setView("list");
  await openFile(rel);
  setTimeout(async () => {
    let el = $("#units").querySelector(`.unit[data-sid="${sid}"]`);
    if (!el && ($("#hideDone").checked || $("#hideControl").checked)) {
      // 대상이 필터(완료/제어기호 숨기기)에 가려져 있으면 필터를 풀고 다시 찾는다
      $("#hideDone").checked = false;
      $("#hideControl").checked = false;
      await openFile(rel);
      el = $("#units").querySelector(`.unit[data-sid="${sid}"]`);
    }
    if (!el) return toast("대상 문장을 찾지 못했습니다");
    // 접힌 말투 그룹 안의 문장이면 그룹을 펼쳐 보이게 한다
    const body = el.closest(".tg-body");
    if (body && body.style.display === "none") {
      const headEl = body.parentElement.querySelector(".tg-head");
      if (headEl) headEl.click();
    }
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("flash");
    setTimeout(() => el.classList.remove("flash"), 1600);
  }, 60);
}

async function addTerm() {
  const jp = $("#termAddJp").value.trim();
  if (!jp) return toast("추가할 단어/문장을 입력하세요");
  const ko = $("#termAddKo").value.trim();
  const r = await post("/api/term_add", { jp, ko });
  if (r.error) return toast(r.error);
  $("#termAddJp").value = ""; $("#termAddKo").value = "";
  toast(`추가됨 · ${r.term ? r.term.count : 0}곳 등장`);
  reloadTerms();
}

async function applyTerms() {
  const r = await post("/api/apply_terms", { only_untranslated: true });
  toast(`${r.drafted}개 대사에 용어 초안 적용`);
  if (r.stats) renderProgress(r.stats);
  if (STATE.curRel) openFile(STATE.curRel);
}

// ── 검색 (원문/번역) ──
function escRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
function hl(text, q) {
  const safe = esc(text);
  if (!q) return safe;
  try { return safe.replace(new RegExp("(" + escRe(esc(q)) + ")", "ig"), "<mark>$1</mark>"); }
  catch (e) { return safe; }
}
const SR_CAT = { dialogue: "대사", narration: "나레이션", choice: "선택지", label: "카드 이름", desc: "카드 설명", scnname: "시나리오 제목", scndesc: "시나리오 설명", sysname: "내부명", varvalue: "변수값" };
async function showSearch() {
  if (!STATE.open) return toast("먼저 시나리오를 여세요");
  $("#search").style.display = "flex";
  $("#searchQ").focus(); $("#searchQ").select();
}
function closeSearch() { $("#search").style.display = "none"; }
async function runSearch() {
  const q = $("#searchQ").value.trim();
  const scope = $("#searchScope").value;
  const jpcond = $("#replaceJpCond").value.trim();   // 원문 조건 — 검색 결과에도 적용
  const box = $("#searchResults");
  if (!q && !jpcond) { box.innerHTML = `<div class="empty">검색어 또는 원문 조건을 입력하세요</div>`; return; }
  box.innerHTML = `<div class="empty">검색 중…</div>`;
  const r = await api(`/api/search?q=${encodeURIComponent(q)}&scope=${encodeURIComponent(scope)}`
    + `&jpcond=${encodeURIComponent(jpcond)}`);
  if (r.error) { box.innerHTML = `<div class="empty">${esc(r.error)}</div>`; return; }
  renderSearchResults(r.results || [], q);
}
function renderSearchResults(list, q) {
  const box = $("#searchResults");
  box.innerHTML = "";
  const head = document.createElement("div");
  head.className = "search-count";
  head.textContent = list.length ? `${list.length}건${list.length >= 300 ? "+ (상한)" : ""}` : "결과 없음";
  box.appendChild(head);
  list.forEach((m) => {
    const row = document.createElement("div");
    row.className = "sr-row";
    const file = m.rel.split(/[\\/]/).pop();
    const cat = m.cat ? `<span class="badge cat-${m.cat}">${SR_CAT[m.cat] || m.cat}</span>` : "";
    const spk = m.speaker ? `<span class="badge spk">🗣 ${esc(m.speaker)}</span>` : "";
    const jpLine = m.jp ? `<div class="sr-jp">${m.in_jp ? hl(m.jp, q) : esc(m.jp)}</div>` : "";
    const koLine = m.ko
      ? `<div class="sr-ko">${m.in_ko ? hl(m.ko, q) : esc(m.ko)}</div>`
      : `<div class="sr-ko sr-empty">(미번역)</div>`;
    row.innerHTML = `<div class="sr-meta"><span class="sr-file" title="${esc(m.rel)}">${esc(file)}</span>${cat}${spk}</div>${jpLine}${koLine}`;
    row.onclick = () => { closeSearch(); jumpTo(m.rel, m.sid); };
    box.appendChild(row);
  });
}

// ── 넘침 목록 (번역이 7줄 초과해 게임에서 잘리는 대사) ──
async function showOverflow() {
  if (!STATE.open) return toast("먼저 시나리오를 여세요");
  $("#overflow").style.display = "flex";
  runOverflow();
}
function closeOverflow() { $("#overflow").style.display = "none"; }
async function bulkTidyOverflow(mode) {
  const scope = $("#overflowScope").value;
  if (scope === "file" && !STATE.curRel) return toast("현재 열린 파일이 없습니다");
  const where = scope === "file" ? "현재 파일의" : "시나리오 전체의";
  const what = mode === "simple"
    ? "줄바꿈은 건드리지 않고 끝의 빈 줄만 제거합니다."
    : "문단 안 수동 줄바꿈을 없애 게임 자동 줄바꿈에 맡기고(문단 빈 줄은 유지), 끝의 빈 줄을 제거합니다.";
  if (!confirm(`${where} 넘치는 대사(7줄 초과)를 정돈합니다.\n${what}\n\n계속할까요?`)) return;
  const r = await post("/api/overflow_tidy", { scope, rel: STATE.curRel || "", mode });
  if (r.error) return toast(r.error);
  if (r.stats) renderProgress(r.stats);
  if (STATE.curRel) await openFile(STATE.curRel);   // 현재 파일 뷰 갱신(정돈 반영)
  runOverflow();
  toast(`정돈 ${r.tidied}건 · 여전히 넘침 ${r.still_over}건`);
}
async function runOverflow() {
  const scope = $("#overflowScope").value;
  const box = $("#overflowResults");
  const dupBox = $("#dupResults");
  if (scope === "file" && !STATE.curRel) {
    box.innerHTML = `<div class="empty">현재 열린 파일이 없습니다</div>`;
    dupBox.innerHTML = "";
    return;
  }
  box.innerHTML = `<div class="empty">스캔 중…</div>`;
  dupBox.innerHTML = `<div class="empty">스캔 중…</div>`;
  const rel = STATE.curRel ? `&rel=${encodeURIComponent(STATE.curRel)}` : "";
  // 선택지 중복번역 먼저(더 치명적), 그다음 넘침
  const d = await api(`/api/dup_choices?scope=${encodeURIComponent(scope)}${rel}`);
  if (d.error) { dupBox.innerHTML = `<div class="empty">${esc(d.error)}</div>`; }
  else { renderDupChoices(d.results || []); }
  const mf = await api("/api/mt_failed");
  renderMtFailed(mf.results || []);
  const r = await api(`/api/overflow?scope=${encodeURIComponent(scope)}${rel}`);
  if (r.error) { box.innerHTML = `<div class="empty">${esc(r.error)}</div>`; return; }
  renderOverflowResults(r.results || []);
  refreshTermCheck();
}
async function refreshTermCheck() {
  const tc = await api("/api/term_check");
  if (!tc.error) renderTermCheck(tc.results || [], tc.ignored_rows || 0, tc.ignored_terms || 0);
}

// 용어 불일치 — 원문에 용어가 있는데 번역문에 그 표기가 없는 문장 (옛 표기 의심).
// 용어별로 묶어 건수를 보여주고, 그룹을 펼치면 문장 목록 + 찾아 바꾸기로 바로 이동.
function renderTermCheck(list, ignoredRows, ignoredTerms) {
  const box = $("#termCheckResults");
  if (!box) return;
  box.innerHTML = "";
  box.classList.toggle("is-empty", !list.length);
  const head = document.createElement("div");
  head.className = "search-count";
  head.textContent = list.length
    ? `${list.length}건${list.length >= 300 ? "+ (상한)" : ""} — 용어를 펼쳐 옛 표기를 확인하고 [🔍 찾아 바꾸기]로 교정하세요`
    : "용어 불일치가 없습니다 👍";
  if (ignoredRows || ignoredTerms) {
    const un = document.createElement("button");
    un.className = "tc-fix";
    un.style.marginLeft = "8px";
    un.textContent = `무시 중 ${ignoredTerms}용어·${ignoredRows}문장 — 모두 해제`;
    un.onclick = async () => {
      await post("/api/term_ignore", { clear: true });
      refreshTermCheck();
    };
    head.appendChild(un);
  }
  box.appendChild(head);
  // 용어별 그룹핑 (건수 많은 순)
  const groups = new Map();
  list.forEach((m) => {
    if (!groups.has(m.term)) groups.set(m.term, { term_ko: m.term_ko, rows: [] });
    groups.get(m.term).rows.push(m);
  });
  [...groups.entries()].sort((a, b) => b[1].rows.length - a[1].rows.length)
    .forEach(([term, g]) => {
      const gh = document.createElement("div");
      gh.className = "tc-group";
      const caret = document.createElement("span");
      caret.className = "sec-caret";
      caret.textContent = "▸";
      const lab = document.createElement("span");
      lab.className = "tc-label";
      lab.textContent = `${term} → ${g.term_ko} 없음`;
      const cnt = document.createElement("span");
      cnt.className = "term-cnt";
      cnt.textContent = `${g.rows.length}건`;
      const fix = document.createElement("button");
      fix.className = "tc-fix";
      fix.textContent = "🔍 찾아 바꾸기";
      fix.title = `검색 모달을 열고 원문 조건 "${term}" · 바꿀 말 "${g.term_ko}" 를 미리 채웁니다.\n검색어에 옛 표기를 입력해 확인 후 바꾸세요.`;
      fix.onclick = (e) => {
        e.stopPropagation();
        closeOverflow();
        showSearch();
        $("#searchScope").value = "ko";
        $("#searchQ").value = "";
        $("#replaceJpCond").value = term;
        $("#replaceKo").value = g.term_ko;
        $("#searchQ").focus();
        runSearch();   // 원문 조건만으로 바로 검색 — 해당 문장 전부 표시
        toast(`원문에 ${term} 가 있는 문장을 표시했어요 — 옛 표기가 보이면 검색어에 입력해 좁히세요`);
      };
      const mute = document.createElement("button");
      mute.className = "tc-fix";
      mute.textContent = "🙈 용어 무시";
      mute.title = `"${term}" 를 이 시나리오의 불일치 검사에서 제외합니다 (오탐이 많은 용어용).
상단의 "모두 해제"로 되돌릴 수 있습니다`;
      mute.onclick = async (e) => {
        e.stopPropagation();
        await post("/api/term_ignore", { term });
        toast(`불일치 검사에서 제외: ${term}`);
        refreshTermCheck();
      };
      gh.appendChild(caret); gh.appendChild(lab); gh.appendChild(cnt); gh.appendChild(fix); gh.appendChild(mute);
      const body = document.createElement("div");
      body.style.display = "none";
      g.rows.forEach((m) => {
        const row = document.createElement("div");
        row.className = "sr-row";
        row.innerHTML = `<div class="sr-top"><span class="sr-file"></span></div>
          <div class="sr-jp"></div><div class="sr-ko"></div>`;
        row.querySelector(".sr-file").textContent = m.rel;
        row.querySelector(".sr-jp").innerHTML = hl(m.jp, m.term);   // 걸린 용어 하이라이트
        row.querySelector(".sr-ko").textContent = m.ko;
        row.onclick = () => { closeOverflow(); jumpTo(m.rel, m.sid); };
        const ig = document.createElement("button");
        ig.className = "tc-ignore";
        ig.textContent = "무시";
        ig.title = "이 문장의 이 용어 불일치를 목록에서 제외합니다 (오탐/의도된 번역)";
        ig.onclick = async (e) => {
          e.stopPropagation();
          await post("/api/term_ignore", { term: m.term, rel: m.rel, sid: m.sid });
          refreshTermCheck();
        };
        row.querySelector(".sr-top").appendChild(ig);
        body.appendChild(row);
      });
      gh.onclick = () => {
        const open = body.style.display === "none";
        body.style.display = open ? "" : "none";
        caret.textContent = open ? "▾" : "▸";
      };
      box.appendChild(gh);
      box.appendChild(body);
    });
}
function renderMtFailed(list) {
  const box = $("#mtFailResults");
  if (!box) return;
  box.innerHTML = "";
  box.classList.toggle("is-empty", !list.length);
  const head = document.createElement("div");
  head.className = "search-count";
  head.textContent = list.length
    ? `${list.length}건 — 변수/코드 복원 실패로 빈 칸 (클릭 → 그 문장으로 이동)`
    : "자동번역 복원 실패로 남은 문장이 없습니다 👍";
  box.appendChild(head);
  list.forEach((m) => {
    const row = document.createElement("div");
    row.className = "sr-row";
    const file = m.rel.split(/[\/]/).pop();
    const cat = m.cat ? `<span class="badge cat-${m.cat}">${SR_CAT[m.cat] || m.cat}</span>` : "";
    row.innerHTML = `<div class="sr-meta"><span class="sr-file" title="${esc(m.rel)}">${esc(file)}</span>${cat}</div>`
      + `<div class="sr-ko">${esc(m.jp)}</div>`;
    row.onclick = () => { closeOverflow(); jumpTo(m.rel, m.sid); };
    box.appendChild(row);
  });
}
function renderDupChoices(list) {
  const box = $("#dupResults");
  box.innerHTML = "";
  box.classList.toggle("is-empty", !list.length);   // 결과 없으면 섹션을 접어 공간 양보
  const head = document.createElement("div");
  head.className = "search-count";
  head.textContent = list.length
    ? `${list.length}건 중복${list.length >= 500 ? "+ (상한)" : ""}`
    : `같은 메뉴에 겹치는 선택지 번역이 없습니다 👍`;
  box.appendChild(head);
  list.forEach((m) => {
    const row = document.createElement("div");
    row.className = "sr-row";
    const file = m.rel.split(/[\\/]/).pop();
    const items = m.items
      .map((it) => `<span class="badge spk" title="원문">${esc(it.jp)}</span>`)
      .join(" ");
    row.innerHTML = `<div class="sr-meta"><span class="sr-file" title="${esc(m.rel)}">${esc(file)}</span>`
      + `<span class="badge over">번역 “${esc(m.ko)}” ×${m.count}</span>${items}</div>`
      + `<div class="sr-ko">원문이 다른데 번역이 같아 선택지 구분 불가 — 클릭해 첫 항목으로 이동</div>`;
    row.onclick = () => { closeOverflow(); jumpTo(m.rel, m.items[0].sid); };
    box.appendChild(row);
  });
}
function renderOverflowResults(list) {
  const box = $("#overflowResults");
  box.innerHTML = "";
  box.classList.toggle("is-empty", !list.length);   // 결과 없으면 섹션을 접어 공간 양보
  const head = document.createElement("div");
  head.className = "search-count";
  head.textContent = list.length
    ? `${list.length}건 넘침${list.length >= 500 ? "+ (상한)" : ""}`
    : `${WRAP_ROWS}줄을 넘기는 번역이 없습니다 👍`;
  box.appendChild(head);
  list.forEach((m) => {
    const row = document.createElement("div");
    row.className = "sr-row";
    const file = m.rel.split(/[\\/]/).pop();
    const cat = m.cat ? `<span class="badge cat-${m.cat}">${SR_CAT[m.cat] || m.cat}</span>` : "";
    const spk = m.speaker ? `<span class="badge spk">🗣 ${esc(m.speaker)}</span>` : "";
    const img = m.img ? `<span class="badge img">🖼 33칸</span>` : "";
    const over = `<span class="badge over">${m.rows}줄 (+${m.over})</span>`;
    row.innerHTML = `<div class="sr-meta"><span class="sr-file" title="${esc(m.rel)}">${esc(file)}</span>${cat}${spk}${img}${over}</div><div class="sr-ko">${esc(m.ko)}</div>`;
    row.onclick = () => { closeOverflow(); jumpTo(m.rel, m.sid); };
    box.appendChild(row);
  });
}

// ── DeepL 자동 번역 초안 ──
function renderDeeplKeyStat(d) {
  const el = $("#deeplKeyStat");
  if (!el) return;
  if (d && d.set) {
    el.textContent = d.free === false ? "● 설정됨 (Pro)" : "● 설정됨 (무료)";
    el.className = "hint deepl-ok";
  } else {
    el.textContent = "○ 미설정 — 키를 저장하세요";
    el.className = "hint deepl-no";
  }
}
async function loadDeeplUsage() {
  const el = $("#deeplUsage");
  if (!el) return;
  el.textContent = "사용량 조회 중…";
  const r = await api("/api/deepl_usage");
  if (r.error) { el.textContent = "사용량: 조회 실패 (" + r.error + ")"; el.className = "deepl-usage err"; return; }
  const pct = r.limit ? Math.round((r.count / r.limit) * 100) : 0;
  el.className = "deepl-usage";
  el.innerHTML = `이번 달 사용 <b>${r.count.toLocaleString()}</b> / ${r.limit.toLocaleString()}자 (${pct}%)
    · 남음 <b>${r.remaining.toLocaleString()}</b>자
    <span class="deepl-bar"><span style="width:${Math.min(100, pct)}%"></span></span>`;
}
function curEngine() {
  const r = document.querySelector('input[name="mtEngine"]:checked');
  return r ? r.value : "deepl";
}
function renderAzureKeyStat(d) {
  const el = $("#azureKeyStat");
  if (!el) return;
  if (d && d.set) {
    el.textContent = "● 설정됨 (" + (d.region || "지역 미상") + ")";
    el.className = "hint deepl-ok";
  } else {
    el.textContent = "○ 미설정 — 키를 저장하세요";
    el.className = "hint deepl-no";
  }
}
async function loadAzureUsage() {
  const el = $("#azureUsage");
  if (!el) return;
  el.textContent = "사용량 집계 중…";
  const r = await api("/api/azure_usage");
  if (r.error) { el.textContent = "사용량: 조회 실패 (" + r.error + ")"; el.className = "deepl-usage err"; return; }
  const pct = r.limit ? Math.round((r.count / r.limit) * 100) : 0;
  el.className = "deepl-usage";
  el.innerHTML = `이번 달 사용 <b>${r.count.toLocaleString()}</b> / ${r.limit.toLocaleString()}자 (${pct}%)
    · 남음 <b>${r.remaining.toLocaleString()}</b>자 <span class="hint">· 이 툴에서 보낸 분량 기준 자체 집계</span>
    <span class="deepl-bar"><span style="width:${Math.min(100, pct)}%"></span></span>`;
}
function applyEngineUi() {
  const az = curEngine() === "azure";
  $("#deeplKeySec").style.display = az ? "none" : "";
  $("#azureKeySec").style.display = az ? "" : "none";
  if (az) loadAzureUsage();
}
async function showDeepl() {
  if (!STATE.open) return toast("먼저 시나리오를 여세요");
  $("#deepl").style.display = "flex";
  $("#deeplResult").textContent = "";
  $("#deeplDraftFile").disabled = !STATE.curRel;
  $("#deeplDraftFile").textContent = STATE.curRel
    ? "📄 현재 파일만 (" + STATE.curRel.split(/[\\/]/).pop() + ")" : "📄 현재 파일만 (없음)";
  const s = await api("/api/state");
  renderDeeplKeyStat(s.deepl);
  renderAzureKeyStat(s.azure);
  if (s.deepl && s.deepl.set) loadDeeplUsage();
  else $("#deeplUsage").textContent = "";
  applyEngineUi();
  runDeeplCount();
}
function closeDeepl() { $("#deepl").style.display = "none"; }
async function runDeeplCount() {
  const el = $("#deeplCount");
  if (!el) return;
  el.textContent = "번역 분량 계산 중…";
  const overwrite = $("#deeplOverwrite").checked ? 1 : 0;
  const rel = STATE.curRel ? `&rel=${encodeURIComponent(STATE.curRel)}` : "";
  const r = await api(`/api/deepl_count?overwrite=${overwrite}${rel}`);
  if (r.error) { el.textContent = "분량 계산 실패: " + r.error; return; }
  const cur = STATE.curRel ? STATE.curRel.split(/[\\/]/).pop() : null;
  const fmt = (c) => c
    ? `${c.chars.toLocaleString()}자 (고유 ${c.unique.toLocaleString()}문장${
        c.chars_raw !== c.chars ? ` · 중복포함 ${c.chars_raw.toLocaleString()}자` : ""})`
    : "—";
  const fileLine = r.file
    ? `📄 현재 파일 (${esc(cur)}): <b>${fmt(r.file)}</b>`
    : `📄 현재 파일: 열린 파일 없음`;
  const allLine = `📚 전체 시나리오: <b>${fmt(r.all)}</b>`;
  const note = overwrite ? "" : `<span class="hint"> · 빈 칸만 기준</span>`;
  el.innerHTML = `${fileLine}<br>${allLine}${note}`;
}
async function saveDeeplKey() {
  const key = $("#deeplKey").value.trim();
  if (!key) return toast("키를 입력하세요");
  const r = await post("/api/deepl_key", { key });
  if (r.error) return toast("오류: " + r.error);
  $("#deeplKey").value = "";
  renderDeeplKeyStat(r);
  if (r.set) loadDeeplUsage();
  toast("키 저장됨");
}
async function saveAzureKey() {
  const key = $("#azureKey").value.trim();
  const region = $("#azureRegion").value.trim();
  if (!key) return toast("키를 입력하세요");
  const r = await post("/api/azure_key", { key, region });
  if (r.error) return toast("오류: " + r.error);
  $("#azureKey").value = "";
  renderAzureKeyStat(r);
  toast("키 저장됨");
}
async function runDeeplDraft(scope) {
  const overwrite = $("#deeplOverwrite").checked;
  const rel = scope === "file" ? STATE.curRel : null;
  if (scope === "file" && !rel) return toast("먼저 파일을 여세요");
  const btns = ["#deeplDraftFile", "#deeplDraftAll", "#deeplKeySave", "#azureKeySave"];
  btns.forEach((b) => ($(b).disabled = true));
  $("#deeplResult").textContent = "번역 중… (문장 수에 따라 수십 초 걸릴 수 있어요)";
  const ep = curEngine() === "azure" ? "/api/azure_draft" : "/api/deepl_draft";
  const r = await post(ep, { rel, overwrite });
  btns.forEach((b) => ($(b).disabled = false));
  $("#deeplDraftFile").disabled = !STATE.curRel;
  if (r.error) { $("#deeplResult").textContent = "오류: " + r.error; return; }
  const x = r.result;
  $("#deeplResult").textContent =
    `완료: ${x.translated}개 초안 생성 (고유 ${x.unique}문장 · ${x.chars.toLocaleString()}자 전송)` +
    (x.skipped ? ` · 복원 실패 ${x.skipped}문장은 빈 칸 (DeepL 초안으로 채우세요)` : "");
  if (x.skipped && r.failed && r.failed.length) {
    // 복원 실패 문장을 바로 확인할 수 있게 첫 실패 문장으로 이동 (전체 목록은 ⚠ 경고 패널)
    setTimeout(() => {
      closeDeepl();
      toast(`복원 실패 ${r.failed.length}문장 — 첫 문장으로 이동 (전체는 ⚠ 경고 패널)`);
      jumpTo(r.failed[0].rel, r.failed[0].sid);
    }, 1200);
  }
  renderProgress(r.stats);
  loadDeeplUsage();
  if (curEngine() === "azure") loadAzureUsage();
  runDeeplCount();               // 초안 채운 뒤 남은 분량 갱신
  await refreshState();
  if (STATE.curRel) openFile(STATE.curRel);
}

// ── 번역 원문 초기화 ──
function askConfirm(msg, yesLabel = "네") {
  return new Promise((resolve) => {
    $("#confirmMsg").textContent = msg;
    $("#confirmYes").textContent = yesLabel;
    $("#confirmBox").style.display = "flex";
    const done = (v) => { $("#confirmBox").style.display = "none"; resolve(v); };
    $("#confirmYes").onclick = () => done(true);
    $("#confirmNo").onclick = () => done(false);
  });
}

async function resetTranslations(scope) {
  if (!STATE.open) return toast("먼저 시나리오를 여세요");
  if (scope === "file" && !STATE.curRel) return toast("먼저 파일을 여세요");
  const msg = scope === "file"
    ? `현재 파일의 번역을 모두 지우고 원문 상태로 되돌립니다.\n\n${STATE.curRel}\n\n정말로 초기화하시겠습니까?`
    : "시나리오 전체의 번역(본문 + 식별자)을 모두 지우고\n원문 상태로 되돌립니다.\n\n용어집 단어 번역과 툴 표시 이름은 유지됩니다.\n\n정말로 초기화하시겠습니까?";
  if (!(await askConfirm(msg, "네, 초기화합니다"))) return;
  const r = await post("/api/reset", { scope, rel: STATE.curRel });
  if (r.error) return toast(r.error);
  toast(`번역 ${r.cleared}개 초기화 (직전 상태는 projects/….bak_reset 에 백업)`);
  renderProgress(r.stats);
  const s = await api("/api/state");
  STATE.files = s.files || [];
  renderFileList();
  if (STATE.curRel) openFile(STATE.curRel);
}

// ── 스토리 흐름 플로우차트 ──
let flowInited = false;
async function showFlow() {
  if (!STATE.open) return toast("먼저 시나리오를 여세요");
  if (window.mermaid && !flowInited) {
    mermaid.initialize({ startOnLoad: false, securityLevel: "loose", flowchart: { useMaxWidth: false } });
    flowInited = true;
  }
  $("#flow").style.display = "flex";
  const host = $("#flowChart");
  host.innerHTML = "그래프 생성 중…";
  const r = await api("/api/flow?all=" + ($("#flowAll").checked ? "1" : "0"));
  if (r.error) { host.innerHTML = `<div class="empty">${r.error}</div>`; return; }
  if (!window.mermaid) { host.innerHTML = `<div class="empty">mermaid 로드 실패</div>`; return; }
  try {
    const { svg } = await mermaid.render("flowSvg", r.mermaid);
    host.innerHTML = svg;
    // 노드 클릭 → 파일 편집 / ✏ 이름 번역 모드면 툴 전용 표시명 입력
    Object.entries(r.id2rel).forEach(([nid, rel]) => {
      const el = host.querySelector(`[id^="flowchart-${nid}-"]`) || host.querySelector(`#${nid}`);
      if (el) {
        el.style.cursor = "pointer";
        el.addEventListener("click", () => {
          if ($("#flowEdit").checked) {
            openFlowNameBar((r.id2name || {})[nid] || "", (r.id2tool || {})[nid] || "");
          } else {
            $("#flow").style.display = "none"; openFile(rel);
          }
        });
      }
    });
  } catch (e) {
    host.innerHTML = `<div class="empty">그래프 렌더 실패: ${e}</div>`;
  }
}
function closeFlow() { $("#flow").style.display = "none"; }

// ── 툴 전용 이름 번역 (흐름 노드 라벨 — export 에 안 들어감) ──
let flowNameTarget = "";
let flowNamePrefill = "";
function openFlowNameBar(orig, curTool) {
  if (!orig) return;
  flowNameTarget = orig;
  flowNamePrefill = curTool || orig;
  $("#flowNameOrig").textContent = orig;
  // 현재 표시명(있으면) 또는 원문을 미리 채워, 일부만 고쳐 쓸 수 있게
  // (예: 02会話　⑥VS2 → 한자만 고쳐 02대화　⑥VS2)
  $("#flowNameKo").value = flowNamePrefill;
  $("#flowNameBar").style.display = "flex";
  $("#flowNameKo").focus();
  $("#flowNameKo").select();
}
async function saveFlowName() {
  if (!flowNameTarget) return;
  const target = flowNameTarget;
  flowNameTarget = "";                    // blur+버튼/Enter 중복 저장 방지
  const v = $("#flowNameKo").value.trim();
  if (v === flowNamePrefill) {            // 변경 없음 → 저장 없이 닫기
    $("#flowNameBar").style.display = "none";
    return;
  }
  const r = await post("/api/tool_name", { name: target, ko: v });
  if (r.error) return toast(r.error);
  $("#flowNameBar").style.display = "none";
  toast("표시 이름 저장 (툴에서만 보임)");
  showFlow();   // 새 라벨로 다시 그림
}

async function doExport() {
  let def;
  if (STATE.srcWsn) {
    // .wsn 으로 열었으면 기본 .wsn 으로 내보냄
    def = STATE.srcWsn.replace(/\.wsn$/i, "") + "_KR.wsn";
  } else {
    def = $("#scenDir").value.trim().replace(/[\\/]+$/, "") + "_KR";
  }
  // 폴더/wsn 선택처럼 네이티브 저장 다이얼로그로. 기본 경로를 폴더/파일명으로 분리해 전달.
  const norm = def.replace(/\\/g, "/");
  const slash = norm.lastIndexOf("/");
  const initdir = slash >= 0 ? norm.slice(0, slash) : "";
  const initfile = slash >= 0 ? norm.slice(slash + 1) : norm;
  toast("저장 위치 선택창을 여는 중…");
  const pick = await post("/api/pick_folder", { kind: "save", initfile, initdir });
  if (pick.error) return toast("선택창 오류: " + pick.error + " (터미널에서 직접 서버를 실행했는지 확인)");
  if (!pick.path) return toast("취소됨");
  const out = pick.path;
  toast("내보내는 중…");
  const r = await post("/api/export", { out_dir: out });
  if (r.error) return toast("오류: " + r.error);
  const tail = r.wsn ? ` · .wsn 패키지(${r.entries}개) → ${r.out_dir}` : ` → ${r.out_dir}`;
  toast(`완료: ${r.result.applied}곳 번역 · ${r.result.xml_files} XML · 에셋 ${r.result.copied_assets}개${tail}`);
}

$("#btnOpen").onclick = () => pickAndOpen("dir");
$("#btnOpenWsn").onclick = () => pickAndOpen("file");
$("#scenDir").addEventListener("keydown", (e) => { if (e.key === "Enter") openScenario(); });
$("#btnSave").onclick = async () => { const r = await post("/api/save"); toast(r.ok ? "저장됨" : "오류"); };
$("#btnExport").onclick = doExport;
// CSV 기본 경로(시나리오 폴더_번역.csv)를 폴더/파일명으로 분리
function csvDefault() {
  const def = $("#scenDir").value.trim().replace(/[\\/]+$/, "") + "_번역.csv";
  const norm = def.replace(/\\/g, "/");
  const slash = norm.lastIndexOf("/");
  return { initdir: slash >= 0 ? norm.slice(0, slash) : "",
           initfile: slash >= 0 ? norm.slice(slash + 1) : norm };
}
async function bulkExport() {
  if (!STATE.open) return toast("먼저 시나리오를 여세요");
  toast("저장 위치 선택창을 여는 중…");
  const pick = await post("/api/pick_folder", { kind: "csv_save", ...csvDefault() });
  if (pick.error) return toast("선택창 오류: " + pick.error);
  const path = pick.path;
  if (!path) return;                 // 취소
  toast("내보내는 중…");
  const r = await post("/api/bulk_export", { path });
  if (r.error) return toast("오류: " + r.error);
  toast(`${r.rows}행 내보냄 → ${r.path}`);
}
async function bulkImport() {
  if (!STATE.open) return toast("먼저 시나리오를 여세요");
  toast("파일 선택창을 여는 중…");
  const pick = await post("/api/pick_folder", { kind: "csv_open", ...csvDefault() });
  if (pick.error) return toast("선택창 오류: " + pick.error);
  const path = pick.path;
  if (!path) return;                 // 취소
  toast("가져오는 중…");
  const r = await post("/api/bulk_import", { path });
  if (r.error) return toast("오류: " + r.error);
  const x = r.result;
  toast(`적용 ${x.applied} · 변화없음 ${x.skipped} · 미매칭 ${x.unmatched} (총 ${x.rows}행)`);
  renderProgress(r.stats);
  await refreshState();
  if (STATE.curRel) openFile(STATE.curRel);
}
$("#btnBulkOut").onclick = bulkExport;
$("#btnBulkIn").onclick = bulkImport;
$("#btnSearch").onclick = showSearch;
// 번역문 전체 찾아 바꾸기 — 용어 오타가 초안에 구워진 뒤 일괄 복구용 (원문 불변)
async function replaceInKo() {
  const q = $("#searchQ").value;
  const repl = $("#replaceKo").value;
  const jp_cond = $("#replaceJpCond").value.trim();
  if (!q.trim()) return toast("먼저 위 칸에 바꿀 검색어를 입력하세요");
  const dry = await post("/api/replace_ko", { q, repl, jp_cond, dry: true });
  if (dry.error) return toast(dry.error);
  if (!dry.hits) return toast(jp_cond
    ? "조건에 맞는 칸의 번역문에서 해당 문자열을 찾지 못했습니다"
    : "번역문에서 해당 문자열을 찾지 못했습니다 (대소문자 구분)");
  const cond = jp_cond ? `\n대상: 원문에 "${jp_cond}" 가 있는 칸만` : "";
  const yes = await askConfirm(
    `번역문 ${dry.units}개 칸에서 ${dry.hits}곳을 바꿉니다.${cond}\n\n"${q}" → "${repl}"\n\n원문은 건드리지 않습니다. 계속할까요?`,
    "네, 바꿉니다");
  if (!yes) return;
  const r = await post("/api/replace_ko", { q, repl, jp_cond });
  if (r.error) return toast(r.error);
  toast(`번역문 ${r.units}개 칸 · ${r.hits}곳 바꿈`);
  renderProgress(r.stats);
  runSearch();                                  // 결과 목록 갱신
  if (STATE.curRel) openFile(STATE.curRel);     // 열린 파일 화면 갱신
}

$("#searchClose").onclick = closeSearch;
$("#searchGo").onclick = runSearch;
$("#replaceGo").onclick = replaceInKo;
$("#searchQ").addEventListener("keydown", (e) => { if (e.key === "Enter") runSearch(); });
$("#searchScope").onchange = runSearch;
$("#search").addEventListener("click", (e) => { if (e.target.id === "search") closeSearch(); });
$("#btnOverflow").onclick = showOverflow;
$("#overflowClose").onclick = closeOverflow;
$("#overflowGo").onclick = runOverflow;
$("#overflowTidy").onclick = () => bulkTidyOverflow("full");
$("#overflowTidySimple").onclick = () => bulkTidyOverflow("simple");
$("#overflowScope").onchange = runOverflow;
$("#overflow").addEventListener("click", (e) => { if (e.target.id === "overflow") closeOverflow(); });
$("#btnFlow").onclick = showFlow;
$("#btnTerms").onclick = showTerms;
$("#btnDeepl").onclick = showDeepl;
$("#deeplClose").onclick = closeDeepl;
$("#deeplKeySave").onclick = saveDeeplKey;
$("#azureKeySave").onclick = saveAzureKey;
document.querySelectorAll('input[name="mtEngine"]')
  .forEach((r) => r.addEventListener("change", applyEngineUi));
$("#azureKey").addEventListener("keydown", (e) => { if (e.key === "Enter") saveAzureKey(); });
$("#deeplDraftFile").onclick = () => runDeeplDraft("file");
$("#deeplDraftAll").onclick = () => runDeeplDraft("all");
$("#deeplOverwrite").addEventListener("change", runDeeplCount);   // 덮어쓰기 토글 시 분량 재계산
$("#deeplKey").addEventListener("keydown", (e) => { if (e.key === "Enter") saveDeeplKey(); });
$("#deepl").addEventListener("click", (e) => { if (e.target.id === "deepl") closeDeepl(); });
$("#termsClose").onclick = closeTerms;
$("#btnApplyTerms").onclick = applyTerms;
$("#termAdd").onclick = addTerm;
$("#termAddKo").addEventListener("keydown", (e) => { if (e.key === "Enter") addTerm(); });
$("#termAddJp").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#termAddKo").focus(); });
$("#terms").addEventListener("click", (e) => { if (e.target.id === "terms") closeTerms(); });
// 용어집 섹션 접기/펼치기 — 헤더 클릭 (헤더 안 버튼/체크박스는 제외), 상태 기억
document.querySelectorAll(".terms-sec").forEach((sec) => {
  const h = sec.querySelector("h3");
  const list = sec.querySelector(".terms-list");
  if (!h || !list) return;
  const key = "termsec:" + list.id;
  const caret = document.createElement("span");
  caret.className = "sec-caret";
  h.prepend(caret);
  let open = localStorage.getItem(key) !== "0";
  const apply = () => {
    sec.classList.toggle("collapsed", !open);
    caret.textContent = open ? "▾" : "▸";
  };
  apply();
  h.style.cursor = "pointer";
  h.addEventListener("click", (e) => {
    if (e.target.closest("button, input, label")) return;
    open = !open;
    localStorage.setItem(key, open ? "1" : "0");
    apply();
  });
});

// 경고 패널 섹션 접기/펼치기 — 제목 클릭, 상태 기억
document.querySelectorAll("#overflow .warn-section-title").forEach((h) => {
  const body = h.nextElementSibling;              // 대응하는 .search-results
  if (!body) return;
  const key = "warnsec:" + body.id;
  const caret = document.createElement("span");
  caret.className = "sec-caret";
  h.prepend(caret);
  let open = localStorage.getItem(key) !== "0";
  const apply = () => {
    body.style.display = open ? "" : "none";
    caret.textContent = open ? "▾" : "▸";
  };
  apply();
  h.style.cursor = "pointer";
  h.addEventListener("click", () => {
    open = !open;
    localStorage.setItem(key, open ? "1" : "0");
    apply();
  });
});

// ── 공용 용어집 패널 (전체 관리) ──
let GT_CACHE = [];
async function loadGTerms() {
  const r = await api("/api/global_terms");
  GT_CACHE = r.results || [];
  renderGTList();
}
function renderGTList() {
  const host = $("#gtList");
  host.innerHTML = "";
  const q = $("#gtFilter").value.trim().toLowerCase();
  const list = GT_CACHE.filter((t) =>
    !q || t.jp.toLowerCase().includes(q) || (t.ko || "").toLowerCase().includes(q));
  $("#gtCount").textContent = q
    ? `${list.length}개 표시 / 전체 ${GT_CACHE.length}개`
    : `전체 ${GT_CACHE.length}개 · 등장 횟수(왼쪽 숫자)는 현재 열린 시나리오 기준`;
  if (!list.length) {
    host.innerHTML = `<div class="empty">${q ? "필터에 맞는 용어가 없습니다" : "등록된 공용 용어가 없습니다"}</div>`;
    return;
  }
  list.forEach((t) => renderGlobalRow(host, t));
}
async function showGTerms() {
  $("#gterms").style.display = "flex";
  await loadGTerms();
}
$("#btnGTerms2").onclick = showGTerms;
$("#gtermsClose").onclick = () => { $("#gterms").style.display = "none"; };
$("#gtFilter").oninput = renderGTList;
$("#gtAdd").onclick = async () => {
  const jp = $("#gtAddJp").value.trim();
  const ko = $("#gtAddKo").value.trim();
  if (!jp || !ko) return toast("단어와 번역을 모두 입력하세요");
  await post("/api/global_term", { jp, ko });
  $("#gtAddJp").value = ""; $("#gtAddKo").value = "";
  toast(`공용 용어 등록: ${jp} → ${ko}`);
  refreshGlobalViews();
};
$("#gtAddKo").onkeydown = (e) => { if (e.key === "Enter") $("#gtAdd").click(); };

$("#globalReapply").onclick = async () => {
  const dry = await post("/api/reapply_terms", { dry: true });
  if (dry.error) return toast(dry.error);
  if (!dry.would) return toast("잔존 원문에 적용할 용어가 없습니다 (완성 번역은 대상 아님)");
  const yes = await askConfirm(
    `번역칸에 원문 단어가 남아 있는 ${dry.would}개 문장에\n용어집(공용+이 시나리오) 번역을 일괄 적용합니다.\n\n완성된 한국어 번역·완료 표시 문장은 건드리지 않습니다.`,
    "네, 적용합니다");
  if (!yes) return;
  const r = await post("/api/reapply_terms", {});
  if (r.error) return toast(r.error);
  toast(`${r.applied}개 문장에 용어 재적용`);
  renderProgress(r.stats);
  if (STATE.curRel) openFile(STATE.curRel);
  reloadTerms();
};
$("#globalExport").onclick = async () => {
  const r = await post("/api/global_export", {});
  if (r.error) return toast(r.error);
  if (!r.path) return;                       // 취소
  toast(`공용 용어 ${r.count}개 내보냄 → ${r.path}`);
};
$("#globalImport").onclick = async () => {
  const r = await post("/api/global_import", {});
  if (r.error) return toast(r.error);
  if (!r.path) return;                       // 취소
  let overwrite = false;
  if (r.conflict > 0) {
    overwrite = await askConfirm(
      `받은 파일: 용어 ${r.total}개 (새 단어 ${r.new} · 겹침 ${r.conflict} · 동일 ${r.same})\n\n`
      + `겹치는 단어를 받은 번역으로 덮어쓸까요?\n(아니오 = 내 번역 유지, 새 단어만 추가)`,
      "네, 덮어씁니다");
  }
  const r2 = await post("/api/global_import", { path: r.path, apply: true, overwrite });
  if (r2.error) return toast(r2.error);
  toast(`가져오기 완료 — 추가 ${r2.added}개 · 갱신 ${r2.updated}개`);
  refreshGlobalViews();
};
$("#globalOn").onchange = async () => {
  const r = await post("/api/global_toggle", { on: $("#globalOn").checked });
  if (r.error) return toast(r.error);
  toast(r.on ? "공용 용어집 적용 켬" : "공용 용어집 적용 끔 (이 시나리오만)");
  reloadTerms();
};
// Ctrl+S = 진행상황 저장 (브라우저 저장 대화상자 대신)
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
    e.preventDefault();
    if (!STATE.open) return;
    // 편집 중이던 칸이 있으면 blur 로 먼저 커밋한 뒤 저장
    const el = document.activeElement;
    if (el && (el.tagName === "TEXTAREA" || el.tagName === "INPUT")) el.blur();
    setTimeout(async () => {
      const r = await post("/api/save");
      toast(r.ok ? "저장됨 (Ctrl+S)" : "저장 오류");
    }, 250);
  }
});

// 파일 사이드바 접기/펼치기 (상태 기억)
{
  const sb = $("#sidebar");
  let col = localStorage.getItem("sidecol") === "1";
  const applySide = () => sb.classList.toggle("collapsed", col);
  applySide();
  const flip = () => { col = !col; localStorage.setItem("sidecol", col ? "1" : "0"); applySide(); };
  $("#sideToggle").onclick = flip;
  $("#sideExpand").onclick = flip;
}

$("#btnResetFile").onclick = () => resetTranslations("file");
$("#btnResetAll").onclick = () => resetTranslations("all");
$("#flowClose").onclick = closeFlow;
$("#flowAll").onchange = showFlow;
$("#flowEdit").onchange = () => { if (!$("#flowEdit").checked) $("#flowNameBar").style.display = "none"; };
$("#flowNameSave").onclick = saveFlowName;
$("#flowNameKo").onkeydown = (e) => { if (e.key === "Enter") saveFlowName(); };
$("#flowNameKo").onblur = saveFlowName;   // 포커스 아웃 = 자동 저장
$("#flow").addEventListener("click", (e) => { if (e.target.id === "flow") closeFlow(); });
$("#viewList").onclick = () => setView("list");
$("#viewFlow").onclick = () => setView("flow");
$("#hideEmpty").onchange = renderFileList;
$("#hideDone").onchange = () => STATE.curRel && openFile(STATE.curRel);
$("#hideControl").onchange = () => STATE.curRel && openFile(STATE.curRel);
$("#updateBtn").onclick = applyUpdate;
$("#updateDismiss").onclick = () => ($("#updateBar").style.display = "none");

refreshState();
checkUpdate();

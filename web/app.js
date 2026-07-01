"use strict";
const $ = (s) => document.querySelector(s);
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
const WRAP_ROWS = 8;        // 넘침 판정 기준 줄 수(넘으면 잘림/페이지 넘어감)
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
function wrapForGameRuns(text, units) {
  const lines = [];
  let cur = [], color = "", w = 0;
  const push = (ch) => {
    const last = cur[cur.length - 1];
    if (last && last.color === color) last.text += ch;
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
    const cw = charUnits(ch);
    if (w + cw > units && w > 0) newline();
    push(ch); w += cw;
  }
  lines.push(cur);                                            // 마지막(빈) 줄
  return lines;
}

// 카드 해설용 평문 줄바꿈 — 색코드/치환 해석 없이 있는 그대로 units 폭으로 접는다(wx 다이얼로그).
function wrapPlain(text, units) {
  const out = [];
  for (const raw of text.split("\n")) {
    let line = "", w = 0;
    for (const ch of raw) {
      const cw = charUnits(ch);
      if (w + cw > units && line !== "") { out.push(line); line = ""; w = 0; }
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
const SUBST_RE = /(\$[^$\n]+\$|%[^%\n]+%|#[A-Za-z])/g;   // $..$ / %..% 변수, #x 이름코드
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
  if ($("#hideDone").checked && u.ko) return false;
  if ($("#hideControl").checked && u.control) return false;
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
async function renderFlowView(rel) {
  const box = $("#units");
  box.innerHTML = `<div class="empty">흐름 불러오는 중…</div>`;
  const r = await api("/api/outline?rel=" + encodeURIComponent(rel));
  box.innerHTML = "";
  if (r.error || !r.outline) { box.innerHTML = `<div class="empty">흐름 정보 없음</div>`; return; }
  const wrap = document.createElement("div");
  wrap.className = "outline";
  r.outline.forEach((e) => {
    if (e.kind === "talk") {
      const ids = (e.unit_ids || []).map((id) => STATE.unitById[id]).filter(Boolean);
      if (!ids.length) return;
      const row = document.createElement("div");
      row.className = "ol-talk";
      row.style.marginLeft = (e.depth * 18) + "px";
      // 말투 변형이면 묶음, 아니면 단일
      if (ids.length > 1 && ids[0].group != null) row.appendChild(toneGroupEl(rel, ids));
      else ids.forEach((u) => row.appendChild(freeUnitEl(rel, u)));
      wrap.appendChild(row);
    } else {
      const row = document.createElement("div");
      row.className = "ol-mark ol-" + e.kind;
      row.style.marginLeft = (e.depth * 18) + "px";
      row.innerHTML = `<span class="ol-ic">${OL_ICON[e.kind] || "·"}</span> <span class="ol-desc"></span>`;
      row.querySelector(".ol-desc").textContent = e.desc;
      if (e.target_rel) {
        row.classList.add("ol-jump");
        row.title = "클릭 → " + e.target_rel;
        row.onclick = () => openFile(e.target_rel);
      }
      wrap.appendChild(row);
    }
  });
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
  el.className = "unit" + (u.ko ? " done" : "") + (u.control ? " control" : "");
  el.dataset.sid = u.id;
  const CAT = { dialogue: "대사", narration: "나레이션", choice: "선택지", label: "제목", desc: "설명", sysname: "내부명" };
  const catBadge = u.cat ? `<span class="badge cat-${u.cat}">${CAT[u.cat] || u.cat}</span>` : "";
  const left = document.createElement("div");
  const spk = u.speaker ? `<span class="badge spk">🗣 ${esc(u.speaker)}</span>` : "";
  const conds = condBadges(u.conditions);
  const tone = u.tone ? `<span class="badge tone">말투 ${esc(u.tone)}</span>` : "";
  const ctrl = u.control ? '<span class="badge">제어기호</span>' : "";
  const imgB = u.img ? '<span class="badge img" title="그림이 떠서 한 줄 폭이 좁음 (43→33단위)">🖼 그림·33</span>' : "";
  left.innerHTML = `<div class="meta">${catBadge}${spk}${conds}${tone}${ctrl}${imgB}</div>
    <div class="jp"></div>`;
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

  // ko 변경을 서버에 반영 (onblur·되돌리기 공용)
  const commit = async (newKo) => {
    if (newKo === (u.ko || "")) return;
    u.ko = newKo;
    el.classList.toggle("done", !!u.ko);
    const res = await post("/api/set", { kind: "free", rel, id: u.id, ko: newKo });
    renderProgress(res.stats);
    api("/api/state").then((s) => { STATE.files = s.files || []; renderFileList(); });
  };

  ta.onblur = () => {
    let val = ta.value;
    if (val === "") { val = u.jp; ta.value = u.jp; }   // 비우면 원문 복원
    commit(val === u.jp ? "" : val);                   // 원문 그대로면 미번역으로 취급
  };

  // 게임 창 미리보기 — 메시지창(대사/나레이션)에만. 카드 설명(CastCard/ItemCard/SkillCard)은
  // centering_y=True(card.py) 라 7줄 초과해도 안 잘리고 폭도 달라서 미리보기를 붙이지 않는다.
  const isMsg = u.cat === "dialogue" || u.cat === "narration";
  const isCard = u.cat === "desc";   // 카드 해설(CastCard/ItemCard/SkillCard) = 별도 미리보기
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
          if (run.color) {
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

  // "정돈" — 문단 안 수동 줄바꿈을 없애 8줄 넘침을 완화. 메시지창에서 넘칠 때만 노출.
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
async function reloadTerms() {
  const r = await api("/api/terms");
  renderTermList($("#termsManual"), r.manual || [], "manual");
  renderTermList($("#termsExact"), r.exact || [], "exact");
  renderTermList($("#termsWord"), r.word || [], "word");
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
    if (t.is_identifier) jp.innerHTML += `<span class="term-idbadge" title="식별자이기도 함 — 식별자 자체는 원문 유지, 자유 텍스트에서만 치환">식별자</span>`;
    jp.appendChild(document.createTextNode(t.jp));
    const inp = document.createElement("input");
    inp.type = "text"; inp.value = t.ko || ""; inp.placeholder = "번역";
    inp.onblur = async () => {
      if (inp.value === (t.ko || "")) return;
      t.ko = inp.value;
      row.classList.toggle("done", !!t.ko);
      const res = await post("/api/term", { kind, jp: t.jp, ko: inp.value });
      if (kind === "exact" && res.applied) toast(`${res.applied}곳 일괄 적용`);
      if (res.stats) renderProgress(res.stats);
      if (STATE.curRel) openFile(STATE.curRel);
    };
    const occBtn = document.createElement("button");
    occBtn.className = "term-occbtn";
    occBtn.textContent = `📍 ${(t.occurrences || []).length}`;
    occBtn.title = "등장 위치 보기";
    head.appendChild(jp); head.appendChild(inp); head.appendChild(occBtn);
    if (kind === "manual") {
      const del = document.createElement("button");
      del.className = "term-del"; del.textContent = "✕"; del.title = "삭제";
      del.onclick = async () => { await post("/api/term_remove", { jp: t.jp }); reloadTerms(); };
      head.appendChild(del);
    }
    row.appendChild(head);
    // 펼침: 등장 위치(파일·문장) 목록 → 클릭 이동
    const occBox = document.createElement("div");
    occBox.className = "term-occ"; occBox.style.display = "none";
    (t.occurrences || []).forEach((o) => {
      const orow = document.createElement("div");
      orow.className = "occ-row";
      orow.innerHTML = `<span class="occ-file"></span><span class="occ-prev"></span>`;
      orow.querySelector(".occ-file").textContent = o.rel.split(/[\\/]/).pop();
      orow.querySelector(".occ-prev").textContent = o.preview;
      orow.title = o.rel;
      orow.onclick = () => { closeTerms(); jumpTo(o.rel, o.sid); };
      occBox.appendChild(orow);
    });
    occBtn.onclick = () => {
      const open = occBox.style.display === "none";
      occBox.style.display = open ? "block" : "none";
    };
    row.appendChild(occBox);
    host.appendChild(row);
  });
}

// 특정 파일의 특정 문장(sid)으로 이동 + 강조
async function jumpTo(rel, sid) {
  if (VIEW === "flow") setView("list");
  await openFile(rel);
  setTimeout(() => {
    const el = $("#units").querySelector(`.unit[data-sid="${sid}"]`);
    if (!el) return;
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
const SR_CAT = { dialogue: "대사", narration: "나레이션", choice: "선택지", label: "제목", desc: "설명", sysname: "내부명" };
async function showSearch() {
  if (!STATE.open) return toast("먼저 시나리오를 여세요");
  $("#search").style.display = "flex";
  $("#searchQ").focus(); $("#searchQ").select();
}
function closeSearch() { $("#search").style.display = "none"; }
async function runSearch() {
  const q = $("#searchQ").value.trim();
  const scope = $("#searchScope").value;
  const box = $("#searchResults");
  if (!q) { box.innerHTML = `<div class="empty">검색어를 입력하세요</div>`; return; }
  box.innerHTML = `<div class="empty">검색 중…</div>`;
  const r = await api(`/api/search?q=${encodeURIComponent(q)}&scope=${encodeURIComponent(scope)}`);
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
async function bulkTidyOverflow() {
  const scope = $("#overflowScope").value;
  if (scope === "file" && !STATE.curRel) return toast("현재 열린 파일이 없습니다");
  const where = scope === "file" ? "현재 파일의" : "시나리오 전체의";
  if (!confirm(`${where} 넘치는 대사(8줄 초과)를 정돈합니다.\n문단 안 수동 줄바꿈을 없애 게임 자동 줄바꿈에 맡기고(문단 빈 줄은 유지), 끝의 빈 줄을 제거합니다.\n\n계속할까요?`)) return;
  const r = await post("/api/overflow_tidy", { scope, rel: STATE.curRel || "" });
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
  const r = await api(`/api/overflow?scope=${encodeURIComponent(scope)}${rel}`);
  if (r.error) { box.innerHTML = `<div class="empty">${esc(r.error)}</div>`; return; }
  renderOverflowResults(r.results || []);
}
function renderDupChoices(list) {
  const box = $("#dupResults");
  box.innerHTML = "";
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
async function showDeepl() {
  if (!STATE.open) return toast("먼저 시나리오를 여세요");
  $("#deepl").style.display = "flex";
  $("#deeplResult").textContent = "";
  $("#deeplDraftFile").disabled = !STATE.curRel;
  $("#deeplDraftFile").textContent = STATE.curRel
    ? "📄 현재 파일만 (" + STATE.curRel.split(/[\\/]/).pop() + ")" : "📄 현재 파일만 (없음)";
  const s = await api("/api/state");
  renderDeeplKeyStat(s.deepl);
  if (s.deepl && s.deepl.set) loadDeeplUsage();
  else $("#deeplUsage").textContent = "";
}
function closeDeepl() { $("#deepl").style.display = "none"; }
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
async function runDeeplDraft(scope) {
  const overwrite = $("#deeplOverwrite").checked;
  const rel = scope === "file" ? STATE.curRel : null;
  if (scope === "file" && !rel) return toast("먼저 파일을 여세요");
  const btns = ["#deeplDraftFile", "#deeplDraftAll", "#deeplKeySave"];
  btns.forEach((b) => ($(b).disabled = true));
  $("#deeplResult").textContent = "번역 중… (문장 수에 따라 수십 초 걸릴 수 있어요)";
  const r = await post("/api/deepl_draft", { rel, overwrite });
  btns.forEach((b) => ($(b).disabled = false));
  $("#deeplDraftFile").disabled = !STATE.curRel;
  if (r.error) { $("#deeplResult").textContent = "오류: " + r.error; return; }
  const x = r.result;
  $("#deeplResult").textContent =
    `완료: ${x.translated}개 초안 생성 (고유 ${x.unique}문장 · ${x.chars.toLocaleString()}자 전송)`;
  renderProgress(r.stats);
  loadDeeplUsage();
  await refreshState();
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
    // 노드 클릭 → 해당 파일 편집
    Object.entries(r.id2rel).forEach(([nid, rel]) => {
      const el = host.querySelector(`[id^="flowchart-${nid}-"]`) || host.querySelector(`#${nid}`);
      if (el) {
        el.style.cursor = "pointer";
        el.addEventListener("click", () => { $("#flow").style.display = "none"; openFile(rel); });
      }
    });
  } catch (e) {
    host.innerHTML = `<div class="empty">그래프 렌더 실패: ${e}</div>`;
  }
}
function closeFlow() { $("#flow").style.display = "none"; }

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
async function bulkExport() {
  if (!STATE.open) return toast("먼저 시나리오를 여세요");
  const def = $("#scenDir").value.trim().replace(/[\\/]+$/, "") + "_번역.csv";
  const path = prompt("내보낼 CSV 경로 (스프레드시트에서 ko 열을 번역기로 채우세요):", def);
  if (!path) return;
  toast("내보내는 중…");
  const r = await post("/api/bulk_export", { path });
  if (r.error) return toast("오류: " + r.error);
  toast(`${r.rows}행 내보냄 → ${r.path}`);
}
async function bulkImport() {
  if (!STATE.open) return toast("먼저 시나리오를 여세요");
  const def = $("#scenDir").value.trim().replace(/[\\/]+$/, "") + "_번역.csv";
  const path = prompt("가져올 CSV 경로:", def);
  if (!path) return;
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
$("#searchClose").onclick = closeSearch;
$("#searchGo").onclick = runSearch;
$("#searchQ").addEventListener("keydown", (e) => { if (e.key === "Enter") runSearch(); });
$("#searchScope").onchange = runSearch;
$("#search").addEventListener("click", (e) => { if (e.target.id === "search") closeSearch(); });
$("#btnOverflow").onclick = showOverflow;
$("#overflowClose").onclick = closeOverflow;
$("#overflowGo").onclick = runOverflow;
$("#overflowTidy").onclick = bulkTidyOverflow;
$("#overflowScope").onchange = runOverflow;
$("#overflow").addEventListener("click", (e) => { if (e.target.id === "overflow") closeOverflow(); });
$("#btnFlow").onclick = showFlow;
$("#btnTerms").onclick = showTerms;
$("#btnDeepl").onclick = showDeepl;
$("#deeplClose").onclick = closeDeepl;
$("#deeplKeySave").onclick = saveDeeplKey;
$("#deeplDraftFile").onclick = () => runDeeplDraft("file");
$("#deeplDraftAll").onclick = () => runDeeplDraft("all");
$("#deeplKey").addEventListener("keydown", (e) => { if (e.key === "Enter") saveDeeplKey(); });
$("#deepl").addEventListener("click", (e) => { if (e.target.id === "deepl") closeDeepl(); });
$("#termsClose").onclick = closeTerms;
$("#btnApplyTerms").onclick = applyTerms;
$("#termAdd").onclick = addTerm;
$("#termAddKo").addEventListener("keydown", (e) => { if (e.key === "Enter") addTerm(); });
$("#termAddJp").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#termAddKo").focus(); });
$("#terms").addEventListener("click", (e) => { if (e.target.id === "terms") closeTerms(); });
$("#flowClose").onclick = closeFlow;
$("#flowAll").onchange = showFlow;
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

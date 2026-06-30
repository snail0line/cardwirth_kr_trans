"use strict";
const $ = (s) => document.querySelector(s);
const api = async (path, opts) => (await fetch(path, opts)).json();
const post = (path, body) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

let STATE = { open: false, files: [], curRel: null };

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
  left.innerHTML = `<div class="meta">${catBadge}${spk}${conds}${tone}${ctrl}</div>
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
  ta.onblur = async () => {
    let val = ta.value;
    if (val === "") { val = u.jp; ta.value = u.jp; }   // 비우면 원문 복원
    const newKo = (val === u.jp) ? "" : val;           // 원문 그대로면 미번역으로 취급
    if (newKo === (u.ko || "")) return;
    u.ko = newKo;
    el.classList.toggle("done", !!u.ko);
    const res = await post("/api/set", { kind: "free", rel, id: u.id, ko: newKo });
    renderProgress(res.stats);
    api("/api/state").then((s) => { STATE.files = s.files || []; renderFileList(); });
  };
  right.appendChild(ta);
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
  const out = prompt("내보낼 경로 (폴더, 또는 .wsn 으로 끝나면 패키지로 압축):", def);
  if (!out) return;
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

/* 従業員用UI＋共通処理（かんたん入力モード） */
"use strict";

const S = { user: null, meta: null, view: "loading" };
const $app = () => document.getElementById("app");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const todayStr = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`; };
const fmtDate = (s) => { if (!s) return ""; const [y,m,d] = s.split("-"); return `${y}年${+m}月${+d}日`; };
const yen = (n) => (n ?? 0).toLocaleString("ja-JP") + "円";
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 8);

/* SVG線画アイコン（絵文字不使用） */
const ICONS = {
  truck: '<rect x="1" y="3" width="15" height="13" rx="1"/><path d="M16 8h4l3 3v5h-7z"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/>',
  return: '<polyline points="9 10 4 15 9 20"/><path d="M20 4v7a4 4 0 0 1-4 4H4"/>',
  calplus: '<rect x="3" y="4" width="18" height="17" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="12" y1="12.5" x2="12" y2="17.5"/><line x1="9.5" y1="15" x2="14.5" y2="15"/>',
  trash: '<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/>',
  camera: '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
  clip: '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/><polyline points="9 14 11 16 15 12"/>',
  check: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
  alert: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
};
const icon = (n, size = 24) =>
  `<svg class="icn-svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" ` +
  `stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ` +
  `aria-hidden="true">${ICONS[n]}</svg>`;

/* ---------------- API・オフライン対応 ---------------- */
async function api(path, opt = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opt });
  let data = null;
  try { data = await res.json(); } catch (e) { /* HTMLレスポンス等 */ }
  if (res.status === 401 && S.view !== "login") { S.user = null; renderLogin(); throw new Error("unauth"); }
  return { ok: res.ok, status: res.status, data };
}
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body) });
const put = (path, body) => api(path, { method: "PUT", body: JSON.stringify(body) });

/* 通信が弱い現場向け: 送信失敗したら端末に保存し、復旧時に自動同期 */
function queueLoad() { try { return JSON.parse(localStorage.getItem("sendQueue") || "[]"); } catch (e) { return []; } }
function queueSave(q) { localStorage.setItem("sendQueue", JSON.stringify(q)); updateOfflineBand(); }
function queueAdd(path, body) { const q = queueLoad(); q.push({ path, body, at: new Date().toISOString() }); queueSave(q); }
async function queueFlush() {
  let q = queueLoad();
  if (!q.length) return;
  const rest = [];
  for (const item of q) {
    try {
      const r = await post(item.path, item.body);
      if (!r.ok && r.status !== 422) rest.push(item);
    } catch (e) { rest.push(item); }
  }
  queueSave(rest);
  if (rest.length < q.length && S.view === "home") renderHome();
}
function updateOfflineBand() {
  const n = queueLoad().length;
  const band = document.getElementById("offline-band");
  band.style.display = n ? "block" : "none";
  band.textContent = n ? `未送信のデータが ${n} 件あります（通信が回復すると自動で送信します）` : "";
}
window.addEventListener("online", queueFlush);
setInterval(() => { if (navigator.onLine) queueFlush(); }, 30000);

/* 送信: オンラインなら即送信、失敗したら未送信キューへ */
async function submitOrQueue(path, body) {
  try {
    const r = await post(path, body);
    return r;
  } catch (e) {
    queueAdd(path, body);
    return { ok: true, queued: true, data: {} };
  }
}

/* ---------------- 下書き（自動保存） ---------------- */
function draftSave(kind, data) { localStorage.setItem("draft_" + kind, JSON.stringify(data)); refreshDraftCount(); }
function draftLoad(kind) { try { return JSON.parse(localStorage.getItem("draft_" + kind)); } catch (e) { return null; } }
function draftClear(kind) { localStorage.removeItem("draft_" + kind); refreshDraftCount(); }
function draftCount() { return ["rental","return","extend","waste"].filter(k => localStorage.getItem("draft_" + k)).length; }
function refreshDraftCount() { const e = document.getElementById("draft-count"); if (e) e.textContent = draftCount(); }

/* ---------------- エラー表示（日本語・項目直下） ---------------- */
function showErrors(errors) {
  document.querySelectorAll(".field-error").forEach(e => e.remove());
  document.querySelectorAll(".err-field").forEach(e => e.classList.remove("err-field"));
  const top = document.getElementById("top-error");
  if (top) top.remove();
  const msgs = [];
  for (const [field, msg] of Object.entries(errors || {})) {
    msgs.push(msg);
    const input = document.querySelector(`[data-field="${field}"]`);
    if (input) {
      input.classList.add("err-field");
      const div = document.createElement("div");
      div.className = "field-error";
      div.textContent = msg;
      input.insertAdjacentElement("afterend", div);
    }
  }
  if (msgs.length) {
    const div = document.createElement("div");
    div.id = "top-error";
    div.className = "top-error";
    div.textContent = "入力を確認してください： " + msgs[0];
    $app().prepend(div);
    window.scrollTo(0, 0);
  }
}

/* 二重登録防止: 送信中はボタン無効化 */
let submitting = false;
async function guard(btn, fn) {
  if (submitting) return;
  submitting = true;
  if (btn) { btn.disabled = true; btn.textContent = "送信中…"; }
  try { await fn(); } finally { submitting = false; if (btn) btn.disabled = false; }
}

/* ---------------- 起動 ---------------- */
async function boot() {
  updateOfflineBand();
  const { data } = await api("/api/state");
  if (!data.setup_done) return renderSetup();
  if (!data.user) return renderLogin();
  S.user = data.user;
  if (data.user.must_change_password) return renderChangePassword(true);
  S.meta = (await api("/api/meta")).data;
  if (data.user.role === "admin") return renderAdmin();
  renderHome();
}

/* ---------------- 初期セットアップ ---------------- */
function renderSetup() {
  S.view = "setup";
  $app().innerHTML = `
  <h1>はじめての設定（管理者）</h1>
  <div class="card">
    <label class="f">管理者名</label><input data-field="admin_name" id="su-name">
    <label class="f">会社名</label><input data-field="company_name" id="su-comp">
    <label class="f">メールアドレス</label><input data-field="email" id="su-mail" type="email">
    <label class="f">パスワード（8文字以上）</label><input data-field="password" id="su-pw" type="password">
    <div class="btnrow"><button class="btn green" id="su-go">設定してはじめる</button></div>
  </div>`;
  document.getElementById("su-go").onclick = (ev) => guard(ev.target, async () => {
    const r = await post("/api/setup", {
      admin_name: v("su-name"), company_name: v("su-comp"),
      email: v("su-mail"), password: v("su-pw") });
    ev.target.textContent = "設定してはじめる";
    if (!r.ok) return showErrors(r.data.errors);
    boot();
  });
}
const v = (id) => document.getElementById(id).value.trim();

/* ---------------- ログイン ---------------- */
function renderLogin() {
  S.view = "login";
  $app().innerHTML = `
  <div style="text-align:center;margin-top:36px">
    <img src="/static/icon-192.png" alt="" style="width:96px;height:96px;border-radius:22px;
      box-shadow:0 4px 14px rgba(13,58,125,.3)">
  </div>
  <h1 style="text-align:center">レンタル・廃棄物管理</h1>
  <div class="card">
    <label class="f">ログインID</label><input data-field="login" id="li-id" autocapitalize="none">
    <label class="f">パスワード</label><input data-field="login" id="li-pw" type="password">
    <div class="btnrow"><button class="btn" id="li-go">ログイン</button></div>
  </div>`;
  document.getElementById("li-go").onclick = (ev) => guard(ev.target, async () => {
    const r = await post("/api/login", { login_id: v("li-id"), password: v("li-pw") });
    ev.target.textContent = "ログイン";
    if (!r.ok) return showErrors(r.data.errors);
    boot();
  });
}

function renderChangePassword(first) {
  S.view = "changepw";
  $app().innerHTML = `
  <h1>${first ? "はじめに、仮パスワードを変更してください" : "パスワード変更"}</h1>
  <div class="card">
    <label class="f">現在のパスワード</label><input data-field="old_password" id="cp-old" type="password">
    <label class="f">新しいパスワード（8文字以上）</label><input data-field="new_password" id="cp-new" type="password">
    <div class="btnrow"><button class="btn green" id="cp-go">変更する</button></div>
  </div>`;
  document.getElementById("cp-go").onclick = (ev) => guard(ev.target, async () => {
    const r = await post("/api/change_password", { old_password: v("cp-old"), new_password: v("cp-new") });
    ev.target.textContent = "変更する";
    if (!r.ok) return showErrors(r.data.errors);
    boot();
  });
}

/* ---------------- 従業員ホーム ---------------- */
async function renderHome() {
  S.view = "home";
  const { data: h } = await api("/api/home");
  const now = new Date();
  const days = ["日","月","火","水","木","金","土"];
  const nowTxt = `${now.getMonth()+1}月${now.getDate()}日(${days[now.getDay()]}) ${now.getHours()}:${String(now.getMinutes()).padStart(2,"0")}`;
  $app().innerHTML = `
  <div class="homehead">
    <div class="name">${esc(h.user.display_name)} さん</div>
    <div class="sub">${nowTxt}</div>
    <div class="sub">選択中の現場：${h.last_site ? esc(h.last_site.name) : "（未選択）"}</div>
    <div class="stats">
      <div class="stat"><div class="v">${h.today_count}</div><div class="k">本日の入力</div></div>
      <div class="stat"><div class="v">${h.due_soon}</div><div class="k">返却期限間近</div></div>
      <div class="stat"><div class="v" id="draft-count">${draftCount()}</div><div class="k">下書き</div></div>
    </div>
  </div>
  <div class="btn-grid">
    <button class="bigbtn" onclick="startRental()"><span class="icn tint-blue">${icon("truck", 26)}</span>レンタル開始</button>
    <button class="bigbtn" onclick="startReturn()"><span class="icn tint-green">${icon("return", 26)}</span>レンタル返却</button>
    <button class="bigbtn" onclick="startExtend()"><span class="icn tint-orange">${icon("calplus", 26)}</span>レンタル延長</button>
    <button class="bigbtn" onclick="startWaste()"><span class="icn tint-purple">${icon("trash", 26)}</span>廃棄物を登録</button>
    <button class="bigbtn" style="grid-column:1/-1;min-height:76px;flex-direction:row"
      onclick="renderToday()"><span class="icn tint-teal">${icon("clip", 26)}</span>記録を確認する</button>
  </div>
  <button class="backlink" onclick="logout()">ログアウト</button>`;
}
async function logout() { await post("/api/logout", {}); location.reload(); }

/* ---------------- 現場選択（ステップ共通） ---------------- */
async function renderSitePick(title, stepLabel, onPick, onBack) {
  const { data: pd } = await api("/api/sites/pickdata");
  window.__sitePick = onPick;
  const row = (s, tag) => `
    <div class="item-row" onclick='__sitePick(${JSON.stringify(s).replace(/'/g,"&#39;")})'>
      <div class="grow"><div class="tt">${esc(s.name)}</div>
      <div class="sub">${esc(s.contractor || "")}</div></div>
      ${tag ? `<span class="badge">${tag}</span>` : ""}</div>`;
  const lastBlock = pd.last_site ? `
    <div class="card" style="border-color:var(--blue)">
      <div class="muted">前回の現場</div>
      <div class="tt" style="font-size:1.15rem;font-weight:800">${esc(pd.last_site.name)}</div>
      <div class="btnrow"><button class="btn green" id="sp-last">この現場でよければタップ</button></div>
    </div>` : "";
  const seen = new Set();
  const list = (arr, tag) => arr.filter(s => !seen.has(s.id) && seen.add(s.id)).map(s => row(s, tag)).join("");
  $app().innerHTML = `
  <button class="backlink" id="sp-back">← 戻る</button>
  <div class="stephead"><span class="no">${stepLabel}</span><span class="t">${title}</span></div>
  ${lastBlock}
  <input id="sp-q" placeholder="現場名・元請会社名で検索" style="margin:8px 0">
  <div id="sp-list">
    ${list(pd.recent, "最近")}
    ${list(pd.favorites, "お気に入り")}
    ${list(pd.active, "施工中")}
  </div>
  <button class="btn secondary" id="sp-new" style="margin-top:10px">＋ 新しい現場を登録</button>
  <div id="sp-new-form" class="card" style="display:none">
    <label class="f">現場名</label>
    <input id="sp-new-name" data-field="name" placeholder="例：○○公園整備工事">
    <div id="sp-similar"></div>
    <label class="f">元請会社名（任意）</label>
    <input id="sp-new-con" placeholder="例：△△建設">
    <div class="btnrow"><button class="btn green" id="sp-new-go">登録してこの現場を選ぶ</button></div>
  </div>`;
  document.getElementById("sp-back").onclick = onBack;
  document.getElementById("sp-new").onclick = () => {
    const f = document.getElementById("sp-new-form");
    f.style.display = "block";
    f.scrollIntoView({ behavior: "smooth" });
    document.getElementById("sp-new-name").focus();
  };
  // 似た名前の現場を候補表示（表記ゆれによる重複登録を防ぐ）
  document.getElementById("sp-new-name").oninput = async (e) => {
    const q = e.target.value.trim();
    const box = document.getElementById("sp-similar");
    if (q.length < 2) { box.innerHTML = ""; return; }
    const { data: sim } = await api(`/api/sites?q=${encodeURIComponent(q)}`);
    box.innerHTML = sim.length ? `
      <div class="muted" style="margin-top:6px">似た名前の現場があります。同じ現場ならタップで選択：</div>
      ${sim.slice(0, 5).map(s => `
        <div class="item-row" onclick='__sitePick(${JSON.stringify(s).replace(/'/g, "&#39;")})'>
          <div class="grow"><div class="tt">${esc(s.name)}</div>
          <div class="sub">${esc(s.contractor || "")}</div></div></div>`).join("")}` : "";
  };
  document.getElementById("sp-new-go").onclick = (ev) => guard(ev.target, async () => {
    const name = v("sp-new-name");
    const r = await post("/api/sites", { name, contractor: v("sp-new-con") });
    ev.target.textContent = "登録してこの現場を選ぶ";
    if (!r.ok) return showErrors(r.data.errors);
    onPick(r.data.site);
  });
  if (pd.last_site) document.getElementById("sp-last").onclick = () => onPick(pd.last_site);
  document.getElementById("sp-q").oninput = async (e) => {
    const q = e.target.value.trim();
    if (!q) return;
    const { data: sites } = await api(`/api/sites?q=${encodeURIComponent(q)}`);
    const { data: sites2 } = await api(`/api/sites?contractor=${encodeURIComponent(q)}`);
    const all = [...sites, ...sites2];
    const seen2 = new Set();
    document.getElementById("sp-list").innerHTML =
      all.filter(s => !seen2.has(s.id) && seen2.add(s.id)).map(s => row(s, "")).join("") ||
      "<p class='muted'>見つかりませんでした</p>";
  };
}

/* ---------------- 写真ステップ共通 ---------------- */
function photoStepHTML(photos, categories, selCat) {
  return `
  <label class="f">撮影の分類</label>
  <select id="ph-cat" data-field="category">${categories.map(c =>
    `<option ${c === selCat ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>
  <div class="btnrow">
    <button class="btn" id="ph-take">${icon("camera", 20)}　カメラで撮影</button>
    <button class="btn secondary" id="ph-pick">${icon("image", 20)}　アルバムから選ぶ</button>
  </div>
  <input type="file" id="ph-file-cam" accept="image/*" capture="environment" multiple style="display:none">
  <input type="file" id="ph-file-lib" accept="image/*,.pdf" multiple style="display:none">
  <div class="thumbs" id="ph-thumbs">${photoThumbs(photos)}</div>
  <p class="muted">連続で撮影できます。長押しではなくタップで削除・並び替えできます。</p>`;
}
function photoThumbs(photos) {
  return photos.map((p, i) => `
    <div class="thumb">
      <img src="${p.url || p.dataUrl}" alt="">
      <button class="del" data-i="${i}">✕</button>
      ${i > 0 ? `<button class="mv" data-i="${i}">←</button>` : ""}
      ${p.unsent ? `<span class="badge orange unsent">未送信</span>` : ""}
    </div>`).join("");
}
function bindPhotoStep(state, rerender) {
  const upload = async (files) => {
    for (const f of files) {
      const cat = document.getElementById("ph-cat").value;
      const fd = new FormData();
      fd.append("file", f);
      fd.append("category", cat);
      try {
        const res = await fetch("/api/photos", { method: "POST", body: fd });
        const d = await res.json();
        if (res.ok) state.photos.push({ id: d.id, url: d.url, category: cat });
        else alert((d.errors && Object.values(d.errors)[0]) || "アップロードできませんでした");
      } catch (e) {
        // 通信不可: 端末に保持し「未送信」表示（同期は写真再選択で対応）
        const dataUrl = await new Promise(r => { const fr = new FileReader(); fr.onload = () => r(fr.result); fr.readAsDataURL(f); });
        state.photos.push({ dataUrl, category: cat, unsent: true });
      }
    }
    rerender();
  };
  document.getElementById("ph-take").onclick = () => document.getElementById("ph-file-cam").click();
  document.getElementById("ph-pick").onclick = () => document.getElementById("ph-file-lib").click();
  document.getElementById("ph-file-cam").onchange = (e) => upload([...e.target.files]);
  document.getElementById("ph-file-lib").onchange = (e) => upload([...e.target.files]);
  document.getElementById("ph-thumbs").onclick = (e) => {
    const i = +e.target.dataset.i;
    if (e.target.classList.contains("del")) { state.photos.splice(i, 1); rerender(); }
    if (e.target.classList.contains("mv")) { const [p] = state.photos.splice(i, 1); state.photos.splice(i - 1, 0, p); rerender(); }
  };
}

/* ================= レンタル開始ウィザード ================= */
function startRental(resume) {
  const d = resume ? draftLoad("rental") : null;
  window.__rw = d || { step: 1, site: null, vendor: "", item: null, itemQ: "", qty: 1,
    start_date: todayStr(), due_date: "", photos: [], client_key: uid() };
  renderRentalStep();
}
function rwSave() { const w = window.__rw; draftSave("rental", { ...w, photos: w.photos.filter(p => !p.dataUrl) }); }

async function renderRentalStep() {
  const w = window.__rw;
  rwSave();
  const total = 5;
  if (w.step === 1) {
    return renderSitePick("現場を選択", `1／${total}`, (s) => { w.site = s; w.step = 2; renderRentalStep(); }, () => renderHome());
  }
  if (w.step === 2) {
    const { data: pick } = await api("/api/items/pickdata");
    window.__rwPickItem = (it) => { w.item = it; w.step = 3; renderRentalStep(); };
    const itemRow = (it, tag) => `
      <div class="item-row" onclick='__rwPickItem(${JSON.stringify(it).replace(/'/g,"&#39;")})'>
        <div class="grow"><div class="tt">${esc(it.name)}</div>
        <div class="sub">${esc(it.spec || "")} ${it.code ? "コード:" + esc(it.code) : ""}</div></div>
        ${tag ? `<span class="badge">${tag}</span>` : ""}</div>`;
    $app().innerHTML = `
    <button class="backlink" id="rw-back">← 戻る</button>
    <div class="stephead"><span class="no">2／${total}</span><span class="t">商品を選択</span></div>
    <div class="flexrow">
      <input id="rw-code" placeholder="商品コード" inputmode="latin" style="flex:1">
      <button class="btn small" id="rw-code-go">コードで探す</button>
      <button class="btn small secondary" id="rw-qr">QR読取</button>
    </div>
    <input id="rw-q" placeholder="商品名・規格で検索" style="margin:8px 0" value="${esc(w.itemQ)}">
    <div id="rw-items">
      ${pick.recent.map(i => itemRow(i, "最近")).join("")}
      ${pick.favorites.map(i => itemRow(i, "お気に入り")).join("")}
    </div>
    <button class="btn secondary" id="rw-all" style="margin-top:8px">料金表から選ぶ（全商品）</button>`;
    document.getElementById("rw-back").onclick = () => { w.step = 1; renderRentalStep(); };
    const search = async (q) => {
      const { data: items } = await api(`/api/price_master?q=${encodeURIComponent(q)}`);
      document.getElementById("rw-items").innerHTML =
        items.map(i => itemRow(i, "")).join("") || "<p class='muted'>見つかりませんでした</p>";
    };
    document.getElementById("rw-q").oninput = (e) => { w.itemQ = e.target.value.trim(); if (w.itemQ) search(w.itemQ); };
    document.getElementById("rw-all").onclick = () => search("");
    document.getElementById("rw-code-go").onclick = () => search(v("rw-code"));
    document.getElementById("rw-qr").onclick = () => qrScan((text) => { document.getElementById("rw-code").value = text; search(text); });
    return;
  }
  if (w.step === 3) {
    const it = w.item;
    $app().innerHTML = `
    <button class="backlink" id="rw-back">← 戻る</button>
    <div class="stephead"><span class="no">3／${total}</span><span class="t">数量と日付</span></div>
    <div class="card">
      <div class="tt" style="font-weight:800">${esc(it.name)} ${esc(it.spec || "")}</div>
      <div class="muted">コード: ${esc(it.code || "—")}</div>
      <table class="confirm-table" style="margin-top:6px">
        <tr><td>日割単価</td><td>${it.daily_rate == null ? "要確認" : yen(it.daily_rate)}</td></tr>
        <tr><td>月極単価</td><td>${it.monthly_rate == null ? "要確認" : yen(it.monthly_rate)}</td></tr>
        <tr><td>基本料</td><td>${it.basic_fee == null ? "要確認" : yen(it.basic_fee)}</td></tr>
        <tr><td>サポート料／日</td><td>${it.support_per_day == null ? "要確認" : yen(it.support_per_day)}</td></tr>
        <tr><td>賠償対策費／日</td><td>${it.damage_per_day == null ? "要確認" : yen(it.damage_per_day)}</td></tr>
      </table>
      <p class="muted">※ 金額は料金マスターから自動設定されます（確認表示のみ）</p>
    </div>
    <label class="f">レンタル業者</label><input id="rw-vendor" data-field="vendor_id" value="${esc(w.vendor)}" placeholder="例：アクティオ">
    <label class="f">数量（台数）</label><input id="rw-qty" data-field="qty" type="number" inputmode="numeric" min="1" value="${w.qty}">
    <label class="f">レンタル開始日</label><input id="rw-start" data-field="start_date" type="date" value="${w.start_date}">
    <label class="f">返却予定日</label><input id="rw-due" data-field="due_date" type="date" value="${w.due_date}">
    <div class="btnrow"><button class="btn" id="rw-next">次へ（写真）</button></div>`;
    document.getElementById("rw-back").onclick = () => { save3(); w.step = 2; renderRentalStep(); };
    const save3 = () => { w.vendor = v("rw-vendor"); w.qty = v("rw-qty"); w.start_date = v("rw-start"); w.due_date = v("rw-due"); };
    document.getElementById("rw-next").onclick = () => {
      save3();
      const errs = {};
      if (!w.vendor) errs.vendor_id = "レンタル業者を入力してください";
      if (!w.qty || +w.qty < 1) errs.qty = "数量は1以上で入力してください";
      if (!w.start_date) errs.start_date = "レンタル開始日を選んでください";
      if (!w.due_date) errs.due_date = "返却予定日を選んでください";
      if (w.start_date && w.due_date && w.due_date < w.start_date) errs.due_date = "返却予定日は開始日以降にしてください";
      if (Object.keys(errs).length) return showErrors(errs);
      w.step = 4; renderRentalStep();
    };
    return;
  }
  if (w.step === 4) {
    $app().innerHTML = `
    <button class="backlink" id="rw-back">← 戻る</button>
    <div class="stephead"><span class="no">4／${total}</span><span class="t">写真・伝票を追加（任意）</span></div>
    ${photoStepHTML(w.photos, ["レンタル開始", "機械全体", "管理番号", "請求書", "その他"], "レンタル開始")}
    <div class="btnrow"><button class="btn" id="rw-next">次へ（内容確認）</button></div>`;
    document.getElementById("rw-back").onclick = () => { w.step = 3; renderRentalStep(); };
    bindPhotoStep(w, () => renderRentalStep());
    document.getElementById("rw-next").onclick = () => { w.step = 5; renderRentalStep(); };
    return;
  }
  /* step 5: 確認 */
  $app().innerHTML = `
  <button class="backlink" id="rw-back">← 戻る</button>
  <div class="stephead"><span class="no">5／${total}</span><span class="t">内容確認</span></div>
  <div class="card">
    <table class="confirm-table">
      <tr><td>現場</td><td>${esc(w.site.name)}</td></tr>
      <tr><td>商品</td><td>${esc(w.item.name)} ${esc(w.item.spec || "")}</td></tr>
      <tr><td>レンタル業者</td><td>${esc(w.vendor)}</td></tr>
      <tr><td>数量</td><td>${esc(w.qty)}台</td></tr>
      <tr><td>開始日</td><td>${fmtDate(w.start_date)}</td></tr>
      <tr><td>返却予定日</td><td>${fmtDate(w.due_date)}</td></tr>
      <tr><td>写真</td><td>${w.photos.length}枚</td></tr>
    </table>
  </div>
  <div class="btnrow"><button class="btn green" id="rw-go" style="min-height:64px">この内容で登録する</button></div>`;
  document.getElementById("rw-back").onclick = () => { w.step = 4; renderRentalStep(); };
  document.getElementById("rw-go").onclick = (ev) => guard(ev.target, async () => {
    const body = { site_id: w.site.id, vendor_name: w.vendor, item_id: w.item.id, qty: +w.qty,
      start_date: w.start_date, due_date: w.due_date, client_key: w.client_key,
      photo_ids: w.photos.filter(p => p.id).map(p => p.id),
      skip_photo: !w.photos.some(p => p.id) };
    const r = await submitOrQueue("/api/rentals", body);
    ev.target.textContent = "この内容で登録する";
    if (!r.ok) return showErrors(r.data.errors);
    draftClear("rental");
    renderDone("レンタル開始を登録しました", r.queued, [
      ["同じ現場でもう1件登録", () => { startRental(); window.__rw.site = w.site; window.__rw.step = 2; renderRentalStep(); }],
      ["別の現場を登録", () => startRental()],
      ["ホームへ戻る", () => renderHome()],
    ]);
  });
}

/* QRコード読取（対応端末のみ / 非対応はコード入力を案内） */
async function qrScan(onText) {
  if (!("BarcodeDetector" in window)) {
    alert("この端末はQR読取に対応していません。商品コードを入力してください");
    return;
  }
  const input = document.createElement("input");
  input.type = "file"; input.accept = "image/*"; input.capture = "environment";
  input.onchange = async () => {
    try {
      const bmp = await createImageBitmap(input.files[0]);
      const det = new BarcodeDetector({ formats: ["qr_code", "code_128", "ean_13"] });
      const codes = await det.detect(bmp);
      if (codes.length) onText(codes[0].rawValue);
      else alert("QRコードを読み取れませんでした。もう一度撮影するか、コードを入力してください");
    } catch (e) { alert("読み取れませんでした。コードを入力してください"); }
  };
  input.click();
}

function renderDone(msg, queued, actions) {
  window.__doneActions = actions.map(a => a[1]);
  $app().innerHTML = `
  <div class="done-big"><span class="done-circle">${icon("check", 44)}</span><br>${esc(msg)}</div>
  ${queued ? `<div class="alertband">通信が弱いため端末に保存しました。「未送信」は通信回復後に自動送信されます</div>` : ""}
  <div class="btnrow" style="flex-direction:column">
    ${actions.map((a, i) => `<button class="btn ${i === 0 ? "" : "secondary"}" onclick="__doneActions[${i}]()">${esc(a[0])}</button>`).join("")}
  </div>`;
}

/* ================= レンタル返却 ================= */
function startReturn(resume) {
  const d = resume ? draftLoad("return") : null;
  window.__rt = d || { step: 1, site: null, list: [], checked: [], returned_date: todayStr(),
    flags: {}, comment: "", photos: [] };
  renderReturnStep();
}
async function renderReturnStep() {
  const w = window.__rt;
  draftSave("return", { ...w, photos: w.photos.filter(p => !p.dataUrl) });
  if (w.step === 1) {
    return renderSitePick("現場を選択", "1／4", async (s) => {
      w.site = s;
      const { data } = await api(`/api/rentals?site_id=${s.id}&status=active`);
      w.list = data; w.checked = []; w.step = 2; renderReturnStep();
    }, () => renderHome());
  }
  if (w.step === 2) {
    $app().innerHTML = `
    <button class="backlink" id="rt-back">← 戻る</button>
    <div class="stephead"><span class="no">2／4</span><span class="t">返却する商品にチェック</span></div>
    <p class="muted">${esc(w.site.name)} でレンタル中の商品だけを表示しています</p>
    <div id="rt-list">${w.list.length ? w.list.map(r => `
      <label class="item-row ${w.checked.includes(r.id) ? "sel" : ""}">
        <input type="checkbox" data-id="${r.id}" ${w.checked.includes(r.id) ? "checked" : ""}>
        <div class="grow">
          <div class="tt">${esc(r.item_name)} ${esc(r.spec || "")} × ${r.qty}</div>
          <div class="sub">開始 ${fmtDate(r.start_date)} ／ 予定 ${fmtDate(r.due_date)} ／ ${r.days_elapsed}日目</div>
        </div>
        ${r.photos.length ? `<img src="${r.photos[0].file_path}" style="width:56px;height:56px;object-fit:cover;border-radius:8px">` : ""}
      </label>`).join("") : "<p class='muted'>この現場にレンタル中の商品はありません</p>"}
    </div>
    <div class="btnrow"><button class="btn" id="rt-next">次へ（返却日）</button></div>`;
    document.getElementById("rt-back").onclick = () => { w.step = 1; renderReturnStep(); };
    document.getElementById("rt-list").onchange = (e) => {
      const id = +e.target.dataset.id;
      if (e.target.checked) w.checked.push(id); else w.checked = w.checked.filter(x => x !== id);
      renderReturnStep();
    };
    document.getElementById("rt-next").onclick = () => {
      if (!w.checked.length) return showErrors({ ids: "返却する商品を選んでください" });
      w.step = 3; renderReturnStep();
    };
    return;
  }
  if (w.step === 3) {
    const flag = (k, label) => `
      <label class="chip wide ${w.flags[k] ? "sel" : ""}"><input type="checkbox" data-k="${k}"
        ${w.flags[k] ? "checked" : ""} style="display:none">${label}</label>`;
    $app().innerHTML = `
    <button class="backlink" id="rt-back">← 戻る</button>
    <div class="stephead"><span class="no">3／4</span><span class="t">返却日と状態</span></div>
    <label class="f">実際の返却日</label>
    <input id="rt-date" data-field="returned_date" type="date" value="${w.returned_date}">
    <label class="f">状態（あてはまるものにタップ・任意）</label>
    <div class="chips" id="rt-flags">
      ${flag("broken", "故障あり")}${flag("damaged", "破損あり")}
      ${flag("dirty", "汚れあり")}${flag("missing", "不足品あり")}
    </div>
    <label class="f">コメント（任意）</label>
    <textarea id="rt-com">${esc(w.comment)}</textarea>
    <div id="rt-photo-block">${photoStepHTML(w.photos, ["レンタル返却", "機械全体", "故障・破損"], "レンタル返却")}</div>
    <div class="btnrow"><button class="btn" id="rt-next">次へ（内容確認）</button></div>`;
    document.getElementById("rt-back").onclick = () => { w.step = 2; renderReturnStep(); };
    bindPhotoStep(w, () => renderReturnStep());
    document.getElementById("rt-flags").onchange = (e) => {
      w.flags[e.target.dataset.k] = e.target.checked;
      w.returned_date = v("rt-date"); w.comment = v("rt-com");
      renderReturnStep();
    };
    document.getElementById("rt-next").onclick = () => {
      w.returned_date = v("rt-date"); w.comment = v("rt-com");
      if (!w.returned_date) return showErrors({ returned_date: "返却日を選んでください" });
      w.step = 4; renderReturnStep();
    };
    return;
  }
  /* 確認 */
  const items = w.list.filter(r => w.checked.includes(r.id));
  const flagsTxt = [w.flags.broken && "故障", w.flags.damaged && "破損", w.flags.dirty && "汚れ",
    w.flags.missing && "不足品"].filter(Boolean).join("・") || "問題なし";
  $app().innerHTML = `
  <button class="backlink" id="rt-back">← 戻る</button>
  <div class="stephead"><span class="no">4／4</span><span class="t">内容確認</span></div>
  <div class="card">
    <table class="confirm-table">
      <tr><td>現場</td><td>${esc(w.site.name)}</td></tr>
      <tr><td>返却する商品</td><td>${items.map(r => esc(r.item_name) + " × " + r.qty).join("<br>")}</td></tr>
      <tr><td>返却日</td><td>${fmtDate(w.returned_date)}</td></tr>
      <tr><td>状態</td><td>${flagsTxt}</td></tr>
      <tr><td>写真</td><td>${w.photos.length}枚</td></tr>
    </table>
  </div>
  <div class="btnrow"><button class="btn green" id="rt-go" style="min-height:64px">返却を登録する</button></div>`;
  document.getElementById("rt-back").onclick = () => { w.step = 3; renderReturnStep(); };
  document.getElementById("rt-go").onclick = (ev) => guard(ev.target, async () => {
    const r = await submitOrQueue("/api/rentals/return", {
      ids: w.checked, returned_date: w.returned_date, condition_flags: w.flags,
      comment: w.comment, photo_ids: w.photos.filter(p => p.id).map(p => p.id) });
    ev.target.textContent = "返却を登録する";
    if (!r.ok) return showErrors(r.data.errors);
    draftClear("return");
    renderDone("返却を登録しました", r.queued, [["ホームへ戻る", () => renderHome()],
      ["続けて返却を登録", () => startReturn()]]);
  });
}

/* ================= レンタル延長 ================= */
function startExtend() {
  window.__ex = { step: 1, site: null, rental: null, new_due: "", reason: "", comment: "", estimate: null };
  renderExtendStep();
}
async function renderExtendStep() {
  const w = window.__ex;
  draftSave("extend", w);
  if (w.step === 1) {
    return renderSitePick("現場を選択", "1／3", async (s) => {
      w.site = s;
      const { data } = await api(`/api/rentals?site_id=${s.id}&status=active`);
      w.list = data; w.step = 2; renderExtendStep();
    }, () => renderHome());
  }
  if (w.step === 2) {
    window.__exPick = (r) => { w.rental = r; w.step = 3; renderExtendStep(); };
    $app().innerHTML = `
    <button class="backlink" id="ex-back">← 戻る</button>
    <div class="stephead"><span class="no">2／3</span><span class="t">延長する商品を選択</span></div>
    ${w.list.length ? w.list.map(r => `
      <div class="item-row" onclick='__exPick(${JSON.stringify(r).replace(/'/g,"&#39;")})'>
        <div class="grow"><div class="tt">${esc(r.item_name)} × ${r.qty}</div>
        <div class="sub">返却予定 ${fmtDate(r.due_date)}（${r.days_elapsed}日目）</div></div></div>`).join("")
      : "<p class='muted'>この現場にレンタル中の商品はありません</p>"}`;
    document.getElementById("ex-back").onclick = () => { w.step = 1; renderExtendStep(); };
    return;
  }
  const reasons = S.meta.extension_reasons;
  $app().innerHTML = `
  <button class="backlink" id="ex-back">← 戻る</button>
  <div class="stephead"><span class="no">3／3</span><span class="t">新しい返却予定日</span></div>
  <div class="card"><div class="tt" style="font-weight:800">${esc(w.rental.item_name)} × ${w.rental.qty}</div>
    <div class="muted">現在の返却予定日：${fmtDate(w.rental.due_date)}</div></div>
  <label class="f">新しい返却予定日</label>
  <input id="ex-due" data-field="new_due" type="date" value="${w.new_due}">
  <label class="f">延長理由</label>
  <div class="chips" id="ex-reasons">${reasons.map(r =>
    `<button class="chip ${w.reason === r ? "sel" : ""}" data-r="${esc(r)}">${esc(r)}</button>`).join("")}</div>
  <div id="ex-com-block" style="display:${w.reason === "その他" ? "block" : "none"}">
    <label class="f">理由の内容</label><textarea id="ex-com" data-field="comment">${esc(w.comment)}</textarea>
  </div>
  <div id="ex-est">${w.estimate ? estimateHTML(w.estimate) : ""}</div>
  <div class="btnrow"><button class="btn green" id="ex-go">延長を登録する</button></div>`;
  document.getElementById("ex-back").onclick = () => { w.step = 2; renderExtendStep(); };
  document.getElementById("ex-reasons").onclick = (e) => {
    if (!e.target.dataset.r) return;
    w.reason = e.target.dataset.r; w.new_due = v("ex-due");
    renderExtendStep();
  };
  document.getElementById("ex-due").onchange = async (e) => {
    w.new_due = e.target.value;
    if (w.new_due) {
      const { data } = await api(`/api/rentals/${w.rental.id}/estimate?end=${w.new_due}`);
      w.estimate = data.estimate;
      document.getElementById("ex-est").innerHTML = estimateHTML(w.estimate);
    }
  };
  document.getElementById("ex-go").onclick = (ev) => guard(ev.target, async () => {
    w.new_due = v("ex-due");
    w.comment = w.reason === "その他" ? v("ex-com") : "";
    const r = await submitOrQueue(`/api/rentals/${w.rental.id}/extend`,
      { new_due: w.new_due, reason: w.reason || null, comment: w.comment });
    ev.target.textContent = "延長を登録する";
    if (!r.ok) return showErrors(r.data.errors);
    draftClear("extend");
    renderDone("延長を登録しました", r.queued, [["ホームへ戻る", () => renderHome()]]);
  });
}
function estimateHTML(est) {
  if (!est) return "";
  return `<div class="card"><div class="muted">延長後の概算金額（自動計算・変更できません）</div>
    <div style="font-size:1.4rem;font-weight:800">${yen(est.total)}（${est.days}日間）</div>
    <div class="muted">レンタル料 ${yen(est.rental)} ／ 基本料 ${yen(est.basic)} ／
    サポート料 ${yen(est.support)} ／ 賠償対策費 ${yen(est.damage)}</div></div>`;
}

/* ================= 廃棄物登録 ================= */
function startWaste(resume) {
  const d = resume ? draftLoad("waste") : null;
  window.__ws = d || { step: 1, site: null, out_date: todayStr(), waste_type: "", qty: "",
    unit: "", hauler: "", disposal: "", slip_no: "", photos: [], client_key: uid() };
  renderWasteStep();
}
async function renderWasteStep() {
  const w = window.__ws;
  draftSave("waste", { ...w, photos: w.photos.filter(p => !p.dataUrl) });
  const total = 5;
  if (w.step === 1) {
    return renderSitePick("現場を選択", `1／${total}`, async (s) => {
      w.site = s;
      const { data: def } = await api(`/api/waste/defaults?site_id=${s.id}`);
      if (def.hauler_id && !w.hauler) w.hauler = def.hauler_id.name;
      if (def.disposal_id && !w.disposal) w.disposal = def.disposal_id.name;
      w.step = 2; renderWasteStep();
    }, () => renderHome());
  }
  if (w.step === 2) {
    const top = S.meta.waste_types_top;
    const rest = S.meta.waste_types.filter(t => !top.includes(t));
    const chip = (t) => `<button class="chip wide ${w.waste_type === t ? "sel" : ""}" data-t="${esc(t)}">${esc(t)}</button>`;
    $app().innerHTML = `
    <button class="backlink" id="ws-back">← 戻る</button>
    <div class="stephead"><span class="no">2／${total}</span><span class="t">廃棄物の種類を選択</span></div>
    <div class="muted">よく使う品目</div>
    <div class="chips" id="ws-types-top">${top.map(chip).join("")}</div>
    <div class="muted">その他の品目</div>
    <div class="chips" id="ws-types">${rest.map(chip).join("")}</div>`;
    document.getElementById("ws-back").onclick = () => { w.step = 1; renderWasteStep(); };
    const pick = (e) => { if (!e.target.dataset.t) return; w.waste_type = e.target.dataset.t; w.step = 3; renderWasteStep(); };
    document.getElementById("ws-types-top").onclick = pick;
    document.getElementById("ws-types").onclick = pick;
    return;
  }
  if (w.step === 3) {
    $app().innerHTML = `
    <button class="backlink" id="ws-back">← 戻る</button>
    <div class="stephead"><span class="no">3／${total}</span><span class="t">数量と業者</span></div>
    <div class="card"><div class="tt" style="font-weight:800">${esc(w.waste_type)}</div></div>
    <label class="f">搬出日</label><input id="ws-date" data-field="out_date" type="date" value="${w.out_date}">
    <label class="f">数量</label><input id="ws-qty" data-field="qty" type="number" inputmode="decimal" step="any" value="${esc(w.qty)}">
    <label class="f">単位</label>
    <div class="chips" id="ws-units" data-field="unit">${S.meta.waste_units.map(u =>
      `<button class="chip ${w.unit === u ? "sel" : ""}" data-u="${esc(u)}">${esc(u)}</button>`).join("")}</div>
    <label class="f">運搬業者</label><input id="ws-hauler" data-field="hauler_id" value="${esc(w.hauler)}" placeholder="前回の業者が自動で入ります">
    <label class="f">処分先</label><input id="ws-disposal" data-field="disposal_id" value="${esc(w.disposal)}" placeholder="前回の処分先が自動で入ります">
    <div class="btnrow"><button class="btn" id="ws-next">次へ（写真）</button></div>`;
    document.getElementById("ws-back").onclick = () => { save(); w.step = 2; renderWasteStep(); };
    const save = () => { w.out_date = v("ws-date"); w.qty = v("ws-qty"); w.hauler = v("ws-hauler"); w.disposal = v("ws-disposal"); };
    document.getElementById("ws-units").onclick = (e) => {
      if (!e.target.dataset.u) return;
      save(); w.unit = e.target.dataset.u; renderWasteStep();
    };
    document.getElementById("ws-next").onclick = () => {
      save();
      const errs = {};
      if (!w.out_date) errs.out_date = "搬出日を選んでください";
      if (!w.qty || +w.qty <= 0) errs.qty = "数量は0より大きい値で入力してください";
      if (!w.unit) errs.unit = "単位を選んでください";
      if (!w.hauler) errs.hauler_id = "運搬業者を入力してください";
      if (!w.disposal) errs.disposal_id = "処分先を入力してください";
      if (Object.keys(errs).length) return showErrors(errs);
      w.step = 4; renderWasteStep();
    };
    return;
  }
  if (w.step === 4) {
    $app().innerHTML = `
    <button class="backlink" id="ws-back">← 戻る</button>
    <div class="stephead"><span class="no">4／${total}</span><span class="t">写真・伝票を追加（任意）</span></div>
    ${photoStepHTML(w.photos, ["廃棄物積込前", "積込中", "積込後", "処分場", "計量票", "マニフェスト", "その他"], "計量票")}
    <label class="f">伝票番号（任意）</label><input id="ws-slip" value="${esc(w.slip_no)}">
    <div class="btnrow"><button class="btn" id="ws-next">次へ（内容確認）</button></div>`;
    document.getElementById("ws-back").onclick = () => { w.slip_no = v("ws-slip"); w.step = 3; renderWasteStep(); };
    bindPhotoStep(w, () => renderWasteStep());
    document.getElementById("ws-next").onclick = () => {
      w.slip_no = v("ws-slip");
      w.step = 5; renderWasteStep();
    };
    return;
  }
  /* 確認 */
  $app().innerHTML = `
  <button class="backlink" id="ws-back">← 戻る</button>
  <div class="stephead"><span class="no">5／${total}</span><span class="t">内容確認</span></div>
  <div class="card">
    <table class="confirm-table">
      <tr><td>現場</td><td>${esc(w.site.name)}</td></tr>
      <tr><td>搬出日</td><td>${fmtDate(w.out_date)}</td></tr>
      <tr><td>種類</td><td>${esc(w.waste_type)}</td></tr>
      <tr><td>数量</td><td>${esc(w.qty)} ${esc(w.unit)}</td></tr>
      <tr><td>運搬業者</td><td>${esc(w.hauler)}</td></tr>
      <tr><td>処分先</td><td>${esc(w.disposal)}</td></tr>
      <tr><td>写真</td><td>${w.photos.length}枚</td></tr>
    </table>
  </div>
  <div class="btnrow"><button class="btn green" id="ws-go" style="min-height:64px">この内容で登録する</button></div>`;
  document.getElementById("ws-back").onclick = () => { w.step = 4; renderWasteStep(); };
  document.getElementById("ws-go").onclick = (ev) => guard(ev.target, async () => {
    const r = await submitOrQueue("/api/waste", {
      site_id: w.site.id, out_date: w.out_date, waste_type: w.waste_type, qty: +w.qty,
      unit: w.unit, hauler_name: w.hauler, disposal_name: w.disposal, slip_no: w.slip_no,
      client_key: w.client_key, photo_ids: w.photos.filter(p => p.id).map(p => p.id),
      skip_photo: !w.photos.some(p => p.id) });
    ev.target.textContent = "この内容で登録する";
    if (!r.ok) return showErrors(r.data.errors);
    draftClear("waste");
    renderDone("廃棄物を登録しました", r.queued, [
      ["同じ現場でもう1件登録", () => { startWaste(); window.__ws.site = w.site; window.__ws.step = 2; renderWasteStep(); }],
      ["ホームへ戻る", () => renderHome()],
    ]);
  });
}

/* ================= 記録の確認 ================= */
async function renderToday() {
  const [{ data: rentals }, { data: waste }] = await Promise.all([
    api("/api/rentals?mine=1"), api("/api/waste")]);
  const drafts = ["rental", "return", "extend", "waste"].filter(k => draftLoad(k));
  const draftLabel = { rental: "レンタル開始（入力途中）", return: "レンタル返却（入力途中）",
    extend: "レンタル延長（入力途中）", waste: "廃棄物登録（入力途中）" };
  const resume = { rental: () => startRental(true), return: () => startReturn(true),
    extend: () => startExtend(), waste: () => startWaste(true) };
  window.__resume = resume;
  window.__delRec = async (type, id, label) => {
    if (!confirm(`「${label}」の記録を削除しますか？`)) return;
    const url = type === "rental" ? `/api/rentals/${id}` : `/api/waste/${id}`;
    const r = await api(url, { method: "DELETE" });
    if (r.ok) renderToday();
  };
  $app().innerHTML = `
  <button class="backlink" onclick="renderHome()">← ホームへ</button>
  <h1>記録を確認</h1>
  ${drafts.length ? `<h2>入力途中の下書き</h2>${drafts.map(k => `
    <div class="item-row" onclick="__resume['${k}']()"><div class="grow">
      <div class="tt">${draftLabel[k]}</div><div class="sub">タップして続きから入力</div></div>
      <span class="badge orange">下書き</span></div>`).join("")}` : ""}
  <h2>レンタル（${rentals.length}件）</h2>
  ${rentals.slice(0, 30).map(r => `<div class="item-row"><div class="grow">
    <div class="tt">${esc(r.item_name)} × ${r.qty}（${esc(r.site_name)}）</div>
    <div class="sub">${fmtDate(r.start_date)} 〜 ${fmtDate(r.returned_date || r.due_date)}
      ${r.status === "returned" ? "／ 返却済み" : "／ レンタル中"}</div></div>
    <button class="btn small red" onclick="__delRec('rental',${r.id},'${esc(r.item_name)}')">削除</button></div>`).join("") ||
    "<p class='muted'>まだありません</p>"}
  <h2>廃棄物（${waste.length}件）</h2>
  ${waste.slice(0, 30).map(x => `<div class="item-row"><div class="grow">
    <div class="tt">${esc(x.waste_type)} ${x.qty}${esc(x.unit)}（${esc(x.site_name)}）</div>
    <div class="sub">搬出日 ${fmtDate(x.out_date)} ／ ${esc(x.disposal_name || "")}</div></div>
    <button class="btn small red" onclick="__delRec('waste',${x.id},'${esc(x.waste_type)}')">削除</button></div>`).join("") ||
    "<p class='muted'>まだありません</p>"}`;
}

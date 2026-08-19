/* KI-LEAGUE 対戦表・スコアシート（画面まわり） */
"use strict";

const S = {
  view: "matches", tab: "members", side: "home",
  meta: null, teams: [], matches: [], match: null, standings: null,
  teamId: null, players: [], preview: null,
  opts: { objective: "points", avoid_consecutive: true, min_games: "", max_games: "", seed: 1 },
};
const CIRCLE = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩", "⑪", "⑫", "⑬"];
const $app = () => document.getElementById("app");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (p) => Math.round(p * 100) + "%";
const num1 = (v) => (Math.round(v * 10) / 10).toFixed(1);
const todayStr = () => new Date().toISOString().slice(0, 10);

/* ---------------- 通信 ---------------- */
async function api(path, opt = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opt });
  let data = null;
  try { data = await res.json(); } catch (e) { /* CSVなど */ }
  if (!res.ok) { toast((data && data.error) || "うまくいきませんでした"); return null; }
  return data;
}
const get = (p) => api(p);
const post = (p, b) => api(p, { method: "POST", body: JSON.stringify(b || {}) });
const put = (p, b) => api(p, { method: "PUT", body: JSON.stringify(b || {}) });
const del = (p) => api(p, { method: "DELETE" });

/* 更新は1件ずつ順番に送る。速く連打しても前の結果を上書きしない。 */
let queueChain = Promise.resolve();
function queue(fn) {
  queueChain = queueChain.then(fn).catch((e) => console.error(e));
  return queueChain;
}

let toastTimer = null;
function toast(msg) {
  document.querySelectorAll(".toast").forEach((n) => n.remove());
  const d = document.createElement("div");
  d.className = "toast";
  d.textContent = msg;
  document.body.appendChild(d);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => d.remove(), 2600);
}

/* ---------------- 起動 ---------------- */
async function boot() {
  S.meta = await get("/api/meta");
  await loadTeams();
  await loadMatches();
  $app().addEventListener("click", onClick);
  $app().addEventListener("change", onChange);
  render();
}
async function loadTeams() {
  const d = await get("/api/teams");
  S.teams = (d && d.teams) || [];
  if (!S.teamId && S.teams.length) S.teamId = S.teams[0].id;
}
async function loadMatches() {
  const d = await get("/api/matches");
  S.matches = (d && d.matches) || [];
}
async function loadMatch(id) {
  const d = await get(`/api/matches/${id}`);
  if (d) { S.match = d; S.preview = null; }
}
async function loadPlayers(teamId) {
  const d = await get(`/api/teams/${teamId}/players`);
  S.players = (d && d.players) || [];
}

/* ---------------- 画面切り替え ---------------- */
function render() {
  const tabs = [["matches", "対戦"], ["teams", "チーム・選手"], ["standings", "成績"]];
  const nav = tabs.map(([v, label]) =>
    `<button data-act="view" data-view="${v}" class="${S.view === v ? "on" : ""}">${label}</button>`).join("");
  const head = `<div class="head">
      <div class="logo">Ki</div>
      <div><h1>KI-LEAGUE 対戦表</h1>
      <div class="sub">DARTS BAR ITSUKI OFFICIAL DARTS LEAGUE</div></div>
    </div><nav class="tabs">${nav}</nav>`;
  let body = "";
  if (S.view === "matches") body = viewMatches();
  else if (S.view === "teams") body = viewTeams();
  else if (S.view === "standings") body = viewStandings();
  else if (S.view === "match") body = viewMatch();
  $app().innerHTML = head + body;
}

/* ---------------- 対戦一覧 ---------------- */
function teamOptions(sel, blank) {
  return (blank ? `<option value="">${blank}</option>` : "") + S.teams.map((t) =>
    `<option value="${t.id}" ${String(sel) === String(t.id) ? "selected" : ""}>${esc(t.name)}</option>`).join("");
}

function viewMatches() {
  if (!S.teams.length) {
    return `<div class="card"><p class="empty">まず「チーム・選手」でチームと選手を登録してください。</p></div>`;
  }
  const list = S.matches.length ? S.matches.map((m) => `
    <div class="card spread" data-act="open" data-id="${m.id}" style="cursor:pointer">
      <div>
        <b>${esc(m.home_team_name)} vs ${esc(m.away_team_name)}</b>
        <div class="muted">${m.section ? `第${esc(m.section)}節 / ` : ""}${esc(m.match_date || "")}</div>
      </div>
      <div style="text-align:right">
        <b style="font-size:1.2rem">${m.home_wins} - ${m.away_wins}</b>
        <div class="muted">${m.played}/${m.games} 試合</div>
      </div>
    </div>`).join("") : `<p class="empty">まだ対戦がありません。下から作ってください。</p>`;
  return `${list}
    <div class="card">
      <h2>新しい対戦をつくる</h2>
      <div class="inline-fields">
        <label class="field">節<input id="m-section" type="text" inputmode="numeric" placeholder="1"></label>
        <label class="field">日付<input id="m-date" type="date" value="${todayStr()}"></label>
        <label class="field">HOME（自分たち）<select id="m-home">${teamOptions(S.teamId)}</select></label>
        <label class="field">AWAY（登録済み）<select id="m-away">${teamOptions("", "— 未登録の相手 —")}</select></label>
        <label class="field">AWAY名（未登録のとき）<input id="m-awayname" type="text" placeholder="相手チーム名"></label>
        <label class="field">相手の想定Rt<input id="m-awayrt" type="number" step="0.1" min="1" max="20" placeholder="8"></label>
      </div>
      <button class="btn primary" data-act="create-match">この内容で作成</button>
      <p class="muted">相手が未登録でも、想定レーティングを入れれば勝率の計算とオーダー自動編成ができます。</p>
    </div>`;
}

/* ---------------- チーム・選手 ---------------- */
function viewTeams() {
  const rows = S.players.map((p) => `
    <tr>
      <td><input data-pid="${p.id}" data-f="name" value="${esc(p.name)}" style="width:100%;border:none"></td>
      <td><input data-pid="${p.id}" data-f="rating" type="number" step="0.1" min="1" max="20"
          value="${p.input_rating ?? ""}" placeholder="${p.rating}" style="width:64px;border:none"></td>
      <td><input data-pid="${p.id}" data-f="ppd" type="number" step="0.01"
          value="${p.ppd ?? ""}" placeholder="${p.est_ppd}" style="width:70px;border:none"></td>
      <td><input data-pid="${p.id}" data-f="mpr" type="number" step="0.01"
          value="${p.mpr ?? ""}" placeholder="${p.est_mpr}" style="width:64px;border:none"></td>
      <td class="num">${p.skill_01} / ${p.skill_cricket}</td>
      <td><button class="btn small" data-act="del-player" data-id="${p.id}">削除</button></td>
    </tr>`).join("");
  const team = S.teams.find((t) => t.id === S.teamId);
  return `
    <div class="card">
      <div class="row">
        <label class="field grow">チーム<select id="t-sel">${teamOptions(S.teamId)}</select></label>
        <button class="btn small" data-act="del-team">チーム削除</button>
      </div>
      <div class="row">
        <input id="t-name" placeholder="新しいチーム名" style="flex:1;min-height:44px;padding:8px 10px;border:1px solid var(--line);border-radius:8px">
        <button class="btn" data-act="add-team">チーム追加</button>
      </div>
    </div>
    <div class="card">
      <h2>${esc(team ? team.name : "")} の選手${team && team.avg_rating ? `（平均Rt ${team.avg_rating}）` : ""}</h2>
      <p class="muted">レーティング(Rt)だけでも、PPD/MPRだけでも構いません。入れた方から自動で換算します。
        空欄の欄は薄い字が推定値です。数字を変えたら「保存」を押してください。</p>
      <table class="data">
        <tr><th>名前</th><th>Rt</th><th>PPD</th><th>MPR</th><th class="num">01/CR実力</th><th></th></tr>
        ${rows || `<tr><td colspan="6" class="muted">選手がいません</td></tr>`}
      </table>
      <div class="row" style="margin-top:8px">
        <button class="btn dark" data-act="save-players">保存</button>
      </div>
      <h3>選手を追加</h3>
      <div class="inline-fields">
        <label class="field">名前<input id="p-name" type="text" placeholder="山田"></label>
        <label class="field">Rt<input id="p-rating" type="number" step="0.1" min="1" max="20"></label>
        <label class="field">PPD<input id="p-ppd" type="number" step="0.01"></label>
        <label class="field">MPR<input id="p-mpr" type="number" step="0.01"></label>
      </div>
      <button class="btn primary" data-act="add-player">追加する</button>
    </div>`;
}

/* ---------------- 成績 ---------------- */
function viewStandings() {
  const st = S.standings;
  if (!st) return `<div class="card"><p class="empty">読み込み中…</p></div>`;
  const teams = st.teams.map((t, i) => `<tr><td>${i + 1}</td><td>${esc(t.name)}</td>
    <td class="num">${t.matches}</td><td class="num">${t.won}-${t.lost}</td>
    <td class="num">${t.game_wins}-${t.game_losses}</td><td class="num"><b>${t.points}</b></td></tr>`).join("");
  const players = st.players.filter((p) => p.games).map((p) => `<tr><td>${esc(p.name)}</td>
    <td class="num">${p.rating}</td><td class="num">${p.games}</td>
    <td class="num">${p.wins}-${p.losses}</td>
    <td class="num">${p.win_rate === null ? "—" : pct(p.win_rate)}</td></tr>`).join("");
  return `<div class="card"><h2>チーム順位（合計ポイント）</h2>
      <table class="data"><tr><th>#</th><th>チーム</th><th class="num">節</th><th class="num">節の勝敗</th>
      <th class="num">試合勝敗</th><th class="num">Pt</th></tr>
      ${teams || `<tr><td colspan="6" class="muted">まだ結果がありません</td></tr>`}</table></div>
    <div class="card"><h2>選手成績</h2>
      <table class="data"><tr><th>選手</th><th class="num">Rt</th><th class="num">出場</th>
      <th class="num">勝敗</th><th class="num">勝率</th></tr>
      ${players || `<tr><td colspan="5" class="muted">まだ結果がありません</td></tr>`}</table></div>`;
}

/* ---------------- 対戦の詳細 ---------------- */
function viewMatch() {
  const d = S.match;
  if (!d) return "";
  const m = d.match, t = d.totals;
  const tabs = [["members", "参加メンバー"], ["auto", "自動オーダー"], ["sheet", "スコアシート"],
                ["games", "試合ごと入力"]];
  const sub = tabs.map(([v, l]) =>
    `<button data-act="tab" data-tab="${v}" class="${S.tab === v ? "on" : ""}">${l}</button>`).join("");
  let body = "";
  if (S.tab === "members") body = tabMembers();
  else if (S.tab === "auto") body = tabAuto();
  else if (S.tab === "sheet") body = tabSheet();
  else body = tabGames();
  return `
    <div class="card no-print">
      <div class="spread">
        <div>
          <b>${esc(m.home_team_name)} vs ${esc(m.away_team_name)}</b>
          <div class="muted">${m.section ? `第${esc(m.section)}節 / ` : ""}${esc(m.match_date || "")}</div>
        </div>
        <div style="text-align:right">
          <b style="font-size:1.3rem">${t.home_points} - ${t.away_points}</b>
          <div class="muted">${t.home_wins}勝${t.away_wins}敗</div>
        </div>
      </div>
      <div class="row" style="margin-top:8px">
        <button class="btn small" data-act="back">一覧へ</button>
        <button class="btn small" data-act="print">印刷</button>
        <a class="btn small" href="/api/matches/${m.id}/csv">CSV</a>
        <button class="btn small" data-act="del-match">この対戦を削除</button>
      </div>
    </div>
    <nav class="tabs no-print">${sub}</nav>${body}`;
}

function rosterOf(side) { return side === "home" ? S.match.home_roster : S.match.away_roster; }

function tabMembers() {
  const d = S.match, m = d.match;
  const teamId = S.side === "home" ? m.home_team_id : m.away_team_id;
  const chosen = rosterOf(S.side).map((p) => p.id);
  const pool = (S.pool && S.pool.side === S.side) ? S.pool.players : null;
  const sideBtns = `<div class="row">
      <button class="btn small ${S.side === "home" ? "dark" : ""}" data-act="side" data-side="home">HOME ${esc(m.home_team_name)}</button>
      <button class="btn small ${S.side === "away" ? "dark" : ""}" data-act="side" data-side="away">AWAY ${esc(m.away_team_name)}</button>
    </div>`;
  if (!teamId) {
    return `<div class="card">${sideBtns}
      <p class="muted" style="margin-top:8px">この相手は未登録チームです。想定レーティングだけ設定できます。</p>
      <label class="field">相手の想定Rt（1〜20）
        <input id="away-rt" type="number" step="0.1" min="1" max="20" value="${m.away_rating ?? ""}" placeholder="8"></label>
      <button class="btn primary" data-act="save-awayrt">保存</button></div>`;
  }
  const cards = (pool || []).map((p) => {
    const idx = chosen.indexOf(p.id);
    return `<div class="pcard ${idx >= 0 ? "on" : ""}" data-act="member" data-id="${p.id}">
        ${idx >= 0 ? `<span class="slot">${CIRCLE[idx] || idx + 1}</span>` : ""}
        <div class="nm">${esc(p.name)}</div>
        <div class="muted">Rt ${p.rating} / 01 ${p.skill_01} ・ CR ${p.skill_cricket}</div>
      </div>`;
  }).join("");
  const need = S.meta.total_slots;
  return `<div class="card">${sideBtns}
      <h2>参加メンバー（${chosen.length}人 / 最大10人）</h2>
      <p class="muted">押した順に①②③…の枠へ入ります。13試合で必要な出場枠は のべ${need}人分。
        ${chosen.length ? `いまの人数だと1人あたり約${num1(need / chosen.length)}試合です。`
          : "4人以上（⑦⑧を4人制で行う場合）選んでください。"}</p>
      <div class="plist">${cards || `<p class="empty">このチームに選手がいません</p>`}</div>
    </div>`;
}

function tabAuto() {
  const o = S.opts;
  const objOpts = Object.entries(S.meta.objectives).map(([k, v]) =>
    `<option value="${k}" ${o.objective === k ? "selected" : ""}>${esc(v)}</option>`).join("");
  const r = S.preview;
  const sideBtns = `<div class="row">
      <button class="btn small ${S.side === "home" ? "dark" : ""}" data-act="side" data-side="home">HOME</button>
      <button class="btn small ${S.side === "away" ? "dark" : ""}" data-act="side" data-side="away">AWAY</button>
    </div>`;
  const table = r ? `
    <table class="data">
      <tr><th>No</th><th>GAME</th><th>人数</th><th>出場</th><th class="num">予想勝率</th><th>判定</th></tr>
      ${r.games.map((g) => {
        const info = S.match.games.find((x) => x.game_no === g.game_no);
        return `<tr><td>${CIRCLE[g.game_no - 1] || g.game_no}</td>
          <td>${esc(info.name)}</td>
          <td>${g.mode}(${g.size})</td>
          <td>${g.players.map((p) => esc(p.name)).join("・")}</td>
          <td class="num">${pct(g.win_prob)}</td>
          <td><span class="pill tag-${g.tag}">${g.tag}</span></td></tr>`;
      }).join("")}
    </table>
    <h3>出場数</h3>
    <div class="chips">${r.counts.map((c) => `<span class="chip">${esc(c.name)} ${c.games}</span>`).join("")}</div>
    ${r.warnings.map((w) => `<p class="muted">※ ${esc(w)}</p>`).join("")}
    <div class="row" style="margin-top:10px">
      <button class="btn primary" data-act="auto-apply">この編成で決定</button>
      <button class="btn" data-act="auto-run">組み直す</button>
    </div>` : `<p class="muted">「オーダーを組む」を押すと、参加メンバーから自動で13試合分を割り振ります。</p>`;
  const stats = r ? `<div class="stats">
      <div class="stat"><b>${num1(r.expected_wins)}</b><span>期待勝ち星</span></div>
      <div class="stat"><b>${pct(r.match_win_prob)}</b><span>節に勝つ確率</span></div>
      <div class="stat"><b>${num1(r.expected_points)}</b><span>期待合計ポイント</span></div>
    </div><div class="bar" style="margin:8px 0"><i style="width:${pct(r.match_win_prob)}"></i></div>` : "";
  return `<div class="card">${sideBtns}
      <h2>オーダー自動編成</h2>
      <div class="inline-fields">
        <label class="field">なにを重視するか<select id="o-obj">${objOpts}</select></label>
        <label class="field">1人の最少出場<input id="o-min" type="number" min="0" max="13" value="${o.min_games}" placeholder="自動"></label>
        <label class="field">1人の最多出場<input id="o-max" type="number" min="1" max="13" value="${o.max_games}" placeholder="自動"></label>
      </div>
      <label class="row"><input id="o-consec" type="checkbox" ${o.avoid_consecutive ? "checked" : ""}>
        <span>連続する試合に続けて出さない</span></label>
      <label class="row"><input id="o-trios" type="checkbox" ${trios() ? "checked" : ""}>
        <span>⑦⑧をトリオス(3人)にする</span></label>
      <div class="row" style="margin:10px 0">
        <button class="btn dark" data-act="auto-run">オーダーを組む</button>
        <button class="btn" data-act="auto-shuffle">別の案を出す</button>
      </div>
      <p class="muted">勝てる試合・捨て試合を見分けて、勝ち星と「節に勝つ確率」がいちばん高くなる並びを探します。
        くじの試合(⑤⑩)はランダム、鍵付き(固定)と結果入力済みの試合はそのままにします。</p>
      ${stats}${table}
    </div>`;
}

function trios() {
  const g7 = S.match.games.find((g) => g.game_no === 7);
  return g7 && g7.mode === "T";
}

/* 紙のスコアシートと同じ並びの表 */
function tabSheet() {
  const d = S.match, m = d.match, t = d.totals;
  const home = d.home_roster, away = d.away_roster;
  const slot = (list, i) => list[i] || null;
  const noCell = (i) => `<th class="slot-no">${CIRCLE[i]}</th>`;
  const nameCell = (list, i) => {
    const p = slot(list, i);
    // 紙のシートと同じく、細い列に名前を縦書きする（1文字ずつ改行）
    const vert = p ? [...p.name].slice(0, 7).map(esc).join("<br>") : "";
    return `<th class="slot-h" title="${esc(p ? p.name : "")}"><div class="nm-v">${vert}</div></th>`;
  };
  const homeSlots = [...Array(10).keys()].reverse();
  const awaySlots = [...Array(10).keys()];
  const homeNos = homeSlots.map(noCell).join("");
  const awayNos = awaySlots.map(noCell).join("");
  const homeNames = homeSlots.map((i) => nameCell(home, i)).join("");
  const awayNames = awaySlots.map((i) => nameCell(away, i)).join("");
  const cell = (g, side, list, i) => {
    const p = slot(list, i);
    if (!p) return `<td></td>`;
    const on = g[side].find((x) => x.player_id === p.id);
    return `<td class="cell ${on ? "on" : ""} ${on && on.locked ? "lock" : ""}"
      data-act="cell" data-g="${g.game_no}" data-side="${side}" data-id="${p.id}">${on ? "●" : ""}</td>`;
  };
  const wl = (g, side) => {
    const cls = g.winner === side ? "w" : g.winner ? "l" : "";
    const mark = g.winner === side ? "○" : g.winner ? "×" : "";
    return `<td class="wl ${cls}" data-act="wl" data-g="${g.game_no}" data-side="${side}">${mark}</td>`;
  };
  const rows = d.games.map((g) => `<tr>
      ${[...Array(10).keys()].reverse().map((i) => cell(g, "home", home, i)).join("")}
      ${wl(g, "home")}
      <td>${CIRCLE[g.game_no - 1] || g.game_no}</td>
      <td class="gname">${esc(g.name)}</td>
      <td class="gmeta" ${g.alt_mode ? `data-act="mode" data-g="${g.game_no}" style="cursor:pointer"` : ""}>
        ${g.mode}${g.alt_mode ? "*" : ""}</td>
      <td class="gmeta">${g.rounds}R</td>
      <td class="gmeta">${g.coins}</td>
      ${wl(g, "away")}
      ${[...Array(10).keys()].map((i) => cell(g, "away", away, i)).join("")}
    </tr>`).join("");
  const totalRow = (label, h, a) => `<tr class="total">
      <td colspan="10"></td><td>${h}</td><td colspan="5">${label}</td><td>${a}</td><td colspan="10"></td></tr>`;
  return `<div class="card">
    <div class="sheet-wrap">
      <table class="sheet">
        <tr>
          <th class="side" colspan="10">HOME TEAM: ${esc(m.home_team_name)}</th>
          <th class="side" rowspan="3">勝敗</th>
          <th class="side" colspan="5">
            第<input value="${esc(m.section)}" data-f="section" style="width:34px;text-align:center">節
            ${esc(m.match_date || "")}</th>
          <th class="side" rowspan="3">勝敗</th>
          <th class="side" colspan="10">AWAY TEAM: ${esc(m.away_team_name)}</th>
        </tr>
        <tr>${homeNos}<th colspan="5" rowspan="2">GAME</th>${awayNos}</tr>
        <tr>${homeNames}${awayNames}</tr>
        ${rows}
        ${totalRow("獲得ポイント", t.home_wins, t.away_wins)}
        ${totalRow(`勝利ポイント(${S.meta.bonus_point}P加算)`, t.home_bonus, t.away_bonus)}
        ${totalRow("合計ポイント", t.home_points, t.away_points)}
        <tr>
          <td colspan="11" class="sign">HOMEキャプテン
            <input data-f="home_sign" value="${esc(m.home_sign)}"></td>
          <td colspan="5">キャプテンサイン</td>
          <td colspan="11" class="sign">AWAYキャプテン
            <input data-f="away_sign" value="${esc(m.away_sign)}"></td>
        </tr>
      </table>
    </div>
    <p class="muted no-print">マス目を押すと出場、勝敗の列を押すと勝ち負けが入ります（もう一度押すと取り消し）。
      ⑦⑧の人数欄(*)を押すと4人⇔トリオスを切り替えられます。</p>
  </div>`;
}

/* スマホで1試合ずつ入力する画面 */
function tabGames() {
  const d = S.match;
  const chip = (g, side, p) => {
    const on = g[side].find((x) => x.player_id === p.id);
    return `<span class="chip ${on ? "on" : ""}" data-act="cell" data-g="${g.game_no}"
      data-side="${side}" data-id="${p.id}">${esc(p.name)}${on && on.locked ? " 固定" : ""}</span>`;
  };
  const fc = {};
  (d.forecast.games || []).forEach((g) => { fc[g.game_no] = g; });
  return d.games.map((g) => {
    const f = fc[g.game_no] || {};
    const lockBtns = g.home.length ? `<div class="chips">${g.home.map((x) =>
      `<button class="btn small" data-act="lock" data-g="${g.game_no}" data-id="${x.player_id}">
        ${x.locked ? "固定を外す" : "固定する"}：${esc(x.name)}</button>`).join("")}</div>` : "";
    return `<div class="gcard">
      <div class="spread">
        <div><span class="no">${CIRCLE[g.game_no - 1] || g.game_no}</span><b>${esc(g.name)}</b>
          <span class="muted">${g.mode}(${g.size}人) ${g.rounds}R ${g.coins}コイン</span></div>
        <div>${f.settled ? `<span class="pill">結果あり</span>`
          : `<span class="pill tag-${f.tag || "五分"}">${f.tag || ""} ${f.win_prob !== undefined ? pct(f.win_prob) : ""}</span>`}</div>
      </div>
      ${g.alt_mode ? `<button class="btn small" data-act="mode" data-g="${g.game_no}">
        ${g.mode === "G" ? "トリオス(3人)にする" : "4人制にもどす"}</button>` : ""}
      <h3>HOME</h3>
      <div class="chips">${d.home_roster.map((p) => chip(g, "home", p)).join("") || "<span class='muted'>参加メンバー未設定</span>"}</div>
      ${lockBtns}
      <h3>AWAY</h3>
      <div class="chips">${d.away_roster.map((p) => chip(g, "away", p)).join("") || "<span class='muted'>参加メンバー未設定</span>"}</div>
      <div class="wlbtns" style="margin-top:8px">
        <button data-act="wl" data-g="${g.game_no}" data-side="home"
          class="${g.winner === "home" ? "on-h" : ""}">HOMEの勝ち</button>
        <button data-act="wl" data-g="${g.game_no}" data-side="away"
          class="${g.winner === "away" ? "on-a" : ""}">AWAYの勝ち</button>
      </div>
    </div>`;
  }).join("");
}

/* ---------------- 操作 ---------------- */
function val(id) { const el = document.getElementById(id); return el ? el.value.trim() : ""; }
function checked(id) { const el = document.getElementById(id); return !!(el && el.checked); }

async function onClick(e) {
  const el = e.target.closest("[data-act]");
  if (!el) return;
  const act = el.dataset.act;
  const mid = S.match && S.match.match.id;

  if (act === "view") {
    S.view = el.dataset.view;
    if (S.view === "teams" && S.teamId) await loadPlayers(S.teamId);
    if (S.view === "standings") S.standings = await get("/api/standings");
    return render();
  }
  if (act === "back") { S.view = "matches"; await loadMatches(); return render(); }
  if (act === "tab") { S.tab = el.dataset.tab; return render(); }
  if (act === "side") {
    S.side = el.dataset.side; S.preview = null;
    if (S.tab === "members") await fillPool();
    return render();
  }
  if (act === "open") {
    await loadMatch(el.dataset.id);
    S.view = "match"; S.tab = "members"; S.side = "home";
    await fillPool();
    return render();
  }
  if (act === "print") return window.print();

  if (act === "create-match") {
    const body = {
      section: val("m-section"), match_date: val("m-date"),
      home_team_id: Number(val("m-home")) || null,
      away_team_id: Number(val("m-away")) || null,
      away_name: val("m-awayname"), away_rating: val("m-awayrt"),
    };
    const d = await post("/api/matches", body);
    if (!d) return;
    S.match = d; S.view = "match"; S.tab = "members"; S.side = "home";
    await loadMatches(); await fillPool();
    return render();
  }
  if (act === "del-match") {
    if (!confirm("この対戦を削除します。よろしいですか？")) return;
    await del(`/api/matches/${mid}`);
    S.view = "matches"; await loadMatches();
    return render();
  }
  if (act === "add-team") {
    const name = val("t-name");
    if (!name) return toast("チーム名を入れてください");
    const d = await post("/api/teams", { name });
    if (!d) return;
    await loadTeams(); S.teamId = d.team.id; await loadPlayers(S.teamId);
    return render();
  }
  if (act === "del-team") {
    if (!S.teamId || !confirm("このチームを削除します。よろしいですか？")) return;
    await del(`/api/teams/${S.teamId}`);
    S.teamId = null; await loadTeams();
    if (S.teamId) await loadPlayers(S.teamId); else S.players = [];
    return render();
  }
  if (act === "add-player") {
    const name = val("p-name");
    if (!name) return toast("選手名を入れてください");
    const d = await post("/api/players", {
      team_id: S.teamId, name, rating: val("p-rating"), ppd: val("p-ppd"), mpr: val("p-mpr") });
    if (!d) return;
    await loadPlayers(S.teamId); await loadTeams();
    return render();
  }
  if (act === "del-player") {
    if (!confirm("この選手を削除します。よろしいですか？")) return;
    await del(`/api/players/${el.dataset.id}`);
    await loadPlayers(S.teamId); await loadTeams();
    return render();
  }
  if (act === "save-players") {
    for (const p of S.players) {
      const pick = (f) => {
        const inp = document.querySelector(`input[data-pid="${p.id}"][data-f="${f}"]`);
        return inp ? inp.value.trim() : "";
      };
      await put(`/api/players/${p.id}`, {
        name: pick("name"), rating: pick("rating"), ppd: pick("ppd"), mpr: pick("mpr") });
    }
    await loadPlayers(S.teamId); await loadTeams();
    toast("保存しました");
    return render();
  }
  if (act === "save-awayrt") {
    await put(`/api/matches/${mid}`, { away_rating: val("away-rt") });
    await loadMatch(mid);
    toast("保存しました");
    return render();
  }
  if (act === "member") {
    const pid = Number(el.dataset.id);
    const side = S.side;
    return queue(async () => {
      const ids = rosterOf(side).map((p) => p.id);
      const idx = ids.indexOf(pid);
      if (idx >= 0) ids.splice(idx, 1);
      else if (ids.length >= 10) return toast("参加メンバーは10人までです");
      else ids.push(pid);
      const d = await put(`/api/matches/${mid}/entries`, { side, player_ids: ids });
      if (d) { S.match = d; S.preview = null; }
      render();
    });
  }
  if (act === "auto-run" || act === "auto-shuffle" || act === "auto-apply") {
    readOpts();
    if (act === "auto-shuffle") S.opts.seed = Math.floor(Math.random() * 1e6);
    const body = {
      side: S.side, objective: S.opts.objective, seed: S.opts.seed,
      avoid_consecutive: S.opts.avoid_consecutive,
      min_games: S.opts.min_games === "" ? null : Number(S.opts.min_games),
      max_games: S.opts.max_games === "" ? null : Number(S.opts.max_games),
      apply: act === "auto-apply",
    };
    await applyTrios();
    const d = await post(`/api/matches/${mid}/auto`, body);
    if (!d) return;
    S.preview = d.result;
    if (d.match) { S.match = d.match; S.tab = "sheet"; toast("オーダーを決定しました"); }
    return render();
  }
  if (act === "cell") {
    const gno = Number(el.dataset.g), side = el.dataset.side, pid = Number(el.dataset.id);
    return queue(async () => {
      const g = S.match.games.find((x) => x.game_no === gno);
      let ids = g[side].map((x) => x.player_id);
      if (ids.includes(pid)) ids = ids.filter((i) => i !== pid);
      else if (ids.length >= g.size) return toast(`この試合は${g.size}人までです`);
      else ids.push(pid);
      const locked = g[side].filter((x) => x.locked).map((x) => x.player_id)
        .filter((i) => ids.includes(i));
      const d = await put(`/api/matches/${mid}/games/${gno}`,
        { [`${side}_players`]: ids, [`${side}_locked`]: locked });
      if (d) S.match = d;
      render();
    });
  }
  if (act === "lock") {
    const gno = Number(el.dataset.g), pid = Number(el.dataset.id);
    return queue(async () => {
      const g = S.match.games.find((x) => x.game_no === gno);
      const ids = g.home.map((x) => x.player_id);
      let locked = g.home.filter((x) => x.locked).map((x) => x.player_id);
      locked = locked.includes(pid) ? locked.filter((i) => i !== pid) : [...locked, pid];
      const d = await put(`/api/matches/${mid}/games/${gno}`,
        { home_players: ids, home_locked: locked });
      if (d) S.match = d;
      render();
    });
  }
  if (act === "wl") {
    const gno = Number(el.dataset.g), side = el.dataset.side;
    return queue(async () => {
      const g = S.match.games.find((x) => x.game_no === gno);
      const d = await put(`/api/matches/${mid}/games/${gno}`,
        { winner: g.winner === side ? "" : side });
      if (d) S.match = d;
      render();
    });
  }
  if (act === "mode") {
    const gno = Number(el.dataset.g);
    return queue(async () => {
      const g = S.match.games.find((x) => x.game_no === gno);
      if (!g.alt_mode) return;
      const next = g.mode === g.alt_mode ? modeOf(gno) : g.alt_mode;
      const keep = g.home.map((x) => x.player_id).slice(0, S.meta.mode_size[next]);
      const keepA = g.away.map((x) => x.player_id).slice(0, S.meta.mode_size[next]);
      const d = await put(`/api/matches/${mid}/games/${gno}`,
        { mode: next, home_players: keep, away_players: keepA });
      if (d) S.match = d;
      render();
    });
  }
}

function modeOf(gno) {
  const t = S.meta.template.find((g) => g.game_no === gno);
  return t ? t.mode : "D";
}

async function applyTrios() {
  const want = checked("o-trios") ? "T" : "G";
  for (const gno of [7, 8]) {
    const g = S.match.games.find((x) => x.game_no === gno);
    if (!g || g.mode === want) continue;
    const keep = g.home.map((x) => x.player_id).slice(0, S.meta.mode_size[want]);
    const keepA = g.away.map((x) => x.player_id).slice(0, S.meta.mode_size[want]);
    const d = await put(`/api/matches/${S.match.match.id}/games/${gno}`,
      { mode: want, home_players: keep, away_players: keepA });
    if (d) S.match = d;
  }
}

function readOpts() {
  const el = document.getElementById("o-obj");
  if (!el) return;
  S.opts.objective = el.value;
  S.opts.min_games = val("o-min");
  S.opts.max_games = val("o-max");
  S.opts.avoid_consecutive = checked("o-consec");
}

async function fillPool() {
  const m = S.match.match;
  const teamId = S.side === "home" ? m.home_team_id : m.away_team_id;
  if (!teamId) { S.pool = { side: S.side, players: [] }; return; }
  const d = await get(`/api/teams/${teamId}/players`);
  S.pool = { side: S.side, players: ((d && d.players) || []).filter((p) => p.active) };
}

async function onChange(e) {
  const el = e.target;
  if (el.id === "t-sel") {
    S.teamId = Number(el.value);
    await loadPlayers(S.teamId);
    return render();
  }
  if (el.dataset && el.dataset.f && S.match) {  // シート上の節・サイン欄
    const mid = S.match.match.id;
    const d = await put(`/api/matches/${mid}`, { [el.dataset.f]: el.value });
    if (d) S.match = d;
  }
}

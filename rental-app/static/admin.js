/* 管理者用UI（ミニマル版：記録一覧・現場・単価・集計・従業員・設定） */
"use strict";

const A = { tab: "summary", month: new Date().toISOString().slice(0, 7) };

function renderAdmin() {
  S.view = "menu";
  document.body.classList.add("admin-wide");
  const tabs = [["summary", "月別集計・出力"], ["sites", "現場"], ["prices", "料金マスター"],
    ["import", "単価表取込"], ["users", "利用者"], ["company", "設定"]];
  $app().innerHTML = `
  <button class="backlink" onclick="renderHome()">← ホームへ</button>
  <h1>メニュー</h1>
  <div class="tabs">${tabs.map(([k, l]) =>
    `<button class="tab ${A.tab === k ? "sel" : ""}" onclick="A.tab='${k}';renderAdmin()">${l}</button>`).join("")}
    <button class="tab" onclick="logout()">ログアウト</button></div>
  <div id="admin-body">読み込み中…</div>`;
  ({ sites: adSites, prices: adPrices, import: adImport, summary: adSummary,
    users: adUsers, company: adCompany })[A.tab]();
}
const $b = () => document.getElementById("admin-body");
const yenOr = (n) => n == null ? "—" : n.toLocaleString() + "円";

async function adSites() {
  const { data: sites } = await api("/api/sites");
  window.__siteAdd = async () => {
    const r = await post("/api/sites", { name: v("st-name"), contractor: v("st-con") });
    if (!r.ok) return showErrors(r.data.errors);
    adSites();
  };
  window.__siteToggle = async (id, status) => {
    await put(`/api/sites/${id}`, { status: status === "active" ? "done" : "active" });
    adSites();
  };
  window.__siteDel = async (id, name) => {
    if (!confirm(`現場「${name}」を削除しますか？（記録は残ります）`)) return;
    await api(`/api/sites/${id}`, { method: "DELETE" });
    adSites();
  };
  $b().innerHTML = `<h2>現場</h2>
  <div class="card"><div class="flexrow">
    <input id="st-name" data-field="name" placeholder="現場名" style="flex:2">
    <input id="st-con" placeholder="元請会社名" style="flex:1">
    <button class="btn small" onclick="__siteAdd()">登録</button></div></div>
  <table class="data"><tr><th>現場名</th><th>元請</th><th>状態</th><th>登録者</th><th></th></tr>
  ${sites.map(s => `<tr><td>${esc(s.name)}</td><td>${esc(s.contractor)}</td>
    <td>${s.status === "active" ? "施工中" : "完了"}</td>
    <td>${esc(s.creator || "管理者")}</td>
    <td><button class="btn small secondary" onclick="__siteToggle(${s.id},'${s.status}')">
      ${s.status === "active" ? "完了にする" : "施工中に戻す"}</button>
      <button class="btn small red" onclick="__siteDel(${s.id},'${esc(s.name)}')">削除</button></td></tr>`).join("")}
  </table>`;
}

async function adPrices() {
  const { data: items } = await api("/api/price_master");
  window.__priceEdit = async (id) => {
    const it = items.find(x => x.id === id);
    const fields = [["daily_rate", "日割単価"], ["monthly_rate", "月極単価"], ["basic_fee", "基本料"],
      ["support_per_day", "サポート料／日"], ["damage_per_day", "賠償対策費／日"]];
    const body = {};
    for (const [k, label] of fields) {
      const cur = it[k] == null ? "" : it[k];
      const val = prompt(`${label}（現在：${cur === "" ? "要確認" : cur}円）`, cur);
      if (val === null) return;
      body[k] = val;
    }
    const r = await put(`/api/price_master/${id}`, body);
    if (!r.ok) alert(Object.values(r.data.errors || {})[0]);
    adPrices();
  };
  window.__priceAdd = async () => {
    const r = await post("/api/price_master", {
      name: v("pm-name"), code: v("pm-code"), spec: v("pm-spec"),
      daily_rate: v("pm-d"), monthly_rate: v("pm-m"), basic_fee: v("pm-b"),
      support_per_day: v("pm-s"), damage_per_day: v("pm-g") });
    if (!r.ok) return showErrors(r.data.errors);
    adPrices();
  };
  const n = (x) => x == null ? "<span class='badge red'>要確認</span>" : x.toLocaleString();
  $b().innerHTML = `<h2>料金マスター</h2>
  <div class="card"><div class="flexrow">
    <input id="pm-name" data-field="name" placeholder="品名" style="flex:2">
    <input id="pm-code" placeholder="商品コード" style="flex:1">
    <input id="pm-spec" placeholder="規格" style="flex:1"></div>
    <div class="flexrow" style="margin-top:6px">
    <input id="pm-d" data-field="daily_rate" placeholder="日割単価" inputmode="numeric">
    <input id="pm-m" data-field="monthly_rate" placeholder="月極単価" inputmode="numeric">
    <input id="pm-b" data-field="basic_fee" placeholder="基本料" inputmode="numeric">
    <input id="pm-s" data-field="support_per_day" placeholder="サポート料/日" inputmode="numeric">
    <input id="pm-g" data-field="damage_per_day" placeholder="賠償対策費/日" inputmode="numeric">
    <button class="btn small" onclick="__priceAdd()">登録</button></div></div>
  <div style="overflow-x:auto"><table class="data"><tr>
    <th>品名</th><th>コード</th><th>規格</th><th class="num">日割</th><th class="num">月極</th>
    <th class="num">基本料</th><th class="num">サポート/日</th><th class="num">賠償/日</th>
    <th>原本</th><th></th></tr>
  ${items.map(it => `<tr ${it.needs_review ? "style='background:#fff8f0'" : ""}>
    <td>${esc(it.name)}</td><td>${esc(it.code)}</td><td>${esc(it.spec)}</td>
    <td class="num">${n(it.daily_rate)}</td><td class="num">${n(it.monthly_rate)}</td>
    <td class="num">${n(it.basic_fee)}</td><td class="num">${n(it.support_per_day)}</td>
    <td class="num">${n(it.damage_per_day)}</td>
    <td>${it.source_image ? `<a href="${it.source_image}" target="_blank">画像</a>` : "—"}</td>
    <td><button class="btn small secondary" onclick="__priceEdit(${it.id})">単価変更</button></td></tr>`).join("")}
  </table></div>`;
}

async function adImport(openBatch) {
  const { data: batches } = await api("/api/admin/import/batches");
  window.__openBatch = (id) => adImport(id);
  let batchHTML = "";
  if (openBatch) {
    const { data: b } = await api(`/api/admin/import/batches/${openBatch}`);
    const isImage = /\.(jpg|jpeg|png|gif|webp|heic)$/i.test(b.batch.image_path || "");
    window.__rowEdit = async (id) => {
      const row = b.rows.find(r => r.id === id);
      const body = { name: row.name, code: row.code, spec: row.spec };
      for (const [k, label] of [["daily_rate", "日割単価"], ["monthly_rate", "月極単価"],
        ["basic_fee", "基本料"], ["support_per_day", "サポート料／日"], ["damage_per_day", "賠償対策費／日"]]) {
        const cur = row[k] == null ? "" : row[k];
        const val = prompt(`${row.name} の${label}（読み取れない場合は空欄のまま＝要確認）`, cur);
        if (val === null) return;
        body[k] = val;
      }
      await put(`/api/admin/import/rows/${id}`, body);
      adImport(openBatch);
    };
    window.__rowApprove = async (id) => {
      const r = await post(`/api/admin/import/rows/${id}/approve`, {});
      if (!r.ok) alert(Object.values(r.data.errors || {})[0]);
      adImport(openBatch);
    };
    window.__rowReject = async (id) => { await post(`/api/admin/import/rows/${id}/reject`, {}); adImport(openBatch); };
    const n = (x) => x == null ? "<span class='badge red'>要確認</span>" : x.toLocaleString();
    batchHTML = `
    <h2>取込確認：${esc(b.batch.filename)}</h2>
    <p class="muted">原本を見ながら確認し、承認した行だけ料金マスターに登録されます。</p>
    <div class="import-split">
      <div>${isImage ? `<img src="${b.batch.image_path}">`
        : `<a href="${b.batch.image_path}" target="_blank">原本ファイルを開く</a>`}</div>
      <div><div style="overflow-x:auto"><table class="data"><tr>
          <th>品名</th><th>コード</th><th class="num">日割</th><th class="num">月極</th>
          <th class="num">基本</th><th class="num">サポ</th><th class="num">賠償</th><th>状態</th><th></th></tr>
        ${b.rows.map(r => `<tr ${r.needs_review ? "style='background:#fff8f0'" : ""}>
          <td>${esc(r.name)}<br><small>${esc(r.spec)}</small></td><td>${esc(r.code)}</td>
          <td class="num">${n(r.daily_rate)}</td><td class="num">${n(r.monthly_rate)}</td>
          <td class="num">${n(r.basic_fee)}</td><td class="num">${n(r.support_per_day)}</td>
          <td class="num">${n(r.damage_per_day)}</td>
          <td>${r.status === "approved" ? "<span class='badge green'>承認済</span>"
            : r.status === "rejected" ? "<span class='badge'>却下</span>"
            : r.needs_review ? "<span class='badge red'>要確認</span>" : "<span class='badge orange'>未確認</span>"}</td>
          <td>${r.status === "pending" ? `
            <button class="btn small secondary" onclick="__rowEdit(${r.id})">確認・修正</button>
            <button class="btn small green" onclick="__rowApprove(${r.id})">承認</button>
            <button class="btn small red" onclick="__rowReject(${r.id})">却下</button>` : ""}</td></tr>`).join("")}
        </table></div>
      </div>
    </div>`;
  }
  $b().innerHTML = `<h2>単価表の取込</h2>
  <div class="card">
    <p>見積内訳書の画像（またはExcel）をアップロードしてください。</p>
    <input type="file" id="imp-file" accept="image/*,.xlsx,.pdf">
    <div class="btnrow" style="max-width:300px"><button class="btn" id="imp-go">アップロード</button></div>
  </div>
  <table class="data"><tr><th>ファイル</th><th>登録日</th><th>未確認行</th><th></th></tr>
  ${batches.map(x => `<tr><td>${esc(x.filename)}</td><td>${esc(x.created_at)}</td>
    <td>${x.pending}</td><td><button class="btn small secondary" onclick="__openBatch(${x.id})">確認画面を開く</button></td></tr>`).join("")}
  </table>
  ${batchHTML}`;
  document.getElementById("imp-go").onclick = async (ev) => {
    const f = document.getElementById("imp-file").files[0];
    if (!f) return alert("ファイルを選んでください");
    ev.target.disabled = true;
    const fd = new FormData();
    fd.append("file", f);
    const res = await fetch("/api/admin/import/upload", { method: "POST", body: fd });
    const d = await res.json();
    ev.target.disabled = false;
    if (d.note) alert(d.note);
    adImport(d.batch_id);
  };
}

async function adSummary() {
  const { data: s } = await api(`/api/admin/summary?month=${A.month}`);
  const siteBlocks = Object.entries(s.sites).map(([name, x]) => `
    <h2>${esc(name)} <span class="muted">レンタル ${x.rental_total.toLocaleString()}円 ＋ 廃棄物 ${x.waste_total.toLocaleString()}円</span></h2>
    ${x.rentals.length ? `<div style="overflow-x:auto"><table class="data"><tr>
      <th>商品</th><th class="num">数量</th><th>期間</th><th class="num">当月日数</th>
      <th class="num">レンタル料</th><th class="num">基本料</th><th class="num">サポート</th>
      <th class="num">賠償</th><th class="num">当月小計</th></tr>
      ${x.rentals.map(r => `<tr><td>${esc(r.item_name)}</td><td class="num">${r.qty}</td>
        <td>${fmtShort(r.start_date)}〜${fmtShort(r.returned_date || r.due_date)}</td><td class="num">${r.days}</td>
        <td class="num">${r.rental.toLocaleString()}</td><td class="num">${r.basic.toLocaleString()}</td>
        <td class="num">${r.support.toLocaleString()}</td><td class="num">${r.damage.toLocaleString()}</td>
        <td class="num"><b>${r.subtotal.toLocaleString()}</b></td></tr>`).join("")}
      </table></div>` : ""}
    ${x.waste.length ? `<div style="overflow-x:auto"><table class="data"><tr>
      <th>搬出日</th><th>種類</th><th class="num">数量</th><th>運搬</th><th>処分先</th>
      <th class="num">金額</th></tr>
      ${x.waste.map(w2 => `<tr><td>${fmtShort(w2.out_date)}</td><td>${esc(w2.waste_type)}</td>
        <td class="num">${w2.qty}${esc(w2.unit)}</td><td>${esc(w2.hauler_name || "")}</td>
        <td>${esc(w2.disposal_name || "")}</td>
        <td class="num">${w2.amount != null ? w2.amount.toLocaleString() : "—"}</td></tr>`).join("")}
      </table></div>` : ""}`).join("");
  $b().innerHTML = `
  <div class="flexrow">
    <label class="f" style="margin:0">対象月</label>
    <input type="month" id="sm-month" value="${A.month}" style="width:180px">
    <a class="btn small secondary" href="/api/admin/export/csv?month=${A.month}">CSV出力</a>
    <a class="btn small secondary" href="/api/admin/export/xlsx?month=${A.month}">Excel出力</a>
    <a class="btn small secondary" href="/api/admin/export/pdf?month=${A.month}" target="_blank">PDF（印刷）</a>
    <a class="btn small secondary" href="/api/admin/backup">バックアップ</a>
  </div>
  <h2>合計 ${s.grand_total.toLocaleString()}円</h2>
  ${siteBlocks || "<p class='muted'>この月の記録はありません</p>"}`;
  document.getElementById("sm-month").onchange = (e) => { A.month = e.target.value; adSummary(); };
}

async function adUsers() {
  const { data: users } = await api("/api/users");
  window.__userAdd = async () => {
    const r = await post("/api/users", { name: v("us-name"), pin: v("us-pin") });
    if (!r.ok) return showErrors(r.data.errors);
    alert("利用者を登録しました。4桁番号を本人に伝えてください");
    adUsers();
  };
  window.__userToggle = async (id) => { await post(`/api/users/${id}/toggle_active`, {}); adUsers(); };
  window.__userReset = async (id, name) => {
    const pin = prompt(`${name}さんの新しい4桁番号を入力してください`);
    if (!pin) return;
    const r = await post(`/api/users/${id}/reset_password`, { pin });
    if (!r.ok) return alert(Object.values(r.data.errors || {})[0]);
    alert("番号を変更しました");
    adUsers();
  };
  $b().innerHTML = `<h2>利用者</h2>
  <p class="muted">ログインは1人ひとつの4桁番号だけです。番号は他の人と同じにできません。</p>
  <div class="card"><div class="flexrow">
    <input id="us-name" data-field="name" placeholder="名前" style="flex:2">
    <input id="us-pin" data-field="pin" placeholder="4桁番号" inputmode="numeric" maxlength="4" style="flex:1">
    <button class="btn small" onclick="__userAdd()">利用者を追加</button></div></div>
  <table class="data"><tr><th>名前</th><th>状態</th><th></th></tr>
  ${users.map(u => `<tr><td>${esc(u.name)}</td>
    <td>${u.active ? "利用中" : "<span class='badge red'>停止中</span>"}</td>
    <td><button class="btn small secondary" onclick="__userReset(${u.id},'${esc(u.name)}')">番号変更</button>
      ${u.role === "admin" ? "" : `
      <button class="btn small secondary" onclick="__userToggle(${u.id})">${u.active ? "停止" : "再開"}</button>`}</td></tr>`).join("")}
  </table>`;
}

async function adCompany() {
  const { data: c } = await api("/api/admin/company");
  window.__compSave = async () => {
    const r = await put("/api/admin/company",
      { company_name: v("co-name"), closing_day: +v("co-close") || 31,
        skip_sundays: document.getElementById("co-sun").checked });
    if (r.ok) { alert("保存しました。次に登録するレンタルから反映されます"); S.meta = (await api("/api/meta")).data; }
  };
  $b().innerHTML = `<h2>設定</h2>
  <div class="card" style="max-width:480px">
    <label class="f">会社名</label><input id="co-name" value="${esc(c.company_name || "")}">
    <label class="f">締め日（日）</label><input id="co-close" type="number" inputmode="numeric" value="${c.closing_day || 31}">
    <label class="f">レンタル料金の休止</label>
    <label class="chip ${c.skip_sundays ? "sel" : ""}" style="width:100%;justify-content:flex-start" id="co-sun-chip">
      <input type="checkbox" id="co-sun" ${c.skip_sundays ? "checked" : ""}
        style="width:26px;height:26px;min-height:26px;margin-right:10px">
      日曜日は休止（料金に含めない）</label>
    <p class="muted">これは初期値です。個々のレンタルごとに休止日の変更や、たまの休止日の追加ができます。</p>
    <div class="btnrow"><button class="btn" onclick="__compSave()">保存する</button></div>
  </div>`;
  document.getElementById("co-sun-chip").onclick = (e) => {
    if (e.target.id !== "co-sun") document.getElementById("co-sun").checked = !document.getElementById("co-sun").checked;
    document.getElementById("co-sun-chip").classList.toggle("sel", document.getElementById("co-sun").checked);
  };
}

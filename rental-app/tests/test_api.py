import importlib
import io
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

os.environ["RENTAL_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

from backend import db as D  # noqa: E402
importlib.reload(D)
from backend import main as M  # noqa: E402
importlib.reload(M)


@pytest.fixture(scope="module")
def clients():
    admin = TestClient(M.app)
    emp = TestClient(M.app)
    emp2 = TestClient(M.app)
    # 初期セットアップ（管理者1名）
    r = admin.post("/api/setup", json={
        "admin_name": "山田代表", "company_name": "山田造園",
        "email": "admin@example.com", "password": "adminpass123"})
    assert r.status_code == 200, r.text
    # 従業員2名を登録
    for c, name, lid in [(emp, "佐藤太郎", "sato"), (emp2, "鈴木次郎", "suzuki")]:
        r = admin.post("/api/users", json={
            "name": name, "display_name": name[:2], "login_id": lid,
            "temp_password": "temp1234"})
        assert r.status_code == 200, r.text
        r = c.post("/api/login", json={"login_id": lid, "password": "temp1234"})
        assert r.status_code == 200
        assert r.json()["user"]["must_change_password"] == 1
        # 初回ログイン時に仮パスワードを変更
        r = c.post("/api/change_password",
                   json={"old_password": "temp1234", "new_password": f"{lid}newpass1"})
        assert r.status_code == 200
    return admin, emp, emp2


# ---------------- 第1段階: 認証・権限
def test_setup_only_once(clients):
    admin, _, _ = clients
    r = admin.post("/api/setup", json={"admin_name": "x", "company_name": "y",
                                       "email": "z@e.com", "password": "password1"})
    assert r.status_code == 400


def test_login_wrong_password(clients):
    c = TestClient(M.app)
    r = c.post("/api/login", json={"login_id": "sato", "password": "wrong"})
    assert r.status_code == 401
    assert "違います" in r.json()["errors"]["login"]


def test_employee_cannot_manage_users_or_prices(clients):
    _, emp, _ = clients
    assert emp.get("/api/users").status_code == 403
    assert emp.post("/api/price_master", json={"name": "x"}).status_code == 403
    assert emp.post("/api/sites", json={"name": "x"}).status_code == 403
    assert emp.get("/api/admin/audit").status_code == 403
    assert emp.get("/api/admin/summary?month=2026-07").status_code == 403


def test_admin_can_stop_employee(clients):
    admin, _, _ = clients
    r = admin.post("/api/users", json={"name": "一時", "display_name": "一時",
                                       "login_id": "temp_user", "temp_password": "temp1234"})
    uid = r.json()["id"]
    r = admin.post(f"/api/users/{uid}/toggle_active")
    assert r.json()["active"] == 0
    c = TestClient(M.app)
    assert c.post("/api/login", json={"login_id": "temp_user",
                                      "password": "temp1234"}).status_code == 403


# ---------------- 第2段階: 現場
def test_site_crud_and_pickdata(clients):
    admin, emp, _ = clients
    r = admin.post("/api/sites", json={"name": "○○公園整備工事", "contractor": "大成建設"})
    assert r.status_code == 200
    sid = r.json()["id"]
    admin.post("/api/sites", json={"name": "△△河川敷伐採", "contractor": "地元建設"})
    r = emp.get("/api/sites", params={"q": "公園"})
    assert len(r.json()) == 1
    r = emp.get("/api/sites", params={"contractor": "大成"})
    assert len(r.json()) == 1
    r = emp.post(f"/api/sites/{sid}/favorite")
    assert sid in r.json()["favorites"]
    pd = emp.get("/api/sites/pickdata").json()
    assert any(s["id"] == sid for s in pd["favorites"])
    assert pd["last_site"] is None  # まだ入力していない


def test_site_validation_japanese(clients):
    admin, _, _ = clients
    r = admin.post("/api/sites", json={"name": ""})
    assert r.status_code == 422
    assert "現場名" in r.json()["errors"]["name"]


# ---------------- 第6段階(先行): 料金マスターと取込
def test_price_master_and_needs_review(clients):
    admin, emp, _ = clients
    r = admin.post("/api/price_master", json={
        "name": "高所作業車17m", "code": "K17", "spec": "17m", "daily_rate": 12000,
        "monthly_rate": 96000, "basic_fee": 5000, "support_per_day": 300,
        "damage_per_day": 200})
    assert r.status_code == 200 and r.json()["needs_review"] == 0
    # 空欄は補完せず要確認
    r = admin.post("/api/price_master", json={"name": "ミニバックホウ", "daily_rate": 8000})
    assert r.json()["needs_review"] == 1
    # 従業員は閲覧できるが変更できない
    items = emp.get("/api/price_master").json()
    assert len(items) >= 2
    pid = items[0]["id"]
    assert emp.put(f"/api/price_master/{pid}", json={"daily_rate": 1}).status_code == 403


def test_import_xlsx_flow(clients):
    admin, _, _ = clients
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["品名", "商品コード", "規格", "日割単価", "月極単価", "サポート料／日",
               "基本料", "賠償対策費／日"])
    ws.append(["チェーンソー", "CS-01", "40cm", 1500, 12000, 100, 500, 80])
    ws.append(["チェーンソー", "CS-02", "50cm", 1800, 14000, 100, 500, 80])   # 同名別規格→別商品
    ws.append(["不明機械", "X-99", "", "読めない", 5000, 100, 500, 80])        # 不鮮明→要確認
    buf = io.BytesIO()
    wb.save(buf)
    r = admin.post("/api/admin/import/upload",
                   files={"file": ("prices.xlsx", buf.getvalue(),
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200
    bid = r.json()["batch_id"]
    batch = admin.get(f"/api/admin/import/batches/{bid}").json()
    rows = batch["rows"]
    assert len(rows) == 3
    cs = [x for x in rows if x["name"] == "チェーンソー"]
    assert len(cs) == 2  # 同名でもコード違いは別行
    bad = next(x for x in rows if x["name"] == "不明機械")
    assert bad["needs_review"] == 1 and bad["daily_rate"] is None  # 勝手に補完しない
    # 要確認の行は承認できない
    r = admin.post(f"/api/admin/import/rows/{bad['id']}/approve")
    assert r.status_code == 422
    # 修正してから承認できる
    r = admin.put(f"/api/admin/import/rows/{bad['id']}",
                  json={"daily_rate": 2000, "monthly_rate": 5000, "basic_fee": 500,
                        "support_per_day": 100, "damage_per_day": 80})
    assert r.json()["needs_review"] == 0
    r = admin.post(f"/api/admin/import/rows/{bad['id']}/approve")
    assert r.status_code == 200
    # 承認行だけ本登録され、原本画像が関連付く
    pm = admin.get("/api/price_master", params={"q": "不明機械"}).json()
    assert len(pm) == 1 and pm[0]["source_image"]
    r = admin.post(f"/api/admin/import/rows/{cs[0]['id']}/approve")
    assert r.status_code == 200
    assert len(admin.get("/api/price_master", params={"q": "チェーンソー"}).json()) == 1


# ---------------- 第3段階: レンタル
@pytest.fixture(scope="module")
def rental_ctx(clients):
    admin, emp, emp2 = clients
    site = admin.post("/api/sites", json={"name": "□□団地外構工事"}).json()["id"]
    item = admin.post("/api/price_master", json={
        "name": "発電機", "code": "GEN-1", "spec": "2.8kVA", "daily_rate": 1000,
        "monthly_rate": 8000, "basic_fee": 500, "support_per_day": 100,
        "damage_per_day": 50}).json()["id"]
    return site, item


def test_rental_validation_messages(clients, rental_ctx):
    _, emp, _ = clients
    r = emp.post("/api/rentals", json={})
    e = r.json()["errors"]
    assert e["site_id"] == "現場を選んでください"
    assert e["qty"] == "数量は1以上で入力してください"
    assert "写真" in e["photo_ids"]


def test_rental_create_snapshot_and_estimate(clients, rental_ctx):
    _, emp, _ = clients
    site, item = rental_ctx
    r = emp.post("/api/rentals", json={
        "site_id": site, "vendor_name": "アクティオ", "item_id": item, "qty": 2,
        "start_date": "2026-07-01", "due_date": "2026-07-05",
        "skip_photo": True, "client_key": "ck-001"})
    assert r.status_code == 200, r.text
    est = r.json()["estimate"]
    assert est["days"] == 5
    assert est["rental"] == 1000 * 5 * 2
    assert est["basic"] == 500 * 2
    # 二重送信は同じIDを返す（二重登録防止）
    r2 = emp.post("/api/rentals", json={
        "site_id": site, "vendor_name": "アクティオ", "item_id": item, "qty": 2,
        "start_date": "2026-07-01", "due_date": "2026-07-05",
        "skip_photo": True, "client_key": "ck-001"})
    assert r2.json()["duplicate"] is True
    assert r2.json()["id"] == r.json()["id"]
    # 前回の現場が記憶される
    pd = emp.get("/api/sites/pickdata").json()
    assert pd["last_site"]["id"] == site


def test_active_rentals_visible_for_return(clients, rental_ctx):
    _, emp, emp2 = clients
    site, _ = rental_ctx
    # 他の従業員も現場のレンタル中一覧は見える
    rows = emp2.get("/api/rentals", params={"site_id": site, "status": "active"}).json()
    assert len(rows) >= 1
    assert rows[0]["days_elapsed"] >= 1


def test_return_requires_photo_when_damaged(clients, rental_ctx):
    _, emp, _ = clients
    site, item = rental_ctx
    rid = emp.post("/api/rentals", json={
        "site_id": site, "vendor_name": "アクティオ", "item_id": item, "qty": 1,
        "start_date": "2026-07-01", "due_date": "2026-07-10", "skip_photo": True}).json()["id"]
    r = emp.post("/api/rentals/return", json={
        "ids": [rid], "returned_date": "2026-07-08",
        "condition_flags": {"broken": True}})
    assert r.status_code == 422
    assert "写真" in r.json()["errors"]["photo_ids"]
    # 写真を付ければ返却できる
    p = emp.post("/api/photos", files={"file": ("damage.jpg", b"fakejpg", "image/jpeg")},
                 data={"category": "故障・破損"})
    assert p.status_code == 200
    r = emp.post("/api/rentals/return", json={
        "ids": [rid], "returned_date": "2026-07-08",
        "condition_flags": {"broken": True}, "photo_ids": [p.json()["id"]]})
    assert r.status_code == 200 and rid in r.json()["returned"]


def test_bulk_return(clients, rental_ctx):
    _, emp, _ = clients
    site, item = rental_ctx
    ids = [emp.post("/api/rentals", json={
        "site_id": site, "vendor_name": "アクティオ", "item_id": item, "qty": 1,
        "start_date": "2026-07-01", "due_date": "2026-07-20",
        "skip_photo": True}).json()["id"] for _ in range(2)]
    r = emp.post("/api/rentals/return",
                 json={"ids": ids, "returned_date": "2026-07-15"})
    assert sorted(r.json()["returned"]) == sorted(ids)


def test_extension(clients, rental_ctx):
    _, emp, _ = clients
    site, item = rental_ctx
    rid = emp.post("/api/rentals", json={
        "site_id": site, "vendor_name": "アクティオ", "item_id": item, "qty": 1,
        "start_date": "2026-07-01", "due_date": "2026-07-05", "skip_photo": True}).json()["id"]
    # その他はコメント必須
    r = emp.post(f"/api/rentals/{rid}/extend", json={"new_due": "2026-07-20", "reason": "その他"})
    assert "理由" in r.json()["errors"]["comment"]
    # 過去日はエラー
    r = emp.post(f"/api/rentals/{rid}/extend", json={"new_due": "2026-07-04", "reason": "天候"})
    assert r.status_code == 422
    r = emp.post(f"/api/rentals/{rid}/extend", json={"new_due": "2026-07-20", "reason": "天候"})
    assert r.status_code == 200
    est = r.json()["estimate"]
    assert est["days"] == 20
    assert est["rental"] == 8000  # 10日以上→月極


def test_employee_cannot_edit_price_on_rental(clients, rental_ctx):
    admin, emp, _ = clients
    site, item = rental_ctx
    rid = emp.post("/api/rentals", json={
        "site_id": site, "vendor_name": "アクティオ", "item_id": item, "qty": 1,
        "start_date": "2026-07-01", "due_date": "2026-07-03", "skip_photo": True}).json()["id"]
    # 従業員が単価を送っても無視される
    emp.put(f"/api/rentals/{rid}", json={"daily_rate": 1, "qty": 3})
    row = [x for x in emp.get("/api/rentals", params={"mine": 1}).json() if x["id"] == rid][0]
    assert row["daily_rate"] == 1000 and row["qty"] == 3


def test_delete_request_flow(clients, rental_ctx):
    admin, emp, _ = clients
    site, item = rental_ctx
    rid = emp.post("/api/rentals", json={
        "site_id": site, "vendor_name": "アクティオ", "item_id": item, "qty": 1,
        "start_date": "2026-07-01", "due_date": "2026-07-02", "skip_photo": True}).json()["id"]
    # 従業員は削除APIを持たない→取消申請
    r = emp.post("/api/delete_requests",
                 json={"target_type": "rental", "target_id": rid, "reason": "重複入力"})
    assert r.status_code == 200
    reqs = admin.get("/api/delete_requests").json()
    target = next(x for x in reqs if x["target_id"] == rid)
    r = admin.post(f"/api/delete_requests/{target['id']}/decide", json={"approve": True})
    assert r.status_code == 200
    assert not [x for x in emp.get("/api/rentals", params={"mine": 1}).json() if x["id"] == rid]


# ---------------- 第4段階: 廃棄物・写真・下書き
def test_waste_create_and_defaults(clients, rental_ctx):
    _, emp, _ = clients
    site, _ = rental_ctx
    r = emp.post("/api/waste", json={})
    e = r.json()["errors"]
    assert e["waste_type"] == "廃棄物の種類を選んでください"
    assert "単位" in e["unit"]
    r = emp.post("/api/waste", json={
        "site_id": site, "out_date": "2026-07-10", "waste_type": "枝葉", "qty": 2.5,
        "unit": "t", "hauler_name": "山川運送", "disposal_name": "グリーンリサイクル",
        "skip_photo": True, "client_key": "wk-1"})
    assert r.status_code == 200, r.text
    wid = r.json()["id"]
    # 前回業者が候補になる
    d = emp.get("/api/waste/defaults", params={"site_id": site}).json()
    assert d["hauler_id"]["name"] == "山川運送"
    assert d["disposal_id"]["name"] == "グリーンリサイクル"
    # 処分完了
    assert emp.post(f"/api/waste/{wid}/disposal_done").status_code == 200
    row = [x for x in emp.get("/api/waste").json() if x["id"] == wid][0]
    assert row["disposal_done"] == 1


def test_photo_upload_and_reorder(clients):
    _, emp, _ = clients
    ids = []
    for i in range(3):
        p = emp.post("/api/photos", files={"file": (f"p{i}.jpg", b"x", "image/jpeg")},
                     data={"category": "計量票"})
        ids.append(p.json()["id"])
    emp.post("/api/photos/reorder", json={"ids": list(reversed(ids))})
    rows = emp.get("/api/photos", params={"target_type": "pending"}).json()
    mine = [r["id"] for r in rows if r["id"] in ids]
    assert mine == list(reversed(ids))
    assert emp.delete(f"/api/photos/{ids[0]}").status_code == 200


def test_photo_bad_extension(clients):
    _, emp, _ = clients
    p = emp.post("/api/photos", files={"file": ("x.exe", b"x", "application/x-exe")})
    assert p.status_code == 422


def test_drafts(clients):
    _, emp, _ = clients
    r = emp.post("/api/drafts", json={"kind": "rental", "payload": {"step": 2, "qty": 1}})
    did = r.json()["id"]
    r = emp.post("/api/drafts", json={"id": did, "payload": {"step": 3}})
    rows = emp.get("/api/drafts").json()
    assert any(d["id"] == did for d in rows)
    emp.delete(f"/api/drafts/{did}")


def test_home_counts(clients):
    _, emp, _ = clients
    h = emp.get("/api/home").json()
    assert "today_count" in h and "due_soon" in h and "drafts" in h


def test_ocr_returns_candidates_not_confirmed(clients):
    _, emp, _ = clients
    r = emp.post("/api/ocr/slip")
    assert r.status_code == 200
    assert set(r.json()["candidates"]) >= {"date", "qty", "slip_no"}


# ---------------- 第7段階: 確認ワークフロー・集計・出力・監査
def test_workflow_and_lock(clients, rental_ctx):
    admin, emp, _ = clients
    site, item = rental_ctx
    rid = emp.post("/api/rentals", json={
        "site_id": site, "vendor_name": "アクティオ", "item_id": item, "qty": 1,
        "start_date": "2026-07-01", "due_date": "2026-07-05", "skip_photo": True}).json()["id"]
    # 差し戻しは理由必須
    r = admin.post(f"/api/admin/records/rental/{rid}/wf", json={"status": "fix_requested"})
    assert r.status_code == 422
    r = admin.post(f"/api/admin/records/rental/{rid}/wf",
                   json={"status": "fix_requested", "reason": "数量を確認してください"})
    assert r.status_code == 200
    # 従業員ホームに修正依頼として出る
    fr = emp.get("/api/my/fix_requests").json()
    assert any(x["id"] == rid for x in fr["rentals"])
    # 従業員が修正すると未確認に戻る
    emp.put(f"/api/rentals/{rid}", json={"qty": 2})
    # 金額確定→従業員は編集不可
    admin.post(f"/api/admin/records/rental/{rid}/wf", json={"status": "fixed_amount"})
    assert emp.put(f"/api/rentals/{rid}", json={"qty": 5}).status_code == 403
    row = [x for x in admin.get("/api/rentals").json() if x["id"] == rid][0]
    assert row["amount_total"] == (1000 * 5 + 500 + 100 * 5 + 50 * 5) * 2
    # 請求済み→支払済み
    for st in ("billed", "paid"):
        assert admin.post(f"/api/admin/records/rental/{rid}/wf",
                          json={"status": st}).status_code == 200


def test_monthly_summary_and_exports(clients):
    admin, _, _ = clients
    s = admin.get("/api/admin/summary", params={"month": "2026-07"}).json()
    assert s["grand_total"] > 0
    assert s["sites"]
    r = admin.get("/api/admin/export/csv", params={"month": "2026-07"})
    assert r.status_code == 200 and "レンタル" in r.text
    r = admin.get("/api/admin/export/xlsx", params={"month": "2026-07"})
    assert r.status_code == 200 and len(r.content) > 1000
    r = admin.get("/api/admin/export/pdf", params={"month": "2026-07"})
    assert r.status_code == 200 and "月次集計" in r.text


def test_month_spanning_rental_split(clients, rental_ctx):
    admin, emp, _ = clients
    site, item = rental_ctx
    emp.post("/api/rentals", json={
        "site_id": site, "vendor_name": "アクティオ", "item_id": item, "qty": 1,
        "start_date": "2026-08-25", "due_date": "2026-09-10", "skip_photo": True})
    aug = admin.get("/api/admin/summary", params={"month": "2026-08"}).json()
    sep = admin.get("/api/admin/summary", params={"month": "2026-09"}).json()
    site_name = "□□団地外構工事"
    aug_lines = aug["sites"][site_name]["rentals"]
    sep_lines = sep["sites"][site_name]["rentals"]
    a = next(x for x in aug_lines if x["start_date"] == "2026-08-25")
    b = next(x for x in sep_lines if x["start_date"] == "2026-08-25")
    assert a["days"] == 7 and b["days"] == 10
    assert a["basic"] == 500 and b["basic"] == 0  # 基本料は開始月のみ


def test_audit_log_admin_only(clients):
    admin, emp, _ = clients
    rows = admin.get("/api/admin/audit").json()
    assert any(r["action"] == "レンタル開始登録" for r in rows)
    row = next(r for r in rows if r["action"] == "レンタル開始登録")
    assert row["user_name"] and row["created_at"]
    assert emp.get("/api/admin/audit").status_code == 403


def test_backup_excludes_password(clients):
    admin, _, _ = clients
    r = admin.get("/api/admin/backup")
    assert r.status_code == 200
    assert "password_hash" not in r.text


def test_company_settings(clients):
    admin, emp, _ = clients
    assert admin.put("/api/admin/company",
                     json={"company_name": "山田造園株式会社", "closing_day": 25}).status_code == 200
    assert admin.get("/api/admin/company").json()["closing_day"] == 25
    assert emp.get("/api/admin/company").status_code == 403

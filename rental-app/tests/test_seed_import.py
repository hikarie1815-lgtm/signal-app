from backend import db as D
from backend import seed_import


def test_seed_creates_two_batches_with_41_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "DB_PATH", str(tmp_path / "seed_test.db"))
    D.init_db()
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    assert seed_import.seed(str(uploads)) is True
    conn = D.get_db()
    batches = conn.execute("SELECT * FROM price_import_batches ORDER BY id").fetchall()
    assert len(batches) == 2
    rows = conn.execute("SELECT * FROM price_import_rows").fetchall()
    assert len(rows) == 25 + 16
    # 全41商品が料金マスターへ直接登録され、すぐ商品選択で使える
    masters = conn.execute("SELECT * FROM price_master").fetchall()
    assert len(masters) == 41
    assert all(m["source_image"] for m in masters)  # 原本画像が関連付く
    # 原本画像がアップロード先にコピーされ、バッチに関連付く
    for b in batches:
        fname = b["image_path"].split("/")[-1]
        assert (uploads / fname).exists()
    # 値のスポットチェック（原本より）
    by_code = {r["code"]: r for r in rows}
    r = by_code["SEA17001"]  # 高所作業車 17m/ETC
    assert (r["daily_rate"], r["monthly_rate"], r["support_per_day"],
            r["basic_fee"], r["damage_per_day"]) == (33000, 363000, 1100, 2000, 200)
    r = by_code["VAC45KNC"]  # バックホー小旋回クレーン 0.45m3
    assert (r["daily_rate"], r["monthly_rate"], r["support_per_day"],
            r["basic_fee"]) == (15000, 165000, 750, 2000)
    # 原本で環境対策費が空欄の行は補完せず要確認
    assert r["damage_per_day"] is None and r["needs_review"] == 1
    assert "要確認" in r["note"]
    # 値がある行は要確認にならない
    assert by_code["SAA40000"]["needs_review"] == 0
    # 同名でも規格・コード違いは別行（別商品）
    dumps = [r for r in rows if r["name"] == "ダンプ"]
    assert len(dumps) == 4 and len({d["code"] for d in dumps}) == 4
    # 2回目は投入されない（冪等）
    assert seed_import.seed(str(uploads)) is False
    assert conn.execute("SELECT COUNT(*) c FROM price_import_rows").fetchone()["c"] == 41
    conn.close()

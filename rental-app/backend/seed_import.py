"""見積内訳書（2枚）の取込データ投入。

原本画像を static/uploads にコピーして取込バッチを作成し、読み取った行を
price_import_rows に投入する。要件どおり料金マスターへは直接登録せず、
管理者が取込確認画面で承認した行だけ本登録される。

原本の「環境対策費／日」列はアプリの「賠償対策費／日」として取り込む。
原本が空欄の値は補完せず None のまま（＝要確認）とする。
"""
from __future__ import annotations

import os
import shutil

from .db import get_db, now_str

SEED_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "seed")

# (品名, 規格, 商品コード, 日割単価, 月極単価, サポート料/日, 基本料, 賠償(環境)対策費/日)
PAGE1 = [
    ("ダンプ", "0.35t/4WD", "SAA00B00", 5500, 60000, 500, 1500, None),
    ("ダンプ", "2t/低", "SAA2A000", 6600, 70000, 900, 1500, None),
    ("ダンプ", "3t/低", "SAA3A000", 7700, 80000, 900, 1500, None),
    ("ダンプ", "4t", "SAA40000", 8800, 90000, 900, 1500, 400),
    ("トラック", "0.35t", "SBA00000", 5000, 55000, 500, 1500, None),
    ("トラック", "2t/低/ETC", "SBA2AD00", 7700, 80000, 900, 1500, None),
    ("トラック", "4t/ETC", "SBA40D00", 10000, 110000, 900, 1500, 400),
    ("スライドダンプ", "3t", "SAF30000", 9900, 108900, 900, 1500, 200),
    ("スライドダンプ", "4t/ETC/手動コボレーン", "SAF40DA0", 11000, 121000, 900, 1500, 400),
    ("トラック／クレーン", "2t/3段/ETC", "SBB20D30", 12000, 130000, 900, 1500, None),
    ("トラック／クレーン", "3t/3段/ETC", "SBB30D30", 13000, 140000, 900, 1500, None),
    ("トラック／クレーン", "4t/4段/ETC", "SBB40D40", 14000, 150000, 900, 1500, None),
    ("高所作業車", "9.9m/ETC", "SEA09901", 16500, 181500, 1100, 2000, 200),
    ("高所作業車", "12m/ETC", "SEA12001", 17600, 193600, 1100, 2000, 200),
    ("高所作業車／複合", "15.5m/ETC", "SEE15501", 30000, 330000, 1100, 2000, None),
    ("高所作業車", "17m/ETC", "SEA17001", 33000, 363000, 1100, 2000, 200),
    ("高所作業車／複合", "19.5m/ETC", "SEE19501", 35000, 385000, 1100, 2000, None),
    ("高所作業車", "22m/ETC", "SEA22001", 35200, 387200, 1100, 2000, 200),
    ("高所作業車", "27m/ETC", "SEA27001", 45000, 495000, 1100, 2000, 400),
    ("塵芥車", "2t/ETC", "STA02001", 25300, 278300, 900, 3000, None),
    ("バックホー小旋回", "0.03m3/キャノピー排土板/ゴムシュー", "VAA030EB", 6000, 65000, 450, 1000, None),
    ("バックホー小旋回", "0.07m3/キャノピー排土板/PAD", "VAA070EC", 6500, 70000, 450, 1500, None),
    ("バックホー小旋回", "0.1m3/キャノピー排土板/PAD", "VAA100EC", 7000, 77000, 550, 1500, None),
    ("バックホー小旋回", "0.12m3/キャノピー排土板/PAD", "VAA120EC", 8000, 88000, 550, 1000, None),
    ("バックホー小旋回クレーン", "0.25m3/1.7t/キャビンAC排土板/PAD", "VAC25GNC", 11000, 121000, 750, 1500, None),
]
PAGE2 = [
    ("バックホー小旋回クレーン", "0.45m3/2.9t/キャビンAC排土板/PAD", "VAC45KNC", 15000, 165000, 750, 2000, None),
    ("バックホー後方小旋回配管", "0.14m3/キャノピー排土板/SHOE/3次", "VBB140E2", 9900, 108900, 550, 1500, None),
    ("バックホー後方小旋回配管", "0.25m3/解体仕様/PAD/オフロード", "VBB250Z3", 13200, 145200, 750, 3000, None),
    ("バックホー後方小旋回配管クレーン", "0.45m3/2.9t/キャビンAC/PAD/オフ", "VBD45KL3", 15400, 169400, 750, 4000, None),
    ("解体用フォーク", "0.25m3/機械 3点式", "MCY25001", 7500, 127500, 330, 1500, None),
    ("解体用フォーク", "0.45m3/機械 3点式", "MCY45001", 10000, 150000, 400, 1500, None),
    ("スケルトンバケット", "0.45m3/100×165", "MAK45AF1", 6000, 90000, 300, 1000, None),
    ("シングルリッパー", "0.45m3", "MCK45000", 6000, 90000, 180, 1000, None),
    ("芝刈機（マサオ）", "975mm", "JCL09750", 15400, 169400, 100, 3000, None),
    ("芝刈機（搭乗式ハンマーナイフ）", "1525mm", "JCL15250", 27500, 302500, 400, 5000, None),
    ("集草機（搭乗式）", "2000mm", "JCN20000", 30000, 330000, 400, 3000, None),
    ("自走式草刈機（ラジコン）", "1100mm遠隔式", "JCP1100A", 38500, 462000, 350, 5000, None),
    ("ランマー", "60kgガソリン", "GA106000", 1980, 21780, 50, 500, None),
    ("プレート", "50kgガソリン", "GB105000", 1800, 19800, 50, 500, None),
    ("エンジンウォッシャー", "100kgf/13L", "JA710013", 2750, 30250, 50, 1000, None),
    ("アルミブリッジ", "3.0tセーフベロ", "ZZN30100", 1800, 19800, 50, 500, None),
]
PAGES = [("mitsumori_uchiwakesho_1.jpg", "見積内訳書 No.1（造園土木）", PAGE1),
         ("mitsumori_uchiwakesho_2.jpg", "見積内訳書 No.2", PAGE2)]

BLANK_NOTE = "原本の環境対策費／日が空欄のため要確認（0円なら0を入力して承認してください）"


def seed(uploads_dir: str) -> bool:
    """初回のみ取込バッチを投入する。投入したら True。"""
    conn = get_db()
    try:
        if conn.execute("SELECT COUNT(*) c FROM price_import_batches").fetchone()["c"]:
            return False
        for fname, label, rows in PAGES:
            src = os.path.join(SEED_DIR, fname)
            if not os.path.exists(src):
                continue
            shutil.copyfile(src, os.path.join(uploads_dir, fname))
            conn.execute(
                "INSERT INTO price_import_batches(filename,image_path,created_by,created_at)"
                " VALUES(?,?,NULL,?)", (label, f"/uploads/{fname}", now_str()))
            bid = conn.execute("SELECT last_insert_rowid() i").fetchone()["i"]
            for name, spec, code, daily, monthly, support, basic, damage in rows:
                needs = 1 if None in (daily, monthly, support, basic, damage) else 0
                conn.execute(
                    "INSERT INTO price_import_rows(batch_id,code,name,spec,daily_rate,"
                    "monthly_rate,basic_fee,support_per_day,damage_per_day,needs_review,note)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (bid, code, name, spec, daily, monthly, basic, support, damage,
                     needs, BLANK_NOTE if needs else ""))
        conn.commit()
        return True
    finally:
        conn.close()

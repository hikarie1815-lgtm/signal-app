# 建設レンタル・廃棄物処理管理アプリ 最終仕様書

対象: 造園・建設業（管理者1名＋従業員2名）
最優先事項: **建設現場の従業員が iPhone / iPad から説明書なしで短時間入力できること**

---

## 1. 最終要件定義

### 1.1 目的
- 建設機械レンタル（開始・返却・延長）と廃棄物搬出・処分の記録を現場から入力する
- 料金マスターに基づき日割・月極・基本料・サポート料・賠償対策費を自動計算する
- 管理者が確認・金額確定・請求管理・月別集計・出力を行う

### 1.2 利用者
| 役割 | 人数 | 説明 |
|---|---|---|
| 管理者 | 1名 | 会社代表者。全操作可能 |
| 従業員 | 2名 | 現場入力と閲覧のみ |

### 1.3 主要機能
- 認証（初回セットアップ、従業員招待、仮パスワード強制変更）
- 現場管理（最近使用・施工中・お気に入り・検索）
- かんたん入力モード（1画面1作業のステップ形式、下書き自動保存）
- レンタル開始／返却（レンタル中一覧からチェック式）／延長（新返却予定日のみ）
- 廃棄物登録（大ボタン種類選択、単位選択、前回業者候補）
- 写真・伝票登録（カメラ直接起動、分類、連続撮影、未送信→自動同期）
- 料金計算（独立モジュール・整数円・単体テスト付き）
- 単価表画像取込（管理者承認制、不明値は「要確認」）
- 管理者確認ワークフロー（未確認→確認済→金額確定→請求済→支払済、差し戻し）
- 削除は従業員には完全削除させず「取消申請」→管理者承認
- 操作履歴（管理者のみ閲覧）
- 月別集計、CSV / Excel / PDF出力、バックアップ

### 1.4 非機能要件
- スマホ最優先UI（ボタン最小タップ領域 56px、本文16px以上）
- オフライン耐性: 下書き・写真は端末保存し、通信復旧時に自動同期（未送信表示）
- 二重登録防止（送信中ボタン無効化＋クライアント生成の冪等キー）
- エラーメッセージは日本語・該当項目直下に表示
- 位置情報による現場自動判定は将来対応（設計上フックのみ用意）

---

## 2. 管理者画面一覧

| # | 画面 | 内容 |
|---|---|---|
| A1 | ダッシュボード | 未確認件数、取消申請、修正依頼中、今月金額 |
| A2 | 記録一覧（レンタル） | 全件、状態フィルタ、確認/差し戻し/確定/請求済/支払済 |
| A3 | 記録一覧（廃棄物） | 同上 |
| A4 | 現場管理 | 登録・編集・削除（論理削除） |
| A5 | 業者管理 | レンタル業者・運搬業者・処分先 |
| A6 | 料金マスター | 一覧・登録・変更、原本画像リンク |
| A7 | 単価表取込 | 画像/PDF/Excelアップロード → 行ごとに確認 → 承認行のみ本登録 |
| A8 | 月別集計 | 現場別・月別内訳、金額確定 |
| A9 | 出力 | CSV / Excel / PDF（印刷用）、バックアップ |
| A10 | 従業員管理 | 追加・停止・仮パスワード再発行 |
| A11 | 操作履歴 | 全操作ログ（管理者のみ） |
| A12 | 会社設定 | 会社名・締め日など |

## 3. 従業員画面一覧

| # | 画面 | 内容 |
|---|---|---|
| E0 | ログイン / 仮パスワード変更 | |
| E1 | ホーム | 大ボタン6つ＋氏名/日時/選択中現場/本日件数/返却間近/下書き件数/修正が必要な入力 |
| E2 | 現場選択 | 最近使用（最上部）・施工中・お気に入り・名称/元請検索。前回現場は確認ボタン付き候補 |
| E3 | レンタル開始ウィザード | 5ステップ（現場→業者・商品→数量・日付→写真→確認） |
| E4 | レンタル返却 | レンタル中一覧→チェック→返却日（初期値本日）→状態→確認 |
| E5 | レンタル延長 | レンタル中一覧→新返却予定日→理由選択→概算表示→確認 |
| E6 | 廃棄物登録ウィザード | 現場→種類（大ボタン）→数量・単位→業者・処分先→写真→確認 |
| E7 | 写真・伝票登録 | 分類選択→連続撮影→サムネイル並替/削除 |
| E8 | 今日の入力確認 | 本日の自分の登録一覧、下書き一覧、修正依頼一覧 |

## 4. 権限表

| 操作 | 管理者 | 従業員 |
|---|:-:|:-:|
| 全データ閲覧 | ○ | ×（自分の記録＋現場のレンタル中一覧） |
| 現場 登録 | ○ | ○（現場選択画面から新規登録可。同名は重複せず既存を選択。類似名は候補表示） |
| 現場 編集/削除 | ○ | × |
| レンタル記録 登録 | ○ | ○ |
| レンタル記録 編集 | ○ | 自分の未確定記録のみ |
| レンタル記録 削除 | ○（論理削除） | ×→取消申請 |
| 廃棄物記録 登録/編集 | ○ | 登録○ / 編集は自分の未確定のみ |
| 料金マスター 登録/変更 | ○ | ×（金額は確認表示のみ） |
| 単価表取込 | ○ | × |
| 従業員アカウント管理 | ○ | × |
| 月別集計・金額確定・請求済/支払済 | ○ | × |
| CSV/Excel/PDF出力・バックアップ | ○ | × |
| 会社設定 | ○ | × |
| 確定済み金額の変更 | ○（履歴記録） | × |
| 月次締め解除 | ○ | × |
| 操作履歴閲覧 | ○ | × |
| 写真撮影・添付 | ○ | ○ |
| 下書き保存 | ○ | ○ |

サーバー側で全APIに権限チェックを行う（UI非表示だけに頼らない）。

## 5. データベース設計（SQLite）

```
users(id, role[admin|employee], name, display_name, login_id, email,
      password_hash, must_change_password, active, created_at)
sessions(token, user_id, created_at, expires_at)
company(id=1, company_name, admin_name, closing_day, created_at)
sites(id, name, contractor, status[active|done], address, deleted, created_at)
vendors(id, kind[rental|hauler|disposal], name, deleted)
price_master(id, code, name, spec, daily_rate, monthly_rate, basic_fee,
             support_per_day, damage_per_day, needs_review, active,
             source_image, created_at)
price_import_batches(id, filename, image_path, status, created_by, created_at)
price_import_rows(id, batch_id, code, name, spec, daily_rate, monthly_rate,
                  basic_fee, support_per_day, damage_per_day,
                  needs_review, note, status[pending|approved|rejected])
rentals(id, site_id, vendor_id, item_id, item_name, spec, code, qty,
        start_date, due_date, returned_date,
        daily_rate, monthly_rate, basic_fee, support_per_day, damage_per_day,  -- 登録時点の単価スナップショット
        status[active|returned], condition_flags(json), condition_comment,
        wf_status[unconfirmed|confirmed|fix_requested|fixed_amount|billed|paid],
        wf_reason, amount_total, amount_locked, created_by, deleted, client_key, created_at)
rental_extensions(id, rental_id, old_due, new_due, reason, comment, created_by, created_at)
waste_records(id, site_id, out_date, waste_type, qty, unit, hauler_id,
              disposal_id, disposal_done, slip_no, amount, wf_status, wf_reason,
              created_by, deleted, client_key, created_at)
photos(id, target_type[rental|waste|site|other], target_id, category,
       file_path, taken_by, created_at, sort_order, deleted)
drafts(id, user_id, kind, payload(json), updated_at)
delete_requests(id, target_type, target_id, reason, requested_by,
                status[pending|approved|rejected], decided_by, decided_at, created_at)
audit_log(id, user_id, user_name, action, target_type, target_id,
          before(json), after(json), device, created_at, synced_at)
user_prefs(user_id, key, value)   -- last_site, favorite_sites, recent_items, favorite_items 等
```

- 単価は**登録時にレンタル記録へスナップショット**し、後からマスターを変えても確定金額が変わらない。
- 従業員の「削除」は `delete_requests` に記録し、管理者承認で `deleted=1`（完全削除しない）。

## 6. 料金計算仕様（`backend/pricing.py` 独立モジュール）

- 日数 = 返却日 − 開始日 + 1（**両端を含む**）
- 30日を1ブロックとし、ブロックごとに:
  - 1〜9日: `日割単価 × 日数`
  - 10日以上: `月極料金`（10〜30日は月極1か月分）
- 最大3か月程度（90日超は警告、計算自体は継続）
- 基本料: 契約初日の1回のみ（開始月に計上）
- サポート料/日・賠償対策費/日: 全日数×毎日発生
- すべて**整数の円**で計算（端数は月別配賦時、最終月に寄せて合計を一致させる）
- 月をまたぐ場合は暦月ごとの内訳を作成:
  - サポート料・賠償対策費 = 単価×当月日数（正確）
  - レンタル料 = 日数比例で配賦し、丸め差分は最終月へ
  - 基本料 = 開始月のみ
- 単体テスト: `tests/test_pricing.py`（1日/9日/10日/30日/31日/45日/90日/月跨ぎ/合計一致/数量）

## 7. 単価表取込仕様

1. 管理者が A7 で見積内訳書の画像（またはPDF/Excel）をアップロード → `price_import_batches` 作成
2. 自動読取（OCRが利用可能な環境ではフックで実行）。**読み取れない文字・空欄・不鮮明な数値は補完せず `needs_review`（要確認）**
3. 取込確認画面: 原本画像を横に表示しながら行ごとに 品名/商品コード/規格/日割/月極/基本料/サポート料/賠償対策費 を確認・修正
4. 同名でも規格・能力・商品コードが異なるものは**別商品**として別行のまま登録
5. 管理者が「承認」した行だけ `price_master` へ本登録。原本画像パスを各マスター行に関連付け保存
6. Excel取込は列名マッピング（品名/商品コード/日割単価/月極単価/サポート料/基本料/賠償対策費）

※ 本セッションには見積内訳書2枚の画像が添付されていないため、初期データは未投入。管理者が A7 から2枚をアップロードして取り込む。

## 8. 画面遷移図

```
[ログイン] ─ 初回 → [初期セットアップ(管理者)]
   ├─ 従業員(初回) → [仮パスワード変更] → E1
   ├─ 従業員 → E1 ホーム
   │     ├─ レンタル開始 → E2現場 → 商品 → 数量/日付 → 写真 → 確認 → 完了
   │     │        完了 → [同じ現場でもう1件 / 別の現場 / ホーム]
   │     ├─ レンタル返却 → E2現場 → レンタル中一覧(チェック) → 返却日/状態 → 確認 → 完了
   │     ├─ レンタル延長 → E2現場 → レンタル中一覧 → 新返却予定日/理由 → 概算 → 確認 → 完了
   │     ├─ 廃棄物を登録 → E2現場 → 種類 → 数量/単位 → 業者/処分先 → 写真 → 確認 → 完了
   │     ├─ 写真・伝票を登録 → 分類 → 撮影 → 対象選択 → 完了
   │     └─ 今日の入力を確認 → 一覧 / 下書き再開 / 修正依頼対応 / 取消申請
   └─ 管理者 → A1 ダッシュボード → A2..A12
```

## 9. 実装順序

| 段階 | 内容 | テスト |
|---|---|---|
| 1 | 認証・初期セットアップ・権限管理（管理者1+従業員2） | APIテスト |
| 2 | 現場管理・従業員ホーム・現場選択 | APIテスト |
| 3 | レンタル開始/返却/延長ウィザード・下書き | APIテスト |
| 4 | 廃棄物入力・写真/伝票登録・未送信同期 | APIテスト |
| 5 | 料金計算モジュール・月別分割 | 単体テスト |
| 6 | 単価表取込確認画面 | APIテスト |
| 7 | 管理者確認・集計・CSV/Excel/PDF出力・監査ログ | APIテスト |

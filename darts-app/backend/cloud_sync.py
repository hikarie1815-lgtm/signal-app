"""Firebase(Cloud Storage) にデータベースを預けて永続化する（任意）。

Render の無料プランは再起動でディスクが消えるため、設定しておくと
起動時に復元・更新時にバックアップされる。未設定ならローカル保存のみ。

環境変数:
- FIREBASE_STORAGE_BUCKET  : 例 ki-league.appspot.com
- FIREBASE_SERVICE_ACCOUNT : サービスアカウントJSONの中身（文字列）
  もしくは FIREBASE_SERVICE_ACCOUNT_FILE : JSONファイルのパス
- DARTS_CLOUD_PATH : 保存先のパス（既定 darts/darts.db。他アプリと同じ
  バケットを使っても衝突しないようにアプリごとに分ける）
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

_bucket = None
_enabled = False
_lock = threading.Lock()
_dirty = False
BLOB = os.environ.get("DARTS_CLOUD_PATH", "darts/darts.db")


def _log(msg: str) -> None:
    print(f"[cloud_sync] {msg}", flush=True)
    sys.stdout.flush()


def _load_credentials():
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    path = os.environ.get("FIREBASE_SERVICE_ACCOUNT_FILE")
    if raw:
        return json.loads(raw)
    if path and os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def init() -> bool:
    global _bucket, _enabled
    bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET")
    creds = _load_credentials()
    if not bucket_name or not creds:
        _log(f"未設定のため無効（bucket={bool(bucket_name)}, creds={bool(creds)}）")
        return False
    try:
        import firebase_admin
        from firebase_admin import credentials, storage
        if not firebase_admin._apps:
            firebase_admin.initialize_app(
                credentials.Certificate(creds), {"storageBucket": bucket_name})
        _bucket = storage.bucket()
        _enabled = True
        _log(f"Firebase接続OK bucket={bucket_name} path={BLOB}")
        return True
    except Exception as e:  # ライブラリ未導入・認証失敗などはローカル動作にする
        _log(f"Firebase無効化（設定を確認してください）: {e}")
        return False


def enabled() -> bool:
    return _enabled


def restore(db_path: str) -> None:
    if not _enabled:
        return
    try:
        blob = _bucket.blob(BLOB)
        if blob.exists():
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
            blob.download_to_filename(db_path)
            _log("darts.db を復元しました")
    except Exception as e:
        _log(f"復元エラー: {e}")


def mark_dirty(db_path: str) -> None:
    """データ変更後に呼ぶ。少し待ってまとめてアップロードする。"""
    global _dirty
    if not _enabled:
        return
    with _lock:
        _dirty = True
    threading.Thread(target=_debounced_upload, args=(db_path,), daemon=True).start()


def _debounced_upload(db_path: str) -> None:
    global _dirty
    time.sleep(2)
    with _lock:
        if not _dirty:
            return
        _dirty = False
    try:
        _bucket.blob(BLOB).upload_from_filename(db_path)
    except Exception as e:
        with _lock:
            _dirty = True  # 失敗したら次の変更でまとめて送る
        _log(f"アップロード失敗: {e}")


def flush(db_path: str) -> None:
    if not _enabled:
        return
    try:
        _bucket.blob(BLOB).upload_from_filename(db_path)
    except Exception as e:
        _log(f"flush失敗: {e}")

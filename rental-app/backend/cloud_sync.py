"""Firebase(Cloud Storage) を使ったデータ永続化。

Render無料プランは再起動でディスクが消えるため、SQLite の data.db と
写真フォルダ(uploads) を Firebase Storage に預け、起動時に復元・変更時に
バックアップする。これによりアプリはそのままで、データだけ Firebase に貯まる。

環境変数（未設定ならローカルのみで動作＝従来どおり）:
- FIREBASE_STORAGE_BUCKET : 例 genba-kiroku.appspot.com
- FIREBASE_SERVICE_ACCOUNT : サービスアカウントJSONの中身（文字列）
    もしくは FIREBASE_SERVICE_ACCOUNT_FILE : JSONファイルのパス
"""
from __future__ import annotations

import json
import os
import threading
import time

_bucket = None
_enabled = False
_lock = threading.Lock()
_dirty = False
_last_upload = 0.0


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
    """Firebase を初期化。設定が無ければ False（従来どおりローカル動作）。"""
    global _bucket, _enabled
    bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET")
    creds = _load_credentials()
    if not bucket_name or not creds:
        return False
    try:
        import firebase_admin
        from firebase_admin import credentials, storage
        if not firebase_admin._apps:
            firebase_admin.initialize_app(
                credentials.Certificate(creds), {"storageBucket": bucket_name})
        _bucket = storage.bucket()
        _enabled = True
        return True
    except Exception as e:  # ライブラリ未導入・認証失敗などは黙ってローカル動作
        print(f"[cloud_sync] Firebase無効化: {e}")
        return False


def enabled() -> bool:
    return _enabled


def restore(db_path: str, uploads_dir: str) -> None:
    """起動時に Firebase から data.db と写真を復元する。"""
    if not _enabled:
        return
    try:
        blob = _bucket.blob("data.db")
        if blob.exists():
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
            blob.download_to_filename(db_path)
            print("[cloud_sync] data.db を復元しました")
        os.makedirs(uploads_dir, exist_ok=True)
        for b in _bucket.list_blobs(prefix="uploads/"):
            name = b.name[len("uploads/"):]
            if not name:
                continue
            dst = os.path.join(uploads_dir, name)
            if not os.path.exists(dst):
                b.download_to_filename(dst)
        print("[cloud_sync] 写真を復元しました")
    except Exception as e:
        print(f"[cloud_sync] 復元エラー: {e}")


def upload_photo(local_path: str, filename: str) -> None:
    if not _enabled:
        return
    try:
        _bucket.blob(f"uploads/{filename}").upload_from_filename(local_path)
    except Exception as e:
        print(f"[cloud_sync] 写真アップロード失敗: {e}")


def mark_dirty(db_path: str) -> None:
    """データ変更後に呼ぶ。少し待ってまとめて data.db をアップロードする。"""
    global _dirty
    if not _enabled:
        return
    with _lock:
        _dirty = True
    threading.Thread(target=_debounced_upload, args=(db_path,), daemon=True).start()


def _debounced_upload(db_path: str) -> None:
    global _dirty, _last_upload
    time.sleep(2)  # 連続変更をまとめる
    with _lock:
        if not _dirty:
            return
        _dirty = False
    try:
        _bucket.blob("data.db").upload_from_filename(db_path)
        _last_upload = time.time()
    except Exception as e:
        global _dirty2
        with _lock:
            _dirty = True  # 失敗したら次回に持ち越し
        print(f"[cloud_sync] data.db アップロード失敗: {e}")


def flush(db_path: str) -> None:
    """終了時などに即アップロード。"""
    if not _enabled:
        return
    try:
        _bucket.blob("data.db").upload_from_filename(db_path)
    except Exception as e:
        print(f"[cloud_sync] flush失敗: {e}")

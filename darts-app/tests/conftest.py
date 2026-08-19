import os
import tempfile

# テスト用の一時DBを使う（本物のデータを触らない）
os.environ.setdefault("DARTS_DATA_DIR", tempfile.mkdtemp(prefix="darts-test-"))
os.environ["DARTS_DB"] = os.path.join(os.environ["DARTS_DATA_DIR"], "test.db")

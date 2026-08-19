"""テスト用のDBとストレージを一時ディレクトリへ向ける。

`app.settings` の import 時に Settings が、`app.database` の import 時に engine が
作られるので、環境変数の差し替えは `app` を一切 import する前に済ませる必要がある。
pytest はテストモジュールより先にこの conftest を読むため、ここに書けば間に合う。
このファイルの先頭で `app` を import してはいけない。
"""

import os
import tempfile
from pathlib import Path

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="bcman-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_ROOT / 'test.db').as_posix()}"
os.environ["STORAGE_DIR"] = str(_TEST_ROOT / "storage")
# 招待リンクの絶対URLを組み立てるため。テストでは到達性は問わない
os.environ.setdefault("PUBLIC_BASE_URL", "https://example.test/bcman")
# TestClient は HTTPS ではないので、Secure 属性付きCookieだと保持されない
os.environ["COOKIE_SECURE"] = "false"

"""SQLite への手書きマイグレーション。

Alembic を持たないので、起動時に `PRAGMA table_info` で列の有無を見て
`ALTER TABLE ... ADD COLUMN` する方式を取っている。`Base.metadata.create_all` は
テーブルを作るだけで、既存テーブルへの列追加もインデックス追加もしない。

`main` から切り出してあるのは、ここが「一度きり・本番の復元不能なデータに対して走る」
コードだからで、cv2 等を読み込む `main` を import せずにテストできるようにするため。
"""

from sqlalchemy import text


def apply_sqlite_migrations(connection) -> None:
    contact_columns = _columns(connection, "contacts")
    if "review_flags" not in contact_columns:
        connection.execute(text("ALTER TABLE contacts ADD COLUMN review_flags JSON DEFAULT '{}'"))
    if "search_text" not in contact_columns:
        connection.execute(text("ALTER TABLE contacts ADD COLUMN search_text TEXT DEFAULT ''"))

    card_columns = _columns(connection, "business_cards")
    if "oriented_image_path" not in card_columns:
        connection.execute(text("ALTER TABLE business_cards ADD COLUMN oriented_image_path VARCHAR DEFAULT ''"))
    if "orientation" not in card_columns:
        connection.execute(text("ALTER TABLE business_cards ADD COLUMN orientation INTEGER DEFAULT 0"))
    if "orientation_decision" not in card_columns:
        connection.execute(text("ALTER TABLE business_cards ADD COLUMN orientation_decision VARCHAR DEFAULT ''"))

    photo_columns = _columns(connection, "photos")
    if "pipeline_version" not in photo_columns:
        connection.execute(text("ALTER TABLE photos ADD COLUMN pipeline_version VARCHAR DEFAULT 'v1'"))


def _columns(connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}

"""SQLite への手書きマイグレーション。

Alembic を持たないので、起動時に `PRAGMA table_info` で列の有無を見て
`ALTER TABLE ... ADD COLUMN` する方式を取っている。`Base.metadata.create_all` は
テーブルを作るだけで、既存テーブルへの列追加もインデックス追加もしない。

`main` から切り出してあるのは、ここが「一度きり・本番の復元不能なデータに対して走る」
コードだからで、cv2 等を読み込む `main` を import せずにテストできるようにするため。
"""

from sqlalchemy import text

# Company Code 導入前から在る「唯一の」Organization に一度だけ入れる値（docs/identity/adr/0002）。
LEGACY_ORGANIZATION_CODE = "ykr"


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

    _migrate_users(connection)
    _migrate_organization_codes(connection)


def _migrate_users(connection) -> None:
    """ログインIDを全社通し一意から Organization 内一意へ張り替える。"""
    user_columns = _columns(connection, "users")
    if "activated_at" not in user_columns:
        connection.execute(text("ALTER TABLE users ADD COLUMN activated_at DATETIME"))
        # 招待の導入前から在る利用者は全員すでに使えているので、有効化済みとして扱う。
        # この列追加の分岐の中でだけ実行すること。毎起動で走らせると、招待待ちの利用者まで
        # 勝手に有効化してしまう。
        connection.execute(text("UPDATE users SET activated_at = created_at WHERE activated_at IS NULL"))
    if "is_provider_operator" not in user_columns:
        connection.execute(text("ALTER TABLE users ADD COLUMN is_provider_operator BOOLEAN DEFAULT 0"))

    # unique=True と index=True を併記した列は独立した CREATE UNIQUE INDEX になる（origin='c'）ので
    # DROP できる。unique=True 単独ならテーブル制約（origin='u'）になり、テーブル再構築が要る。
    # 握りつぶすと「2社目が admin を使えない」という本来直したい欠陥が数ヶ月後に再発するので、
    # 想定外の形だったときは黙って続けず起動を止める。
    for _seq, name, _unique, origin, *_rest in connection.execute(text("PRAGMA index_list('users')")):
        if name == "ix_users_username" and origin != "c":
            raise RuntimeError(
                "ix_users_username がテーブル制約由来です。users テーブルの再構築が必要です"
            )
    connection.execute(text("DROP INDEX IF EXISTS ix_users_username"))
    # (organization_id, username) は username 単独より弱い制約なので、既存データで必ず成功する
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_org_username ON users (organization_id, username)"
    ))


def _migrate_organization_codes(connection) -> None:
    """Company Code を導入し、導入前から在る唯一の Organization にだけ既定値を入れる。"""
    if "code" not in _columns(connection, "organizations"):
        connection.execute(text("ALTER TABLE organizations ADD COLUMN code VARCHAR DEFAULT ''"))

    # COUNT(*) = 1 が肝。新規DB（0件）ではコードも Organization もでっち上げず、
    # 既に複数ある状態では何も触らない。これが無いと、将来コード未設定の Organization が
    # 混入したときに他社のログイン名前空間へ接ぎ木してしまう。
    connection.execute(
        text(
            "UPDATE organizations SET code = :code "
            "WHERE (code IS NULL OR code = '') AND (SELECT COUNT(*) FROM organizations) = 1"
        ),
        {"code": LEGACY_ORGANIZATION_CODE},
    )
    # 順序が重要。先にUNIQUE INDEXを張ると、コード未設定が2件あるDBで '' が衝突して失敗する
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_organizations_code ON organizations (code)"
    ))

    # コードの無い Organization は、その全員が永久にログインできない Organization。
    # サポート問い合わせで気づくのではなく、起動時に分かるようにする。
    stranded = connection.execute(
        text("SELECT COUNT(*) FROM organizations WHERE code IS NULL OR code = ''")
    ).scalar()
    if stranded:
        raise RuntimeError(f"Company Code の無い Organization が {stranded} 件あります。手動で設定してください")


def _columns(connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}

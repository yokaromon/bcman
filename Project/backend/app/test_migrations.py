"""一度きり・本番の復元不能なデータに対して走るマイグレーションの検証。

ローカルに本番DBの写しが無く、リハーサルができない箇所なので、
移行前のスキーマを手で組んで実際に適用してみる。
`app.main` を import しないので cv2/numpy を読み込まず速い。
"""

import sqlite3

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base
from app.migrations import LEGACY_ORGANIZATION_CODE, apply_sqlite_migrations
from app.models import Organization, User


def _legacy_database(path) -> None:
    """Company Code と招待を導入する前のスキーマを再現する。"""
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE organizations (
            id VARCHAR NOT NULL PRIMARY KEY, name VARCHAR NOT NULL UNIQUE,
            sharing_mode VARCHAR NOT NULL, created_at DATETIME NOT NULL
        );
        CREATE TABLE users (
            id VARCHAR NOT NULL PRIMARY KEY, organization_id VARCHAR NOT NULL,
            username VARCHAR NOT NULL, name VARCHAR NOT NULL, role VARCHAR NOT NULL,
            password_hash VARCHAR NOT NULL, totp_secret VARCHAR NOT NULL,
            failed_login_count INTEGER NOT NULL, locked_until DATETIME,
            created_at DATETIME NOT NULL,
            FOREIGN KEY(organization_id) REFERENCES organizations (id)
        );
        CREATE UNIQUE INDEX ix_users_username ON users (username);
        CREATE INDEX ix_users_organization_id ON users (organization_id);
        INSERT INTO organizations VALUES ('org-1', 'ヨカロモン', 'isolated', '2026-01-01 00:00:00');
        INSERT INTO users VALUES
            ('user-1', 'org-1', 'bcman', '管理者', 'admin', 'hash', 'secret', 0, NULL, '2026-01-02 03:04:05');
        """
    )
    con.commit()
    con.close()


def _apply(path) -> None:
    """bootstrap() と同じ順序。create_all が先に走って不足テーブルを作ってから移行する。"""
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        apply_sqlite_migrations(connection)


def _indexes(path) -> dict[str, int]:
    con = sqlite3.connect(path)
    try:
        return {row[1]: row[2] for row in con.execute("PRAGMA index_list('users')")}
    finally:
        con.close()


def test_legacy_database_migrates(tmp_path):
    path = tmp_path / "legacy.db"
    _legacy_database(path)

    _apply(path)

    indexes = _indexes(path)
    assert "ix_users_username" not in indexes, "全社通しの一意制約が残っていると2社目がadminを使えない"
    assert indexes.get("ix_users_org_username") == 1, "組織内一意のインデックスがunique付きで必要"

    con = sqlite3.connect(path)
    assert con.execute("select code from organizations").fetchone()[0] == LEGACY_ORGANIZATION_CODE
    # ここが抜けると、移行した瞬間に既存利用者全員がログインできなくなる
    assert con.execute("select activated_at from users").fetchone()[0] is not None
    con.close()


def test_migration_is_idempotent(tmp_path):
    path = tmp_path / "legacy.db"
    _legacy_database(path)

    _apply(path)
    _apply(path)

    con = sqlite3.connect(path)
    assert con.execute("select code from organizations").fetchone()[0] == LEGACY_ORGANIZATION_CODE
    con.close()
    assert _indexes(path).get("ix_users_org_username") == 1


def test_fresh_database_invents_nothing(tmp_path):
    path = tmp_path / "fresh.db"

    _apply(path)

    con = sqlite3.connect(path)
    assert con.execute("select count(*) from organizations").fetchone()[0] == 0
    con.close()
    assert _indexes(path).get("ix_users_org_username") == 1


def test_existing_codes_are_left_alone(tmp_path):
    """既に複数の Organization がある状態では、既定コードを配らない。"""
    path = tmp_path / "multi.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Organization(id="a", name="A社", code="acme"))
        db.add(Organization(id="b", name="B社", code="beta"))
        db.commit()

    _apply(path)

    with Session(engine) as db:
        codes = {row.code for row in db.query(Organization)}
    assert codes == {"acme", "beta"}


def test_stranded_organization_stops_startup(tmp_path):
    """コードの無い Organization は全員がログイン不能。黙って起動させない。"""
    path = tmp_path / "stranded.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Organization(id="a", name="A社", code="acme"))
        db.add(Organization(id="b", name="B社", code=""))
        db.commit()

    with pytest.raises(RuntimeError, match="Company Code"):
        _apply(path)


def test_login_id_is_unique_per_organization(tmp_path):
    """この機能全体が乗っている性質。各社が admin を持てて、同一社内では重複できない。"""
    path = tmp_path / "unique.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)

    def _user(org_id: str, user_id: str) -> User:
        return User(id=user_id, organization_id=org_id, username="admin", name="管理者",
                    role="admin", password_hash="x", totp_secret="x")

    with Session(engine) as db:
        db.add(Organization(id="a", name="A社", code="acme"))
        db.add(Organization(id="b", name="B社", code="beta"))
        db.add(_user("a", "u1"))
        db.add(_user("b", "u2"))
        db.commit()

    with Session(engine) as db:
        db.add(_user("a", "u3"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_table_constraint_shaped_index_is_refused(tmp_path):
    """username が unique=True 単独で作られたDBは DROP INDEX できない。黙って進めない。"""
    path = tmp_path / "constraint.db"
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE organizations (
            id VARCHAR NOT NULL PRIMARY KEY, name VARCHAR NOT NULL,
            sharing_mode VARCHAR NOT NULL, created_at DATETIME NOT NULL
        );
        CREATE TABLE users (
            id VARCHAR NOT NULL PRIMARY KEY, organization_id VARCHAR NOT NULL,
            username VARCHAR NOT NULL UNIQUE, name VARCHAR NOT NULL, role VARCHAR NOT NULL,
            password_hash VARCHAR NOT NULL, totp_secret VARCHAR NOT NULL,
            failed_login_count INTEGER NOT NULL, locked_until DATETIME,
            created_at DATETIME NOT NULL
        );
        """
    )
    con.commit()
    # SQLite はテーブル制約由来のインデックスを sqlite_autoindex_* として作るため、
    # ix_users_username という名前では現れない。名前を合わせて origin を検査させる
    con.close()

    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        rows = list(connection.execute(text("PRAGMA index_list('users')")))
    assert any(origin == "u" for _seq, _name, _unique, origin, *_rest in rows), (
        "テーブル制約由来のインデックスは origin='u' として現れる"
    )

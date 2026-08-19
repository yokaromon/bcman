"""会社コード付きログインと、未有効化利用者の扱い。"""

import uuid

import pyotp
import pytest
from fastapi.testclient import TestClient

from app import auth
from app.database import SessionLocal
from app.main import app
from app.models import Organization, User

PASSWORD = "correct-horse-battery"


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def _organization_with(username: str, *, activated: bool = True) -> tuple[str, str]:
    """(会社コード, TOTP秘密鍵) を返す。"""
    code = "c" + uuid.uuid4().hex[:8]
    secret = auth.generate_totp_secret()
    with SessionLocal() as db:
        org = Organization(name=f"会社{code}", code=code)
        db.add(org); db.flush()
        db.add(User(
            organization_id=org.id, username=username, name="利用者", role="admin",
            password_hash=auth.hash_password(PASSWORD) if activated else "",
            totp_secret=secret if activated else "",
            activated_at=auth.now() if activated else None,
        ))
        db.commit()
    return code, secret


def _login(client: TestClient, code: str, username: str, password: str = PASSWORD):
    return client.post("/api/auth/login", json={"company_code": code, "username": username, "password": password})


def _login_fully(client: TestClient, code: str, username: str, secret: str) -> None:
    """未知端末なのでTOTPまで通さないとセッションが出ない。"""
    first = _login(client, code, username)
    assert first.json()["status"] == "totp_required"
    verified = client.post("/api/auth/verify-totp", json={"code": pyotp.TOTP(secret).now()})
    assert verified.status_code == 200


def test_same_login_id_in_two_companies(client):
    """この機能の目的そのもの。各社が admin を持てて、混ざらない。"""
    first, first_secret = _organization_with("admin")
    second, second_secret = _organization_with("admin")

    _login_fully(client, first, "admin", first_secret)
    assert client.get("/api/auth/me").json()["company_code"] == first
    client.cookies.clear()
    _login_fully(client, second, "admin", second_secret)
    assert client.get("/api/auth/me").json()["company_code"] == second


def test_company_code_is_normalized(client):
    """スマホのキーボードは先頭を大文字にしがち。"""
    code, _secret = _organization_with("admin")

    assert _login(client, f"  {code.upper()}  ", "admin").json()["status"] == "totp_required"


def test_unactivated_user_is_indistinguishable_from_a_missing_one(client):
    """未有効化に親切な文言を出すと、最も推測しやすい初期管理者IDの実在を確認させてしまう。"""
    code, _secret = _organization_with("admin", activated=False)

    unactivated = _login(client, code, "admin")
    missing_user = _login(client, code, "nobody")
    missing_company = _login(client, "no-such-company", "admin")

    assert unactivated.status_code == missing_user.status_code == missing_company.status_code == 401
    # 本文まで一致していることが性質そのもの。状態コードだけの比較では足りない
    assert unactivated.json() == missing_user.json() == missing_company.json()


def test_wrong_company_code_does_not_reach_another_company(client):
    first, _first_secret = _organization_with("admin")
    second, _second_secret = _organization_with("staff")

    assert _login(client, first, "staff").status_code == 401
    assert _login(client, second, "admin").status_code == 401


def test_members_exclude_unactivated_users(client):
    """登録者の選択肢に、まだ受け取っていない人を出さない。"""
    code = "c" + uuid.uuid4().hex[:8]
    secret = auth.generate_totp_secret()
    with SessionLocal() as db:
        org = Organization(name=f"会社{code}", code=code)
        db.add(org); db.flush()
        db.add(User(organization_id=org.id, username="admin", name="管理者", role="admin",
                    password_hash=auth.hash_password(PASSWORD), totp_secret=secret,
                    activated_at=auth.now()))
        db.add(User(organization_id=org.id, username="newcomer", name="新人", role="member",
                    password_hash="", totp_secret="", activated_at=None))
        db.commit()

    _login_fully(client, code, "admin", secret)
    names = {member["name"] for member in client.get("/api/members").json()}

    assert names == {"管理者"}

"""運営者権限の境界。払い出しはできるが、他社のデータには一切届かないこと。"""

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


def _account(*, provider: bool) -> tuple[str, str, str]:
    """(会社コード, username, TOTP秘密鍵) を返す。"""
    code = "c" + uuid.uuid4().hex[:8]
    secret = auth.generate_totp_secret()
    with SessionLocal() as db:
        org = Organization(name=f"会社{code}", code=code)
        db.add(org); db.flush()
        db.add(User(organization_id=org.id, username="admin", name="管理者", role="admin",
                    is_provider_operator=provider, password_hash=auth.hash_password(PASSWORD),
                    totp_secret=secret, activated_at=auth.now()))
        db.commit()
    return code, "admin", secret


def _sign_in(client: TestClient, code: str, username: str, secret: str) -> None:
    client.post("/api/auth/login", json={"company_code": code, "username": username, "password": PASSWORD})
    client.post("/api/auth/verify-totp", json={"code": pyotp.TOTP(secret).now()})


def test_ordinary_admin_cannot_reach_provider_endpoints(client):
    code, username, secret = _account(provider=False)
    _sign_in(client, code, username, secret)

    assert client.get("/api/provider/organizations").status_code == 403
    assert client.post("/api/provider/organizations", json={
        "name": "勝手に作った会社", "code": "sneaky", "admin_username": "admin", "admin_name": "管理者",
    }).status_code == 403


def test_provider_creates_an_organization_and_gets_an_invitation(client):
    code, username, secret = _account(provider=True)
    _sign_in(client, code, username, secret)
    new_code = "n" + uuid.uuid4().hex[:8]

    response = client.post("/api/provider/organizations", json={
        "name": f"新会社{new_code}", "code": new_code.upper(),
        "admin_username": "admin", "admin_name": "新社の管理者",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["company_code"] == new_code, "会社コードは小文字へ正規化される"
    assert body["qr_data_url"].startswith("data:image/png;base64,")
    assert f"/invite/" in body["invitation_url"]

    # 作られた管理者はまだ受け取っていないのでログインできない
    client.cookies.clear()
    blocked = client.post("/api/auth/login", json={"company_code": new_code, "username": "admin", "password": PASSWORD})
    assert blocked.status_code == 401


def test_provider_cannot_read_tenant_data(client):
    """払い出しはできるが名刺・連絡先には届かない、が運営者権限の定義そのもの。"""
    other_code, _username, _secret = _account(provider=False)
    with SessionLocal() as db:
        other_org_id = db.query(Organization).filter_by(code=other_code).one().id

    code, username, secret = _account(provider=True)
    _sign_in(client, code, username, secret)

    # 既存の管理者用エンドポイントは自組織チェックを一切緩めていない
    assert client.get(f"/api/organizations/{other_org_id}/users").status_code == 403
    assert client.get(f"/api/organizations/{other_org_id}/audit-logs").status_code == 403


def test_duplicate_company_code_is_refused(client):
    code, username, secret = _account(provider=True)
    _sign_in(client, code, username, secret)

    response = client.post("/api/provider/organizations", json={
        "name": "別名の会社", "code": code, "admin_username": "admin", "admin_name": "管理者",
    })

    assert response.status_code == 409


def test_invalid_company_code_is_rejected(client):
    code, username, secret = _account(provider=True)
    _sign_in(client, code, username, secret)

    for bad in ("ab", "has space", "日本語", "x" * 21):
        response = client.post("/api/provider/organizations", json={
            "name": f"会社{bad}", "code": bad, "admin_username": "admin", "admin_name": "管理者",
        })
        assert response.status_code == 422, f"{bad!r} は弾かれるべき"


def test_provider_reinvite_is_audited_and_visible_to_the_affected_admin(client):
    """運営者を抑止できるのは監査だけ。当事者が読めなければ抑止になっていない。"""
    victim_code, _u, victim_secret = _account(provider=False)
    with SessionLocal() as db:
        victim = db.query(User).join(Organization, Organization.id == User.organization_id).filter(
            Organization.code == victim_code).one()
        victim_id, victim_org_id = victim.id, victim.organization_id

    code, username, secret = _account(provider=True)
    _sign_in(client, code, username, secret)
    issued = client.post(f"/api/provider/organizations/{victim_org_id}/users/{victim_id}/invitations")
    assert issued.status_code == 200

    client.cookies.clear()
    _sign_in(client, victim_code, "admin", victim_secret)
    actions = [row["action"] for row in client.get(f"/api/organizations/{victim_org_id}/audit-logs").json()]

    assert "provider_invite_user" in actions

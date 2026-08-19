"""招待の発行・完了の性質を固定する。

特に「発行はアカウントを一切変えない」と「完了は古いアクセスを全部切る」の2つは、
崩れても通常操作では気づけないので必ずテストで押さえる。
"""

import uuid

import pyotp
import pytest
from fastapi.testclient import TestClient

from app import auth
from app.database import SessionLocal
from app.main import app
from app.models import Group, Invitation, LoginSession, Organization, TrustedDevice, User, UserGroup

PASSWORD = "correct-horse-battery"


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def _unique_code() -> str:
    return "c" + uuid.uuid4().hex[:8]


def _organization(activated_admin: bool = True) -> tuple[str, str, str]:
    """組織・グループ・管理者を作り、(会社コード, 管理者ID, 管理者のusername) を返す。"""
    code = _unique_code()
    with SessionLocal() as db:
        org = Organization(name=f"会社{code}", code=code)
        db.add(org); db.flush()
        group = Group(organization_id=org.id, name="一般")
        db.add(group); db.flush()
        admin = User(
            organization_id=org.id, username="admin", name="管理者", role="admin",
            password_hash=auth.hash_password(PASSWORD) if activated_admin else "",
            totp_secret=auth.generate_totp_secret() if activated_admin else "",
            activated_at=auth.now() if activated_admin else None,
        )
        db.add(admin); db.flush()
        db.add(UserGroup(user_id=admin.id, group_id=group.id))
        db.commit()
        return code, admin.id, admin.username


def _login(client: TestClient, code: str, username: str, password: str = PASSWORD):
    return client.post("/api/auth/login", json={"company_code": code, "username": username, "password": password})


def _token_for(user_id: str) -> Invitation:
    with SessionLocal() as db:
        return db.query(Invitation).filter_by(user_id=user_id).filter(
            Invitation.used_at.is_(None), Invitation.revoked_at.is_(None)
        ).one()


def _issue_directly(user_id: str, issued_by_id: str) -> str:
    """APIを通さず招待を作り、生トークンを返す。"""
    from app.invitations import issue_invitation

    with SessionLocal() as db:
        target, issuer = db.get(User, user_id), db.get(User, issued_by_id)
        issued = issue_invitation(db, target, issuer)
        db.commit()
    return issued["invitation_url"].rsplit("/", 1)[-1]


def test_issuing_does_not_disturb_the_account(client):
    """発行は純粋に追加的。誤クリックで生きている認証アプリを壊してはいけない。"""
    code, admin_id, username = _organization()
    with SessionLocal() as db:
        before = db.get(User, admin_id)
        secret_before, hash_before = before.totp_secret, before.password_hash

    _issue_directly(admin_id, admin_id)

    with SessionLocal() as db:
        after = db.get(User, admin_id)
        assert after.totp_secret == secret_before
        assert after.password_hash == hash_before
    assert _login(client, code, username).status_code == 200


def test_completion_replaces_credentials_and_cuts_old_access(client):
    code, admin_id, username = _organization()
    with SessionLocal() as db:
        db.add(TrustedDevice(user_id=admin_id, token_hash="old-device", expires_at=auth.now() + auth.DEVICE_TRUST_PERIOD))
        db.add(LoginSession(token_hash="old-session", user_id=admin_id))
        db.commit()

    token = _issue_directly(admin_id, admin_id)
    secret = _token_for(admin_id).totp_secret
    new_password = "brand-new-password"

    response = client.post(f"/api/invitations/{token}/complete",
                           json={"password": new_password, "code": pyotp.TOTP(secret).now()})
    assert response.status_code == 200

    with SessionLocal() as db:
        assert db.query(TrustedDevice).filter_by(token_hash="old-device").one().revoked_at is not None
        assert db.query(LoginSession).filter_by(token_hash="old-session").first() is None, \
            "端末失効だけでは既存セッションが最大8時間生き残り、乗っ取りが復旧を生き延びる"
        invitation = db.query(Invitation).filter_by(user_id=admin_id).one()
        assert invitation.used_at is not None
        assert invitation.totp_secret == "", "使用済みの行を生きた秘密鍵の複製にしない"

    client.cookies.clear()
    assert _login(client, code, username, new_password).status_code == 200
    client.cookies.clear()
    assert _login(client, code, username, PASSWORD).status_code == 401


def test_invitation_is_single_use(client):
    _code, admin_id, _username = _organization()
    token = _issue_directly(admin_id, admin_id)
    secret = _token_for(admin_id).totp_secret

    first = client.post(f"/api/invitations/{token}/complete",
                        json={"password": "first-password-x", "code": pyotp.TOTP(secret).now()})
    assert first.status_code == 200
    client.cookies.clear()
    second = client.post(f"/api/invitations/{token}/complete",
                         json={"password": "second-password-x", "code": pyotp.TOTP(secret).now()})
    assert second.status_code == 404


def test_expired_invitation_is_refused(client):
    _code, admin_id, _username = _organization()
    token = _issue_directly(admin_id, admin_id)
    with SessionLocal() as db:
        invitation = db.query(Invitation).filter_by(user_id=admin_id).one()
        invitation.expires_at = auth.now() - auth.PENDING_LOGIN_TTL
        db.commit()

    assert client.get(f"/api/invitations/{token}").status_code == 404


def test_wrong_code_neither_activates_nor_consumes(client):
    """コードを打ち間違えただけで招待を失うと、やり直す手段が無くなる。"""
    code = _unique_code()
    with SessionLocal() as db:
        org = Organization(name=f"会社{code}", code=code)
        db.add(org); db.flush()
        issuer = User(organization_id=org.id, username="admin", name="管理者", role="admin",
                      password_hash=auth.hash_password(PASSWORD), totp_secret=auth.generate_totp_secret(),
                      activated_at=auth.now())
        pending = User(organization_id=org.id, username="newcomer", name="新人", role="member",
                       password_hash="", totp_secret="", activated_at=None)
        db.add(issuer); db.add(pending); db.commit()
        issuer_id, pending_id = issuer.id, pending.id

    token = _issue_directly(pending_id, issuer_id)
    response = client.post(f"/api/invitations/{token}/complete",
                           json={"password": "a-valid-password", "code": "000000"})

    assert response.status_code == 400
    with SessionLocal() as db:
        assert db.get(User, pending_id).activated_at is None
        assert db.query(Invitation).filter_by(user_id=pending_id).one().used_at is None


def test_reissue_revokes_the_previous_invitation(client):
    _code, admin_id, _username = _organization()
    first_token = _issue_directly(admin_id, admin_id)
    _issue_directly(admin_id, admin_id)

    assert client.get(f"/api/invitations/{first_token}").status_code == 404, \
        "再発行のたびに生きたトークンが増えるのは逆方向"


def test_invitation_page_shows_the_company_code(client):
    """本人が会社コードを知る唯一の機会。ここが抜けると次回ログインで必ず詰まる。"""
    code, admin_id, _username = _organization()
    token = _issue_directly(admin_id, admin_id)

    body = client.get(f"/api/invitations/{token}").json()

    assert body["company_code"] == code
    assert body["totp_qr_data_url"].startswith("data:image/png;base64,")
    assert code in body["otpauth_uri"], "会社ごとに同じIDがある以上、認証アプリの表示名で区別できる必要がある"

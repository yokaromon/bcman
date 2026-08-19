"""招待の発行と完了。docs/identity/CONTEXT.md の Invitation、docs/identity/adr/0002 参照。

管理者用と運営者用の両方のルータがここを呼ぶ。規則を1箇所に集めておかないと、
片方だけ失効処理が漏れるといった食い違いが起きる。
"""

from datetime import timedelta

from fastapi import HTTPException, Request, Response
from sqlalchemy.orm import Session

from . import auth
from .models import Invitation, LoginSession, Organization, PendingLogin, TrustedDevice, User
from .qr import qr_data_url
from .settings import settings

INVITATION_TTL = timedelta(hours=24)


def issue_invitation(db: Session, target: User, issued_by: User) -> dict:
    """招待を発行する。アカウント自体には一切触れない。

    パスワード・TOTP・セッション・信頼済み端末・ロック状態のいずれも変えない。
    発行を純粋に追加的な操作にしておかないと、誤クリックひとつで作業中の利用者を
    追い出したり、届かなかったリンクを唯一の復旧手段にしてしまう。
    """
    _revoke_open_invitations(db, target.id)
    token = auth.new_token()
    invitation = Invitation(
        token_hash=auth.hash_token(token),
        user_id=target.id,
        totp_secret=auth.generate_totp_secret(),
        issued_by_user_id=issued_by.id,
        expires_at=auth.now() + INVITATION_TTL,
    )
    db.add(invitation)
    url = f"{settings.public_base_url.rstrip('/')}/invite/{token}"
    return {
        "invitation_url": url,
        "qr_data_url": qr_data_url(url),
        "expires_at": invitation.expires_at,
        "username": target.username,
        "name": target.name,
    }


def resolve_invitation(db: Session, token: str) -> Invitation:
    """使える招待だけを返す。期限切れ・使用済み・失効済み・不存在は区別しない。"""
    invitation = db.get(Invitation, auth.hash_token(token))
    usable = (
        invitation is not None
        and invitation.used_at is None
        and invitation.revoked_at is None
        and invitation.expires_at > auth.now()
    )
    if not usable:
        raise HTTPException(404, "この招待は使えません。発行者に再発行を依頼してください")
    return invitation


def describe_invitation(db: Session, invitation: Invitation) -> dict:
    """招待ページに出す内容。会社コードを本人が知る唯一の機会になる。"""
    user = db.get(User, invitation.user_id)
    org = db.get(Organization, user.organization_id)
    otpauth = auth.totp_provisioning_uri(invitation.totp_secret, org.code, user.username)
    return {
        "organization_name": org.name,
        "company_code": org.code,
        "username": user.username,
        "name": user.name,
        "otpauth_uri": otpauth,
        "totp_qr_data_url": qr_data_url(otpauth),
        "expires_at": invitation.expires_at,
    }


def complete_invitation(
    db: Session, invitation: Invitation, password: str, code: str,
    request: Request, response: Response,
) -> User:
    """本人がパスワードを決め、認証アプリの登録を証明して受け取りを完了する。

    失敗をロックアウトカウンタへ繋げない。トークンを持つ者が対象アカウントを任意に
    ロックできてしまううえ、そもそもトークン保持者は招待ページから秘密鍵を読めるので
    総当たりの的ではない。トークンが資格情報であり、コード入力は本人確認ではなく
    「認証アプリに登録できたこと」の証明。
    """
    if not auth.verify_totp(invitation.totp_secret, code):
        raise HTTPException(400, "認証アプリのコードが違います")

    user = db.get(User, invitation.user_id)
    user.password_hash = auth.hash_password(password)
    user.totp_secret = invitation.totp_secret
    user.activated_at = auth.now()
    # ロックアウトからの復旧で招待を使うことがある。ここを忘れると復旧が復旧にならない
    user.failed_login_count, user.locked_until = 0, None

    # 端末を失くした・盗られたという状況で使うので、古い端末は全部切る
    for device in db.query(TrustedDevice).filter_by(user_id=user.id).filter(TrustedDevice.revoked_at.is_(None)):
        device.revoked_at = auth.now()
    # 端末の失効は「次回ログイン」にしか効かない。current_user は LoginSession しか見ないため、
    # ここで消さないとセッションCookieが最大8時間生き残り、乗っ取りが自分の復旧を生き延びる
    db.query(LoginSession).filter_by(user_id=user.id).delete()
    db.query(PendingLogin).filter_by(user_id=user.id).delete()

    invitation.used_at = auth.now()
    invitation.totp_secret = ""  # 使用済みの行を生きた秘密鍵の複製にしておかない
    _revoke_open_invitations(db, user.id)

    # セッション発行は最後。先に出すと上の LoginSession 削除で消えてしまう
    auth.issue_session(db, user, response)
    auth.issue_trusted_device(db, user, request, response)
    return user


def _revoke_open_invitations(db: Session, user_id: str) -> None:
    """未使用の招待を失効させる。再発行のたびに生きたトークンが増えるのは逆方向。"""
    open_invitations = db.query(Invitation).filter_by(user_id=user_id).filter(
        Invitation.used_at.is_(None), Invitation.revoked_at.is_(None)
    )
    for invitation in open_invitations:
        invitation.revoked_at = auth.now()

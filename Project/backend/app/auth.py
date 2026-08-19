import hashlib
import secrets
from datetime import datetime, timedelta

import bcrypt
import pyotp
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .database import get_db
from .models import LoginSession, PendingLogin, TrustedDevice, User
from .settings import settings

SESSION_COOKIE = "bcman_session"
DEVICE_COOKIE = "bcman_device"
PENDING_COOKIE = "bcman_pending"
TRUSTED_NETWORK_HEADER = "X-Trusted-Network"  # nginxがオフィスの固定IPからの時だけ立てる

SESSION_IDLE_TIMEOUT = timedelta(hours=8)
DEVICE_TRUST_PERIOD = timedelta(days=90)
PENDING_LOGIN_TTL = timedelta(minutes=5)
LOCKOUT_THRESHOLD = 5
LOCKOUT_DURATION = timedelta(minutes=15)

def now() -> datetime: return datetime.utcnow()

# --- パスワード ---

# 存在しない利用者のログイン試行でも、これに対して照合して所要時間を揃えるためのダミー。
# 実在しないIDだと bcrypt を通らず即座に返る状態だと、応答本文が同じでも所要時間で
# IDや会社コードの実在を推測できてしまう。起動のたびに生成すると毎回100ms掛かるので定数。
ABSENT_USER_PASSWORD_HASH = "$2b$12$C6UzMDM.H6dfI/f/IKcEe.3fCPaFTRxOhYAf/hnfKZbhIuqNTUJmy"

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())

# --- TOTP（未知端末の登録コード） ---

def generate_totp_secret() -> str: return pyotp.random_base32()
def totp_provisioning_uri(secret: str, company_code: str, username: str) -> str:
    """認証アプリに出る名前。会社コードを含めるのは、各社が admin を使える以上、
    含めないと「BCMan: admin」が複数並んで本人が見分けられなくなるため。"""
    return pyotp.TOTP(secret).provisioning_uri(name=f"{company_code}/{username}", issuer_name="BCMan")
def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)

# --- 不透明トークン（Cookieに入れる値とDBに残す値は別） ---

def new_token() -> str: return secrets.token_urlsafe(32)
def hash_token(token: str) -> str: return hashlib.sha256(token.encode()).hexdigest()

# --- ロックアウト（パスワード・TOTP共通） ---

def check_not_locked(user: User):
    if user.locked_until and user.locked_until > now():
        raise HTTPException(423, "試行回数が多すぎます。時間をおいて再度お試しください")

def register_failure(db: Session, user: User):
    user.failed_login_count += 1
    if user.failed_login_count >= LOCKOUT_THRESHOLD:
        user.locked_until = now() + LOCKOUT_DURATION
    db.commit()

def register_success(db: Session, user: User):
    user.failed_login_count = 0
    user.locked_until = None
    db.commit()

# --- 端末信頼・指定IP ---

def is_trusted_network(request: Request) -> bool:
    return request.headers.get(TRUSTED_NETWORK_HEADER) == "1"

def find_trusted_device(db: Session, user: User, request: Request) -> TrustedDevice | None:
    token = request.cookies.get(DEVICE_COOKIE)
    if not token: return None
    device = db.query(TrustedDevice).filter_by(token_hash=hash_token(token), user_id=user.id).first()
    if not device or device.revoked_at or device.expires_at < now(): return None
    return device

def issue_trusted_device(db: Session, user: User, request: Request, response: Response) -> None:
    token = new_token()
    label = request.headers.get("User-Agent", "")[:200]
    db.add(TrustedDevice(user_id=user.id, token_hash=hash_token(token), label=label, expires_at=now() + DEVICE_TRUST_PERIOD))
    db.commit()
    response.set_cookie(DEVICE_COOKIE, token, max_age=int(DEVICE_TRUST_PERIOD.total_seconds()), httponly=True, secure=settings.cookie_secure, samesite="lax")

# --- セッション ---

def issue_session(db: Session, user: User, response: Response) -> None:
    token = new_token()
    db.add(LoginSession(token_hash=hash_token(token), user_id=user.id))
    db.commit()
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=settings.cookie_secure, samesite="lax")

def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    session = db.query(LoginSession).filter_by(token_hash=hash_token(token)).first() if token else None
    if not session or session.last_seen_at + SESSION_IDLE_TIMEOUT < now():
        raise HTTPException(401, "ログインが必要です")
    user = db.get(User, session.user_id)
    if not user: raise HTTPException(401, "ログインが必要です")
    session.last_seen_at = now(); db.commit()
    return user

def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin": raise HTTPException(403, "管理者のみ")
    return user

def clear_session(request: Request, response: Response, db: Session) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token: db.query(LoginSession).filter_by(token_hash=hash_token(token)).delete()
    db.commit()
    response.delete_cookie(SESSION_COOKIE)

# --- ログイン保留状態（ID・パスワード確認後、TOTP入力待ち） ---

def issue_pending_login(db: Session, user: User, response: Response) -> None:
    token = new_token()
    db.add(PendingLogin(token_hash=hash_token(token), user_id=user.id, expires_at=now() + PENDING_LOGIN_TTL))
    db.commit()
    response.set_cookie(PENDING_COOKIE, token, max_age=int(PENDING_LOGIN_TTL.total_seconds()), httponly=True, secure=settings.cookie_secure, samesite="lax")

def resolve_pending_login(db: Session, request: Request) -> User:
    token = request.cookies.get(PENDING_COOKIE)
    pending = db.query(PendingLogin).filter_by(token_hash=hash_token(token)).first() if token else None
    if not pending or pending.expires_at < now():
        raise HTTPException(401, "ログインをやり直してください")
    user = db.get(User, pending.user_id)
    if not user: raise HTTPException(401, "ログインをやり直してください")
    return user

def clear_pending_login(request: Request, response: Response, db: Session) -> None:
    token = request.cookies.get(PENDING_COOKIE)
    if token: db.query(PendingLogin).filter_by(token_hash=hash_token(token)).delete()
    db.commit()
    response.delete_cookie(PENDING_COOKIE)

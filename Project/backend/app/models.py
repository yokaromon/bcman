import uuid
from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

def uid() -> str: return str(uuid.uuid4())
def now() -> datetime: return datetime.utcnow()

class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String, unique=True)
    sharing_mode: Mapped[str] = mapped_column(String, default="isolated")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Group(Base):
    __tablename__ = "groups"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String)

class User(Base):
    """1ユーザは生涯にわたって単一の Organization に属する。所属 Group は
    UserGroup 側の多対多で、Organization を跨ぐ所属はない前提（docs/identity/CONTEXT.md）。"""
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default="member")  # "admin" | "member"
    password_hash: Mapped[str] = mapped_column(String)
    totp_secret: Mapped[str] = mapped_column(String)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class UserGroup(Base):
    """User と Group の多対多所属。isolated モードでの閲覧範囲はここに属する全 Group の和集合。"""
    __tablename__ = "user_groups"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"), index=True)

class LoginSession(Base):
    """ログイン成功後のセッション。トークンそのものではなくハッシュを保持し、
    Cookie が漏れてもDBダンプだけからは再利用できないようにする。"""
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class PendingLogin(Base):
    """ID・パスワード確認後、TOTPコード入力を待つ間だけ存在する短命の状態。
    未知端末・指定IP外のログインでのみ発生する（app/auth.py）。"""
    __tablename__ = "pending_logins"
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)

class TrustedDevice(Base):
    """TOTPを一度通過した端末の記憶。90日で自動失効し、revoked_at があれば
    それより前倒しで即時失効（紛失時に管理者が使う）。"""
    __tablename__ = "trusted_devices"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    label: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class Photo(Base):
    __tablename__ = "photos"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"), index=True)
    original_filename: Mapped[str] = mapped_column(String)
    storage_path: Mapped[str] = mapped_column(String)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, default="uploaded")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class BusinessCard(Base):
    __tablename__ = "business_cards"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    photo_id: Mapped[str] = mapped_column(ForeignKey("photos.id"), index=True)
    detected_image_path: Mapped[str] = mapped_column(String)
    corrected_image_path: Mapped[str] = mapped_column(String)
    oriented_image_path: Mapped[str] = mapped_column(String, default="")
    orientation: Mapped[int] = mapped_column(Integer, default=0)
    detection_confidence: Mapped[float] = mapped_column(Float, default=0)
    x: Mapped[int] = mapped_column(Integer, default=0)
    y: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="detected")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class OCRResult(Base):
    __tablename__ = "card_ocr_results"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    card_id: Mapped[str] = mapped_column(ForeignKey("business_cards.id"), index=True)
    engine: Mapped[str] = mapped_column(String)
    engine_version: Mapped[str] = mapped_column(String, default="")
    raw_text: Mapped[str] = mapped_column(Text, default="")
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    card_id: Mapped[str] = mapped_column(ForeignKey("business_cards.id"), unique=True, index=True)
    company_name: Mapped[str | None] = mapped_column(String, nullable=True)
    company_name_kana: Mapped[str | None] = mapped_column(String, nullable=True)
    department: Mapped[str | None] = mapped_column(String, nullable=True)
    position: Mapped[str | None] = mapped_column(String, nullable=True)
    person_name: Mapped[str | None] = mapped_column(String, nullable=True)
    person_name_kana: Mapped[str | None] = mapped_column(String, nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    telephone: Mapped[str | None] = mapped_column(String, nullable=True)
    fax: Mapped[str | None] = mapped_column(String, nullable=True)
    mobile: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    website: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_flags: Mapped[dict] = mapped_column(JSON, default=dict)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    # 登録者(Card Owner)・名刺交換日(Exchanged At)。confirm()/confirm_cards()で確定時に既定値が入る。
    # docs/CONTEXT.md 参照
    card_owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    exchanged_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

class AuditLog(Base):
    """削除のように実体が残らない操作の記録。写真や名刺を物理削除するため、
    「何を失ったか」はこのテーブルにしか残らない。"""
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    # 利用者が消えても「誰が」を辿れるよう、外部キーではなく値の複製で持つ
    user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    user_name: Mapped[str] = mapped_column(String, default="")
    action: Mapped[str] = mapped_column(String, index=True)
    target_type: Mapped[str] = mapped_column(String)
    target_id: Mapped[str] = mapped_column(String, index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class ProcessingHistory(Base):
    __tablename__ = "processing_history"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    card_id: Mapped[str] = mapped_column(ForeignKey("business_cards.id"), index=True)
    process_type: Mapped[str] = mapped_column(String)
    engine: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String, default="")
    input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

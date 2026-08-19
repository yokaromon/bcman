import uuid
from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

def uid() -> str: return str(uuid.uuid4())
def now() -> datetime: return datetime.utcnow()

class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String, unique=True)
    # ログイン時に打つ会社コード。作成後は不変（この Organization の全員がこれでログインするため、
    # 変えた瞬間に全員が入れなくなる）。OrganizationInput にこの列を足してはいけない。
    # unique と index を両方付けるのは、既存テーブルへ後から張れる独立インデックス形式にするため。
    code: Mapped[str] = mapped_column(String, unique=True, index=True, default="")
    sharing_mode: Mapped[str] = mapped_column(String, default="isolated")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Group(Base):
    __tablename__ = "groups"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String)

class User(Base):
    """1ユーザは生涯にわたって単一の Organization に属する。所属 Group は
    UserGroup 側の多対多で、Organization を跨ぐ所属はない前提（docs/identity/CONTEXT.md）。

    ログインIDは Organization 内でのみ一意。各社が admin を使えるようにするためで、
    どの Organization かは Company Code で指定する（docs/identity/adr/0002）。"""
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    username: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default="member")  # "admin" | "member"
    # 運営者（Provider Operator）。role とは直交する能力で、Organization と初期管理者の
    # 払い出しだけを許す。名刺・連絡先へのアクセスは一切与えない（docs/identity/CONTEXT.md）。
    is_provider_operator: Mapped[bool] = mapped_column(Boolean, default=False)
    password_hash: Mapped[str] = mapped_column(String)
    totp_secret: Mapped[str] = mapped_column(String)
    # 招待を完了した時刻。NULL の間はまだ本人が受け取っていないのでログインできない
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (Index("ix_users_org_username", "organization_id", "username", unique=True),)

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

class Invitation(Base):
    """アカウントを本人が受け取るための一回限り・24時間のリンク。

    TOTP秘密鍵をここに置き、完了するまで User.totp_secret には触れないのが要点。
    発行を純粋に追加的な操作にしておかないと、誤って再招待を押しただけで生きている
    認証アプリが壊れ、復旧手段が届かなかったそのリンクだけになる。
    発行時（ページ表示時ではなく）に作るのは、招待ページを再読み込みしても
    同じ秘密鍵を出し続けるため。"""
    __tablename__ = "invitations"
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    totp_secret: Mapped[str] = mapped_column(String)
    # 他 Organization の運営者が発行することがあるので、AuditLog.user_id と同様に外部キーにしない
    issued_by_user_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

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
    # この写真をどちらの認識パイプラインで処理するか（docs/adr/0019）。既定は "v1"。
    # 管理者が明示的にopt-inした新規写真だけが "v2" になり、既存の写真は "v1" のまま。
    pipeline_version: Mapped[str] = mapped_column(String, default="v1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class BusinessCard(Base):
    __tablename__ = "business_cards"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    photo_id: Mapped[str] = mapped_column(ForeignKey("photos.id"), index=True)
    detected_image_path: Mapped[str] = mapped_column(String)
    corrected_image_path: Mapped[str] = mapped_column(String)
    oriented_image_path: Mapped[str] = mapped_column(String, default="")
    orientation: Mapped[int] = mapped_column(Integer, default=0)
    # Orientation Decision（docs/CONTEXT.md）。回転角そのものとは別に、その向きが
    # auto_confirmed / uncertain / user_confirmed のどれで決まったかを持つ。
    # V1で作られたカードは空のまま（V1に自動向き判定は無い）。
    orientation_decision: Mapped[str] = mapped_column(String, default="")
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
    # 台帳検索用に全項目を正規化して連結したもの。表記ゆれを吸収した一致を SQL 側で
    # 済ませるための派生値で、真実は各項目の側にある（app/contact_search.py 参照）
    search_text: Mapped[str] = mapped_column(Text, default="")
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

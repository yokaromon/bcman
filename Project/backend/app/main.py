import re
import shutil
from pathlib import Path
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from . import auth
from .contact_search import DEFAULT_LEDGER_STATUS, LEDGER_STATUSES, search_contacts
from .database import Base, SessionLocal, engine, get_db
from .directory import models as directory_models, service as directory_service
from .directory.routes import router as directory_router
from .invitations import complete_invitation, describe_invitation, issue_invitation, resolve_invitation
from .migrations import apply_sqlite_migrations
from .models import AuditLog, BusinessCard, Contact, Group, OCRResult, Organization, Photo, TrustedDevice, User, UserGroup
from .provider import router as provider_router
from .schemas import BatchConfirmInput, CardRegistrationInput, CompleteReviewInput, ContactInput, GroupInput, InvitationCompleteInput, LoginInput, ManualCardInput, OrientationInput, OrganizationInput, ReplacementApplyInput, ReprocessInput, TotpInput, UserInput, normalize_company_code
from .search_text import refresh_search_text
from .services import add_manual_card, apply_orientation, apply_replacement, card_image_revision, card_thumbnail, delete_card, delete_photo, discard_replacement, image_size, pending_replacement_path, photo_thumbnail, prepare_replacement, process_card, process_photo, run_ocr, structure, user_group_ids, visible_photo_query
from .settings import settings

# 写真サムネイルは原本ごと、名刺サムネイルは向き補正画像のrevisionごとにURLが変わる。
# 同じURLの中身は変わらないので、しばらくブラウザに持たせる。
# 台帳の1ページ。上限は、利用者が limit を大きくしても1回の応答が膨らみすぎないための頭打ち。
LEDGER_PAGE_SIZE = 50
LEDGER_MAX_PAGE_SIZE = 200

THUMBNAIL_CACHE_CONTROL = "private, max-age=604800"
VERSIONED_IMAGE_CACHE_CONTROL = "private, max-age=31536000, immutable"
MUTABLE_IMAGE_CACHE_CONTROL = "private, no-cache"

app = FastAPI(title="BCMan API", root_path=settings.root_path)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"], allow_credentials=True)
app.include_router(directory_router)
app.include_router(provider_router)

def bootstrap():
    """Organization・初期管理者の作成はアプリ外（scripts/create_org.py）で行う。
    ここではテーブル作成のみ。directory_models の import は使わないが、Base.metadata に
    Person/Company等を登録させるために必要（create_all は import 済みのモデルしか作らない）。"""
    _ = directory_models
    Base.metadata.create_all(engine); settings.storage_dir.mkdir(parents=True, exist_ok=True)
    if engine.dialect.name == "sqlite":
        with engine.begin() as connection:
            apply_sqlite_migrations(connection)
    backfill_search_text()

def backfill_search_text():
    """search_text 列を足す前から在る Contact を検索対象に載せる。
    未設定の行だけを対象にするので、起動のたびに全件を作り直すことはない。"""
    with SessionLocal() as db:
        pending = db.query(Contact).filter((Contact.search_text == "") | (Contact.search_text.is_(None))).all()
        if not pending: return
        for contact in pending: refresh_search_text(contact)
        db.commit()
@app.on_event("startup")
def startup(): bootstrap()

current_user = auth.current_user
require_admin = auth.require_admin

def card_for_user(card_id, db, user):
    card = db.get(BusinessCard, card_id)
    if not card or not visible_photo_query(db, user).filter(Photo.id == card.photo_id).first(): raise HTTPException(404, "名刺が見つかりません")
    return card
def uses_v2(card: BusinessCard, db: Session) -> bool:
    """この名刺がV2で作られたかを、由来する写真のpipeline_versionから判定する。
    V1とV2が同じContactを更新しないよう、再認識も必ず作成時と同じ側で行う（docs/adr/0019）。"""
    photo = db.get(Photo, card.photo_id)
    return bool(photo and photo.pipeline_version == "v2")
async def recognize(card: BusinessCard, db: Session, *, ocr: bool=True, llm: bool=True) -> None:
    if uses_v2(card, db):
        from .recognition_v2.pipeline import run_ocr_v2, structure_v2
        if ocr: await run_ocr_v2(card, db)
        if llm: await structure_v2(card, db)
        return
    if ocr: await run_ocr(card, db)
    if llm: await structure(card, db)
def record_audit(db, user, action, target_type, target_id, detail):
    db.add(AuditLog(user_id=user.id, user_name=user.name, action=action, target_type=target_type, target_id=target_id, detail=detail))
def thumbnail_response(build, cache_control=THUMBNAIL_CACHE_CONTROL):
    # 元画像が消えている古いデータでも一覧そのものは開けるよう、画像だけ 404 にする
    try: path = build()
    except (FileNotFoundError, OSError) as exc: raise HTTPException(404, "画像がありません") from exc
    return FileResponse(path, headers={"Cache-Control": cache_control})
def require_group_in_org(db: Session, org_id: str, group_ids: list[str]):
    found = db.query(Group).filter(Group.organization_id == org_id, Group.id.in_(group_ids)).count()
    if found != len(set(group_ids)): raise HTTPException(400, "指定したグループがこの組織にありません")

@app.get("/api/health")
def health(): return {"status":"ok"}

# --- 認証 ---

@app.post("/api/auth/login")
def login(body: LoginInput, request: Request, response: Response, db: Session=Depends(get_db)):
    org = db.query(Organization).filter_by(code=normalize_company_code(body.company_code)).first()
    user = db.query(User).filter_by(organization_id=org.id, username=body.username).first() if org else None
    if not user or user.activated_at is None:
        # 会社コードが無い・IDが無い・招待未完了の3つを区別させない。応答本文だけでなく
        # bcryptを空回しして所要時間まで揃える。未有効化に親切な文言を出すと、最も推測
        # しやすい文字列である初期管理者IDの実在を確認させてしまう
        auth.verify_password(body.password, auth.ABSENT_USER_PASSWORD_HASH)
        raise HTTPException(401, "IDまたはパスワードが違います")
    auth.check_not_locked(user)
    if not auth.verify_password(body.password, user.password_hash):
        auth.register_failure(db, user); raise HTTPException(401, "IDまたはパスワードが違います")
    auth.register_success(db, user)
    device = auth.find_trusted_device(db, user, request)
    if device: device.last_used_at = auth.now(); db.commit()
    if auth.is_trusted_network(request) or device:
        auth.issue_session(db, user, response); return {"status":"ok"}
    auth.issue_pending_login(db, user, response); return {"status":"totp_required"}

@app.post("/api/auth/verify-totp")
def verify_totp(body: TotpInput, request: Request, response: Response, db: Session=Depends(get_db)):
    user = auth.resolve_pending_login(db, request)
    auth.check_not_locked(user)
    if not auth.verify_totp(user.totp_secret, body.code):
        auth.register_failure(db, user); raise HTTPException(401, "コードが違います")
    auth.register_success(db, user)
    auth.clear_pending_login(request, response, db)
    auth.issue_trusted_device(db, user, request, response)
    auth.issue_session(db, user, response)
    return {"status":"ok"}

@app.post("/api/auth/logout")
def logout(request: Request, response: Response, db: Session=Depends(get_db)):
    auth.clear_session(request, response, db); return {"status":"ok"}

# --- 招待の受け取り。認証不要（トークンの所持が資格情報。docs/identity/adr/0002） ---

@app.get("/api/invitations/{token}")
def read_invitation(token: str, db: Session=Depends(get_db)):
    return describe_invitation(db, resolve_invitation(db, token))

@app.post("/api/invitations/{token}/complete")
def complete_invitation_route(token: str, body: InvitationCompleteInput, request: Request, response: Response, db: Session=Depends(get_db)):
    invitation = resolve_invitation(db, token)
    user = complete_invitation(db, invitation, body.password, body.code, request, response)
    record_audit(db, user, "invitation_completed", "user", user.id, {"organization_id": user.organization_id})
    db.commit()
    return {"status":"ok"}

@app.get("/api/auth/me")
def me(db: Session=Depends(get_db), user: User=Depends(current_user)):
    org = db.get(Organization, user.organization_id)
    groups = db.query(Group).join(UserGroup, UserGroup.group_id == Group.id).filter(UserGroup.user_id == user.id).all()
    return {"id":user.id,"username":user.username,"name":user.name,"role":user.role,"is_provider_operator":bool(user.is_provider_operator),"organization_id":user.organization_id,"company_code":org.code if org else "","sharing_mode":org.sharing_mode if org else None,"groups":[{"id":g.id,"name":g.name} for g in groups],"recognition_v2_active":settings.recognition_pipeline_v2_enabled}

# --- 組織・グループ・ユーザ管理（Organization管理者のみ。Organization自体の新規作成はシェルスクリプトで行う） ---

@app.put("/api/organizations/{org_id}")
def update_org(org_id: str, body: OrganizationInput, db: Session=Depends(get_db), user: User=Depends(require_admin)):
    if user.organization_id != org_id: raise HTTPException(403, "権限がありません")
    org = db.get(Organization, org_id)
    if not org: raise HTTPException(404, "組織が見つかりません")
    org.name, org.sharing_mode = body.name, body.sharing_mode; db.commit(); return org
@app.get("/api/organizations/{org_id}/groups")
def list_groups(org_id: str, db: Session=Depends(get_db), user: User=Depends(require_admin)):
    if user.organization_id != org_id: raise HTTPException(403, "権限がありません")
    return db.query(Group).filter_by(organization_id=org_id).all()
@app.post("/api/organizations/{org_id}/groups")
def create_group(org_id: str, body: GroupInput, db: Session=Depends(get_db), user: User=Depends(require_admin)):
    if user.organization_id != org_id: raise HTTPException(403, "権限がありません")
    item=Group(organization_id=org_id, **body.model_dump()); db.add(item); db.commit(); return item
@app.get("/api/members")
def list_members(db: Session=Depends(get_db), user: User=Depends(current_user)):
    """Card Owner（登録者）選択肢用。list_users と違い管理者限定にせず、自分のOrganizationのid/nameのみ返す。
    招待未完了の利用者は、まだ本人が受け取っていないので登録者に選べない。"""
    members = db.query(User).filter_by(organization_id=user.organization_id).filter(User.activated_at.isnot(None)).order_by(User.name)
    return [{"id":u.id,"name":u.name} for u in members]
@app.get("/api/organizations/{org_id}/users")
def list_users(org_id: str, db: Session=Depends(get_db), user: User=Depends(require_admin)):
    if user.organization_id != org_id: raise HTTPException(403, "権限がありません")
    users = db.query(User).filter_by(organization_id=org_id).all()
    # 未有効化の利用者も出す。管理者は「誰が招待中か」を見て再招待できる必要がある
    return [{"id":u.id,"username":u.username,"name":u.name,"role":u.role,"activated":u.activated_at is not None,"groups":[g.id for g in db.query(Group).join(UserGroup, UserGroup.group_id==Group.id).filter(UserGroup.user_id==u.id)]} for u in users]
@app.post("/api/organizations/{org_id}/users")
def create_user(org_id: str, body: UserInput, db: Session=Depends(get_db), user: User=Depends(require_admin)):
    if user.organization_id != org_id: raise HTTPException(403, "権限がありません")
    require_group_in_org(db, org_id, body.group_ids)
    item = create_invited_user(db, org_id, body.username, body.name, body.role, user)
    for group_id in set(body.group_ids): db.add(UserGroup(user_id=item.id, group_id=group_id))
    issued = issue_invitation(db, item, user)
    record_audit(db, user, "invite", "user", item.id, {"organization_id": org_id, "username": item.username, "reissue": False})
    db.commit()
    return issued
def create_invited_user(db: Session, org_id: str, username: str, name: str, role: str, issued_by: User) -> User:
    """招待待ちの利用者を作る。パスワードとTOTPは本人が招待を完了するまで空のまま。"""
    if db.query(User).filter_by(organization_id=org_id, username=username).first():
        raise HTTPException(409, "そのIDは既に使われています")
    item = User(organization_id=org_id, username=username, name=name, role=role,
                password_hash="", totp_secret="", activated_at=None)
    db.add(item); db.flush()
    return item
def target_user_in_org(db: Session, org_id: str, user_id: str) -> User:
    target = db.get(User, user_id)
    if not target or target.organization_id != org_id: raise HTTPException(404, "利用者が見つかりません")
    return target
@app.post("/api/organizations/{org_id}/users/{user_id}/invitations")
def reinvite_user(org_id: str, user_id: str, db: Session=Depends(get_db), admin: User=Depends(require_admin)):
    """自組織の利用者を招待し直す。パスワード忘れも認証アプリ紛失もこれ1つで戻す。"""
    if admin.organization_id != org_id: raise HTTPException(403, "権限がありません")
    target = target_user_in_org(db, org_id, user_id)
    issued = issue_invitation(db, target, admin)
    record_audit(db, admin, "invite", "user", target.id, {"organization_id": org_id, "username": target.username, "reissue": True})
    db.commit()
    return issued
@app.get("/api/organizations/{org_id}/audit-logs")
def list_audit_logs(org_id: str, limit: int=100, db: Session=Depends(get_db), admin: User=Depends(require_admin)):
    """自組織に対して行われた操作の記録。運営者が他社アカウントを触ったことを
    当事者が後から辿れるようにするためのもの（docs/identity/adr/0002）。"""
    if admin.organization_id != org_id: raise HTTPException(403, "権限がありません")
    member_ids = {row.id for row in db.query(User.id).filter_by(organization_id=org_id)}
    rows = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(max(limit, 1), 500)).all()
    visible = [row for row in rows if row.target_id in member_ids or (row.detail or {}).get("organization_id") == org_id]
    return [{"id":r.id,"user_name":r.user_name,"action":r.action,"target_type":r.target_type,"target_id":r.target_id,"detail":r.detail,"created_at":r.created_at} for r in visible]
@app.post("/api/organizations/{org_id}/users/{user_id}/unlock")
def unlock_user(org_id: str, user_id: str, db: Session=Depends(get_db), admin: User=Depends(require_admin)):
    if admin.organization_id != org_id: raise HTTPException(403, "権限がありません")
    target = target_user_in_org(db, org_id, user_id)
    target.failed_login_count, target.locked_until = 0, None; db.commit(); return {"unlocked":True}

# --- 端末管理（Organization管理者のみ） ---

@app.get("/api/organizations/{org_id}/users/{user_id}/devices")
def list_devices(org_id: str, user_id: str, db: Session=Depends(get_db), admin: User=Depends(require_admin)):
    if admin.organization_id != org_id: raise HTTPException(403, "権限がありません")
    target = db.get(User, user_id)
    if not target or target.organization_id != org_id: raise HTTPException(404, "利用者が見つかりません")
    devices = db.query(TrustedDevice).filter_by(user_id=user_id).order_by(TrustedDevice.created_at.desc()).all()
    return [{"id":d.id,"label":d.label,"created_at":d.created_at,"last_used_at":d.last_used_at,"expires_at":d.expires_at,"revoked":d.revoked_at is not None} for d in devices]
@app.delete("/api/organizations/{org_id}/devices/{device_id}")
def revoke_device(org_id: str, device_id: str, db: Session=Depends(get_db), admin: User=Depends(require_admin)):
    if admin.organization_id != org_id: raise HTTPException(403, "権限がありません")
    device = db.get(TrustedDevice, device_id)
    if not device or db.get(User, device.user_id).organization_id != org_id: raise HTTPException(404, "端末が見つかりません")
    device.revoked_at = auth.now(); db.commit(); return {"revoked":True}

# --- 名刺 ---

def resolve_pipeline_version(user: User) -> str:
    """写真ごとの選択制ではなく、`RECOGNITION_PIPELINE_V2_ENABLED` だけがV1/V2を切り替える
    唯一の分岐点（2026-08-18、写真ごとのopt-inチェックボックスをやめてこちらに一本化）。
    フラグONの間は新規写真すべてがV2で処理される。ロールバックはフラグをOFFに戻すだけでよく、
    既存カードは引き続き再処理しない（docs/adr/0019）。"""
    return "v2" if settings.recognition_pipeline_v2_enabled else "v1"

@app.post("/api/photos")
async def upload_photo(group_id: str, file: UploadFile=File(...), db: Session=Depends(get_db), user: User=Depends(current_user)):
    allowed_groups = {g.id for g in db.query(Group).filter_by(organization_id=user.organization_id)} if user.role == "admin" else set(user_group_ids(db, user))
    if group_id not in allowed_groups: raise HTTPException(400, "アップロード先のグループを正しく選択してください")
    if file.content_type not in {"image/jpeg","image/png"}: raise HTTPException(415, "JPEG または PNG のみ対応")
    photo=Photo(organization_id=user.organization_id, group_id=group_id, original_filename=file.filename or "upload", storage_path="", pipeline_version=resolve_pipeline_version(user)); db.add(photo); db.flush()
    target=settings.storage_dir/"photos"/photo.id; target.mkdir(parents=True); path=target/("original.png" if file.content_type=="image/png" else "original.jpg")
    with path.open("wb") as out: shutil.copyfileobj(file.file, out)
    if path.stat().st_size > settings.max_upload_bytes: path.unlink(); raise HTTPException(413, "20MBを超えています")
    photo.storage_path=str(path); photo.width, photo.height=image_size(path); db.commit(); return {"photo_id":photo.id,"status":"uploaded","pipeline_version":photo.pipeline_version}
@app.get("/api/photos")
def list_photos(db: Session=Depends(get_db), user: User=Depends(current_user)):
    photos=visible_photo_query(db,user).order_by(Photo.created_at.desc()).all(); ids=[p.id for p in photos]
    def tally(*conditions):
        # 一覧に「名刺 3枚 / 登録済み 2」を出すための集計。写真ごとに数えると N+1 になる
        if not ids: return {}
        query=db.query(BusinessCard.photo_id, func.count(BusinessCard.id)).filter(BusinessCard.photo_id.in_(ids), *conditions)
        return dict(query.group_by(BusinessCard.photo_id))
    total, confirmed = tally(), tally(BusinessCard.status=="confirmed")
    return [{"id":p.id,"filename":p.original_filename,"status":p.status,"created_at":p.created_at,"card_count":total.get(p.id,0),"confirmed_count":confirmed.get(p.id,0),"source_retained":bool(p.storage_path)} for p in photos]
@app.delete("/api/photos/{photo_id}")
def remove_photo(photo_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    photo=visible_photo_query(db,user).filter_by(id=photo_id).first()
    if not photo: raise HTTPException(404,"写真が見つかりません")
    record_audit(db,user,"delete","photo",photo_id,delete_photo(photo,db)); db.commit(); return {"deleted":True}
@app.get("/api/photos/{photo_id}/thumbnail")
def photo_thumb(photo_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    photo=visible_photo_query(db,user).filter_by(id=photo_id).first()
    if not photo: raise HTTPException(404,"写真が見つかりません")
    if not photo.storage_path: raise HTTPException(404,"撮影原本は削除済みです")
    return thumbnail_response(lambda: photo_thumbnail(photo))
@app.post("/api/photos/{photo_id}/cards")
def add_card(photo_id: str, body: ManualCardInput, tasks: BackgroundTasks, db: Session=Depends(get_db), user: User=Depends(current_user)):
    photo=visible_photo_query(db,user).filter_by(id=photo_id).first()
    if not photo: raise HTTPException(404,"写真が見つかりません")
    if not photo.storage_path: raise HTTPException(409,"撮影原本は削除済みです")
    use_v2 = photo.pipeline_version == "v2"
    try:
        if use_v2:
            from .recognition_v2.pipeline import add_manual_card_v2
            card = add_manual_card_v2(photo, db, body.corners)
        else:
            card = add_manual_card(photo, db, body.corners)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    async def job():
        if use_v2:
            from .recognition_v2.pipeline import process_card_v2
            await process_card_v2(card.id)
        else:
            await process_card(card.id)
    tasks.add_task(job)
    return {"id":card.id,"status":card.status}
@app.post("/api/photos/{photo_id}/complete-review")
def complete_review(photo_id: str, body: CompleteReviewInput, db: Session=Depends(get_db), user: User=Depends(current_user)):
    photo=visible_photo_query(db,user).filter_by(id=photo_id).first()
    if not photo: raise HTTPException(404,"写真が見つかりません")
    if not body.retain_photo and photo.storage_path:
        source=Path(photo.storage_path); thumb=source.parent / "thumb.jpg"
        source.unlink(missing_ok=True); thumb.unlink(missing_ok=True); photo.storage_path=""
    db.commit(); return {"source_retained":bool(photo.storage_path)}
@app.post("/api/photos/{photo_id}/confirm-cards")
def confirm_cards(photo_id: str, body: BatchConfirmInput, db: Session=Depends(get_db), user: User=Depends(current_user)):
    photo=visible_photo_query(db,user).filter_by(id=photo_id).first()
    if not photo: raise HTTPException(404,"写真が見つかりません")
    cards=db.query(BusinessCard).filter(BusinessCard.photo_id==photo_id, BusinessCard.id.in_(set(body.card_ids))).all()
    if len(cards) != len(set(body.card_ids)): raise HTTPException(400,"選択した名刺が見つかりません")
    for card in cards:
        contact=db.query(Contact).filter_by(card_id=card.id).first()
        if card.status not in {"review_required", "confirmed"} or not contact or contact.review_flags: raise HTTPException(400,"要確認項目が残っている名刺が含まれています")
        if not contact.confirmed:
            contact.confirmed=True; card.status="confirmed"
            contact.card_owner_user_id, contact.exchanged_at = user.id, photo.created_at.date()
        db.flush(); directory_service.register_confirmed_contact(contact.id, user, db)
    db.commit(); return {"confirmed_count":len(cards)}
@app.post("/api/photos/{photo_id}/process")
def process(photo_id: str, tasks: BackgroundTasks, db: Session=Depends(get_db), user: User=Depends(current_user)):
    photo=visible_photo_query(db,user).filter_by(id=photo_id).first()
    if not photo: raise HTTPException(404,"写真が見つかりません")
    # 認識パイプラインは写真ごとに固定（アップロード時に確定済み）。V1とV2が同じ写真を
    # 二重に処理することはない（docs/adr/0019）。
    use_v2 = photo.pipeline_version == "v2"
    async def job():
        with SessionLocal() as session:
            if use_v2:
                from .recognition_v2.pipeline import process_photo_v2
                await process_photo_v2(photo_id,session)
            else:
                await process_photo(photo_id,session)
    tasks.add_task(job); return {"photo_id":photo_id,"status":"processing","pipeline_version":photo.pipeline_version}
@app.get("/api/photos/{photo_id}/cards")
def cards(photo_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    if not visible_photo_query(db,user).filter_by(id=photo_id).first(): raise HTTPException(404,"写真が見つかりません")
    return [{"id":c.id,"status":c.status,"confidence":c.detection_confidence,"image_revision":card_image_revision(c),"bounding_box":{"x":c.x,"y":c.y,"width":c.width,"height":c.height}} for c in db.query(BusinessCard).filter_by(photo_id=photo_id)]
# --- 台帳（登録済み連絡先の検索）。docs/CONTEXT.md の「台帳検索」参照 ---

@app.get("/api/contacts")
def list_contacts(q: str="", status: str=DEFAULT_LEDGER_STATUS, limit: int=LEDGER_PAGE_SIZE, offset: int=0, db: Session=Depends(get_db), user: User=Depends(current_user)):
    if status not in LEDGER_STATUSES: raise HTTPException(400,"status の指定が不正です")
    return search_contacts(db, user, q, min(max(limit,1), LEDGER_MAX_PAGE_SIZE), max(offset,0), status)

@app.get("/api/cards/{card_id}")
def card(card_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    c=card_for_user(card_id,db,user); contact=db.query(Contact).filter_by(card_id=c.id).first(); ocr=db.query(OCRResult).filter_by(card_id=c.id).order_by(OCRResult.created_at.desc()).first()
    revision=card_image_revision(c)
    return {"id":c.id,"status":c.status,"image_url":f"/api/cards/{c.id}/image?v={revision}","image_revision":revision,"contact":{k:getattr(contact,k) for k in Contact.__table__.columns.keys()} if contact else None,"ocr_text":ocr.raw_text if ocr else "","review_flags":contact.review_flags if contact else {},"orientation":c.orientation,"orientation_decision":c.orientation_decision}
@app.delete("/api/cards/{card_id}")
def remove_card(card_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    card=card_for_user(card_id,db,user)
    record_audit(db,user,"delete","card",card_id,delete_card(card,db)); db.commit(); return {"deleted":True}
@app.get("/api/cards/{card_id}/image")
def card_image(card_id: str, v: str | None=None, db: Session=Depends(get_db), user: User=Depends(current_user)):
    card=card_for_user(card_id,db,user)
    cache_control = VERSIONED_IMAGE_CACHE_CONTROL if v == card_image_revision(card) else MUTABLE_IMAGE_CACHE_CONTROL
    return FileResponse(card.oriented_image_path or card.corrected_image_path, headers={"Cache-Control":cache_control})
@app.get("/api/cards/{card_id}/thumbnail")
def card_thumb(card_id: str, v: str | None=None, db: Session=Depends(get_db), user: User=Depends(current_user)):
    card=card_for_user(card_id,db,user)
    cache_control = VERSIONED_IMAGE_CACHE_CONTROL if v == card_image_revision(card) else MUTABLE_IMAGE_CACHE_CONTROL
    return thumbnail_response(lambda: card_thumbnail(card), cache_control)
@app.post("/api/cards/{card_id}/ocr")
async def ocr(card_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    c=card_for_user(card_id,db,user)
    try: await recognize(c,db,llm=False)
    except ValueError as exc: raise HTTPException(502, str(exc)) from exc
    return {"status":c.status}
@app.post("/api/cards/{card_id}/structure")
async def struct(card_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    c=card_for_user(card_id,db,user)
    try: await recognize(c,db,ocr=False)
    except ValueError as exc: raise HTTPException(502, str(exc)) from exc
    return {"status":c.status}
@app.put("/api/cards/{card_id}/contact")
def save_contact(card_id: str, body: ContactInput, db: Session=Depends(get_db), user: User=Depends(current_user)):
    c=card_for_user(card_id,db,user); contact=db.query(Contact).filter_by(card_id=c.id).first() or Contact(card_id=c.id)
    values=body.model_dump(); resolved=set(values.pop("resolved_fields", []))
    # 未入力はフォームからは "" 、DBには NULL で来る。同じ「空」を変更として数えない
    changed={key for key,value in values.items() if (getattr(contact,key,None) or "") != (value or "")}
    was_confirmed=bool(contact.confirmed)
    for key,value in values.items(): setattr(contact,key,value)
    contact.review_flags={key:value for key,value in (contact.review_flags or {}).items() if key not in resolved}
    refresh_search_text(contact)
    db.add(contact); db.flush()
    if was_confirmed and changed:
        # 登録済みの台帳を書き換えた記録。値そのものは残さない（監査ログに個人情報を溜めない）
        record_audit(db,user,"update","contact",contact.id,{"card_id":c.id,"fields":sorted(changed)})
        directory_service.rematch_contact(contact, changed, user, db)
    db.commit(); return contact
@app.post("/api/cards/{card_id}/confirm")
def confirm(card_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    c=card_for_user(card_id,db,user); contact=db.query(Contact).filter_by(card_id=c.id).first()
    if not contact: raise HTTPException(400,"連絡先情報がありません")
    photo=db.get(Photo,c.photo_id)
    if not contact.confirmed:
        contact.confirmed=True; c.status="confirmed"
        contact.card_owner_user_id, contact.exchanged_at = user.id, photo.created_at.date()
    db.flush(); directory_service.register_confirmed_contact(contact.id, user, db)
    db.commit(); return {"status":"confirmed"}
@app.put("/api/cards/{card_id}/registration")
def update_registration(card_id: str, body: CardRegistrationInput, db: Session=Depends(get_db), user: User=Depends(current_user)):
    c=card_for_user(card_id,db,user); contact=db.query(Contact).filter_by(card_id=c.id).first()
    if not contact or not contact.confirmed: raise HTTPException(400,"まだ登録されていません")
    owner=db.get(User, body.card_owner_user_id)
    if not owner or owner.organization_id != user.organization_id: raise HTTPException(400,"登録者を正しく選択してください")
    contact.card_owner_user_id, contact.exchanged_at = body.card_owner_user_id, body.exchanged_at
    db.commit(); return {"card_owner_user_id":contact.card_owner_user_id,"exchanged_at":contact.exchanged_at}
@app.post("/api/cards/{card_id}/reprocess")
async def reprocess(card_id: str, body: ReprocessInput, db: Session=Depends(get_db), user: User=Depends(current_user)):
    c=card_for_user(card_id,db,user)
    try:
        # 向きは探索せず、現在の向き（ユーザーが直していればその向き）のままOCRし直す。
        await recognize(c,db,ocr=body.ocr,llm=body.llm)
    except ValueError as exc: raise HTTPException(502, str(exc)) from exc
    return {"status":c.status}
# --- 名刺画像の撮り直し。採用するまで既存の画像に触れない2段構え（docs/adr/0013 参照） ---

@app.post("/api/cards/{card_id}/replacement")
async def start_replacement(card_id: str, file: UploadFile=File(...), db: Session=Depends(get_db), user: User=Depends(current_user)):
    c=card_for_user(card_id,db,user)
    if file.content_type not in {"image/jpeg","image/png"}: raise HTTPException(415, "JPEG または PNG のみ対応")
    upload=Path(c.corrected_image_path).parent / "pending-upload.tmp"; upload.parent.mkdir(parents=True, exist_ok=True)
    with upload.open("wb") as out: shutil.copyfileobj(file.file, out)
    try:
        if upload.stat().st_size > settings.max_upload_bytes: raise HTTPException(413, "20MBを超えています")
        try: token, detected = prepare_replacement(c, upload)
        except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    finally:
        upload.unlink(missing_ok=True)
    return {"token":token,"detected":detected}

def pending_replacement_for_user(card_id: str, token: str, db: Session, user: User):
    card=card_for_user(card_id,db,user)
    # トークンはファイル名になる。生成した16進以外は受け取らず、パスを組み立てさせない
    if not re.fullmatch(r"[0-9a-f]{32}", token): raise HTTPException(404, "撮り直した画像が見つかりません")
    return card

@app.get("/api/cards/{card_id}/replacement/{token}")
def replacement_preview(card_id: str, token: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    card=pending_replacement_for_user(card_id,token,db,user)
    path=pending_replacement_path(card, token)
    if not path.exists(): raise HTTPException(404, "撮り直した画像が見つかりません")
    return FileResponse(path, headers={"Cache-Control":MUTABLE_IMAGE_CACHE_CONTROL})

@app.delete("/api/cards/{card_id}/replacement/{token}")
def cancel_replacement(card_id: str, token: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    discard_replacement(pending_replacement_for_user(card_id,token,db,user), token); return {"discarded":True}

@app.post("/api/cards/{card_id}/replacement/{token}/apply")
async def commit_replacement(card_id: str, token: str, body: ReplacementApplyInput, db: Session=Depends(get_db), user: User=Depends(current_user)):
    card=pending_replacement_for_user(card_id,token,db,user)
    was_confirmed = card.status == "confirmed"
    try: apply_replacement(card, db, token)
    except ValueError as exc: raise HTTPException(404, str(exc)) from exc
    record_audit(db,user,"replace_image","card",card.id,{"reread":body.reread}); db.commit()
    if body.reread:
        try: await recognize(card, db)
        except ValueError as exc: raise HTTPException(502, str(exc)) from exc
        # structure() は解析直後の状態として review_required を立てる。読み直しは登録を
        # 取り消す操作ではないので、登録済みだった名刺は登録済みのまま戻す
        if was_confirmed: card.status = "confirmed"; db.commit()
    return {"status":card.status,"image_revision":card_image_revision(card)}

@app.post("/api/cards/{card_id}/orientation")
async def set_orientation(card_id: str, body: OrientationInput, db: Session=Depends(get_db), user: User=Depends(current_user)):
    c=card_for_user(card_id,db,user)
    try:
        apply_orientation(c, db, body.rotation)
        # ユーザーが決めた向きは、以後の自動判定に上書きさせない（docs/CONTEXT.md Orientation Decision）
        c.orientation_decision = "user_confirmed"; db.commit()
        # 登録時に未確定の回転だけを書き込む経路は、フォームの入力値を再抽出結果で
        # 上書きしないよう、再読み取り(reread)を省略できる。
        if body.reread: await recognize(c, db)
    except ValueError as exc: raise HTTPException(502, str(exc)) from exc
    return {"status":c.status,"orientation":c.orientation,"orientation_decision":c.orientation_decision}

import shutil
from pathlib import Path
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from . import auth
from .database import Base, SessionLocal, engine, get_db
from .models import AuditLog, BusinessCard, Contact, Group, OCRResult, Organization, Photo, TrustedDevice, User, UserGroup
from .schemas import BatchConfirmInput, CompleteReviewInput, ContactInput, GroupInput, LoginInput, ManualCardInput, OrientationInput, OrganizationInput, PasswordResetInput, ReprocessInput, TotpInput, UserInput
from .services import add_manual_card, apply_orientation, card_thumbnail, delete_card, delete_photo, image_size, photo_thumbnail, process_card, process_photo, run_ocr, structure
from .settings import settings

# サムネイルは中身が変わらず、変われば元の名刺ごと別IDになる。
# 一覧を開くたびに取り直させる理由がないので、しばらくブラウザに持たせる。
THUMBNAIL_CACHE_CONTROL = "private, max-age=604800"

app = FastAPI(title="BCMan API", root_path=settings.root_path)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"], allow_credentials=True)

def bootstrap():
    """Organization・初期管理者の作成はアプリ外（scripts/create_org.py）で行う。
    ここではテーブル作成のみ。"""
    Base.metadata.create_all(engine); settings.storage_dir.mkdir(parents=True, exist_ok=True)
    if engine.dialect.name == "sqlite":
        with engine.begin() as connection:
            columns = {row[1] for row in connection.execute(text("PRAGMA table_info(contacts)"))}
            if "review_flags" not in columns: connection.execute(text("ALTER TABLE contacts ADD COLUMN review_flags JSON DEFAULT '{}'"))
            card_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(business_cards)"))}
            if "oriented_image_path" not in card_columns: connection.execute(text("ALTER TABLE business_cards ADD COLUMN oriented_image_path VARCHAR DEFAULT ''"))
            if "orientation" not in card_columns: connection.execute(text("ALTER TABLE business_cards ADD COLUMN orientation INTEGER DEFAULT 0"))
@app.on_event("startup")
def startup(): bootstrap()

current_user = auth.current_user
require_admin = auth.require_admin

def user_group_ids(db: Session, user: User) -> list[str]:
    return [row.group_id for row in db.query(UserGroup).filter_by(user_id=user.id)]
def visible_photo_query(db: Session, user: User):
    query = db.query(Photo).filter(Photo.organization_id == user.organization_id)
    org = db.get(Organization, user.organization_id)
    if user.role == "admin" or org.sharing_mode == "shared": return query
    return query.filter(Photo.group_id.in_(user_group_ids(db, user)))
def card_for_user(card_id, db, user):
    card = db.get(BusinessCard, card_id)
    if not card or not visible_photo_query(db, user).filter(Photo.id == card.photo_id).first(): raise HTTPException(404, "名刺が見つかりません")
    return card
def record_audit(db, user, action, target_type, target_id, detail):
    db.add(AuditLog(user_id=user.id, user_name=user.name, action=action, target_type=target_type, target_id=target_id, detail=detail))
def thumbnail_response(build):
    # 元画像が消えている古いデータでも一覧そのものは開けるよう、画像だけ 404 にする
    try: path = build()
    except (FileNotFoundError, OSError) as exc: raise HTTPException(404, "画像がありません") from exc
    return FileResponse(path, headers={"Cache-Control": THUMBNAIL_CACHE_CONTROL})
def require_group_in_org(db: Session, org_id: str, group_ids: list[str]):
    found = db.query(Group).filter(Group.organization_id == org_id, Group.id.in_(group_ids)).count()
    if found != len(set(group_ids)): raise HTTPException(400, "指定したグループがこの組織にありません")

@app.get("/api/health")
def health(): return {"status":"ok"}

# --- 認証 ---

@app.post("/api/auth/login")
def login(body: LoginInput, request: Request, response: Response, db: Session=Depends(get_db)):
    user = db.query(User).filter_by(username=body.username).first()
    if not user:
        # ID自体が存在しない場合も所要時間・応答を揃え、IDの実在を推測させない
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

@app.get("/api/auth/me")
def me(db: Session=Depends(get_db), user: User=Depends(current_user)):
    org = db.get(Organization, user.organization_id)
    groups = db.query(Group).join(UserGroup, UserGroup.group_id == Group.id).filter(UserGroup.user_id == user.id).all()
    return {"id":user.id,"username":user.username,"name":user.name,"role":user.role,"organization_id":user.organization_id,"sharing_mode":org.sharing_mode if org else None,"groups":[{"id":g.id,"name":g.name} for g in groups]}

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
@app.get("/api/organizations/{org_id}/users")
def list_users(org_id: str, db: Session=Depends(get_db), user: User=Depends(require_admin)):
    if user.organization_id != org_id: raise HTTPException(403, "権限がありません")
    users = db.query(User).filter_by(organization_id=org_id).all()
    return [{"id":u.id,"username":u.username,"name":u.name,"role":u.role,"groups":[g.id for g in db.query(Group).join(UserGroup, UserGroup.group_id==Group.id).filter(UserGroup.user_id==u.id)]} for u in users]
@app.post("/api/organizations/{org_id}/users")
def create_user(org_id: str, body: UserInput, db: Session=Depends(get_db), user: User=Depends(require_admin)):
    if user.organization_id != org_id: raise HTTPException(403, "権限がありません")
    require_group_in_org(db, org_id, body.group_ids)
    if db.query(User).filter_by(username=body.username).first(): raise HTTPException(409, "そのIDは既に使われています")
    secret = auth.generate_totp_secret()
    item = User(organization_id=org_id, username=body.username, name=body.name, role=body.role, password_hash=auth.hash_password(body.password), totp_secret=secret)
    db.add(item); db.flush()
    for group_id in set(body.group_ids): db.add(UserGroup(user_id=item.id, group_id=group_id))
    db.commit()
    return {"id":item.id,"username":item.username,"totp_provisioning_uri":auth.totp_provisioning_uri(secret, item.username)}
def target_user_in_org(db: Session, org_id: str, user_id: str) -> User:
    target = db.get(User, user_id)
    if not target or target.organization_id != org_id: raise HTTPException(404, "利用者が見つかりません")
    return target
@app.put("/api/organizations/{org_id}/users/{user_id}/password")
def reset_password(org_id: str, user_id: str, body: PasswordResetInput, db: Session=Depends(get_db), admin: User=Depends(require_admin)):
    if admin.organization_id != org_id: raise HTTPException(403, "権限がありません")
    target = target_user_in_org(db, org_id, user_id)
    target.password_hash = auth.hash_password(body.password); db.commit(); return {"reset":True}
@app.post("/api/organizations/{org_id}/users/{user_id}/reset-totp")
def reset_totp(org_id: str, user_id: str, db: Session=Depends(get_db), admin: User=Depends(require_admin)):
    if admin.organization_id != org_id: raise HTTPException(403, "権限がありません")
    target = target_user_in_org(db, org_id, user_id)
    secret = auth.generate_totp_secret(); target.totp_secret = secret; db.commit()
    return {"totp_provisioning_uri":auth.totp_provisioning_uri(secret, target.username)}
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

@app.post("/api/photos")
async def upload_photo(group_id: str, file: UploadFile=File(...), db: Session=Depends(get_db), user: User=Depends(current_user)):
    allowed_groups = {g.id for g in db.query(Group).filter_by(organization_id=user.organization_id)} if user.role == "admin" else set(user_group_ids(db, user))
    if group_id not in allowed_groups: raise HTTPException(400, "アップロード先のグループを正しく選択してください")
    if file.content_type not in {"image/jpeg","image/png"}: raise HTTPException(415, "JPEG または PNG のみ対応")
    photo=Photo(organization_id=user.organization_id, group_id=group_id, original_filename=file.filename or "upload", storage_path=""); db.add(photo); db.flush()
    target=settings.storage_dir/"photos"/photo.id; target.mkdir(parents=True); path=target/("original.png" if file.content_type=="image/png" else "original.jpg")
    with path.open("wb") as out: shutil.copyfileobj(file.file, out)
    if path.stat().st_size > settings.max_upload_bytes: path.unlink(); raise HTTPException(413, "20MBを超えています")
    photo.storage_path=str(path); photo.width, photo.height=image_size(path); db.commit(); return {"photo_id":photo.id,"status":"uploaded"}
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
    try: card = add_manual_card(photo, db, body.corners)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    async def job(): await process_card(card.id)
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
        contact.confirmed=True; card.status="confirmed"
    db.commit(); return {"confirmed_count":len(cards)}
@app.post("/api/photos/{photo_id}/process")
def process(photo_id: str, tasks: BackgroundTasks, db: Session=Depends(get_db), user: User=Depends(current_user)):
    if not visible_photo_query(db,user).filter_by(id=photo_id).first(): raise HTTPException(404,"写真が見つかりません")
    async def job():
        with SessionLocal() as session: await process_photo(photo_id,session)
    tasks.add_task(job); return {"photo_id":photo_id,"status":"processing"}
@app.get("/api/photos/{photo_id}/cards")
def cards(photo_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    if not visible_photo_query(db,user).filter_by(id=photo_id).first(): raise HTTPException(404,"写真が見つかりません")
    return [{"id":c.id,"status":c.status,"confidence":c.detection_confidence,"bounding_box":{"x":c.x,"y":c.y,"width":c.width,"height":c.height}} for c in db.query(BusinessCard).filter_by(photo_id=photo_id)]
@app.get("/api/cards/{card_id}")
def card(card_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    c=card_for_user(card_id,db,user); contact=db.query(Contact).filter_by(card_id=c.id).first(); ocr=db.query(OCRResult).filter_by(card_id=c.id).order_by(OCRResult.created_at.desc()).first()
    return {"id":c.id,"status":c.status,"image_url":f"/api/cards/{c.id}/image","contact":{k:getattr(contact,k) for k in Contact.__table__.columns.keys()} if contact else None,"ocr_text":ocr.raw_text if ocr else "","review_flags":contact.review_flags if contact else {},"orientation":c.orientation}
@app.delete("/api/cards/{card_id}")
def remove_card(card_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    card=card_for_user(card_id,db,user)
    record_audit(db,user,"delete","card",card_id,delete_card(card,db)); db.commit(); return {"deleted":True}
@app.get("/api/cards/{card_id}/image")
def card_image(card_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    card=card_for_user(card_id,db,user); return FileResponse(card.oriented_image_path or card.corrected_image_path)
@app.get("/api/cards/{card_id}/thumbnail")
def card_thumb(card_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    card=card_for_user(card_id,db,user)
    return thumbnail_response(lambda: card_thumbnail(card))
@app.post("/api/cards/{card_id}/ocr")
async def ocr(card_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    c=card_for_user(card_id,db,user)
    try: await run_ocr(c,db)
    except ValueError as exc: raise HTTPException(502, str(exc)) from exc
    return {"status":c.status}
@app.post("/api/cards/{card_id}/structure")
async def struct(card_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    c=card_for_user(card_id,db,user)
    try: await structure(c,db)
    except ValueError as exc: raise HTTPException(502, str(exc)) from exc
    return {"status":c.status}
@app.put("/api/cards/{card_id}/contact")
def save_contact(card_id: str, body: ContactInput, db: Session=Depends(get_db), user: User=Depends(current_user)):
    c=card_for_user(card_id,db,user); contact=db.query(Contact).filter_by(card_id=c.id).first() or Contact(card_id=c.id)
    values=body.model_dump(); resolved=set(values.pop("resolved_fields", []))
    for key,value in values.items(): setattr(contact,key,value)
    contact.review_flags={key:value for key,value in (contact.review_flags or {}).items() if key not in resolved}
    db.add(contact); db.commit(); return contact
@app.post("/api/cards/{card_id}/confirm")
def confirm(card_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    c=card_for_user(card_id,db,user); contact=db.query(Contact).filter_by(card_id=c.id).first()
    if not contact: raise HTTPException(400,"連絡先情報がありません")
    contact.confirmed=True; c.status="confirmed"; db.commit(); return {"status":"confirmed"}
@app.post("/api/cards/{card_id}/reprocess")
async def reprocess(card_id: str, body: ReprocessInput, db: Session=Depends(get_db), user: User=Depends(current_user)):
    c=card_for_user(card_id,db,user)
    try:
        if body.ocr: await run_ocr(c,db)
        if body.llm: await structure(c,db)
    except ValueError as exc: raise HTTPException(502, str(exc)) from exc
    return {"status":c.status}
@app.post("/api/cards/{card_id}/orientation")
async def set_orientation(card_id: str, body: OrientationInput, db: Session=Depends(get_db), user: User=Depends(current_user)):
    c=card_for_user(card_id,db,user)
    try:
        apply_orientation(c, db, body.rotation)
        await run_ocr(c, db); await structure(c, db)
    except ValueError as exc: raise HTTPException(502, str(exc)) from exc
    return {"status":c.status,"orientation":c.orientation}

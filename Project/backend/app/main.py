import shutil
from pathlib import Path
from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from .database import Base, SessionLocal, engine, get_db
from .models import AuditLog, BusinessCard, Contact, Group, OCRResult, Organization, Photo, User
from .schemas import ContactInput, GroupInput, OrganizationInput, ReprocessInput, UserInput
from .services import card_thumbnail, delete_card, delete_photo, detect_cards, image_size, photo_thumbnail, process_photo, run_ocr, structure
from .settings import settings

# サムネイルは中身が変わらず、変われば元の名刺ごと別IDになる。
# 一覧を開くたびに取り直させる理由がないので、しばらくブラウザに持たせる。
THUMBNAIL_CACHE_CONTROL = "private, max-age=604800"

app = FastAPI(title="BCMan API", root_path=settings.root_path)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])

def bootstrap():
    Base.metadata.create_all(engine); settings.storage_dir.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        if not db.query(User).first():
            org = Organization(name="サンプル組織", sharing_mode="isolated"); db.add(org); db.flush()
            group = Group(organization_id=org.id, name="一般"); db.add(group); db.flush()
            db.add(User(name="システム管理者", role="system_admin")); db.add(User(name="組織管理者", organization_id=org.id, group_id=group.id, role="org_admin")); db.commit()
@app.on_event("startup")
def startup(): bootstrap()

def current_user(x_user_id: str | None = Header(default=None), db: Session = Depends(get_db)):
    user = db.get(User, x_user_id) if x_user_id else db.query(User).filter_by(role="system_admin").first()
    if not user: raise HTTPException(401, "利用者が見つかりません")
    return user
def visible_photo_query(db, user):
    query = db.query(Photo)
    if user.role == "system_admin": return query
    org = db.get(Organization, user.organization_id)
    if not org: raise HTTPException(403, "組織に所属していません")
    return query.filter(Photo.organization_id == user.organization_id) if user.role == "org_admin" or org.sharing_mode == "shared" else query.filter(Photo.group_id == user.group_id)
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

@app.get("/api/health")
def health(): return {"status":"ok"}
@app.get("/api/bootstrap")
def bootstrap_data(db: Session=Depends(get_db)): return {"users":[{"id":u.id,"name":u.name,"role":u.role,"organization_id":u.organization_id,"group_id":u.group_id} for u in db.query(User)], "organizations":[{"id":o.id,"name":o.name,"sharing_mode":o.sharing_mode} for o in db.query(Organization)], "groups":[{"id":g.id,"organization_id":g.organization_id,"name":g.name} for g in db.query(Group)]}
@app.post("/api/organizations")
def create_org(body: OrganizationInput, db: Session=Depends(get_db), user: User=Depends(current_user)):
    if user.role != "system_admin": raise HTTPException(403, "システム管理者のみ")
    org=Organization(**body.model_dump()); db.add(org); db.commit(); db.refresh(org); return org
@app.put("/api/organizations/{org_id}")
def update_org(org_id: str, body: OrganizationInput, db: Session=Depends(get_db), user: User=Depends(current_user)):
    org=db.get(Organization, org_id)
    if not org or user.role not in ("system_admin", "org_admin") or user.role=="org_admin" and user.organization_id!=org_id: raise HTTPException(403, "権限がありません")
    org.name, org.sharing_mode=body.name, body.sharing_mode; db.commit(); return org
@app.post("/api/organizations/{org_id}/groups")
def create_group(org_id: str, body: GroupInput, db: Session=Depends(get_db), user: User=Depends(current_user)):
    if user.role not in ("system_admin","org_admin") or user.role=="org_admin" and user.organization_id!=org_id: raise HTTPException(403, "権限がありません")
    item=Group(organization_id=org_id, **body.model_dump()); db.add(item); db.commit(); return item
@app.post("/api/organizations/{org_id}/users")
def create_user(org_id: str, body: UserInput, db: Session=Depends(get_db), user: User=Depends(current_user)):
    if user.role not in ("system_admin","org_admin") or user.role=="org_admin" and user.organization_id!=org_id: raise HTTPException(403, "権限がありません")
    item=User(organization_id=org_id, **body.model_dump()); db.add(item); db.commit(); return item

@app.post("/api/photos")
async def upload_photo(file: UploadFile=File(...), db: Session=Depends(get_db), user: User=Depends(current_user)):
    if user.role == "system_admin" or not user.organization_id or not user.group_id: raise HTTPException(400, "組織とグループを持つ利用者を選択してください")
    if file.content_type not in {"image/jpeg","image/png"}: raise HTTPException(415, "JPEG または PNG のみ対応")
    photo=Photo(organization_id=user.organization_id, group_id=user.group_id, original_filename=file.filename or "upload", storage_path=""); db.add(photo); db.flush()
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
    return [{"id":p.id,"filename":p.original_filename,"status":p.status,"created_at":p.created_at,"card_count":total.get(p.id,0),"confirmed_count":confirmed.get(p.id,0)} for p in photos]
@app.delete("/api/photos/{photo_id}")
def remove_photo(photo_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    photo=visible_photo_query(db,user).filter_by(id=photo_id).first()
    if not photo: raise HTTPException(404,"写真が見つかりません")
    record_audit(db,user,"delete","photo",photo_id,delete_photo(photo,db)); db.commit(); return {"deleted":True}
@app.get("/api/photos/{photo_id}/thumbnail")
def photo_thumb(photo_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    photo=visible_photo_query(db,user).filter_by(id=photo_id).first()
    if not photo: raise HTTPException(404,"写真が見つかりません")
    return thumbnail_response(lambda: photo_thumbnail(photo))
@app.post("/api/photos/{photo_id}/detect")
def detect(photo_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    photo=visible_photo_query(db,user).filter_by(id=photo_id).first()
    if not photo: raise HTTPException(404,"写真が見つかりません")
    detect_cards(photo, db); return {"photo_id":photo.id,"detected_count":db.query(BusinessCard).filter_by(photo_id=photo.id).count()}
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
    return {"id":c.id,"status":c.status,"image_url":f"/api/cards/{c.id}/image","contact":{k:getattr(contact,k) for k in Contact.__table__.columns.keys()} if contact else None,"ocr_text":ocr.raw_text if ocr else ""}
@app.delete("/api/cards/{card_id}")
def remove_card(card_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    card=card_for_user(card_id,db,user)
    record_audit(db,user,"delete","card",card_id,delete_card(card,db)); db.commit(); return {"deleted":True}
@app.get("/api/cards/{card_id}/image")
def card_image(card_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)): return FileResponse(card_for_user(card_id,db,user).corrected_image_path)
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
    for key,value in body.model_dump().items(): setattr(contact,key,value)
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

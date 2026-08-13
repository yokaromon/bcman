import asyncio, base64, json, shutil
from io import BytesIO
from pathlib import Path
import cv2
import httpx
import numpy as np
from PIL import Image
from sqlalchemy.orm import Session
from .models import BusinessCard, Contact, OCRResult, Photo, ProcessingHistory
from .schemas import CONTACT_FIELDS
from .settings import settings

OCR_PROMPT = "画像内の文字をすべて正確に書き起こしてください。説明や前置きは不要で、本文のみを出力してください。"
STRUCTURE_PROMPT = """次のOCR原文から名刺情報をJSONだけで抽出してください。原文にない情報はnull。電話、FAX、携帯を区別してください。キーは company_name, company_name_kana, department, position, person_name, person_name_kana, postal_code, address, telephone, fax, mobile, email, website, notes です。\n\nOCR原文:\n"""

OCR_MAX_EDGE = 1600
OCR_JPEG_QUALITY = 85
DETECTION_PROMPT = """Find every business card in this image. Return JSON only: {\"cards\":[{\"corners\":[[x,y],[x,y],[x,y],[x,y]],\"rotation\":0|90|180|270|null}]}. Coordinates are pixels in the original image, corners ordered top-left, top-right, bottom-right, bottom-left. rotation is the clockwise turn needed to make text upright; use null when uncertain. Return an empty array only if no card is visible."""
ORIENTATION_PROMPT = "Return JSON only: {\"rotation\":0|90|180|270|null}. Choose the clockwise rotation needed to make the business card text upright for reading. Return null when uncertain."

THUMBNAIL_MAX_EDGE = 800
THUMBNAIL_JPEG_QUALITY = 80

def image_size(path: Path):
    with Image.open(path) as image: return image.size

def ensure_thumbnail(source: Path, thumb: Path) -> Path:
    """一覧用の縮小JPEGのパスを返す。無ければ作って残す。
    アップロード時ではなく初回参照時に作るのは、すでに保存済みの写真・名刺に対して
    作り直しのバッチを用意せずに済ませるため。原本はそのまま残す。"""
    if thumb.exists(): return thumb
    if not source.exists(): raise FileNotFoundError(source)
    with Image.open(source) as image:
        prepared = image.convert("RGB")
        prepared.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE))
        thumb.parent.mkdir(parents=True, exist_ok=True)
        prepared.save(thumb, format="JPEG", quality=THUMBNAIL_JPEG_QUALITY)
    return thumb

def photo_thumbnail(photo: Photo) -> Path:
    return ensure_thumbnail(Path(photo.storage_path), settings.storage_dir / "photos" / photo.id / "thumb.jpg")

def card_thumbnail(card: BusinessCard) -> Path:
    source = Path(card.oriented_image_path or card.corrected_image_path)
    return ensure_thumbnail(source, source.parent / "thumb.jpg")

def delete_card(card: BusinessCard, db: Session) -> dict:
    """名刺と派生データを物理削除し、監査ログに残す要約を返す。
    外部キーに CASCADE を張っていないので、子から順に明示的に消す。"""
    # 消した後の card からは値を読めなくなるので、パスもログもここで確定させる
    card_id, photo_id = card.id, card.photo_id
    contact = db.query(Contact).filter_by(card_id=card_id).first()
    summary = {
        "card_id": card_id,
        "confirmed": bool(contact and contact.confirmed),
        "company_name": contact.company_name if contact else None,
        "person_name": contact.person_name if contact else None,
    }
    db.query(Contact).filter_by(card_id=card_id).delete()
    db.query(OCRResult).filter_by(card_id=card_id).delete()
    db.query(ProcessingHistory).filter_by(card_id=card_id).delete()
    db.delete(card)
    shutil.rmtree(settings.storage_dir / "photos" / photo_id / "cards" / card_id, ignore_errors=True)
    return summary

def delete_photo(photo: Photo, db: Session) -> dict:
    photo_id = photo.id
    cards = db.query(BusinessCard).filter_by(photo_id=photo_id).all()
    summary = {
        "photo_id": photo_id,
        "filename": photo.original_filename,
        "created_at": photo.created_at.isoformat(),
        "cards": [delete_card(card, db) for card in cards],
    }
    db.delete(photo)
    shutil.rmtree(settings.storage_dir / "photos" / photo_id, ignore_errors=True)
    return summary

def encode_for_ocr(path: Path) -> str:
    """OCR APIへ送るJPEGをBase64で返す。長辺を抑えるのは、素の切り抜き画像(数MB)を
    Base64化するとリクエストが app.ykr.ltd 側 nginx の上限(既定1MB)を超えて 413 になるため。
    名刺の文字は1600px あれば読めるので、保存済みの原本・切り抜きはそのまま残す。"""
    with Image.open(path) as image:
        prepared = image.convert("RGB")
        prepared.thumbnail((OCR_MAX_EDGE, OCR_MAX_EDGE))
        buffer = BytesIO()
        prepared.save(buffer, format="JPEG", quality=OCR_JPEG_QUALITY)
    return base64.b64encode(buffer.getvalue()).decode()

def review_flags(values: dict) -> dict:
    flags = {}
    email = values.get("email")
    if email and ("@" not in email or email.startswith("@") or email.endswith("@")): flags["email"] = "形式を確認してください"
    for field in ("telephone", "fax", "mobile"):
        value = values.get(field)
        if value and len("".join(c for c in value if c.isdigit())) < 6: flags[field] = "形式を確認してください"
    website = values.get("website")
    if website and not website.startswith(("http://", "https://")): flags["website"] = "URLを確認してください"
    return flags

def _write_card(photo: Photo, db: Session, image, corners, confidence=.75):
    points = np.float32(corners)
    x, y, w, h = cv2.boundingRect(points.astype(np.int32))
    card = BusinessCard(photo_id=photo.id, detected_image_path="", corrected_image_path="", detection_confidence=confidence, x=x, y=y, width=w, height=h)
    db.add(card); db.flush()
    target = settings.storage_dir / "photos" / photo.id / "cards" / card.id; target.mkdir(parents=True, exist_ok=True)
    # 四隅から台形補正する。出力サイズは対辺の長い方を使うため、斜めの名刺でも文字を潰さない。
    widths = [np.linalg.norm(points[1]-points[0]), np.linalg.norm(points[2]-points[3])]
    heights = [np.linalg.norm(points[3]-points[0]), np.linalg.norm(points[2]-points[1])]
    out_w, out_h = max(1, round(max(widths))), max(1, round(max(heights)))
    transform = cv2.getPerspectiveTransform(points, np.float32([[0,0],[out_w-1,0],[out_w-1,out_h-1],[0,out_h-1]]))
    corrected_image = cv2.warpPerspective(image, transform, (out_w, out_h))
    detected = target / "detected.jpg"; corrected = target / "corrected.jpg"; oriented = target / "oriented-0.jpg"
    cv2.imwrite(str(detected), image[max(0,y):max(0,y)+h, max(0,x):max(0,x)+w]); cv2.imwrite(str(corrected), corrected_image); cv2.imwrite(str(oriented), corrected_image)
    card.detected_image_path, card.corrected_image_path, card.oriented_image_path, card.orientation, card.status = str(detected), str(corrected), str(oriented), 0, "corrected"
    return card

def detect_cards(photo: Photo, db: Session):
    source = Path(photo.storage_path)
    image = cv2.imread(str(source))
    if image is None: raise ValueError("画像を読み込めません")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    height, width = image.shape[:2]; candidates = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour); area = w * h
        ratio = max(w / max(h, 1), h / max(w, 1))
        if area > width * height * .04 and 1.25 <= ratio <= 2.4:
            if not any(abs(x-a[0]) < 10 and abs(y-a[1]) < 10 for a in candidates): candidates.append((x, y, w, h))
    # 0枚は写真全体を名刺として扱わない。ユーザーに撮り直しを促す。
    # 輪郭の走査順は写真上の配置と無関係（右下の名刺が先頭になることがある）。
    # 画面では順にめくって確認するので、上の行から・行内は左からの順に並べ替える。
    # 行の判定に自身の高さを使うと、横に並んだ名刺のわずかなy差では行が割れない。
    candidates.sort(key=lambda box: (box[1] // max(box[3], 1), box[0]))
    for x, y, w, h in candidates:
        _write_card(photo, db, image, [[x,y],[x+w,y],[x+w,y+h],[x,y+h]])
    photo.status = "detected"; db.commit()

def add_manual_card(photo: Photo, db: Session, corners):
    image = cv2.imread(str(Path(photo.storage_path)))
    if image is None: raise ValueError("画像を読み込めません")
    height, width = image.shape[:2]
    if any(x < 0 or y < 0 or x >= width or y >= height for x, y in corners): raise ValueError("四隅は写真の範囲内で指定してください")
    card = _write_card(photo, db, image, corners, 1.0); db.commit(); return card

async def improve_detection(photo: Photo, db: Session):
    """輪郭候補が品質目標未満のときだけ画像AIで四隅を補う。"""
    local_cards = db.query(BusinessCard).filter_by(photo_id=photo.id).all()
    if len(local_cards) >= 8 and all(card.detection_confidence >= .5 for card in local_cards): return
    encoded = encode_for_ocr(Path(photo.storage_path))
    content, _ = await chat([{"role":"user","content":[{"type":"text","text":DETECTION_PROMPT},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{encoded}"}}]}])
    try: proposed = json.loads(content.removeprefix("```json").removesuffix("```").strip()).get("cards", [])
    except (json.JSONDecodeError, AttributeError): return
    image = cv2.imread(str(Path(photo.storage_path)))
    if image is None: return
    for item in proposed:
        corners = item.get("corners", []) if isinstance(item, dict) else []
        if len(corners) != 4: continue
        points = np.float32(corners); x, y, w, h = cv2.boundingRect(points.astype(np.int32))
        # 同一物理名刺の重複を抑える（矩形IoU）。AI結果を優先して既存候補を置換する代わりに、
        # 既存の切り出しファイルは残さない。
        duplicate = next((card for card in local_cards if _iou((x,y,w,h), (card.x,card.y,card.width,card.height)) > .5), None)
        if duplicate:
            shutil.rmtree(Path(duplicate.corrected_image_path).parent, ignore_errors=True); db.delete(duplicate); db.flush(); local_cards.remove(duplicate)
        card = _write_card(photo, db, image, corners, .9)
        rotation = item.get("rotation") if isinstance(item, dict) else None
        if rotation in {0, 90, 180, 270}: apply_orientation(card, db, rotation, automatic=True)
        local_cards.append(card)
    db.commit()

def _iou(a, b):
    ax, ay, aw, ah = a; bx, by, bw, bh = b
    ix, iy = max(ax,bx), max(ay,by); ex, ey = min(ax+aw,bx+bw), min(ay+ah,by+bh)
    intersection = max(0, ex-ix) * max(0, ey-iy)
    return intersection / max(1, aw*ah + bw*bh - intersection)

async def chat(messages):
    if not settings.ai_api_key or not settings.ai_model: raise ValueError("AI_API_KEY と AI_MODEL を .env に設定してください")
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(f"{settings.ai_base_url.rstrip('/')}/chat/completions", headers={"Authorization": f"Bearer {settings.ai_api_key}"}, json={"model": settings.ai_model, "messages": messages, "temperature": 0})
        # raise_for_status のままだと画面には「失敗」としか出ず、原因調査がログ頼みになる
        if response.is_error: raise ValueError(f"AI APIがHTTP {response.status_code} を返しました: {response.text[:200]}")
        data = response.json()
    return data["choices"][0]["message"]["content"], data

def _rotated_image(source: Path, rotation: int, target: Path):
    image = cv2.imread(str(source))
    if image is None: raise ValueError("名刺画像を読み込めません")
    transforms = {0: None, 90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}
    if rotation: image = cv2.rotate(image, transforms[rotation])
    cv2.imwrite(str(target), image)

async def orient_card(card: BusinessCard, db: Session):
    """OCRの前に読む向きをAIで推定し、失敗・不明なら無回転の派生画像を維持する。"""
    encoded = encode_for_ocr(Path(card.corrected_image_path))
    try:
        content, _ = await chat([{"role":"user","content":[{"type":"text","text":ORIENTATION_PROMPT},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{encoded}"}}]}])
        rotation = json.loads(content.removeprefix("```json").removesuffix("```").strip()).get("rotation")
        if rotation not in {0, 90, 180, 270}: return
    except Exception: return
    apply_orientation(card, db, rotation, automatic=True)

def apply_orientation(card: BusinessCard, db: Session, rotation: int, automatic=False):
    target = Path(card.corrected_image_path).parent / f"oriented-{rotation}-{len(db.query(OCRResult).filter_by(card_id=card.id).all())}.jpg"
    _rotated_image(Path(card.corrected_image_path), rotation, target)
    card.oriented_image_path, card.orientation = str(target), rotation
    db.add(ProcessingHistory(card_id=card.id, process_type="orientation", engine="ykr-multimodal" if automatic else "user", version=settings.ai_model if automatic else "", input_json={"rotation":rotation}, output_json={"image_path":str(target)}))
    db.commit()

async def run_ocr(card: BusinessCard, db: Session):
    card.status = "ocr_processing"; db.commit()
    encoded = encode_for_ocr(Path(card.oriented_image_path or card.corrected_image_path))
    text, response = await chat([{"role":"user","content":[{"type":"text","text":OCR_PROMPT},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{encoded}"}}]}])
    db.add(OCRResult(card_id=card.id, engine="ykr-multimodal", engine_version=settings.ai_model, raw_text=text, raw_json=response))
    db.add(ProcessingHistory(card_id=card.id, process_type="ocr", engine="ykr-multimodal", version=settings.ai_model, input_json={"prompt":OCR_PROMPT,"orientation":card.orientation}, output_json={"raw_text":text}))
    card.status = "ocr_completed"; db.commit()

async def structure(card: BusinessCard, db: Session):
    result = db.query(OCRResult).filter_by(card_id=card.id).order_by(OCRResult.created_at.desc()).first()
    if not result: raise ValueError("先にOCRを実行してください")
    card.status = "llm_processing"; db.commit()
    content, response = await chat([{"role":"user","content":STRUCTURE_PROMPT + result.raw_text}])
    try: values = json.loads(content.removeprefix("```json").removesuffix("```").strip())
    except json.JSONDecodeError as exc: raise ValueError("構造化APIが有効なJSONを返しませんでした") from exc
    values = {key: values.get(key) for key in CONTACT_FIELDS}
    contact = db.query(Contact).filter_by(card_id=card.id).first() or Contact(card_id=card.id)
    for key, value in values.items(): setattr(contact, key, value)
    contact.review_flags = review_flags(values)
    db.add(contact); db.add(ProcessingHistory(card_id=card.id, process_type="llm", engine="ykr-multimodal", version=settings.ai_model, input_json={"raw_text":result.raw_text}, output_json=response))
    card.status = "review_required"; db.commit()

async def _process_card(card_id: str):
    from .database import SessionLocal
    for attempt in range(2):
        with SessionLocal() as db:
            card = db.get(BusinessCard, card_id)
            try:
                await orient_card(card, db); await run_ocr(card, db); await structure(card, db); return
            except Exception:
                db.rollback()
                if attempt:
                    card = db.get(BusinessCard, card_id); card.status = "retry_required"; db.commit(); return

async def process_card(card_id: str):
    await _process_card(card_id)

async def process_photo(photo_id: str, db: Session):
    photo = db.get(Photo, photo_id)
    try:
        photo.status = "detecting"; db.commit(); detect_cards(photo, db)
        # フォールバック自体のAPI障害で、ローカル検出済み候補まで失わない。
        try: await improve_detection(photo, db)
        except Exception: db.rollback()
        card_ids = [card.id for card in db.query(BusinessCard).filter_by(photo_id=photo.id).all()]
        if not card_ids: photo.status = "failed"; db.commit(); return
        semaphore = asyncio.Semaphore(3)
        async def queued(card_id):
            async with semaphore: await _process_card(card_id)
        await asyncio.gather(*(queued(card_id) for card_id in card_ids))
        photo.status = "completed"; db.commit()
    except Exception as exc:
        photo.status = "failed"; db.commit(); raise exc

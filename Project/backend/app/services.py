import base64, json, shutil
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

def image_size(path: Path):
    with Image.open(path) as image: return image.size

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
    if not candidates: candidates = [(0, 0, width, height)]
    # 輪郭の走査順は写真上の配置と無関係（右下の名刺が先頭になることがある）。
    # 画面では順にめくって確認するので、上の行から・行内は左からの順に並べ替える。
    # 行の判定に自身の高さを使うと、横に並んだ名刺のわずかなy差では行が割れない。
    candidates.sort(key=lambda box: (box[1] // max(box[3], 1), box[0]))
    for x, y, w, h in candidates[:10]:
        card = BusinessCard(photo_id=photo.id, detected_image_path="", corrected_image_path="", detection_confidence=.75 if len(candidates) else .2, x=x, y=y, width=w, height=h)
        db.add(card); db.flush()
        target = settings.storage_dir / "photos" / photo.id / "cards" / card.id; target.mkdir(parents=True, exist_ok=True)
        crop = image[y:y+h, x:x+w]; detected = target / "detected.jpg"; corrected = target / "corrected.jpg"
        cv2.imwrite(str(detected), crop); cv2.imwrite(str(corrected), crop)
        card.detected_image_path, card.corrected_image_path, card.status = str(detected), str(corrected), "corrected"
    photo.status = "detected"; db.commit()

async def chat(messages):
    if not settings.ai_api_key or not settings.ai_model: raise ValueError("AI_API_KEY と AI_MODEL を .env に設定してください")
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(f"{settings.ai_base_url.rstrip('/')}/chat/completions", headers={"Authorization": f"Bearer {settings.ai_api_key}"}, json={"model": settings.ai_model, "messages": messages, "temperature": 0})
        # raise_for_status のままだと画面には「失敗」としか出ず、原因調査がログ頼みになる
        if response.is_error: raise ValueError(f"AI APIがHTTP {response.status_code} を返しました: {response.text[:200]}")
        data = response.json()
    return data["choices"][0]["message"]["content"], data

async def run_ocr(card: BusinessCard, db: Session):
    card.status = "ocr_processing"; db.commit()
    encoded = encode_for_ocr(Path(card.corrected_image_path))
    text, response = await chat([{"role":"user","content":[{"type":"text","text":OCR_PROMPT},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{encoded}"}}]}])
    db.add(OCRResult(card_id=card.id, engine="ykr-multimodal", engine_version=settings.ai_model, raw_text=text, raw_json=response))
    db.add(ProcessingHistory(card_id=card.id, process_type="ocr", engine="ykr-multimodal", version=settings.ai_model, input_json={"prompt":OCR_PROMPT}, output_json={"raw_text":text}))
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
    db.add(contact); db.add(ProcessingHistory(card_id=card.id, process_type="llm", engine="ykr-multimodal", version=settings.ai_model, input_json={"raw_text":result.raw_text}, output_json=response))
    card.status = "review_required"; db.commit()

async def process_photo(photo_id: str, db: Session):
    photo = db.get(Photo, photo_id)
    try:
        photo.status = "detecting"; db.commit(); detect_cards(photo, db)
        for card in db.query(BusinessCard).filter_by(photo_id=photo.id).all():
            await run_ocr(card, db); await structure(card, db)
        photo.status = "completed"; db.commit()
    except Exception as exc:
        photo.status = "failed"; db.commit(); raise exc

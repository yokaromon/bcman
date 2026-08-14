import asyncio, base64, json, re, shutil, subprocess, tempfile
from io import BytesIO
from pathlib import Path
import cv2
import httpx
import numpy as np
from PIL import Image, ImageOps
from sqlalchemy.orm import Session
from .models import BusinessCard, Contact, Organization, OCRResult, Photo, ProcessingHistory, User, UserGroup
from .schemas import CONTACT_FIELDS
from .settings import settings

OCR_PROMPT = "画像内の文字をすべて正確に書き起こしてください。説明や前置きは不要で、本文のみを出力してください。"
STRUCTURE_PROMPT = """次のOCR原文から名刺情報をJSONだけで抽出してください。原文にない情報はnull。電話、FAX、携帯を区別してください。キーは company_name, company_name_kana, department, position, person_name, person_name_kana, postal_code, address, telephone, fax, mobile, email, website, notes です。\n\nOCR原文:\n"""

OCR_MAX_EDGE = 1600
OCR_JPEG_QUALITY = 85

# 名刺に繰り返し現れる要素。向きを間違えたOCRはこれらを揃えられないので、
# 「何種類そろったか」がそのまま向きの正しさの目安になる。
CARD_TEXT_SIGNALS = (
    r"〒\s*[\d０-９]{3}\s*[-‐－ー]?\s*[\d０-９]{4}",
    r"(?:TEL|Tel|ＴＥＬ|電話)[^\d０-９]{0,4}[\d０-９][\d０-９\-‐－()（） ]{7,}",
    r"(?:FAX|Fax|ＦＡＸ)[^\d０-９]{0,4}[\d０-９][\d０-９\-‐－()（） ]{7,}",
    r"[\w.+-]+@[\w-]+\.[\w.-]*\w",
    r"(?:https?://|www\.)[\w./%-]+",
    r"(?:株式会社|有限会社|合同会社|Co\.,?\s*Ltd|Inc\.|Corporation)",
    r"(?:北海道|東京都|大阪府|京都府|[^\W\d_]{2,3}県)",
)
# 3種そろえば採用して打ち切る。一般的な名刺は正しい向きなら5〜7種そろうので、
# ここで止まらないのは情報量の少ない名刺だけになる。
ORIENTATION_ACCEPT_SIGNALS = 3
# 向きが違うとモデルは短い断片か「読めない」旨の文を返す。どちらも0点にする。
OCR_MIN_LENGTH = 10
OCR_REFUSAL_MARKERS = ("読み取れ", "判読", "不鮮明", "認識できま", "cannot", "can't", "unable", "sorry")

# 名刺の実寸 91×55mm は比 1.65。斜めから撮ったときの透視短縮でずれる分だけ幅を持たせる。
CARD_ASPECT_MIN, CARD_ASPECT_MAX = 1.35, 2.10
# 下限は8枚並べの1枚を通す値。上限は「写真全体に近い輪郭」を名刺と見なさないための値。
CARD_AREA_MIN_RATIO, CARD_AREA_MAX_RATIO = .015, .60
# 検出が暴走したときにOCRの実行回数を抑える安全弁。品質目標の8枚より少しだけ余裕を持たせる。
CARD_LIMIT = 12
# 同じ名刺から出た内外の輪郭や文字ブロックは、片方がもう片方にほぼ収まる。
# IoU ではなく「小さい方の面積に対する重なり率」で見るのは、接して置いた別の名刺を消さないため。
CARD_CONTAINMENT = .6
CARD_APPROX_EPSILON_RATIO = .02
CARD_EDGE_CLOSE_KERNEL = 5
# 全画素で1枚も採れなかったときに拾い直す縮小サイズ。手に持って撮った1枚は指で外形が
# 途切れ、1200万画素のままでは輪郭が閉じずに名刺の形にならない。縮小すると途切れが埋まる。
# 逆に机に並べた複数枚では机の輪郭が優勢になって本物を飲み込むので、初手には使わない。
CARD_RETRY_LONG_EDGE = 2000

THUMBNAIL_MAX_EDGE = 800
THUMBNAIL_JPEG_QUALITY = 80

def image_size(path: Path):
    """EXIFの回転を適用したあとの寸法を返す。検出も切り出しも cv2 が EXIF を適用した向きで
    行うので、生の寸法を返すと保存した写真サイズと名刺の座標が別の空間の値になる。"""
    with Image.open(path) as image: return ImageOps.exif_transpose(image).size

def ensure_thumbnail(source: Path, thumb: Path) -> Path:
    """一覧用の縮小JPEGのパスを返す。無ければ作って残す。
    アップロード時ではなく初回参照時に作るのは、すでに保存済みの写真・名刺に対して
    作り直しのバッチを用意せずに済ませるため。原本はそのまま残す。"""
    if thumb.exists(): return thumb
    if not source.exists(): raise FileNotFoundError(source)
    with Image.open(source) as image:
        # スマホの写真はEXIFで向きを持つ。適用しないと一覧だけ横倒しで並ぶ
        prepared = ImageOps.exif_transpose(image).convert("RGB")
        prepared.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE))
        thumb.parent.mkdir(parents=True, exist_ok=True)
        prepared.save(thumb, format="JPEG", quality=THUMBNAIL_JPEG_QUALITY)
    return thumb

def photo_thumbnail(photo: Photo) -> Path:
    return ensure_thumbnail(Path(photo.storage_path), settings.storage_dir / "photos" / photo.id / "thumb.jpg")

def card_image_revision(card: BusinessCard) -> str:
    """向き補正画像が差し替わるたびに変わる、表示キャッシュ用の識別子を返す。
    orientation だけでは同じ角度での再認識を区別できないため、保存先と更新時刻も含める。"""
    source = Path(card.oriented_image_path or card.corrected_image_path)
    try:
        stat = source.stat()
        freshness = f"{stat.st_mtime_ns:x}-{stat.st_size:x}"
    except OSError:
        # 画像が失われた古いレコードでもカード一覧API自体は返せるようにする
        freshness = "missing"
    return f"{card.orientation}-{source.stem}-{freshness}"

def card_thumbnail(card: BusinessCard) -> Path:
    source = Path(card.oriented_image_path or card.corrected_image_path)
    # 向き補正前の thumb.jpg を再利用すると、回転後も一覧だけ古い向きのままになる。
    # 元画像のrevisionごとに別ファイルへ出し、ブラウザ側のversion付きURLと対応させる。
    return ensure_thumbnail(source, source.parent / f"thumb-{card_image_revision(card)}.jpg")

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

def _ordered_corners(corners):
    """四隅を左上・右上・右下・左下の順に整える。
    getPerspectiveTransform はこの順序を前提にしていて、順序が崩れると鏡像・せん断した
    切り抜きになる。重心まわりの角度で並べるのは、どの点も1度ずつ使われることを保証するため
    （和・差の最大最小で選ぶと、正方形に近い四角形で同じ点が二度選ばれて変換が壊れる）。"""
    points = np.float32(corners).reshape(-1, 2)
    center = points.mean(axis=0)
    # 画像座標はyが下向きなので、角度の昇順がそのまま時計回りになる
    clockwise = points[np.argsort(np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0]))]
    top_left = int(np.argmin(clockwise.sum(axis=1)))
    return np.float32(np.roll(clockwise, -top_left, axis=0))

def _write_card(photo: Photo, db: Session, image, corners, confidence=.75):
    points = _ordered_corners(corners)
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

def _quad_from_contour(contour):
    """輪郭を四角形の四隅にする。4頂点に近似できるならその形をそのまま使い、台形の歪みも拾う。
    できないときは最小面積の回転矩形で近似する。軸平行の外接矩形を使わないのは、斜めに置いた
    名刺だと外接矩形の比が正方形に寄って名刺と判定できず、枠も隣の名刺まで巻き込むため。"""
    approx = cv2.approxPolyDP(contour, CARD_APPROX_EPSILON_RATIO * cv2.arcLength(contour, True), True)
    if len(approx) == 4: return approx.reshape(4, 2).astype(np.float32)
    return cv2.boxPoints(cv2.minAreaRect(contour)).astype(np.float32)

def _looks_like_card(quad, photo_area: float) -> bool:
    (_, _), (rect_width, rect_height), _ = cv2.minAreaRect(quad)
    short_edge, long_edge = min(rect_width, rect_height), max(rect_width, rect_height)
    if short_edge <= 0: return False
    within_shape = CARD_ASPECT_MIN <= long_edge / short_edge <= CARD_ASPECT_MAX
    within_size = CARD_AREA_MIN_RATIO <= cv2.contourArea(quad) / photo_area <= CARD_AREA_MAX_RATIO
    return within_shape and within_size

def _containment(a, b) -> float:
    """2つの矩形の重なりを、小さい方の面積に対する割合で返す。"""
    ax, ay, aw, ah = a; bx, by, bw, bh = b
    ix, iy = max(ax, bx), max(ay, by); ex, ey = min(ax+aw, bx+bw), min(ay+ah, by+bh)
    intersection = max(0, ex-ix) * max(0, ey-iy)
    return intersection / max(1, min(aw*ah, bw*bh))

def _card_candidates(image):
    """名刺らしい四角形を輪郭から拾い、重なるものを畳んで (四隅, 外接矩形) を面積の大きい順に返す。"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
    # Canny のエッジは途切れるので、閉じてから輪郭を取らないと1枚の名刺が断片に割れる
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((CARD_EDGE_CLOSE_KERNEL, CARD_EDGE_CLOSE_KERNEL), np.uint8))
    # RETR_EXTERNAL にするのは、名刺の枠線の内側や文字ブロックを別の候補として数えないため
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    height, width = image.shape[:2]
    photo_area = float(max(1, width * height))
    found = [quad for quad in (_quad_from_contour(contour) for contour in contours) if _looks_like_card(quad, photo_area)]
    found.sort(key=cv2.contourArea, reverse=True)
    accepted = []
    for quad in found:
        box = cv2.boundingRect(quad.astype(np.int32))
        # 大きい順に見ているので、採用済みの候補に収まるものは同じ名刺の内側の輪郭とみなせる
        overlapped = any(_containment(box, taken) > CARD_CONTAINMENT for _, taken in accepted)
        if overlapped: continue
        accepted.append((quad, box))
        if len(accepted) >= CARD_LIMIT: break
    return accepted

def _largest_candidate_from_smaller(image):
    """縮小した画像で拾い直し、四隅を元の寸法に戻して1件だけ返す。
    ここへ来るのは全画素で1枚も採れなかった写真、つまり名刺を手に持って大きく撮った類。
    縮小で拾えるのは大きく写った1枚なので、最大の候補だけを採る。"""
    long_edge = max(image.shape[:2])
    if long_edge <= CARD_RETRY_LONG_EDGE: return []
    scale = CARD_RETRY_LONG_EDGE / float(long_edge)
    smaller = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    candidates = _card_candidates(smaller)[:1]
    return [(quad / scale, cv2.boundingRect((quad / scale).astype(np.int32))) for quad, _ in candidates]

def card_quads(image):
    """写真から名刺候補の四隅を、上の行から・行内は左から並べて返す。"""
    accepted = _card_candidates(image) or _largest_candidate_from_smaller(image)
    # 輪郭の走査順は写真上の配置と無関係（右下の名刺が先頭になることがある）。
    # 画面では順にめくって確認するので、上の行から・行内は左からの順に並べ替える。
    # 行の判定に自身の高さを使うと、横に並んだ名刺のわずかなy差では行が割れない。
    accepted.sort(key=lambda item: (item[1][1] // max(item[1][3], 1), item[1][0]))
    return [_ordered_corners(quad).tolist() for quad, _ in accepted]

def detect_cards(photo: Photo, db: Session):
    source = Path(photo.storage_path)
    image = cv2.imread(str(source))
    if image is None: raise ValueError("画像を読み込めません")
    quads = card_quads(image)
    if quads:
        for corners in quads: _write_card(photo, db, image, corners)
    else:
        # 名刺1枚を画面いっぱいに撮ると外形が画面端に接し、輪郭として出てこない。
        # 撮り直しを求める前に、写真全体を1枚として確度を下げて拾う。
        height, width = image.shape[:2]
        _write_card(photo, db, image, [[0,0],[width-1,0],[width-1,height-1],[0,height-1]], .2)
    photo.status = "detected"; db.commit()

def add_manual_card(photo: Photo, db: Session, corners):
    image = cv2.imread(str(Path(photo.storage_path)))
    if image is None: raise ValueError("画像を読み込めません")
    height, width = image.shape[:2]
    if any(x < 0 or y < 0 or x >= width or y >= height for x, y in corners): raise ValueError("四隅は写真の範囲内で指定してください")
    card = _write_card(photo, db, image, corners, 1.0); db.commit(); return card

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

def ocr_text_score(text: str) -> int:
    """OCR結果が名刺として成立している度合いを、名刺特有の要素の種類数で返す。
    向きの判定にモデルへ角度を尋ねないのは、8BクラスのVLMは「何度回すか」という幾何推論より
    読字のほうが確度が高く、読めた結果そのものが向きの答えになるため。"""
    body = (text or "").strip()
    if len(body) < OCR_MIN_LENGTH: return 0
    lowered = body.lower()
    if any(marker in lowered for marker in OCR_REFUSAL_MARKERS): return 0
    return sum(1 for pattern in CARD_TEXT_SIGNALS if re.search(pattern, body))

def orientation_order(width: int, height: int) -> list[int]:
    """試す向きの優先順を返す。日本の名刺は横型が大半なので、切り抜きが縦長のときは
    「縦型名刺が正立している」より「横型名刺を横倒しで撮った」を先に疑う。"""
    return [0, 180, 90, 270] if width >= height else [90, 270, 0, 180]

async def _read_rotated(card: BusinessCard, rotation: int):
    """指定した向きに回した派生画像を作り、それをOCRした結果と得点を返す。"""
    source = Path(card.corrected_image_path)
    target = source.parent / f"oriented-{rotation}.jpg"
    _rotated_image(source, rotation, target)
    encoded = encode_for_ocr(target)
    text, response = await chat([{"role":"user","content":[{"type":"text","text":OCR_PROMPT},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{encoded}"}}]}])
    return {"rotation": rotation, "path": target, "text": text, "response": response, "score": ocr_text_score(text)}

def osd_orientation(path: Path) -> tuple[int | None, float]:
    """Tesseract内蔵OSD(--psm 0)で必要な回転角を1回のローカル処理で推定する。
    バイナリが無い・OSDが向きを決めきれない画像では (None, 0.0) を返し、呼び出し側にAI探索へ委ねさせる。"""
    with tempfile.TemporaryDirectory() as tmp:
        out_base = Path(tmp) / "osd"
        try:
            subprocess.run([settings.tesseract_cmd, str(path), str(out_base), "--psm", "0"], capture_output=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None, 0.0
        result = out_base.with_suffix(".osd")
        if not result.exists(): return None, 0.0
        output = result.read_text(encoding="utf-8", errors="ignore")
    rotate_match = re.search(r"Rotate:\s*(\d+)", output)
    if not rotate_match: return None, 0.0
    conf_match = re.search(r"Orientation confidence:\s*([\d.]+)", output)
    return int(rotate_match.group(1)) % 360, float(conf_match.group(1)) if conf_match else 0.0

async def _finish_recognition(card: BusinessCard, db: Session, rotation: int, target: Path, orientation_history: ProcessingHistory):
    """確定した向きで1回だけOCRし、結果を保存する。"""
    encoded = encode_for_ocr(target)
    text, response = await chat([{"role":"user","content":[{"type":"text","text":OCR_PROMPT},{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{encoded}"}}]}])
    card.oriented_image_path, card.orientation = str(target), rotation
    db.add(OCRResult(card_id=card.id, engine="ykr-multimodal", engine_version=settings.ai_model, raw_text=text, raw_json=response))
    db.add(orientation_history)
    db.add(ProcessingHistory(card_id=card.id, process_type="ocr", engine="ykr-multimodal", version=settings.ai_model, input_json={"prompt":OCR_PROMPT,"orientation":rotation}, output_json={"raw_text":text}))
    card.status = "ocr_completed"; db.commit()

async def recognize_card(card: BusinessCard, db: Session):
    """向きはまずローカルのTesseract OSDで即断する(ADR 0012)。確信が持てないカードだけ、
    向きを変えながらOCRして名刺として最も成立した結果を採用するAI探索(ADR 0011)にフォールバックする。"""
    card.status = "ocr_processing"; db.commit()
    source = Path(card.corrected_image_path)
    osd_rotation, osd_confidence = osd_orientation(source)
    if osd_rotation is not None and osd_confidence >= settings.orientation_osd_confidence_min:
        target = source.parent / f"oriented-{osd_rotation}.jpg"
        _rotated_image(source, osd_rotation, target)
        history = ProcessingHistory(card_id=card.id, process_type="orientation", engine="tesseract-osd", version="", input_json={"confidence_min":settings.orientation_osd_confidence_min}, output_json={"rotation":osd_rotation,"confidence":osd_confidence,"image_path":str(target)})
        await _finish_recognition(card, db, osd_rotation, target, history)
        return
    with Image.open(source) as image: width, height = image.size
    order = orientation_order(width, height)
    attempts, best = [], None
    for rotation in order:
        attempt = await _read_rotated(card, rotation)
        attempts.append({"rotation": rotation, "score": attempt["score"], "length": len(attempt["text"] or "")})
        if best is None or attempt["score"] > best["score"]: best = attempt
        if attempt["score"] >= ORIENTATION_ACCEPT_SIGNALS: break
    card.oriented_image_path, card.orientation = str(best["path"]), best["rotation"]
    db.add(OCRResult(card_id=card.id, engine="ykr-multimodal", engine_version=settings.ai_model, raw_text=best["text"], raw_json=best["response"]))
    db.add(ProcessingHistory(card_id=card.id, process_type="orientation", engine="ykr-multimodal", version=settings.ai_model, input_json={"order":order,"accept_signals":ORIENTATION_ACCEPT_SIGNALS,"osd_rotation":osd_rotation,"osd_confidence":osd_confidence}, output_json={"attempts":attempts,"chosen":best["rotation"],"image_path":str(best["path"])}))
    db.add(ProcessingHistory(card_id=card.id, process_type="ocr", engine="ykr-multimodal", version=settings.ai_model, input_json={"prompt":OCR_PROMPT,"orientation":best["rotation"]}, output_json={"raw_text":best["text"]}))
    card.status = "ocr_completed"; db.commit()

def apply_orientation(card: BusinessCard, db: Session, rotation: int):
    """ユーザーが指定した向きを確定させる。自動判定の派生画像を上書きしないよう、
    読み取り回数を足したファイル名に書き出して訂正の履歴を残す。"""
    target = Path(card.corrected_image_path).parent / f"oriented-{rotation}-{len(db.query(OCRResult).filter_by(card_id=card.id).all())}.jpg"
    _rotated_image(Path(card.corrected_image_path), rotation, target)
    card.oriented_image_path, card.orientation = str(target), rotation
    db.add(ProcessingHistory(card_id=card.id, process_type="orientation", engine="user", version="", input_json={"rotation":rotation}, output_json={"image_path":str(target)}))
    db.commit()

async def run_ocr(card: BusinessCard, db: Session):
    """いま確定している向きのままOCRし直す。向きをユーザーが指定した直後に使うので、
    ここで探索をやり直すと指定を上書きしてしまう。"""
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
                await recognize_card(card, db); await structure(card, db); return
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
        card_ids = [card.id for card in db.query(BusinessCard).filter_by(photo_id=photo.id).all()]
        if not card_ids: photo.status = "failed"; db.commit(); return
        semaphore = asyncio.Semaphore(3)
        async def queued(card_id):
            async with semaphore: await _process_card(card_id)
        await asyncio.gather(*(queued(card_id) for card_id in card_ids))
        photo.status = "completed"; db.commit()
    except Exception as exc:
        photo.status = "failed"; db.commit(); raise exc

# --- 可視範囲（Organization/Group/Sharing Mode）。directory.service からも使う ---

def user_group_ids(db: Session, user: User) -> list[str]:
    return [row.group_id for row in db.query(UserGroup).filter_by(user_id=user.id)]

def visible_photo_query(db: Session, user: User):
    query = db.query(Photo).filter(Photo.organization_id == user.organization_id)
    org = db.get(Organization, user.organization_id)
    if user.role == "admin" or org.sharing_mode == "shared": return query
    return query.filter(Photo.group_id.in_(user_group_ids(db, user)))

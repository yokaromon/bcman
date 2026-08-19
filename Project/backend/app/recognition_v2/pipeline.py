"""Recognition Pipeline V2: 切り抜き→ローカル向き判定→管理ykrによるOCR/Contact構造化。

V1 (`app/services.py`) とは完全に独立したコードパス。既存カード・既存Contactには
一切触れず、`Photo.pipeline_version == "v2"` の写真から作られたカードだけがここを通る。
ADR 0019 / CONTEXT.md の Reading Orientation・Structured Field Candidate の定義に従う:
- 向きはCard Extractionごとに1回だけ自動提案し、確定できなければ撮影時のままOCRへ進む
  （Orientation Uncertain）
- OCR/Contactは常にReview Flag付きの未確定候補。`Contact.confirmed`はここでは絶対にセットしない
  （確定は既存の /confirm・/confirm-cards ルートのみが行う）
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import cv2
from sqlalchemy.orm import Session

from ..models import BusinessCard, Contact, OCRResult, Photo, ProcessingHistory
from ..search_text import refresh_search_text
from ..settings import settings
from . import detector
from .alignment import align_ocr_lines
from .model_runtime import PaddleModels
from .orientation import OrientationEngine
from .recognition_contract import CONTACT_FIELDS, RecognitionContractError, enrich_contact
from .text_regions import LocalTextPipeline
from .ykr_client import ManagedRecognitionClient, ManagedRecognitionError, YkrSettings

logger = logging.getLogger(__name__)

ORIENTATION_MODEL_NAME = "PP-LCNet_x1_0_doc_ori"
DETECTOR_ENGINE = "pickup-detector-v2"
OCR_ENGINE = "ykr-ocr-v2"
CONTACT_ENGINE = "ykr-contact-v2"
CARD_PROCESS_CONCURRENCY = 3

REVIEW_FLAG_MESSAGES = {
    "unreadable": "読み取れませんでした（要確認）",
    "missing_text_evidence": "OCR原文に根拠が見つかりません（要確認）",
    "evidence_mismatch": "OCR原文と一致しません（要確認）",
    "unmatched_text_only": "ローカル検出と対応しない行から抽出されました（要確認）",
    "invalid_email_format": "メールアドレスの形式を確認してください",
    "invalid_phone_format": "電話番号の形式を確認してください",
    "invalid_postal_code_format": "郵便番号の形式を確認してください",
    "invalid_website_format": "URLを確認してください",
}

# Paddleモデルとローカル文字領域パイプラインはプロセス内で1回だけロードして使い回す
# （pickup/model_runtime.py と同じ遅延生成）。
_models: PaddleModels | None = None
_text_pipeline: LocalTextPipeline | None = None


def _shared_models() -> PaddleModels:
    global _models
    if _models is None:
        _models = PaddleModels()
    return _models


def _local_text_pipeline() -> LocalTextPipeline:
    global _text_pipeline
    if _text_pipeline is None:
        _text_pipeline = LocalTextPipeline(_shared_models())
    return _text_pipeline


def _ykr_client() -> ManagedRecognitionClient:
    ykr_settings = YkrSettings(
        base_url=settings.ai_base_url,
        api_key=settings.ai_api_key,
        ocr_model=settings.ai_model,
        contact_model=settings.ai_model,
    )
    return ManagedRecognitionClient(ykr_settings)


def _write_card_v2(photo: Photo, db: Session, image, detection: detector.Detection) -> BusinessCard:
    corners = detector.ordered_corners(detection.corners)
    x, y, w, h = cv2.boundingRect(corners.astype("int32"))
    card = BusinessCard(
        photo_id=photo.id, detected_image_path="", corrected_image_path="",
        detection_confidence=detection.confidence, x=x, y=y, width=w, height=h,
    )
    db.add(card); db.flush()
    target = settings.storage_dir / "photos" / photo.id / "cards" / card.id
    target.mkdir(parents=True, exist_ok=True)
    corrected_image = detector.perspective_crop(image, corners)
    detected_path, corrected_path, oriented_path = target / "detected.jpg", target / "corrected.jpg", target / "oriented-0.jpg"
    detector.write_image(detected_path, image[max(0, y):max(0, y) + h, max(0, x):max(0, x) + w])
    detector.write_image(corrected_path, corrected_image)
    detector.write_image(oriented_path, corrected_image)
    card.detected_image_path, card.corrected_image_path, card.oriented_image_path = str(detected_path), str(corrected_path), str(oriented_path)
    card.orientation, card.status = 0, "corrected"
    db.add(ProcessingHistory(
        card_id=card.id, process_type="extraction", engine=DETECTOR_ENGINE, version=detector.DETECTOR_VERSION,
        input_json={}, output_json={"confidence": detection.confidence, "strategy": detection.strategy, "score": detection.score},
    ))
    return card


def _auto_orient_v2(card: BusinessCard, db: Session) -> None:
    """Card Extraction直後に1回だけ向きを自動提案する（CONTEXT.md Reading Orientation）。
    確定できなければ撮影時のまま(rotation=0)残し、Orientation Decisionをuncertainにする。
    分類器の自己整合性だけで確定できないときは、pickupと同じくローカルOCRの可読性スコアで
    4方向を比較するフォールバックへ進む（readability_scorer）。"""
    image = detector.read_image(Path(card.corrected_image_path))
    engine = OrientationEngine(_shared_models())
    oriented_image, document = engine.analyze(
        image, readability_scorer=_local_text_pipeline().readability
    )
    rotation = document["rotation_applied"]
    if rotation:
        target = Path(card.corrected_image_path).parent / f"oriented-{rotation}-auto.jpg"
        detector.write_image(target, oriented_image)
        card.oriented_image_path, card.orientation = str(target), rotation
    card.orientation_decision = document["status"]
    db.add(ProcessingHistory(
        card_id=card.id, process_type="orientation", engine="pickup-orientation-v2",
        version=ORIENTATION_MODEL_NAME, input_json={}, output_json=document,
    ))


def detect_cards_v2(photo: Photo, db: Session) -> None:
    source = Path(photo.storage_path)
    image = detector.read_image(source)
    detections = detector.detect_cards(image)
    if not detections:
        # V1のフォールバックと同じく、輪郭が拾えない写真は全体を確度の低い1枚として扱う
        height, width = image.shape[:2]
        full_frame = detector.Detection(
            corners=detector.ordered_corners([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]]),
            confidence=0.2, strategy="full_frame_fallback", score=0.0, contrast=0.0,
        )
        detections = [full_frame]
    for detection in detections:
        card = _write_card_v2(photo, db, image, detection)
        _auto_orient_v2(card, db)
    photo.status = "detected"; db.commit()


def add_manual_card_v2(photo: Photo, db: Session, corners) -> BusinessCard:
    image = detector.read_image(Path(photo.storage_path))
    height, width = image.shape[:2]
    if any(x < 0 or y < 0 or x >= width or y >= height for x, y in corners):
        raise ValueError("四隅は写真の範囲内で指定してください")
    detection = detector.Detection(
        corners=detector.ordered_corners(corners), confidence=1.0,
        strategy="manual", score=1.0, contrast=0.0,
    )
    card = _write_card_v2(photo, db, image, detection)
    _auto_orient_v2(card, db)
    db.commit()
    return card


def _apply_contact_fields(contact: Contact, enriched_fields: dict) -> dict:
    flags: dict[str, str] = {}
    for name in CONTACT_FIELDS:
        field = enriched_fields[name]
        value = field["display_value"] if field["state"] == "present" else None
        setattr(contact, name, value)
        reasons = field.get("review_flags") or []
        if reasons:
            flags[name] = REVIEW_FLAG_MESSAGES.get(reasons[0], "要確認")
    return flags


async def run_ocr_v2(card: BusinessCard, db: Session) -> None:
    """向きは探索せず、現在確定している向き(自動提案またはユーザー訂正済み)でOCRする。

    ykr呼び出しの前にローカルPaddleOCRの文字領域検出も行い、ykrの文字起こしと突き合わせた
    alignment（対応証拠）を作る。これはprompts/v2/contact.txtがContact構造化の根拠として
    前提にしている入力で、alignment無しではpickupで検証した精度が出ない（2026-08-18判明）。"""
    card.status = "ocr_processing"; db.commit()
    image_path = Path(card.oriented_image_path or card.corrected_image_path)
    image = detector.read_image(image_path)
    try:
        local_ocr = await asyncio.to_thread(_local_text_pipeline().process, image, server=True)
    except Exception:
        # ローカル検出はalignmentの根拠証拠であって必須ではない。失敗してもykrのOCR/Contact
        # 構造化自体は続行できる（2026-08-19、この例外を素通しにしてカード全体を落として
        # いたことがretry_required多発の原因だった実インシデント）。
        logger.exception("recognition_v2: card %s local text detection failed, continuing without alignment", card.id)
        local_ocr = {"regions": []}
    client = _ykr_client()
    try:
        stage = await asyncio.to_thread(client.run_ocr, image_path)
    except (ManagedRecognitionError, RecognitionContractError) as exc:
        raise ValueError(str(exc)) from exc
    alignment = align_ocr_lines(local_ocr, stage.document)
    raw_text = "\n".join(line.get("text") or "" for line in stage.document["lines"])
    raw_json = {**stage.document, "alignment": alignment}
    db.add(OCRResult(card_id=card.id, engine=OCR_ENGINE, engine_version=stage.model, raw_text=raw_text, raw_json=raw_json))
    db.add(ProcessingHistory(
        card_id=card.id, process_type="ocr", engine=OCR_ENGINE, version=stage.model,
        input_json={"prompt_version": stage.prompt_version, "orientation": card.orientation, "attempts": stage.attempts},
        output_json=raw_json,
    ))
    db.add(ProcessingHistory(
        card_id=card.id, process_type="ocr_local_diagnostic", engine="pickup-text-regions-v2",
        version="PP-OCRv5_server_det+PP-OCRv5_server_rec", input_json={}, output_json=local_ocr,
    ))
    card.status = "ocr_completed"; db.commit()


async def structure_v2(card: BusinessCard, db: Session) -> None:
    result = db.query(OCRResult).filter_by(card_id=card.id).order_by(OCRResult.created_at.desc()).first()
    if not result: raise ValueError("先にOCRを実行してください")
    card.status = "llm_processing"; db.commit()
    alignment = result.raw_json.get("alignment") or []
    ocr_document = {"schema_version": 1, "lines": result.raw_json["lines"]}
    client = _ykr_client()
    try:
        stage = await asyncio.to_thread(client.structure_contact, ocr_document, alignment)
    except (ManagedRecognitionError, RecognitionContractError) as exc:
        raise ValueError(str(exc)) from exc
    enriched = enrich_contact(stage.document, ocr_document, alignment=alignment)
    contact = db.query(Contact).filter_by(card_id=card.id).first() or Contact(card_id=card.id)
    contact.review_flags = _apply_contact_fields(contact, enriched["fields"])
    refresh_search_text(contact)
    db.add(contact)
    db.add(ProcessingHistory(
        card_id=card.id, process_type="llm", engine=CONTACT_ENGINE, version=stage.model,
        input_json={"prompt_version": stage.prompt_version, "attempts": stage.attempts},
        output_json=enriched,
    ))
    card.status = "review_required"; db.commit()


async def _process_card_v2(card_id: str) -> None:
    from ..database import SessionLocal
    for attempt in range(2):
        with SessionLocal() as db:
            card = db.get(BusinessCard, card_id)
            try:
                await run_ocr_v2(card, db); await structure_v2(card, db); return
            except Exception:
                db.rollback()
                # 例外を握りつぶすと本番でのみ再現する失敗の原因が追えなくなる
                # （2026-08-19、retry_requiredが握りつぶされたまま多発した実インシデント）。
                logger.exception("recognition_v2: card %s attempt %d/2 failed", card_id, attempt + 1)
                if attempt:
                    card = db.get(BusinessCard, card_id); card.status = "retry_required"; db.commit(); return


async def process_card_v2(card_id: str) -> None:
    await _process_card_v2(card_id)


async def process_photo_v2(photo_id: str, db: Session) -> None:
    photo = db.get(Photo, photo_id)
    try:
        photo.status = "detecting"; db.commit(); detect_cards_v2(photo, db)
        card_ids = [card.id for card in db.query(BusinessCard).filter_by(photo_id=photo.id).all()]
        if not card_ids: photo.status = "failed"; db.commit(); return
        semaphore = asyncio.Semaphore(CARD_PROCESS_CONCURRENCY)
        async def queued(card_id):
            async with semaphore: await _process_card_v2(card_id)
        await asyncio.gather(*(queued(card_id) for card_id in card_ids))
        photo.status = "completed"; db.commit()
    except Exception as exc:
        # 検出途中で落ちた場合、flush済みの中途半端なカードがsessionに残っている。
        # 先にrollbackしないと、failedを記録するcommitがそれらを一緒に確定させてしまう
        # （向きモデル未配置で1枚目に失敗したとき、OCR前のカードだけが残る）。
        db.rollback()
        logger.exception("recognition_v2: photo %s processing failed", photo_id)
        photo = db.get(Photo, photo_id)
        photo.status = "failed"; db.commit(); raise exc

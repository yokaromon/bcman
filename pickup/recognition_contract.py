from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from jsonschema import Draft202012Validator


BASE_DIR = Path(__file__).resolve().parent
SCHEMA_DIR = BASE_DIR / "schemas" / "v1"
CONTACT_FIELDS = (
    "company_name",
    "company_name_kana",
    "department",
    "position",
    "person_name",
    "person_name_kana",
    "postal_code",
    "address",
    "telephone",
    "fax",
    "mobile",
    "email",
    "website",
    "notes",
)


class RecognitionContractError(ValueError):
    pass


def load_schema(name: str) -> dict:
    path = SCHEMA_DIR / f"{name}.schema.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecognitionContractError(f"schemaを読めません: {path}") from exc


OCR_SCHEMA = load_schema("ykr_ocr_response")
CONTACT_SCHEMA = load_schema("contact_response")
OCR_VALIDATOR = Draft202012Validator(OCR_SCHEMA)
CONTACT_VALIDATOR = Draft202012Validator(CONTACT_SCHEMA)


def parse_json_object(content: str) -> dict:
    try:
        document = json.loads(content.strip())
    except json.JSONDecodeError as exc:
        raise RecognitionContractError("応答がJSON objectではありません") from exc
    if not isinstance(document, dict):
        raise RecognitionContractError("応答のrootはJSON objectである必要があります")
    return document


def _validate(validator: Draft202012Validator, document: dict, label: str) -> None:
    errors = sorted(validator.iter_errors(document), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        location = ".".join(str(value) for value in first.absolute_path) or "$"
        raise RecognitionContractError(f"{label} schema違反 ({location}): {first.message}")


def validate_ocr_response(document: dict) -> dict:
    _validate(OCR_VALIDATOR, document, "OCR")
    lines = []
    for index, source in enumerate(document["lines"], 1):
        text = source["text"]
        if source["legibility"] == "readable" and not (text and text.strip()):
            raise RecognitionContractError("readable行にはtextが必要です")
        if source["legibility"] == "unreadable" and text is not None and not text.strip():
            text = None
        lines.append(
            {
                "line_id": f"line-{index:03d}",
                "text": text,
                "source": source["source"],
                "legibility": source["legibility"],
            }
        )
    return {"schema_version": 1, "lines": lines}


def validate_contact_response(document: dict, ocr_document: dict) -> dict:
    _validate(CONTACT_VALIDATOR, document, "contact")
    available = {line["line_id"] for line in ocr_document["lines"]}
    for name in CONTACT_FIELDS:
        field = document["fields"][name]
        state = field["state"]
        display = field["display_value"]
        candidate = field["candidate_value"]
        source_ids = field["source_line_ids"]
        unknown = set(source_ids) - available
        if unknown:
            raise RecognitionContractError(
                f"{name}が存在しないsource_line_idを参照しています: {sorted(unknown)}"
            )
        if state == "absent" and (display is not None or candidate is not None or source_ids):
            raise RecognitionContractError(f"{name}: absentは値と根拠を持てません")
        if state == "present" and (not display or not display.strip() or not source_ids):
            raise RecognitionContractError(f"{name}: presentには表示値と根拠が必要です")
        if state == "unreadable" and (display is not None or not source_ids):
            raise RecognitionContractError(
                f"{name}: unreadableは表示値なし・根拠ありである必要があります"
            )
    return document


FIELD_KEYS = ("state", "display_value", "candidate_value", "source_line_ids")
FIELD_STATES = ("present", "absent", "unreadable")
LINE_ID_PATTERN = re.compile(r"^line-[0-9]{3,}$")


def empty_contract_field() -> dict:
    return {
        "state": "absent",
        "display_value": None,
        "candidate_value": None,
        "source_line_ids": [],
    }


def _coerce_text(value) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _coerce_line_ids(value) -> list[str]:
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list):
        return []
    result: list[str] = []
    for item in items:
        usable = isinstance(item, str) and LINE_ID_PATTERN.match(item) and item not in result
        if usable:
            result.append(item)
    return result


def _coerce_field(name: str, source, repairs: list[dict]) -> dict:
    if not isinstance(source, dict):
        repairs.append({"field": name, "detail": "項目が無いためabsentとみなしました"})
        return empty_contract_field()

    field = empty_contract_field()
    field["display_value"] = _coerce_text(source.get("display_value"))
    field["candidate_value"] = _coerce_text(source.get("candidate_value"))
    field["source_line_ids"] = _coerce_line_ids(source.get("source_line_ids"))

    state = source.get("state")
    if state not in FIELD_STATES:
        state = "present" if field["display_value"] else "absent"
        repairs.append({"field": name, "detail": f"stateが不正なため{state}とみなしました"})
    field["state"] = state

    missing = [key for key in FIELD_KEYS if key not in source]
    if missing:
        repairs.append({"field": name, "detail": f"不足キーを補いました ({', '.join(missing)})"})
    extra = [key for key in source if key not in FIELD_KEYS]
    if extra:
        repairs.append({"field": name, "detail": f"余分なキーを削除しました ({', '.join(extra)})"})
    return field


def coerce_contact_document(document: dict) -> tuple[dict, list[dict]]:
    """応答を契約の「形」へ寄せる。意味の判断はせず、キー・型のずれだけを直す。"""
    repairs: list[dict] = []
    fields_source = document.get("fields")
    if not isinstance(fields_source, dict):
        # 雛形を無視してroot直下へ14項目を置く崩れ方が実際にあるため拾い上げる
        lifted = any(name in document for name in CONTACT_FIELDS)
        detail = "root直下の項目を拾いました" if lifted else "fieldsがありません"
        repairs.append({"field": None, "detail": detail})
        fields_source = document if lifted else {}

    fields = {name: _coerce_field(name, fields_source.get(name), repairs) for name in CONTACT_FIELDS}
    return {"schema_version": 1, "fields": fields}, repairs


def _repair_field_state(name: str, field: dict, repairs: list[dict]) -> None:
    """意味的invariantを満たさない項目を、他項目を巻き添えにせず単独で救済する。"""
    state, display, candidate = field["state"], field["display_value"], field["candidate_value"]
    if state == "absent" and display:
        field["state"] = "present"
        repairs.append({"field": name, "detail": "absentなのに値があるためpresentへ直しました"})
        return
    if state == "present" and not display:
        field["state"] = "unreadable" if candidate or field["source_line_ids"] else "absent"
        repairs.append({"field": name, "detail": f"presentなのに値が無いため{field['state']}へ直しました"})
        return
    if state == "unreadable" and display:
        # unreadableは表示値を持てない。読めた可能性のある文字列は候補として残す
        field["display_value"], field["candidate_value"] = None, candidate or display
        repairs.append({"field": name, "detail": "unreadableの表示値を候補値へ移しました"})


def repair_contact_document(document: dict, ocr_document: dict) -> tuple[dict, list[dict]]:
    """厳密検証を通らなかった応答を、項目単位の減点で使える形へ落とし込む。

    再試行を使い切った後の最終手段。1項目の崩れで残り13項目の正解まで捨てないために使う
    （2026-08-19、fields.addressのcandidate_valueキー欠落だけで全損した実インシデント）。
    直した項目は呼び出し元がReview Flagにするので、無検証で登録されることはない。
    """
    repaired, repairs = coerce_contact_document(document)
    available = {line["line_id"] for line in ocr_document["lines"]}
    for name in CONTACT_FIELDS:
        field = repaired["fields"][name]
        unknown = [line_id for line_id in field["source_line_ids"] if line_id not in available]
        if unknown:
            field["source_line_ids"] = [i for i in field["source_line_ids"] if i in available]
            repairs.append({"field": name, "detail": f"存在しない根拠行を外しました ({', '.join(unknown)})"})
        _repair_field_state(name, field, repairs)
    return repaired, repairs


def _compact(value: str | None) -> str:
    return re.sub(r"[^0-9a-zA-Zぁ-んァ-ヶ一-龠]", "", value or "").casefold()


def _normalized_value(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if name == "email":
        return re.sub(r"\s+", "", stripped).casefold()
    if name in {"telephone", "fax", "mobile"}:
        plus = "+" if stripped.startswith("+") else ""
        digits = re.sub(r"\D", "", stripped)
        return plus + digits if digits else None
    if name == "postal_code":
        return re.sub(r"[^0-9]", "", stripped) or None
    if name == "website":
        return re.sub(r"\s+", "", stripped).rstrip("/").casefold()
    return stripped


def enrich_contact(
    document: dict,
    ocr_document: dict,
    alignment: list[dict] | None = None,
) -> dict:
    lines = {line["line_id"]: line for line in ocr_document["lines"]}
    matched_lines = {
        item.get("line_id")
        for item in (alignment or [])
        if item.get("alignment_status") == "matched" and item.get("region_id")
    }
    enriched = {"schema_version": 1, "fields": {}, "review_flags": []}
    for name in CONTACT_FIELDS:
        source = document["fields"][name]
        value = source["display_value"] or source["candidate_value"]
        field = dict(source)
        field["normalized_value"] = _normalized_value(name, value)
        flags = []
        evidence_status = "not_applicable" if source["state"] == "absent" else "supported"
        normalized = field["normalized_value"]
        if source["state"] != "absent":
            evidence = " ".join(
                str(lines[line_id].get("text") or "")
                for line_id in source["source_line_ids"]
            )
            compact_value = _compact(value)
            compact_evidence = _compact(evidence)
            similarity = SequenceMatcher(None, compact_value, compact_evidence).ratio()
            if source["state"] == "present" and compact_value and not compact_evidence:
                flags.append("missing_text_evidence")
                evidence_status = "unsupported"
            if compact_value and compact_evidence and (
                compact_value not in compact_evidence
                and compact_evidence not in compact_value
                and similarity < 0.45
            ):
                flags.append("evidence_mismatch")
                evidence_status = "unsupported"
            if alignment is not None and source["source_line_ids"] and not (
                set(source["source_line_ids"]) & matched_lines
            ):
                flags.append("unmatched_text_only")
        if source["state"] == "unreadable":
            flags.append("unreadable")
        if name == "email" and normalized and not re.fullmatch(
            r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized
        ):
            flags.append("invalid_email_format")
        if name in {"telephone", "fax", "mobile"} and normalized:
            if len(re.sub(r"\D", "", normalized)) < 6:
                flags.append("invalid_phone_format")
        if name == "postal_code" and normalized and len(normalized) != 7:
            flags.append("invalid_postal_code_format")
        if name == "website" and normalized and not re.match(
            r"^(https?://|www\.)[^\s]+$", normalized
        ):
            flags.append("invalid_website_format")
        field["review_flags"] = flags
        field["evidence_status"] = evidence_status
        enriched["fields"][name] = field
        enriched["review_flags"].extend(
            {"field": name, "reason": reason} for reason in flags
        )
    return enriched

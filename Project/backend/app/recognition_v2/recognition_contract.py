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

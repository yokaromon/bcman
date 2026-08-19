from __future__ import annotations

import re

try:  # pickupはフラット配置、本番はパッケージ配置なので両方の解決順を許容する
    from .recognition_contract import CONTACT_FIELDS, empty_contract_field
except ImportError:  # pragma: no cover - pickup側の実行経路
    from recognition_contract import CONTACT_FIELDS, empty_contract_field


EMAIL = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)
WEBSITE = re.compile(
    r"(?:https?://|www\.)[A-Z0-9][A-Z0-9./?&_%#=+\-]*", re.IGNORECASE
)
PHONE = re.compile(r"(?:\+?\d[\d()\-\s]{5,}\d)")
# 前後を数字・ハイフンで挟まれた並びは郵便番号ではない（電話番号の一部を
# 「234-5678」のように拾ってしまうため）
POSTAL = re.compile(r"(?<![\d\-ー])(?:〒\s*)?(\d{3})[-ー\s]?(\d{4})(?![\d\-ー])")
MINIMUM_PHONE_DIGITS = 6
FAX_HINTS = ("fax", "ファクス", "ファックス")
MOBILE_HINTS = ("mobile", "cell", "携帯")
TELEPHONE_HINTS = ("tel", "phone", "電話")


def _empty_field() -> dict:
    return {
        "state": "absent",
        "display_value": None,
        "normalized_value": None,
        "source_region_ids": [],
        "review_flags": [],
    }


def _hinted_field(segment: str) -> str | None:
    lowered = segment.casefold()
    if any(hint in lowered for hint in FAX_HINTS):
        return "fax"
    if any(hint in lowered for hint in MOBILE_HINTS):
        return "mobile"
    if any(hint in lowered for hint in TELEPHONE_HINTS):
        return "telephone"
    return None


def _phone_matches(text: str) -> list[tuple[str, str, str]]:
    """番号ごとに、直前(なければ直後)のラベルで種別を決める。

    行全体からラベルを探すと「TEL 03-... FAX 03-...」が全部faxに倒れる。ykrのOCR行は
    ローカルの文字領域より広く、電話とFAXが1行にまとまることが多い。
    郵便番号と重なる並びは電話として拾わない。
    """
    postal_spans = [match.span() for match in POSTAL.finditer(text)]
    matches = []
    for match in PHONE.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        overlaps = any(start < match.end() and match.start() < end for start, end in postal_spans)
        if len(digits) >= MINIMUM_PHONE_DIGITS and not overlaps:
            matches.append(match)

    found: list[tuple[str, str, str]] = []
    for index, match in enumerate(matches):
        before = text[matches[index - 1].end() if index else 0 : match.start()]
        tail = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        after = text[match.end() : tail]
        value = match.group(0).strip()
        digits = re.sub(r"\D", "", value)
        name = _hinted_field(before) or _hinted_field(after)
        if name is None:
            name = "mobile" if digits.startswith(("070", "080", "090")) else "telephone"
        found.append((name, value, digits))
    return found


def _scan(text: str) -> list[tuple[str, str, str]]:
    """1行から(項目名, 表示値, 正規化値)を取り出す。形式で断定できるものだけを扱う。"""
    found: list[tuple[str, str, str]] = []
    for value in EMAIL.findall(text):
        found.append(("email", value, value.casefold()))
    for value in WEBSITE.findall(text):
        trimmed = value.rstrip(".,、。")
        found.append(("website", trimmed, trimmed.casefold()))
    for match in POSTAL.finditer(text):
        found.append(
            ("postal_code", f"{match.group(1)}-{match.group(2)}", "".join(match.groups()))
        )
    return found + _phone_matches(text)


def _set(fields: dict, name: str, value: str, region_id: str) -> None:
    field = fields[name]
    if field["state"] == "present":
        if value not in field["display_value"].split(" / "):
            field["display_value"] += " / " + value
            field["normalized_value"] += " / " + value
            field["source_region_ids"].append(region_id)
        return
    field.update(
        {
            "state": "present",
            "display_value": value,
            "normalized_value": value,
            "source_region_ids": [region_id],
        }
    )


def extract_local_contact(local_ocr: dict) -> dict:
    """ローカルOCRから確実な形式項目だけを抽出する診断用baseline。"""
    fields = {name: _empty_field() for name in CONTACT_FIELDS}
    for region in local_ocr.get("regions", []):
        text = str(region.get("text") or "").strip()
        region_id = str(region.get("region_id") or "")
        if not text or not region_id:
            continue
        for value in EMAIL.findall(text):
            _set(fields, "email", value, region_id)
            fields["email"]["normalized_value"] = fields["email"][
                "normalized_value"
            ].casefold()
        for value in WEBSITE.findall(text):
            _set(fields, "website", value.rstrip(".,、。"), region_id)
            fields["website"]["normalized_value"] = fields["website"][
                "normalized_value"
            ].casefold()
        for match in POSTAL.finditer(text):
            value = f"{match.group(1)}-{match.group(2)}"
            _set(fields, "postal_code", value, region_id)
            fields["postal_code"]["normalized_value"] = "".join(match.groups())
        for name, value, _ in _phone_matches(text):
            _set(fields, name, value, region_id)
            fields[name]["normalized_value"] = re.sub(
                r"\D", "", fields[name]["display_value"]
            )
    return {
        "schema_version": 1,
        "engine": "paddle-format-baseline-v1",
        "fields": fields,
    }


def contact_from_ocr_lines(ocr_document: dict) -> dict:
    """OCR行から形式で断定できる項目だけを拾い、contact契約の形で返す最終手段。

    LLMのContact構造化が全滅しても0点にしないための下限。氏名・会社名・部署のように
    形式では判別できない項目はabsentのまま残し、推測はしない（2026-08-19、契約違反で
    構造化が全損したときに全項目を失っていた実インシデント）。
    """
    collected: dict[str, list[tuple[str, str, str]]] = {name: [] for name in CONTACT_FIELDS}
    for line in ocr_document.get("lines", []):
        text = str(line.get("text") or "").strip()
        line_id = str(line.get("line_id") or "")
        if not text or not line_id:
            continue
        for name, display, normalized in _scan(text):
            already = any(seen == normalized for _, seen, _ in collected[name])
            if not already:
                collected[name].append((display, normalized, line_id))

    fields = {}
    for name in CONTACT_FIELDS:
        field = empty_contract_field()
        values = collected[name]
        if values:
            field["state"] = "present"
            field["display_value"] = " / ".join(display for display, _, _ in values)
            field["source_line_ids"] = sorted({line_id for _, _, line_id in values})
        fields[name] = field
    return {"schema_version": 1, "fields": fields}

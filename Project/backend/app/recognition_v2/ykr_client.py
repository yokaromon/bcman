from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import httpx
from PIL import Image

from .recognition_contract import (
    parse_json_object,
    validate_contact_response,
    validate_ocr_response,
)


BASE_DIR = Path(__file__).resolve().parent
REQUEST_TIMEOUT_SECONDS = 90
MAX_ATTEMPTS_PER_STAGE = 2


class ManagedRecognitionError(RuntimeError):
    pass


@dataclass(frozen=True)
class YkrSettings:
    base_url: str
    api_key: str
    ocr_model: str
    contact_model: str

    def validate(self) -> None:
        missing = []
        if not self.api_key:
            missing.append("AI_API_KEY")
        if not self.ocr_model or not self.contact_model:
            missing.append("AI_MODEL")
        if missing:
            raise ManagedRecognitionError("設定がありません: " + ", ".join(missing))
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "https" or parsed.hostname != "app.ykr.ltd":
            raise ManagedRecognitionError(
                "接続先は管理対象のhttps://app.ykr.ltd/ai/v1だけを許可します"
            )
        for model in (self.ocr_model, self.contact_model):
            if model.casefold() == "latest" or model.casefold().endswith(":latest"):
                raise ManagedRecognitionError("modelはlatestではなく固定名を指定してください")


@dataclass(frozen=True)
class StageResult:
    document: dict
    attempts: int
    model: str
    prompt_version: str
    schema_version: int = 1


PostJson = Callable[[str, dict, dict, float], dict]


def _default_post_json(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, headers=headers, json=payload)
        if response.is_error:
            raise ManagedRecognitionError(
                f"ykr APIがHTTP {response.status_code}を返しました"
            )
        try:
            value = response.json()
        except ValueError as exc:
            raise ManagedRecognitionError("ykr API応答がJSONではありません") from exc
        if not isinstance(value, dict):
            raise ManagedRecognitionError("ykr API応答のrootがobjectではありません")
        return value


def _prompt(name: str, version: str = "v1") -> str:
    return (BASE_DIR / "prompts" / version / f"{name}.txt").read_text(
        encoding="utf-8"
    ).strip()


def _jpeg_data_url(image_path: Path) -> str:
    with Image.open(image_path) as image:
        prepared = image.convert("RGB")
        prepared.thumbnail((1600, 1600))
        stream = BytesIO()
        prepared.save(stream, format="JPEG", quality=85, optimize=True)
    encoded = base64.b64encode(stream.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _content(response: dict) -> str:
    try:
        value = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ManagedRecognitionError("ykr API応答にmessage.contentがありません") from exc
    if not isinstance(value, str):
        raise ManagedRecognitionError("ykr APIのmessage.contentが文字列ではありません")
    return value


class ManagedRecognitionClient:
    def __init__(
        self,
        settings: YkrSettings,
        *,
        post_json: PostJson = _default_post_json,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        settings.validate()
        self.settings = settings
        self.post_json = post_json
        self.timeout = timeout

    def _request(
        self,
        *,
        model: str,
        messages: list[dict],
        validator: Callable[[dict], dict],
        stage: str,
    ) -> tuple[dict, int]:
        last_error: Exception | None = None
        request_messages = list(messages)
        for attempt in range(1, MAX_ATTEMPTS_PER_STAGE + 1):
            try:
                response = self.post_json(
                    f"{self.settings.base_url}/chat/completions",
                    {
                        "Authorization": f"Bearer {self.settings.api_key}",
                        "Content-Type": "application/json",
                    },
                    {
                        "model": model,
                        "messages": request_messages,
                        "temperature": 0,
                        "response_format": {"type": "json_object"},
                    },
                    self.timeout,
                )
                return validator(parse_json_object(_content(response))), attempt
            except Exception as exc:
                last_error = exc
                if attempt < MAX_ATTEMPTS_PER_STAGE:
                    request_messages = request_messages + [
                        {
                            "role": "user",
                            "content": (
                                "前回の応答は契約違反でした。説明やコードフェンスを付けず、"
                                "指定されたroot、必須キー、型を一字一句守ったJSON objectだけを"
                                "返してください。"
                            ),
                        }
                    ]
        raise ManagedRecognitionError(
            f"{stage}は{MAX_ATTEMPTS_PER_STAGE}回とも失敗しました: "
            f"{type(last_error).__name__}"
        ) from last_error

    def run_ocr(self, image_path: Path) -> StageResult:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _prompt("ocr")},
                    {
                        "type": "image_url",
                        "image_url": {"url": _jpeg_data_url(image_path)},
                    },
                ],
            }
        ]
        document, attempts = self._request(
            model=self.settings.ocr_model,
            messages=messages,
            validator=validate_ocr_response,
            stage="OCR",
        )
        return StageResult(document, attempts, self.settings.ocr_model, "ocr-v1")

    def structure_contact(
        self,
        ocr_document: dict,
        alignment: list[dict] | None = None,
    ) -> StageResult:
        source = json.dumps(
            {"ocr": ocr_document, "alignment": alignment or []},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        messages = [
            {
                "role": "user",
                "content": _prompt("contact", "v2") + "\n\n入力OCR・領域照合:\n" + source,
            }
        ]
        document, attempts = self._request(
            model=self.settings.contact_model,
            messages=messages,
            validator=lambda value: validate_contact_response(value, ocr_document),
            stage="contact構造化",
        )
        return StageResult(
            document, attempts, self.settings.contact_model, "contact-v2"
        )

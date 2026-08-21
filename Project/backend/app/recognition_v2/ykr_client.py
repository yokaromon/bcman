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
    repair_contact_document,
    validate_contact_response,
    validate_ocr_response,
)


BASE_DIR = Path(__file__).resolve().parent
REQUEST_TIMEOUT_SECONDS = 90
MAX_ATTEMPTS_PER_STAGE = 2


class ManagedRecognitionError(RuntimeError):
    def __init__(self, message: str, *, payload: dict | None = None) -> None:
        super().__init__(message)
        # 最後に受け取った(検証は通らなかった)JSON。呼び出し元が救済を試みるために残す
        self.payload = payload


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
    # 契約に満たない応答を救済した場合の修復内容。空なら厳密検証をそのまま通っている
    repairs: tuple[dict, ...] = ()


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

    @staticmethod
    def _correction(error: Exception) -> dict:
        """何がどう違反したのかを具体的に伝える。

        汎用的な「契約違反でした」だけでは同じ崩れ方を繰り返すことが分かったため、
        検証エラーの本文をそのまま返す（2026-08-19、candidate_valueキー欠落が
        2回とも同じ形で再発した実インシデント）。
        """
        return {
            "role": "user",
            "content": (
                f"前回の応答は次の理由で契約違反でした: {error}\n"
                "説明やコードフェンスを付けず、指定されたroot、必須キー、型を"
                "一字一句守ったJSON objectだけを返してください。"
                "値が無いキーも省略せず、必ずnullを入れて全キーを含めてください。"
            ),
        }

    def _request(
        self,
        *,
        model: str,
        messages: list[dict],
        validator: Callable[[dict], dict],
        stage: str,
    ) -> tuple[dict, int]:
        last_error: Exception | None = None
        last_payload: dict | None = None
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
                last_payload = parse_json_object(_content(response))
                return validator(last_payload), attempt
            except Exception as exc:
                last_error = exc
                if attempt < MAX_ATTEMPTS_PER_STAGE:
                    request_messages = request_messages + [self._correction(exc)]
        raise ManagedRecognitionError(
            f"{stage}は{MAX_ATTEMPTS_PER_STAGE}回とも失敗しました: "
            f"{type(last_error).__name__}",
            payload=last_payload,
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

    def analyze_image_json(
        self,
        *,
        image_data_url: str,
        prompt: str,
        validator: Callable[[dict], dict],
        stage: str,
        prompt_version: str,
    ) -> StageResult:
        """管理下Visionモデルへメモリ上の画像を送り、検証済みJSONだけを返す。"""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }
        ]
        document, attempts = self._request(
            model=self.settings.ocr_model,
            messages=messages,
            validator=validator,
            stage=stage,
        )
        return StageResult(
            document, attempts, self.settings.ocr_model, prompt_version
        )

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
        try:
            document, attempts = self._request(
                model=self.settings.contact_model,
                messages=messages,
                validator=lambda value: validate_contact_response(value, ocr_document),
                stage="contact構造化",
            )
            repairs: list[dict] = []
        except ManagedRecognitionError as exc:
            # 再試行を使い切っても、届いたJSONから救えるものは救う。1項目の崩れで
            # 残りの正しい項目まで捨てないため（救済分はReview Flagが付く）
            if exc.payload is None:
                raise
            document, repairs = repair_contact_document(exc.payload, ocr_document)
            attempts = MAX_ATTEMPTS_PER_STAGE
        return StageResult(
            document,
            attempts,
            self.settings.contact_model,
            "contact-v2",
            repairs=tuple(repairs),
        )

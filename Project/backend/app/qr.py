"""QRコードを data URI として返す。

JSON応答に埋めて `<img src=...>` で描かせる。画像を返す専用エンドポイントにすると、
そのURLに保持型資格情報（招待トークン）を載せることになり、`api.ts` の
「応答は必ずJSON」という前提も崩れる。
"""

import base64
import io

import qrcode


def qr_data_url(payload: str) -> str:
    image = qrcode.make(payload)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")

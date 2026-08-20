"""
fastapi_router.py — FastAPI 向け受信ビュー（django_view.py の FastAPI 版）

log_module を Django / FastAPI どちらでも流用できるよう、フレームワーク依存の
受信ビューだけを分離している。FastAPI 環境ではこのファイルだけを import すれば
よく（django_view.py は読み込まないので django 非依存）、逆も同様。

組み込み:
    from fastapi_router import router as log_router
    app.include_router(log_router, prefix="/api")   # → POST /api/log
"""

from fastapi import APIRouter, Request

try:
    from . import logger  # パッケージとして使う場合
except ImportError:
    import logger  # sys.path に直接追加した場合

router = APIRouter()


@router.post("/log")
async def receive_logs(request: Request) -> dict[str, int]:
    body = await request.json()
    records = body if isinstance(body, list) else [body]
    count = logger.write_batch(records)
    return {"received": count}

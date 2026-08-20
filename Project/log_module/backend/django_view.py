"""
django_view.py — Django 向け薄いラッパー

他フレームワークへの移植:
  FastAPI  → router.post("/log") でリクエストボディを受け取り logger.write_batch() を呼ぶだけ
  Flask    → @app.route("/log", methods=["POST"]) で同様に呼ぶだけ
"""

import json
from django.http import JsonResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

try:
    from . import logger                # パッケージとして使う場合
except ImportError:
    import logger                       # sys.path に直接追加した場合


@csrf_exempt
@require_http_methods(["POST"])
def receive_logs(request: HttpRequest) -> JsonResponse:
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid JSON"}, status=400)

    records = body if isinstance(body, list) else [body]
    count = logger.write_batch(records)
    return JsonResponse({"received": count})

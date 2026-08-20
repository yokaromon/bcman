# log_module — ボルトオン型ログモジュール

SQLite を使ったフロントエンド / バックエンド統合ログモジュール。

## ファイル構成

```
log_module/
├── backend/
│   ├── logger.py        # コア（Python 標準ライブラリのみ）
│   ├── django_view.py   # Django 薄ラッパー
│   └── urls.py          # Django URL パターン
├── frontend/
│   └── logger.ts        # コア（ブラウザ標準 API のみ）
├── logs.db              # 実行時に自動生成
└── README.md
```

## ログレコード仕様

| フィールド   | 型      | 必須 | 説明                                   |
|-------------|---------|------|----------------------------------------|
| id          | INTEGER | 自動 | 主キー                                 |
| timestamp   | TEXT    | ○   | ISO 8601（UTC）                        |
| source      | TEXT    | ○   | `"frontend"` or `"backend"`            |
| client_id   | TEXT    |     | ブラウザセッション UUID（frontend のみ）|
| seq_no      | INTEGER |     | セッション内連番（frontend のみ・欠損検出用） |
| from_node   | TEXT    |     | 処理の発信元（例: `"CartPage"`）        |
| to_node     | TEXT    |     | 処理の送信先（例: `"CartAPI"`）         |
| source_file | TEXT    |     | ソースファイル名                        |
| message     | TEXT    | ○   | ログメッセージ                          |

### From / To の使い方

```
from_node のみ    → ノード内処理（単独コンポーネントの動作ログ）
from_node + to_node → コンポーネント間通信（PlantUML シーケンス図の矢印に対応）
両方なし          → 単純なテキストログ
```

### seq_no による欠損検出

フロントエンドはセッションごとに seq_no を 1 から採番する。
送信に失敗すると `[SEND_FAILED] seq_no=N~M` というエラーレコードが記録される。
ビューアで seq_no の飛びを検出することで欠損範囲を特定できる。

---

## バックエンドへの組み込み手順

### 1. ファイルを配置

```
your_project/
├── log_module/        ← このディレクトリごとコピー
│   └── backend/
│       ├── __init__.py
│       ├── logger.py
│       ├── django_view.py
│       └── urls.py
└── config/
    ├── settings.py
    └── urls.py
```

### 2. settings.py に初期化コードを追加

```python
# settings.py
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ---- log_module ----
LOG_DB_PATH = BASE_DIR.parent / "log_module" / "logs.db"  # パスは自由に変更可

sys.path.insert(0, str(BASE_DIR.parent / "log_module" / "backend"))
import logger as app_logger
app_logger.init(LOG_DB_PATH)
```

### 3. urls.py にエンドポイントを追加

```python
# config/urls.py
from django.urls import path, include

urlpatterns = [
    ...
    path("api/", include("log_module.backend.urls")),
]
```

### 4. バックエンドでのログ記録

```python
import logger

# シンプル（source_file は自動取得）
logger.write("注文を受け付けました")

# From/To 指定（シーケンス図用）
logger.write(
    "カート内容を取得",
    from_node="OrderView",
    to_node="CartModel",
    source_file="orders/views.py",
)
```

---

## フロントエンドへの組み込み手順

### 1. ファイルを配置

```
your_project/frontend/src/
├── log_module/
│   └── logger.ts    ← このファイルをコピー
└── main.tsx
```

### 2. main.tsx で初期化

```typescript
import { init } from "./log_module/logger";

init({ endpoint: "/api/log" });  // エンドポイント URL はプロジェクトに合わせて変更
```

### 3. 各コンポーネントでのログ記録

```typescript
import { log } from "../log_module/logger";

// シンプル
log("商品詳細を表示", { source_file: "ProductDetailPage.tsx" });

// From/To 指定（シーケンス図用）
log("カートに追加", {
  source_file: "ProductDetailPage.tsx",
  from_node: "ProductDetailPage",
  to_node: "CartAPI",
});
```

---

## FastAPI / Flask への移植

`logger.py` はフレームワーク非依存なのでそのまま使える。
受信ビューだけ書き直す。

```python
# FastAPI の例
from fastapi import APIRouter, Request
import logger

router = APIRouter()

@router.post("/log")
async def receive_logs(request: Request):
    records = await request.json()
    if not isinstance(records, list):
        records = [records]
    count = logger.write_batch(records)
    return {"received": count}
```

---

## 将来の拡張（PlantUML シーケンス図ツール）

logs.db の `from_node` / `to_node` / `client_id` を使って
PlantUML のシーケンス図を自動生成するツールを別途作成予定。

```sql
-- シーケンス図用クエリ例（1セッションを抽出）
SELECT timestamp, from_node, to_node, message
FROM logs
WHERE client_id = 'xxxx-...'
  AND from_node IS NOT NULL
  AND to_node IS NOT NULL
ORDER BY timestamp;
```

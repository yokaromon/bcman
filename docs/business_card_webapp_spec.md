# 複数名刺画像認識 Webアプリケーション 実装仕様書

## 1. 概要

### 1.1 目的

スマートフォンやPCからアップロードされた写真に含まれる1枚または複数枚の名刺を自動検出し、各名刺画像を切り抜き・補正したうえでOCRを実行し、氏名・会社名・部署・役職・住所・電話番号・メールアドレス等の情報を構造化してデータベースへ登録するWebアプリケーションを構築する。

### 1.2 想定利用シーン

- スマートフォンで複数枚の名刺をまとめて撮影
- PCから既存の名刺写真をアップロード
- 写真内から名刺を自動検出
- 名刺ごとにOCRおよび情報抽出
- 認識結果をユーザーが確認・修正
- 確定した情報をデータベースへ登録
- 過去の名刺情報を検索・閲覧
- OCR/LLM改善後に過去画像を再解析

---

## 2. システム構成

```text
[PC / Smartphone]
        |
        | HTTPS
        v
[React Frontend]
        |
        | REST API
        v
[FastAPI Backend]
        |
        +-----------------------------+
        |                             |
        v                             v
[Image Processing]                [Database]
 YOLO / OpenCV                    PostgreSQL
        |
        v
[OCR Engine]
 PaddleOCR
        |
        v
[LLM Structuring]
 Local LLM / OpenAI-compatible API
```

---

## 3. 推奨技術スタック

### 3.1 フロントエンド

- React
- TypeScript
- Vite
- UIライブラリ
  - Chakra UI
  - Material UI
  - Tailwind CSS
- HTTPクライアント
  - fetch
  - Axios

### 3.2 バックエンド

- Python 3.11以上
- FastAPI
- Uvicorn
- Pydantic
- SQLAlchemy
- Alembic

### 3.3 画像処理

- OpenCV
- NumPy
- Pillow

### 3.4 名刺検出

初期PoCでは以下の2方式を切り替え可能とする。

#### 方式A：OpenCV

- Canny Edge Detection
- findContours
- approxPolyDP
- 四角形判定
- 面積・縦横比によるフィルタリング

#### 方式B：YOLO

推奨：

- YOLO Detection
- 将来的には YOLO Segmentation

用途：

- 写真中の名刺候補領域検出
- 複数名刺の個別検出
- 背景に紙や他の矩形物が存在する場合の誤検出低減

### 3.5 OCR

第一候補：

- PaddleOCR

代替候補：

- Google Cloud Vision
- Azure AI Vision
- AWS Textract
- Tesseract OCR

### 3.6 LLM

OCR結果を構造化JSONへ変換する。

候補：

- ローカルLLM
- OpenAI互換API
- OpenAI API
- Ollama
- LM Studio
- vLLM

### 3.7 データベース

- PostgreSQL

---

## 4. 全体処理フロー

```text
写真アップロード
      |
      v
画像保存
      |
      v
名刺検出
      |
      +--> 名刺1
      |
      +--> 名刺2
      |
      +--> 名刺3
      |
      v
各名刺について以下を実行
      |
      +--> 切り抜き
      |
      +--> 四隅検出
      |
      +--> Perspective補正
      |
      +--> 回転補正
      |
      +--> OCR
      |
      +--> LLM構造化
      |
      v
認識結果確認画面
      |
      v
ユーザー修正
      |
      v
DB確定登録
```

---

## 5. 機能要件

## 5.1 写真アップロード

### 必須機能

- JPEG
- PNG
- HEICは将来対応候補
- 1画像あたり最大20MB程度
- ドラッグ&ドロップ対応
- スマートフォンのカメラ撮影対応

### API

```http
POST /api/photos
Content-Type: multipart/form-data
```

### レスポンス例

```json
{
  "photo_id": "4a0ba605-8c58-4e25-a2c4-7b41f02ab123",
  "status": "uploaded"
}
```

---

## 5.2 名刺検出

### 入力

アップロード済み写真。

### 出力

写真内に存在すると判断された名刺候補。

```json
{
  "cards": [
    {
      "card_id": "uuid",
      "confidence": 0.97,
      "bounding_box": {
        "x": 120,
        "y": 80,
        "width": 620,
        "height": 350
      }
    }
  ]
}
```

### 要件

- 1枚以上の名刺を検出可能
- 縦向き・横向きに対応
- 斜め撮影に対応
- 複数名刺に対応
- 名刺ごとにconfidenceを保持
- 小さすぎる候補を除外
- 異常な縦横比を除外

---

## 5.3 名刺画像切り抜き

名刺候補ごとに画像を切り抜く。

### 保存対象

- 元写真
- 検出領域画像
- 補正済み名刺画像

例：

```text
storage/
  photos/
    {photo_id}/
      original.jpg
      cards/
        {card_id}/
          detected.jpg
          corrected.jpg
```

---

## 5.4 Perspective補正

斜めに撮影された名刺を正面画像へ補正する。

### 処理

1. グレースケール化
2. ノイズ除去
3. エッジ検出
4. 輪郭抽出
5. 四隅検出
6. 頂点並び替え
7. Perspective Transform
8. 出力サイズ正規化

OpenCV関数例：

```python
cv2.cvtColor()
cv2.GaussianBlur()
cv2.Canny()
cv2.findContours()
cv2.approxPolyDP()
cv2.getPerspectiveTransform()
cv2.warpPerspective()
```

---

## 5.5 回転補正

OCR前に文字方向を正規化する。

対応角度：

- 0°
- 90°
- 180°
- 270°

将来的には細かい傾き補正も実装する。

---

## 5.6 OCR

補正済み名刺画像をOCRへ渡す。

### OCR結果

文字列だけでなく位置情報も保存する。

```json
{
  "text_blocks": [
    {
      "text": "株式会社ABCシステム",
      "confidence": 0.98,
      "box": [[10,10],[300,10],[300,50],[10,50]]
    },
    {
      "text": "山田 太郎",
      "confidence": 0.96,
      "box": [[20,100],[200,100],[200,140],[20,140]]
    }
  ]
}
```

### 保存項目

- OCR生テキスト
- 各文字ブロック
- OCR confidence
- 文字位置
- OCRエンジン
- OCRエンジンバージョン

---

## 5.7 LLMによる構造化

OCR結果をLLMへ渡し、名刺情報としてJSON化する。

### 出力スキーマ

```json
{
  "company_name": "",
  "company_name_kana": "",
  "department": "",
  "position": "",
  "person_name": "",
  "person_name_kana": "",
  "postal_code": "",
  "address": "",
  "telephone": "",
  "fax": "",
  "mobile": "",
  "email": "",
  "website": "",
  "notes": ""
}
```

### LLM指示の基本方針

- OCR文字列に存在しない情報を推測しない
- 判断不能な項目はnullまたは空文字
- 電話番号とFAXを区別
- 携帯番号をmobileとして分類
- メールアドレスは原文を維持
- 会社名と部署名を混同しない
- 氏名と役職を分離
- JSON以外を返さない

### JSON SchemaまたはStructured Output対応を推奨

---

## 5.8 認識結果確認画面

自動認識結果を即時確定登録しない。

必ずユーザーが確認できる画面を用意する。

### 画面構成

```text
+----------------------------------------------+
| 名刺画像                                    |
|                                              |
| [補正済み名刺画像]                          |
|                                              |
+----------------------+-----------------------+
| 会社名               | 株式会社ABC           |
| 氏名                 | 山田 太郎             |
| 部署                 | 開発部                |
| 役職                 | 課長                  |
| TEL                  | 092-123-4567          |
| Mobile               | 090-1234-5678         |
| Email                | xxx@example.jp        |
| Address              | 福岡県...             |
+----------------------+-----------------------+
| [修正] [確定登録] [再解析] [削除]           |
+----------------------------------------------+
```

### 複数名刺の場合

画面左側に名刺一覧を表示する。

```text
写真
 ├ Card 1
 ├ Card 2
 ├ Card 3
 └ Card 4
```

---

## 6. データベース設計

## 6.1 photos

元写真管理。

| カラム | 型 | 説明 |
|---|---|---|
| id | UUID | PK |
| original_filename | VARCHAR | 元ファイル名 |
| storage_path | VARCHAR | 保存場所 |
| width | INTEGER | 画像幅 |
| height | INTEGER | 画像高さ |
| created_at | TIMESTAMP | 登録日時 |
| status | VARCHAR | 処理状態 |

---

## 6.2 business_cards

名刺1枚につき1レコード。

| カラム | 型 | 説明 |
|---|---|---|
| id | UUID | PK |
| photo_id | UUID | photos FK |
| detected_image_path | VARCHAR | 検出画像 |
| corrected_image_path | VARCHAR | 補正画像 |
| detection_confidence | FLOAT | 検出confidence |
| x | INTEGER | 検出位置 |
| y | INTEGER | 検出位置 |
| width | INTEGER | 検出幅 |
| height | INTEGER | 検出高さ |
| status | VARCHAR | 状態 |
| created_at | TIMESTAMP | 作成日時 |

---

## 6.3 card_ocr_results

OCR生データ。

| カラム | 型 | 説明 |
|---|---|---|
| id | UUID | PK |
| card_id | UUID | business_cards FK |
| engine | VARCHAR | OCRエンジン |
| engine_version | VARCHAR | バージョン |
| raw_text | TEXT | OCR全文 |
| raw_json | JSONB | OCR詳細結果 |
| created_at | TIMESTAMP | OCR日時 |

---

## 6.4 contacts

確定名刺情報。

| カラム | 型 | 説明 |
|---|---|---|
| id | UUID | PK |
| card_id | UUID | business_cards FK |
| company_name | VARCHAR | 会社名 |
| company_name_kana | VARCHAR | 会社名カナ |
| department | VARCHAR | 部署 |
| position | VARCHAR | 役職 |
| person_name | VARCHAR | 氏名 |
| person_name_kana | VARCHAR | 氏名カナ |
| postal_code | VARCHAR | 郵便番号 |
| address | TEXT | 住所 |
| telephone | VARCHAR | 電話番号 |
| fax | VARCHAR | FAX |
| mobile | VARCHAR | 携帯 |
| email | VARCHAR | メール |
| website | VARCHAR | URL |
| notes | TEXT | 備考 |
| confirmed | BOOLEAN | 確定済み |
| created_at | TIMESTAMP | 作成日時 |
| updated_at | TIMESTAMP | 更新日時 |

---

## 6.5 processing_history

再処理履歴を保存する。

| カラム | 型 | 説明 |
|---|---|---|
| id | UUID | PK |
| card_id | UUID | business_cards FK |
| process_type | VARCHAR | detection / ocr / llm |
| engine | VARCHAR | 使用エンジン |
| version | VARCHAR | バージョン |
| input_json | JSONB | 入力 |
| output_json | JSONB | 出力 |
| created_at | TIMESTAMP | 処理日時 |

---

## 7. API仕様

## 7.1 写真アップロード

```http
POST /api/photos
```

---

## 7.2 名刺検出開始

```http
POST /api/photos/{photo_id}/detect
```

レスポンス：

```json
{
  "photo_id": "...",
  "detected_count": 4
}
```

---

## 7.3 名刺一覧

```http
GET /api/photos/{photo_id}/cards
```

---

## 7.4 名刺単体取得

```http
GET /api/cards/{card_id}
```

---

## 7.5 OCR実行

```http
POST /api/cards/{card_id}/ocr
```

---

## 7.6 LLM構造化

```http
POST /api/cards/{card_id}/structure
```

---

## 7.7 一括処理

アップロード後の検出・補正・OCR・LLM処理を一括実行する。

```http
POST /api/photos/{photo_id}/process
```

---

## 7.8 認識結果更新

```http
PUT /api/cards/{card_id}/contact
```

---

## 7.9 確定登録

```http
POST /api/cards/{card_id}/confirm
```

---

## 7.10 再解析

```http
POST /api/cards/{card_id}/reprocess
```

パラメータ例：

```json
{
  "ocr": true,
  "llm": true
}
```

---

## 8. 処理ステータス

写真：

```text
uploaded
detecting
detected
processing
completed
failed
```

名刺：

```text
detected
correcting
corrected
ocr_processing
ocr_completed
llm_processing
review_required
confirmed
failed
```

---

## 9. 非同期処理

画像解析は処理時間が長くなる可能性があるため、本番環境では非同期化を推奨する。

候補：

- Celery + Redis
- RQ + Redis
- FastAPI BackgroundTasks（PoC向け）

推奨構成：

```text
React
   |
FastAPI
   |
   +--> PostgreSQL
   |
   +--> Redis
          |
          v
       Worker
       ├ YOLO
       ├ OpenCV
       ├ OCR
       └ LLM
```

---

## 10. 複数名刺対応時の考慮事項

### 10.1 名刺同士が離れている

最も認識しやすい。

### 10.2 名刺同士が接触している

YOLO Detectionの導入を推奨。

### 10.3 名刺同士が一部重なっている

YOLO Segmentationを検討する。

### 10.4 完全に隠れている文字

画像に写っていない情報は復元対象外とする。

### 10.5 重複名刺

同じ人物の名刺が複数回登録される可能性を考慮する。

候補キー：

- email
- mobile
- company_name + person_name
- OCR全文類似度

ただし自動統合はせず、重複候補としてユーザーへ提示する。

---

## 11. 画像品質チェック

OCR前に画像品質を判定する。

チェック候補：

- 解像度不足
- ピンぼけ
- 白飛び
- 黒つぶれ
- 強い反射
- 名刺の一部欠損

品質不足時：

```json
{
  "quality": "warning",
  "reason": [
    "blur_detected",
    "low_resolution"
  ]
}
```

画面に再撮影を促す。

---

## 12. セキュリティ

名刺には個人情報が含まれるため、以下を必須とする。

### 通信

- HTTPS

### 認証

- ログイン必須
- JWTまたはSession認証

### 権限

将来的に以下を検討。

- 管理者
- 一般ユーザー
- 閲覧専用

### ファイル

- アップロード拡張子検査
- MIME Type検査
- 最大ファイルサイズ制限
- ランダムUUIDでファイル保存
- Web公開ディレクトリへ直接保存しない

### データ

- DBバックアップ
- 削除機能
- 操作ログ
- 必要に応じて保存画像暗号化

---

## 13. 検索機能

以下の検索を提供する。

- 氏名
- 会社名
- 部署
- 役職
- 電話番号
- メール
- 住所

将来的には全文検索を追加する。

候補：

- PostgreSQL Full Text Search
- pg_trgm

---

## 14. フロントエンド画面

### 14.1 ログイン画面

### 14.2 名刺写真アップロード画面

- 写真選択
- ドラッグ&ドロップ
- カメラ撮影
- プレビュー
- 処理開始

### 14.3 写真解析画面

元写真上に名刺検出矩形を表示。

```text
+-----------------------------------+
|                                   |
|  [Card 1]          [Card 2]       |
|                                   |
|          [Card 3]                 |
|                                   |
+-----------------------------------+
```

### 14.4 名刺確認画面

- 補正画像
- OCR結果
- 構造化結果
- 編集フォーム
- 確定ボタン
- 再解析ボタン

### 14.5 名刺一覧画面

- 氏名
- 会社
- 役職
- 電話
- メール
- 登録日

### 14.6 名刺詳細画面

- 名刺画像
- 登録情報
- OCR生データ
- 処理履歴

---

## 15. バックエンド構成例

```text
backend/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── photos.py
│   │   ├── cards.py
│   │   └── contacts.py
│   ├── models/
│   │   ├── photo.py
│   │   ├── business_card.py
│   │   ├── contact.py
│   │   └── ocr_result.py
│   ├── schemas/
│   ├── services/
│   │   ├── detector.py
│   │   ├── image_processor.py
│   │   ├── ocr_service.py
│   │   └── llm_service.py
│   ├── repositories/
│   ├── workers/
│   └── core/
├── migrations/
├── tests/
├── requirements.txt
└── Dockerfile
```

---

## 16. フロントエンド構成例

```text
frontend/
├── src/
│   ├── pages/
│   │   ├── UploadPage.tsx
│   │   ├── PhotoReviewPage.tsx
│   │   ├── CardReviewPage.tsx
│   │   ├── ContactListPage.tsx
│   │   └── ContactDetailPage.tsx
│   ├── components/
│   │   ├── ImageUploader.tsx
│   │   ├── CardBoundingBox.tsx
│   │   ├── CardImage.tsx
│   │   └── ContactForm.tsx
│   ├── api/
│   ├── hooks/
│   ├── types/
│   └── App.tsx
├── package.json
└── Dockerfile
```

---

## 17. Docker構成例

```text
docker-compose.yml

services:
  frontend
  backend
  postgres
  redis
  worker
```

GPUを使用する場合はYOLO/OCR/LLMワーカーをGPU対応コンテナとして分離することを推奨する。

---

## 18. エラー処理

代表的エラー：

### NO_CARD_DETECTED

名刺が検出されなかった。

### MULTIPLE_OBJECT_AMBIGUOUS

名刺候補の判定が不確実。

### IMAGE_QUALITY_LOW

画像品質不足。

### OCR_FAILED

OCR処理失敗。

### LLM_FAILED

LLM構造化失敗。

### INVALID_LLM_OUTPUT

LLMのJSON形式が不正。

### STORAGE_ERROR

画像保存失敗。

---

## 19. ログ

最低限以下を記録する。

- photo_id
- card_id
- user_id
- 処理開始日時
- 処理終了日時
- 処理時間
- 使用モデル
- confidence
- エラー内容

---

## 20. テスト要件

### 20.1 名刺枚数

- 1枚
- 2枚
- 5枚
- 10枚

### 20.2 方向

- 横
- 縦
- 90度回転
- 180度回転

### 20.3 撮影角度

- 真上
- 軽度斜め
- 強い斜め

### 20.4 背景

- 白机
- 黒机
- 木目
- 書類あり
- PCキーボードあり

### 20.5 名刺

- 白背景
- 黒背景
- カラー
- 写真入り
- QRコード入り
- 日本語
- 英語
- 日本語＋英語

---

## 21. PoC実装フェーズ

### Phase 1

目的：

「複数名刺写真から名刺情報をDB登録できる」ことを確認する。

実装：

- Reactアップロード
- FastAPI
- OpenCV名刺検出
- 複数枚切り抜き
- Perspective補正
- PaddleOCR
- LLM JSON化
- 確認画面
- PostgreSQL登録

---

## 22. Phase 2

認識精度向上。

- YOLO Detection導入
- 学習用名刺画像収集
- 独自名刺検出モデル
- OCR前処理改善
- 画像品質判定
- 重複チェック
- 再解析機能

---

## 23. Phase 3

本番運用対応。

- ユーザー認証
- 権限管理
- 操作ログ
- 非同期Worker
- GPU対応
- バックアップ
- インポート・エクスポート
- CSV出力
- vCard出力
- API連携

---

## 24. Phase 4

高度化。

- YOLO Segmentation
- 重なった名刺への対応強化
- QRコード解析
- ロゴ認識
- 会社情報補完
- 名寄せ
- CRM連携
- 自動タグ付け
- ベクトル検索

---

## 25. 初期PoCで実装しないもの

初期開発を複雑にしないため以下は後回しとする。

- 名刺の自動名寄せ
- CRM連携
- QRコード情報との自動マージ
- 多言語完全対応
- YOLO独自学習
- Segmentation
- OCRモデル独自学習
- 完全自動確定登録

---

## 26. PoCの成功基準

以下をPoC完了条件とする。

1. 1枚の写真から複数名刺を検出できる
2. 各名刺を独立した画像として取得できる
3. 斜め撮影された名刺を補正できる
4. 日本語名刺をOCRできる
5. OCR結果から氏名・会社・電話・メールを構造化できる
6. ユーザーが認識結果を修正できる
7. PostgreSQLへ登録できる
8. 元画像・補正画像・OCR生データを保持できる
9. 過去画像を再解析できる

---

## 27. 推奨実装順序

```text
1. React画像アップロード
        ↓
2. FastAPI画像受信
        ↓
3. OpenCVで単一名刺検出
        ↓
4. Perspective補正
        ↓
5. 複数名刺対応
        ↓
6. PaddleOCR
        ↓
7. LLM構造化
        ↓
8. PostgreSQL
        ↓
9. 確認・修正UI
        ↓
10. YOLO導入
        ↓
11. 非同期Worker
```

初期段階ではYOLOから始めず、OpenCVで画像処理パイプライン全体を完成させる。

その後、名刺検出精度が不足した場合にYOLOへ置き換える設計とする。

---

## 28. 設計上の重要方針

### 原本を保存する

元写真は削除しない限り保持する。

### 中間データを保存する

- 名刺切り抜き画像
- 補正画像
- OCR生データ
- OCR位置情報
- LLM出力

を保持する。

### AI結果を即確定しない

ユーザー確認後に確定する。

### 処理エンジンを交換可能にする

以下をインターフェース化する。

```python
CardDetector
ImageCorrector
OCREngine
CardStructurer
```

これにより、

```text
OpenCV → YOLO

PaddleOCR → Cloud Vision

Local LLM → OpenAI API
```

などを変更しやすくする。

---

## 29. 将来拡張を考慮したインターフェース例

```python
class CardDetector:
    def detect(self, image):
        ...

class OCREngine:
    def recognize(self, image):
        ...

class CardStructurer:
    def structure(self, ocr_result):
        ...
```

アプリケーション本体は個々のAIエンジンに依存しない設計とする。

---

## 30. 推奨最終構成

```text
                     Browser
                       |
                       v
                  React / Vite
                       |
                    HTTPS
                       |
                       v
                    FastAPI
             +---------+----------+
             |                    |
             v                    v
         PostgreSQL             Redis
                                  |
                                  v
                               Worker
                     +------------+------------+
                     |            |            |
                     v            v            v
                   YOLO        OpenCV       PaddleOCR
                                               |
                                               v
                                              LLM
                                               |
                                               v
                                         Structured JSON
```

この構成であれば、PoCとして小さく開始し、将来的にGPU推論、独自YOLOモデル、ローカルLLM、複数ユーザー運用へ段階的に拡張できる。

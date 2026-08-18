# BCMan

Dockerを使わない名刺管理PoCです。`/bcman/` 配下で公開するReact/Vite UIと、`/bcman/api/` APIを備えています。

## 起動

1. `cd backend; poetry install; poetry run uvicorn app.main:app --reload --port 8000`
2. `cd frontend; npm install; npm run dev`

フロントエンドは `http://localhost:5173/bcman/`、APIは `http://localhost:8000/bcman/api/` です。`backend/.env.example` を `.env` にコピーしてOCR APIを設定してください。

## 初期セットアップ（Organization・管理者アカウント）

Organizationと初期管理者アカウントの作成にUIはなく、`backend` ディレクトリでCLIを実行します（詳細はリポジトリルートの `docs/identity/CONTEXT.md`、`docs/identity/adr/0001-device-trust-and-totp.md`）。

```
poetry run python -m app.cli create-org --name "会社名" --group "一般" --admin-username admin --admin-name "管理者 太郎"
```

パスワードはその場で入力を求められます。実行するとTOTP（認証アプリ）登録用のURI/QRが一度だけ表示されるので、その場で管理者本人の認証アプリに登録してください。以降のユーザ追加はログイン後の管理画面から行えます。

ログインは初回、未登録の端末・オフィス外のネットワークからだとTOTPコードの入力を求められます。オフィスの固定IPからの許可リストは `Project/deploy/nginx-bcman.conf` の `geo $bcman_trusted_network` で設定します（ローカル開発では未設定のままで構いません）。

## Recognition Pipeline V2（試験運用中・既定OFF）

`pickup/` で検証した「切り抜き→ローカル向き判定→ykrによる構造化OCR」を `backend/app/recognition_v2/`
に移植したものです。ADR 0019 のとおり **既定OFF** で、有効にしても適用されるのは管理者が
写真ごとに明示的にopt-inした新規写真だけです。既存の名刺は再処理されず、V1がロールバック経路
として並行稼働し続けます。

### ⚠️ Python 3.11 が必須（本番サーバも要変更）

V2は **Python 3.11** でしか動きません。3.12以降は venv に `setuptools` が同梱されなくなり、
paddle が import 時に落ちます。加えて pickup での受け入れ評価（向き256/256カード）は 3.11 で
測っており、別minorは未評価の構成になります。`pyproject.toml` で `>=3.11,<3.12` に固定し、
起動時にも `verify_runtime_versions()` が Python の minor まで照合して不一致なら止めます。

**本番(CT113)の Python が 3.11 でない場合、V2を有効化する前にサーバ側の入れ替えが必要です。**
V1はこの制約を受けないため、3.11化が済むまではフラグをOFFのまま運用してください。

有効化の手順（`backend` ディレクトリで実行）:

```
poetry env use /path/to/python3.11                               # 3.11以外のvenvだと起動時に落ちる
poetry install                                                   # paddlepaddle等のV2依存を導入
poetry run python -m app.recognition_v2.provision_models --verify-only   # 同梱モデルのSHA-256検証
```

そのうえで `.env` に `RECOGNITION_PIPELINE_V2_ENABLED=true` を設定して再起動すると、管理者の
撮影画面に「新しい読み取り(V2)を試す」チェックボックスが出ます。チェックを入れて撮った写真だけが
V2で処理されます。フラグがOFFの間、または管理者以外の要求は、サーバー側で無条件にV1へ落とされます。

向きモデル（`backend/models_v2/PP-LCNet_x1_0_doc_ori_infer/`、6.6MB）はリポジトリに同梱してあります。
PaddleOCR公式のApache-2.0事前学習済み分類器で、この案件の名刺は含みません。取得元CDNへ到達できない
環境でもデプロイできるよう、Recognition Releaseの一部として固定世代を追跡しています。別世代へ
差し替えるときだけ `provision_models.py` を `--verify-only` なしで実行します（実行時ダウンロードは
一切行いません）。

PaddleXは日本語フォントを要求するため、Linuxでは `fonts-noto-cjk` 等を導入するか、
`BCMAN_V2_FONT_PATH` へ既存TTF/TTCの絶対パスを設定してください。

モデルが無い・SHA-256が合わない状態でV2を有効にした写真は、途中まで処理せずその写真ごと
`failed` になります（中途半端なカードは残しません）。

V2で読み取った項目は必ず未確定の候補として表示され、根拠のない値・形式が怪しい値・読めなかった
項目にはReview Flagが付きます。登録は従来どおりユーザーの明示操作でのみ確定します。

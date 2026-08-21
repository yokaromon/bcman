# BCMan

Dockerを使わない名刺管理PoCです。`/bcman/` 配下で公開するReact/Vite UIと、`/bcman/api/` APIを備えています。

## 起動

1. `cd backend; poetry install; poetry run uvicorn app.main:app --reload --port 8000`
2. `cd frontend; npm install; npm run dev`

フロントエンドは `http://localhost:5173/bcman/`、APIは `http://localhost:8000/bcman/api/` です。`backend/.env.example` を `.env` にコピーしてOCR APIを設定してください。

公開ホスト名はフロントエンドへ埋め込まず、常に現在開いているoriginを使います。`/bcman/`
以外の配下へ移す場合は、ビルド時に `VITE_APP_BASE_PATH=/new-path/` を設定し、バックエンドの
`ROOT_PATH`、`PUBLIC_BASE_URL`、リバースプロキシのlocationも同じパスへ合わせます。

### 保存しない高解像度矩形検出

ログイン済みCookieを付けて `POST /bcman/api/card-detections` へJPEG/PNGの生バイトを送ると、
V2パイプラインと同じ検出器が元画像座標の四隅を返します。画像、切り抜き、Photo/Card行は
作成しません。上限は圧縮後`MAX_UPLOAD_BYTES`、展開後`MAX_DETECTION_PIXELS`です。

```http
POST /bcman/api/card-detections
Content-Type: image/jpeg
Cookie: bcman_session=...

<JPEG bytes>
```

## ログイン

ログインには**会社コード・ID・パスワード**の3つが必要です。会社コードは会社ごとの短い文字列で、各社が `admin` のようなIDを使えるようにするためのものです（詳細は `docs/identity/CONTEXT.md` の Company Code）。

初回、未登録の端末・オフィス外のネットワークからだと、続けて認証アプリの6桁コードを求められます。オフィスの固定IPからの許可リストは `Project/deploy/nginx-bcman.conf` の `geo $bcman_trusted_network` で設定します（現在は無効化してあり、常にコードを要求します）。

## アカウントの払い出し（招待方式）

**パスワードを誰かが決めて本人へ伝える経路はありません。** 利用者の追加も、パスワード忘れ・認証アプリ紛失からの復旧も、すべて一回限り・24時間有効の招待リンクで行います（`docs/identity/adr/0002-provider-operated-provisioning-by-invitation.md`）。

- **会社を追加する**: 運営者（`bcman`）でログインし「会社」タブから。会社名・会社コード・初期管理者を入力すると招待QRが出るので、新しい会社の管理者に読んでもらいます
- **自社に利用者を追加する**: 管理画面の「利用者を追加」。同じく招待QRが出ます
- **パスワードを忘れた／認証アプリを失くした**: 管理画面で対象の利用者を開き「招待し直す」。本人が自分で設定し直します

招待された人はQRを読むと設定画面が開き、会社コードとIDの提示を受け、認証アプリを登録し、パスワードを決めて完了します。**認証アプリのコードを1回入力してもらうまで完了しません**（登録できていないことに次回ログインで初めて気づく、という事態を防ぐため）。

招待リンクは**それだけでそのアカウントを受け取れてしまう**ので、対面など確実な経路で渡してください。特に復旧の再招待は、既にデータを持つアカウントが対象です。

`PUBLIC_BASE_URL` に**外から見た公開URL**を設定しておく必要があります。招待QRに埋め込む絶対URLの組み立てに使い、社外の人がスマホから到達する先になります。

### 最初の運営者を作る（初回のみ）

UIから会社を作るには運営者が要るので、最初だけ `backend` ディレクトリでCLIを使います。

```
poetry run python -m app.cli create-org --name "会社名" --code ykr --group "一般" \
    --admin-username admin --admin-name "管理者 太郎" --provider-operator
```

パスワードは聞かれません。招待リンクとASCII QRが表示されるので、それを開いて設定してください。既存アカウントに後から運営者権限を与えるときは `grant-provider --company-code ykr --username bcman` を使います（ユーザー名を見た自動付与はしません。改名で別アカウントへ権限が滑るため）。

UIへ一切入れなくなったときの最後の手段として `reinvite --company-code ... --username ...` もあります。

## Recognition Pipeline V2（試験運用中・既定OFF）

`pickup/` で検証した「切り抜き→ローカル向き判定→ykrによる構造化OCR」を `backend/app/recognition_v2/`
に移植したものです。**既定OFF**で、`.env`の`RECOGNITION_PIPELINE_V2_ENABLED`だけがV1/V2を分ける
唯一の分岐点です（2026-08-18、写真ごとのopt-inチェックボックスは撤去し一本化）。フラグONの間は
**新規写真すべて**がV2で処理されます。既存の名刺は再処理されず、フラグをOFFへ戻せばV1へ即座に
ロールバックできます（V1のコードパス自体は無変更のまま残っている）。

### ⚠️ 本番で直したら pickup/ へも戻すこと

`detector.py` / `orientation.py` / `alignment.py` / `text_regions.py` / `recognition_contract.py` /
prompts / schemas は `pickup/` からの移植で、**両側が同一内容であることを前提にしている**。
本番incident対応でこちら側だけ直して pickup へ戻し忘れると、次に pickup で評価したときの
数値と本番の実際の挙動がずれる（2026-08-18に実際に発生）。

```
python scripts/check_v2_parity.py   # 共有ファイルの一致を確認
```

`pickup/` か `recognition_v2/` を触るcommitでは pre-commit フックが自動でこれを実行する
（初回だけ `git config core.hooksPath scripts/hooks` を実行して有効化しておく）。
`model_runtime.py` と `ykr_client.py` は本番固有の配線があり意図的に差分があってよい
（フックは警告だけでブロックしない）。

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

そのうえで `.env` に `RECOGNITION_PIPELINE_V2_ENABLED=true` を設定して再起動すると、**以後の
新規写真は全員分・全件がV2で処理されます**。撮影画面には現在V2で処理される旨の案内だけが出ます
（選べるトグルはありません）。元に戻すときは `.env` を `false` に戻して再起動するだけです。

モデル一式（`backend/models_v2/`、向き分類器6.6MB＋文字検出・認識3種193MB、計約200MB）は
リポジトリに同梱してあります。すべてPaddleOCR公式のApache-2.0事前学習済みモデルで、この案件の
名刺は含みません。取得元CDNへ到達できない環境でもデプロイできるよう、Recognition Releaseの
一部として固定世代を追跡しています。別世代へ差し替えるときだけ `provision_models.py` を
`--verify-only` なしで実行します（実行時ダウンロードは一切行いません）。

文字検出・認識モデルは、Contact構造化の根拠証拠（alignment）と、向き分類器がuncertainのときの
可読性フォールバックに使います（2026-08-18、alignment無しで本番投入した結果pickupの検証結果より
精度が低くなったため追加移植。詳細は`app/recognition_v2/pipeline.py`のコメント参照）。

**Windowsで作業する場合の注意**: `.gitattributes` でモデル一式を `-text` 指定しています。
指定前は `core.autocrlf=true` の環境で `git checkout` するたびに `config.json`/`inference.yml`
がCRLF化され、SHA-256検証が壊れる事故がありました（Linux側は autocrlf 無効のため無事）。
モデルファイルの差分が出た場合は、まず `.gitattributes` が効いているか
(`git check-attr text -- backend/models_v2/.../config.json` で `text: unset` と出るか)を疑うこと。

PaddleXは日本語フォントを要求するため、Linuxでは `fonts-noto-cjk` 等を導入するか、
`BCMAN_V2_FONT_PATH` へ既存TTF/TTCの絶対パスを設定してください。

モデルが無い・SHA-256が合わない状態でV2を有効にした写真は、途中まで処理せずその写真ごと
`failed` になります（中途半端なカードは残しません）。

V2で読み取った項目は必ず未確定の候補として表示され、根拠のない値・形式が怪しい値・読めなかった
項目にはReview Flagが付きます。登録は従来どおりユーザーの明示操作でのみ確定します。

### AIの応答が壊れたときの振る舞い（0点にしない）

ykrが返すJSONが契約を満たさなくても、カード丸ごと失敗にはしません。段階的に減点します
（2026-08-19、`fields.address`の`candidate_value`キーが1つ欠けただけで、正しく取れていた
残り13項目まで捨てて0点になっていた実インシデント）。

1. 再試行では検証エラーの本文をそのままモデルへ返す（汎用文だけだと同じ崩れ方を繰り返す）
2. **Response Repair**: 再試行を使い切ったら、届いたJSONを契約の形へ寄せる。欠落キーの補完、
   型の吸収、余分キーの削除、`fields`を無視してroot直下に置かれた項目の拾い上げ
3. 意味的な矛盾（absentなのに値がある等）は、その項目だけを直して他項目は生かす。存在しない
   根拠行の参照も、その行だけ外す
4. **Format Baseline**: 構造化が全滅しても、OCR本文から形式で断定できる項目だけを拾う
   （メール・URL・郵便番号・電話・FAX・携帯）。氏名や会社名は推測しない

救済・baseline由来の項目には必ずReview Flagが付きます。**この緩和が安全なのはV2が自動確定を
一切しないから**で、将来この前提を変える場合は救済ロジックも見直しが必要です。用語定義は
`CONTEXT.md`の Response Repair / Format Baseline を参照。どちらも評価上はContact Structuringの
**失敗**として数えます（救済で精度指標が嵩上げされないようにするため）。

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

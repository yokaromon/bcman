# BCMan

Dockerを使わない名刺管理PoCです。`/bcman/` 配下で公開するReact/Vite UIと、`/bcman/api/` APIを備えています。

## 起動

1. `cd backend; poetry install; poetry run uvicorn app.main:app --reload --port 8000`
2. `cd frontend; npm install; npm run dev`

フロントエンドは `http://localhost:5173/bcman/`、APIは `http://localhost:8000/bcman/api/` です。`backend/.env.example` を `.env` にコピーしてOCR APIを設定してください。

初回起動時は「システム管理者」「サンプル組織」「一般グループ」が作成されます。認証実装前は `X-User-Id` ヘッダーで利用者を切り替えられ、未指定時は管理者です。

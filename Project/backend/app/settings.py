from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "sqlite:///./bcman.db"
    storage_dir: Path = Path("storage")
    root_path: str = "/bcman"
    ai_base_url: str = "https://app.ykr.ltd/ai/v1"
    ai_api_key: str = ""
    ai_model: str = ""
    max_upload_bytes: int = 20 * 1024 * 1024
    # Recognition Pipeline V2 のマスタースイッチ（docs/adr/0019）。既定OFF。
    # ONにしても適用されるのは管理者が明示的にopt-inした新規写真だけで、既存カードは再処理しない。
    recognition_pipeline_v2_enabled: bool = False
    cookie_secure: bool = True  # ローカルでHTTPS無しに動かす時だけ .env で false にする
    # 招待リンクの絶対URLを組み立てるための、外から見た公開URL。
    # リクエストから導出してはいけない。nginx が /bcman/ を剥がして転送するので
    # request.base_url は内部の http://127.0.0.1:8000/... になり、Host は攻撃者が操作できる。
    # 設定ミスなら招待リンクが404になるだけだが、Host 由来だと招待先が攻撃者のドメインになる。
    public_base_url: str = "https://app.ykr.ltd/bcman"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()

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
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()

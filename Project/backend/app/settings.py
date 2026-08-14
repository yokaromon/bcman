from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "sqlite:///./bcman.db"
    storage_dir: Path = Path("storage")
    root_path: str = "/bcman"
    ai_base_url: str = "https://app.ykr.ltd/ai/v1"
    ai_api_key: str = ""
    ai_model: str = ""
    tesseract_cmd: str = "tesseract"
    # 10枚の実写検証(正解1件のみ低confidence=0.26で誤判定、他は0.73以上で正解)から暫定的に置いた値。
    # 本番投入後はProcessingHistoryのconfidence分布を見て調整する。
    orientation_osd_confidence_min: float = 0.5
    max_upload_bytes: int = 20 * 1024 * 1024
    cookie_secure: bool = True  # ローカルでHTTPS無しに動かす時だけ .env で false にする
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()

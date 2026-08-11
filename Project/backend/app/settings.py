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
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()

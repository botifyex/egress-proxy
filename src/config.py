import os
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(os.getenv("BASE_DIR", Path(__file__).resolve().parent.parent))
PATH_ENV = BASE_DIR / ".env"


class Server(BaseModel):
    host: str
    port: int


class Proxy(BaseModel):
    key: str
    header: str = "X-Key"


class Settings(BaseSettings):
    server: Server
    proxy: Proxy

    model_config = SettingsConfigDict(
        env_file=PATH_ENV,
        env_nested_delimiter="__",
    )


settings = Settings()

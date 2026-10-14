from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def configuration(prefix: str) -> SettingsConfigDict:
    return SettingsConfigDict(env_prefix=prefix, env_file=".env", extra="ignore")


class Server(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8000

    model_config = configuration("SERVER__")


class Proxy(BaseSettings):
    key: SecretStr = Field(min_length=1)
    timeout: float = 30.0
    connect: float = 10.0
    upstreams: list[str] = []
    upstreams_file: Path | None = None
    cooldown: float = Field(default=30.0, ge=0)
    attempts: int = Field(default=3, ge=1)

    model_config = configuration("PROXY__")

    @field_validator("upstreams_file", mode="before")
    @classmethod
    def unset(cls, value: object) -> object:
        return None if value == "" else value

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def configuration(prefix: str) -> SettingsConfigDict:
    return SettingsConfigDict(env_prefix=prefix, env_file=".env", extra="ignore")


class Server(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8000

    model_config = configuration("SERVER__")


class Proxy(BaseSettings):
    key: SecretStr
    timeout: float = 30.0
    connect: float = 10.0

    model_config = configuration("PROXY__")

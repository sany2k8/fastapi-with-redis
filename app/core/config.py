"""Environment-based configuration. No bare os.environ anywhere else in the app."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    redis_host: str = "localhost"
    redis_port: int = 6383
    redis_db: int = 0
    redis_password: str | None = None

    app_env: str = "dev"

    # Stamped into the image at build time (Dockerfile ARG/ENV APP_VERSION) so a
    # running pod can say which build it is. CI passes the git short SHA.
    app_version: str = "dev"

    # Every key this app writes starts with this prefix, which is what makes
    # `POST /demo/reset` able to clean up without touching anything else in the DB.
    key_prefix: str = "rdp"

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()

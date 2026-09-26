from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str = ""
    telegram_allowed_chat_ids: str = ""
    korail_search_interval_seconds: float = 1.0
    korail_search_jitter_min_seconds: float = 0.0
    korail_search_jitter_max_seconds: float = 0.0
    korail_max_search_minutes: int = 10
    korail_netfunnel_enabled: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def allowed_chat_ids(self) -> set[int]:
        if not self.telegram_allowed_chat_ids.strip():
            return set()
        return {int(value.strip()) for value in self.telegram_allowed_chat_ids.split(",") if value.strip()}

    def search_jitter_range(self) -> tuple[float, float]:
        minimum = max(0.0, self.korail_search_jitter_min_seconds)
        maximum = max(0.0, self.korail_search_jitter_max_seconds)
        if minimum > maximum:
            raise ValueError("KORAIL_SEARCH_JITTER_MIN_SECONDS must be <= KORAIL_SEARCH_JITTER_MAX_SECONDS")
        return minimum, maximum


settings = Settings()

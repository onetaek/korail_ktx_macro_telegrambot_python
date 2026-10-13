from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str = ""
    telegram_allowed_chat_ids: str = ""
    korail_id: str = ""
    korail_password: str = ""
    korail_search_interval_seconds: float = 1.0
    korail_search_jitter_min_seconds: float = 0.0
    korail_search_jitter_max_seconds: float = 0.0
    korail_max_search_minutes: int = 10
    korail_auto_payment_enabled: bool = False
    korail_card_number: str = ""
    korail_card_password: str = ""
    korail_card_expire: str = ""
    korail_card_birthday: str = ""
    korail_card_installment: str = "0"
    korail_card_type: str = "J"

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

    def card_payment(self):
        if not self.korail_auto_payment_enabled:
            return None
        values = {
            "card_number": self.korail_card_number.strip(),
            "card_password": self.korail_card_password.strip(),
            "card_expire": self.korail_card_expire.strip(),
            "birthday": self.korail_card_birthday.strip(),
            "installment": self.korail_card_installment.strip(),
        }
        if not values["card_number"].isdigit() or not 12 <= len(values["card_number"]) <= 19:
            raise ValueError("KORAIL_CARD_NUMBER must contain 12~19 digits")
        if not values["card_password"].isdigit() or len(values["card_password"]) != 2:
            raise ValueError("KORAIL_CARD_PASSWORD must contain 2 digits")
        if not values["card_expire"].isdigit() or len(values["card_expire"]) != 4 or not 1 <= int(values["card_expire"][2:]) <= 12:
            raise ValueError("KORAIL_CARD_EXPIRE must use YYMM format")
        if not values["birthday"].isdigit() or len(values["birthday"]) != 6:
            raise ValueError("KORAIL_CARD_BIRTHDAY must contain 6 digits")
        if values["installment"] != "0" and not values["installment"].isdigit():
            raise ValueError("KORAIL_CARD_INSTALLMENT must be 0 or 01~24")
        if values["installment"] != "0" and not 1 <= int(values["installment"]) <= 24:
            raise ValueError("KORAIL_CARD_INSTALLMENT must be 0 or 01~24")
        card_type = self.korail_card_type.strip().upper()
        if card_type not in {"J", "S"}:
            raise ValueError("KORAIL_CARD_TYPE must be J (personal) or S (corporate)")
        from korail_mobile_api import CardPayment
        return CardPayment(**values, card_type=card_type)


settings = Settings()

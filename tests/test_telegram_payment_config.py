import pytest

from app.config import Settings


def test_telegram_auto_payment_is_disabled_by_default():
    settings = Settings(korail_auto_payment_enabled=False)

    assert settings.card_payment() is None


def test_telegram_auto_payment_builds_card_from_environment_values():
    settings = Settings(
        korail_auto_payment_enabled=True,
        korail_card_number="123456789012",
        korail_card_password="12",
        korail_card_expire="3012",
        korail_card_birthday="900101",
        korail_card_installment="0",
        korail_card_type="J",
    )

    card = settings.card_payment()

    assert card.card_number == "123456789012"
    assert card.card_password == "12"
    assert card.card_expire == "3012"
    assert card.birthday == "900101"
    assert card.card_type == "J"
    assert "123456789012" not in repr(card)


def test_telegram_auto_payment_rejects_incomplete_environment_values():
    settings = Settings(
        korail_auto_payment_enabled=True,
        korail_card_number="123456789012",
        korail_card_password="",
        korail_card_expire="3012",
        korail_card_birthday="900101",
    )

    with pytest.raises(ValueError, match="PASSWORD"):
        settings.card_payment()

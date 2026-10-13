from types import SimpleNamespace

import pytest

from app.gui import KorailGui
from app.models import PaymentStatus


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


def _gui(values, enabled=True, card_type="개인"):
    gui = object.__new__(KorailGui)
    gui.auto_payment = _Var(enabled)
    gui.card_type = _Var(card_type)
    gui.payment_entries = {
        key: SimpleNamespace(get=lambda key=key: values.get(key, ""))
        for key in ("card_number", "card_password", "card_expire", "birthday", "installment")
    }
    return gui


def test_card_payment_input_is_not_created_when_disabled():
    assert _gui({}, enabled=False)._payment_values() is None


def test_card_payment_input_is_validated_and_created():
    card = _gui({
        "card_number": "123456789012",
        "card_password": "12",
        "card_expire": "3012",
        "birthday": "900101",
        "installment": "0",
    })._payment_values()

    assert card.card_number == "123456789012"
    assert card.card_password == "12"
    assert card.card_expire == "3012"
    assert card.birthday == "900101"
    assert card.card_type == "J"


@pytest.mark.parametrize("field,value", [
    ("card_password", "1"),
    ("card_expire", "3020"),
    ("birthday", "90010"),
    ("installment", "25"),
])
def test_card_payment_input_rejects_invalid_values(field, value):
    values = {
        "card_number": "123456789012",
        "card_password": "12",
        "card_expire": "3012",
        "birthday": "900101",
        "installment": "0",
    }
    values[field] = value

    with pytest.raises(ValueError):
        _gui(values)._payment_values()


def test_payment_status_has_explicit_success_and_failure_states():
    assert PaymentStatus.PAID.value == "PAID"
    assert PaymentStatus.FAILED.value == "FAILED"

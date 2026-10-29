from types import SimpleNamespace

import pytest

from app.korail_service import KorailService


def _service(reservation=None):
    calls = []
    client = SimpleNamespace(
        reservations=SimpleNamespace(
            find=lambda number: reservation,
            cancel=lambda value: calls.append(value),
        )
    )
    service = object.__new__(KorailService)
    service.provider = "pykorail"
    service.client = client
    return service, calls


def test_pykorail_cancel_finds_and_cancels_reservation():
    reservation = object()
    service, calls = _service(reservation)

    service.cancel_reservation("1234567890")

    assert calls == [reservation]


@pytest.mark.parametrize("number", ["", "abc", "12-34"])
def test_pykorail_cancel_rejects_invalid_reservation_number(number):
    service, _ = _service()

    with pytest.raises(ValueError):
        service.cancel_reservation(number)


def test_pykorail_cancel_reports_missing_reservation():
    service, _ = _service(None)

    with pytest.raises(RuntimeError, match="찾지 못했습니다"):
        service.cancel_reservation("1234567890")

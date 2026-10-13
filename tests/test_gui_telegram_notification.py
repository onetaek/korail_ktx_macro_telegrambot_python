from types import SimpleNamespace

import pytest

from app.gui import KorailGui
from app.models import ConversationSession, JobStatus, ReservationJob


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


def _gui_for_notification(enabled=True, token="token", chat_id="12345"):
    gui = object.__new__(KorailGui)
    gui.telegram_notify = _Var(enabled)
    gui.telegram_token_entry = SimpleNamespace(get=lambda: token)
    gui.telegram_chat_id_entry = SimpleNamespace(get=lambda: chat_id)
    return gui


def test_notification_values_are_optional_when_disabled():
    assert _gui_for_notification(False)._notification_values() is None


def test_notification_values_validate_chat_id():
    assert _gui_for_notification(True)._notification_values() == ("token", 12345)
    with pytest.raises(ValueError, match="Chat ID"):
        _gui_for_notification(True, chat_id="not-a-number")._notification_values()


def test_telegram_message_contains_reservation_details():
    gui = object.__new__(KorailGui)
    session = ConversationSession(
        departure_date="20261010",
        source_station="서울",
        destination_station="부산",
        start_time="0900",
        train_type="KTX",
        seat_option="GENERAL_FIRST",
        passenger_count=1,
    )
    job = ReservationJob("job", 0, session, status=JobStatus.RESERVED)
    job.result_message = "미결제 예약이 완료되었습니다."
    job.reservation_number = "123456"

    message = gui._telegram_message(job)

    assert "코레일 예약이 완료되었습니다." in message
    assert "예약 번호: 123456" in message
    assert "서울" in message and "부산" in message


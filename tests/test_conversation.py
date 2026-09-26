from app.conversation import accept, reset
from app.models import ConversationState


def test_conversation_reaches_confirmation():
    session = reset()
    for value in ["member", "password", "20261010", "서울", "부산", "0900", "2400", "1", "1", "1"]:
        accept(session, value)
    assert session.state == ConversationState.WAITING_FOR_CONFIRMATION


def test_invalid_time_is_rejected():
    session = reset()
    accept(session, "member"); accept(session, "password"); accept(session, "20261010")
    accept(session, "서울"); accept(session, "부산")
    try:
        accept(session, "2560")
        assert False
    except ValueError:
        assert True


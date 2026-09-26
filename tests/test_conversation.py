from app.conversation import accept, reset
from app.models import ConversationState


def test_conversation_reaches_confirmation():
    session = reset()
    for value in ["20261010", "서울", "부산", "0900", "2400", "1", "1", "1"]:
        accept(session, value)
    assert session.state == ConversationState.WAITING_FOR_TRAIN_SELECTION
    session.candidate_train_numbers = ["001", "007", "013"]
    accept(session, "3")
    assert session.selected_train_numbers == ["013"]
    assert session.state == ConversationState.RESERVING


def test_invalid_time_is_rejected():
    session = reset()
    accept(session, "20261010")
    accept(session, "서울"); accept(session, "부산")
    try:
        accept(session, "2560")
        assert False
    except ValueError:
        assert True

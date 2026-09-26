import re
from datetime import datetime

from .models import ConversationSession, ConversationState


def reset() -> ConversationSession:
    return ConversationSession(state=ConversationState.WAITING_FOR_DATE)


def accept(session: ConversationSession, text: str) -> str:
    value = text.strip()
    state = session.state
    if state == ConversationState.WAITING_FOR_DATE:
        datetime.strptime(value, "%Y%m%d"); session.departure_date = value; session.state = ConversationState.WAITING_FOR_SOURCE
        return "출발역을 입력하세요."
    if state == ConversationState.WAITING_FOR_SOURCE:
        session.source_station = value; session.state = ConversationState.WAITING_FOR_DESTINATION
        return "도착역을 입력하세요."
    if state == ConversationState.WAITING_FOR_DESTINATION:
        if value == session.source_station: raise ValueError("출발역과 도착역은 달라야 합니다.")
        session.destination_station = value; session.state = ConversationState.WAITING_FOR_START_TIME
        return "검색 시작 시간을 HHMM 형식으로 입력하세요."
    if state == ConversationState.WAITING_FOR_START_TIME:
        _validate_time(value); session.start_time = value; session.state = ConversationState.WAITING_FOR_MAX_TIME
        return "검색 최대 시간을 HHMM 또는 2400으로 입력하세요."
    if state == ConversationState.WAITING_FOR_MAX_TIME:
        if value != "2400": _validate_time(value)
        session.max_time = value; session.state = ConversationState.WAITING_FOR_TRAIN_TYPE
        return "열차 종류를 입력하세요. 1=KTX, 2=전체"
    if state == ConversationState.WAITING_FOR_TRAIN_TYPE:
        if value not in {"1", "2"}: raise ValueError("1 또는 2를 입력하세요.")
        session.train_type = "KTX" if value == "1" else "ALL"; session.state = ConversationState.WAITING_FOR_SEAT_OPTION
        return "좌석 옵션을 입력하세요. 1=일반실 우선, 2=일반실만, 3=특실 우선, 4=특실만"
    if state == ConversationState.WAITING_FOR_SEAT_OPTION:
        options = {"1":"GENERAL_FIRST", "2":"GENERAL_ONLY", "3":"SPECIAL_FIRST", "4":"SPECIAL_ONLY"}
        if value not in options: raise ValueError("1~4 중 하나를 입력하세요.")
        session.seat_option = options[value]; session.state = ConversationState.WAITING_FOR_PASSENGER_COUNT
        return "탑승 인원 수를 입력하세요. (1~9)"
    if state == ConversationState.WAITING_FOR_PASSENGER_COUNT:
        if not value.isdigit() or not 1 <= int(value) <= 9: raise ValueError("탑승 인원은 1~9명입니다.")
        session.passenger_count = int(value); session.state = ConversationState.WAITING_FOR_TRAIN_SELECTION
        return summary(session) + "\n열차 목록을 조회합니다. 잠시 기다려주세요."
    if state == ConversationState.WAITING_FOR_TRAIN_SELECTION:
        selected = _parse_train_selection(value, len(session.candidate_train_numbers))
        session.selected_train_numbers = [session.candidate_train_numbers[index - 1] for index in selected]
        session.state = ConversationState.RESERVING
        return f"선택한 열차 {', '.join(map(str, selected))}번의 예약 검색을 시작합니다."
    raise ValueError("현재 입력을 처리할 수 없습니다. /start로 다시 시작하세요.")


def _validate_time(value: str) -> None:
    if not re.fullmatch(r"(?:[01]\d|2[0-3])[0-5]\d", value): raise ValueError("시간은 HHMM 형식이어야 합니다.")


def _parse_train_selection(value: str, count: int) -> list[int]:
    try:
        numbers = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise ValueError("예약할 열차 번호를 3 또는 1,4,6 형식으로 입력하세요.") from exc
    numbers = sorted(set(numbers))
    if not numbers or any(number < 1 or number > count for number in numbers):
        raise ValueError(f"열차 번호는 1~{count} 범위에서 입력하세요.")
    return numbers


def summary(s: ConversationSession) -> str:
    return (f"출발일: {s.departure_date}\n출발: {s.source_station}\n도착: {s.destination_station}\n"
            f"시간: {s.start_time}~{s.max_time}\n열차: {s.train_type}\n좌석: {s.seat_option}\n인원: {s.passenger_count}명")

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from .config import settings
from .models import ConversationSession

log = logging.getLogger(__name__)


@dataclass
class ReservationResult:
    message: str
    reservation_number: str | None = None


class KorailService:
    """Small adapter around the GitHub korail-mobile-api client.

    The third-party client is synchronous, so calls are executed in a worker
    thread by the async reservation service. No credentials or raw payloads
    are logged here.
    """

    def __init__(self) -> None:
        try:
            from korail_mobile_api import KorailClient, TrainSearchQuery
        except ImportError as exc:
            raise RuntimeError("korail-mobile-api is not installed") from exc
        self.client_type = KorailClient
        self.query_type = TrainSearchQuery
        self.client = self.client_type()

    def login(self, session: ConversationSession) -> None:
        log.info("Korail login started: user_type=%s", self._user_type(session.korail_id or ""))
        self.client.login(session.korail_id, session.password)
        log.info("Korail login completed")

    def reserve_once(self, session: ConversationSession) -> ReservationResult | None:
        query = self.query_type(
            departure_station_code=session.source_station,
            arrival_station_code=session.destination_station,
            departure_date=session.departure_date,
            departure_time=f"{session.start_time}00",
            passengers=session.passenger_count,
            train_group_code="100" if session.train_type == "KTX" else "109",
        )
        log.info("Train search started: route=%s->%s, date=%s, start=%s",
                 session.source_station, session.destination_station,
                 session.departure_date, session.start_time)
        result = self.client.search_trains(query)
        trains = list(getattr(result, "trains", result or []))
        filtered = [train for train in trains if self._within_max_time(train, session.max_time)]
        log.info("Search completed: count=%d, filtered_count=%d", len(trains), len(filtered))
        for train in filtered:
            if self._seat_available(train, session.seat_option):
                log.info("Train selected: train_no=%s, departure=%s", self._field(train, "train_no"), self._field(train, "departure_time"))
                log.info("Reservation request started")
                try:
                    from korail_mobile_api import KorailPassengerCounts, KorailSeatClass
                    seat_class = KorailSeatClass.SPECIAL if session.seat_option.startswith("SPECIAL") else KorailSeatClass.GENERAL
                    passengers = KorailPassengerCounts(adult=session.passenger_count)
                    hold = self.client.reserve(train, seat_class=seat_class, passengers=passengers)
                except TypeError:
                    hold = self.client.reserve(train)
                number = self._field(hold, "pnr") or self._field(hold, "reservation_number")
                log.info("Reservation completed: reservation_number_present=%s", bool(number))
                return ReservationResult("미결제 예약이 완료되었습니다. 공식 앱/웹에서 결제를 진행하세요.", number)
        return None

    def close(self) -> None:
        clear = getattr(self.client, "clear_session", None)
        close = getattr(self.client, "close", None)
        if clear:
            clear()
        if close:
            close()

    @staticmethod
    def _user_type(value: str) -> str:
        return "email" if "@" in value else "phone" if value.count("-") == 2 else "membership"

    @staticmethod
    def _field(obj, name: str):
        value = getattr(obj, name, None)
        return value if value is not None else getattr(obj, name.replace("_", ""), None)

    def _within_max_time(self, train, max_time: str) -> bool:
        if max_time == "2400":
            return True
        value = str(self._field(train, "departure_time") or "")[:4]
        return value.isdigit() and int(value) <= int(max_time)

    def _seat_available(self, train, option: str) -> bool:
        general_code = self._field(train, "general_reservation_code")
        special_code = self._field(train, "special_reservation_code")
        general_flag = self._field(train, "general_reservation_flag")
        special_flag = self._field(train, "special_reservation_flag")
        general = general_code == "11" or general_flag in {"Y", "11"}
        special = special_code == "11" or special_flag in {"Y", "11"}
        log.info("Seat availability: train_no=%s, general_code=%s, general_flag=%s, special_code=%s, special_flag=%s",
                 self._field(train, "train_no"), general_code, general_flag, special_code, special_flag)
        if option == "GENERAL_ONLY": return general
        if option == "SPECIAL_ONLY": return special
        if option == "SPECIAL_FIRST": return special or general
        return general or special

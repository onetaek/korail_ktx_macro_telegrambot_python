import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import settings
from .models import ConversationSession, PaymentStatus

log = logging.getLogger(__name__)


@dataclass
class ReservationResult:
    message: str
    reservation_number: str | None = None
    payment_status: PaymentStatus = PaymentStatus.NOT_REQUESTED


class KorailService:
    """Small adapter around the GitHub korail-mobile-api client.

    The third-party client is synchronous, so calls are executed in a worker
    thread by the async reservation service. No credentials or raw payloads
    are logged here.
    """

    def __init__(self) -> None:
        self.provider = settings.korail_provider.strip().lower()
        if self.provider == "pykorail":
            self._init_pykorail()
            return
        if self.provider not in {"legacy", "korail-mobile-api"}:
            raise RuntimeError(f"Unsupported KORAIL provider: {self.provider}")
        try:
            import korail_mobile_api
            from korail_mobile_api import KorailClient, KorailConfig, TrainSearchQuery
        except ImportError as exc:
            raise RuntimeError("korail-mobile-api is not installed") from exc
        self.client_type = KorailClient
        self.query_type = TrainSearchQuery
        self.client_version = getattr(korail_mobile_api, "__version__", "unknown")
        self.config = KorailConfig(app_version=settings.korail_app_version)
        self.client = self.client_type(self.config)
        log.info("KORAIL client initialized: package_version=%s, app_version=%s",
                 self.client_version, self.config.app_version)

    def _init_pykorail(self) -> None:
        try:
            import importlib.metadata
            from pykorail import Korail
        except ImportError as exc:
            raise RuntimeError("pykorail is not installed") from exc
        self.client_type = Korail
        self.query_type = None
        self.client_version = importlib.metadata.version("pykorail")
        self.config = None
        self.client = Korail()
        log.info("KORAIL client initialized: provider=pykorail, package_version=%s", self.client_version)

    def login(self, session: ConversationSession) -> None:
        log.info("Korail login started: user_type=%s", self._user_type(settings.korail_id))
        if self.provider == "pykorail":
            try:
                self.client.login(settings.korail_id, settings.korail_password)
            except Exception as exc:
                raise RuntimeError(f"pykorail 로그인 실패: {exc}") from exc
            log.info("Korail login completed: provider=pykorail")
            return
        try:
            self.client.login(settings.korail_id, settings.korail_password)
        except Exception as exc:
            if "-8204" in str(exc):
                raise RuntimeError(
                    "KORAIL 서버가 클라이언트 버전을 거부했습니다(-8204). "
                    f"korail-mobile-api={self.client_version}, AppVersion={self.config.app_version}. "
                    "최신 버전 확인 후 KORAIL_APP_VERSION 환경변수를 조정하세요."
                ) from exc
            raise
        log.info("Korail login completed")

    def reserve_once(self, session: ConversationSession, card_payment=None) -> ReservationResult | None:
        if self.provider == "pykorail":
            return self._reserve_once_pykorail(session, card_payment)
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
            if session.selected_train_numbers and str(self._field(train, "train_no")) not in session.selected_train_numbers:
                continue
            if self._seat_available(train, session.seat_option):
                log.info("Train selected: train_no=%s, departure=%s", self._field(train, "train_no"), self._field(train, "departure_time"))
                log.info("Reservation request started")
                try:
                    from korail_mobile_api import (
                        KorailPassengerCounts,
                        KorailSeatClass,
                    )
                    selected_class = self._seat_class_for_train(train, session.seat_option)
                    if selected_class == "SPECIAL":
                        seat_class = KorailSeatClass.SPECIAL
                    else:
                        seat_class = KorailSeatClass.GENERAL
                    passengers = KorailPassengerCounts(adult=session.passenger_count)
                    hold = self.client.reserve(train, seat_class=seat_class, passengers=passengers)
                except TypeError:
                    hold = self.client.reserve(train)
                except Exception as exc:
                    from korail_mobile_api.errors import KorailSoldOutError

                    if isinstance(exc, KorailSoldOutError):
                        log.info(
                            "Reservation seat sold out; retrying: code=%s, message=%s",
                            getattr(exc, "code", None),
                            getattr(exc, "message", str(exc)),
                        )
                        continue
                    raise
                number = self._field(hold, "pnr") or self._field(hold, "reservation_number")
                log.info("Reservation completed: reservation_number_present=%s", bool(number))
                if card_payment is None:
                    return ReservationResult("미결제 예약이 완료되었습니다. 공식 앱/웹에서 결제를 진행하세요.", number)
                log.info("Card payment started: reservation_number_present=%s", bool(number))
                try:
                    payment = self.client.pay_with_card(hold, card_payment)
                except Exception:
                    log.warning("Card payment request failed; unpaid reservation retained")
                    return ReservationResult(
                        f"예약은 완료되었지만 카드 결제 요청에 실패했습니다. 공식 앱/웹에서 결제하세요.",
                        number,
                        PaymentStatus.FAILED,
                    )
                if getattr(payment, "str_result", None) == "SUCC":
                    log.info("Card payment completed: reservation_number_present=%s", bool(number))
                    return ReservationResult("예약 및 카드 결제가 완료되었습니다.", number, PaymentStatus.PAID)
                message = getattr(payment, "display_message", None) or getattr(payment, "h_msg_txt", None) or "카드 결제가 거절되었습니다."
                log.warning("Card payment failed: reservation_number_present=%s", bool(number))
                return ReservationResult(
                    f"예약은 완료되었지만 카드 결제에 실패했습니다: {message} 공식 앱/웹에서 결제하세요.",
                    number,
                    PaymentStatus.FAILED,
                )
        return None

    def cancel_reservation(self, reservation_number: str) -> None:
        """Cancel an existing unpaid pykorail reservation by reservation number."""
        if self.provider != "pykorail":
            raise RuntimeError("기존 provider의 예약 취소는 아직 별도 연동되지 않았습니다.")
        if not reservation_number or not reservation_number.isdigit():
            raise ValueError("유효한 예약번호가 필요합니다.")
        reservation = self.client.reservations.find(reservation_number)
        if reservation is None:
            raise RuntimeError("예약번호에 해당하는 예약을 찾지 못했습니다.")
        self.client.reservations.cancel(reservation)
        log.info("Reservation cancelled: provider=pykorail")

    def _reserve_once_pykorail(self, session: ConversationSession, card_payment=None) -> ReservationResult | None:
        """Create an unpaid reservation during the pykorail migration phase.

        Payment remains deliberately disabled until the reservation path has
        been verified independently. This method never sends a payment call.
        """
        from pykorail import AdultPassenger, ReserveOption, TrainType
        from pykorail import SoldOutError

        departure = datetime.strptime(
            f"{session.departure_date}{session.start_time}", "%Y%m%d%H%M"
        ).replace(tzinfo=timezone(timedelta(hours=9)))
        train_type = getattr(TrainType, "KTX", "100") if session.train_type == "KTX" else "109"
        trains = self.client.trains.search(
            session.source_station,
            session.destination_station,
            depart_after=departure,
            train_type=train_type,
            passengers=[AdultPassenger(session.passenger_count)],
            include_no_seats=True,
            max_pages=1,
        )
        for train in trains:
            if not self._within_max_time(train, session.max_time):
                continue
            if session.selected_train_numbers and str(self._field(train, "train_no")) not in session.selected_train_numbers:
                continue
            option_name = {
                "GENERAL_ONLY": "GENERAL_ONLY",
                "SPECIAL_ONLY": "SPECIAL_ONLY",
                "SPECIAL_FIRST": "SPECIAL_FIRST",
            }.get(session.seat_option, "GENERAL_FIRST")
            if not self._seat_available(train, session.seat_option):
                continue
            log.info("Reservation request started: provider=pykorail")
            try:
                hold = self.client.reservations.create(
                    train,
                    passengers=[AdultPassenger(session.passenger_count)],
                    option=getattr(ReserveOption, option_name),
                )
            except SoldOutError:
                log.info("Reservation seat sold out; retrying: provider=pykorail")
                continue
            number = self._field(hold, "reservation_number") or self._field(hold, "pnr_no") or self._field(hold, "pnr")
            log.info("Reservation completed: provider=pykorail, reservation_number_present=%s", bool(number))
            if card_payment is None:
                return ReservationResult("미결제 예약이 완료되었습니다. 공식 앱/웹에서 결제를 진행하세요.", number)

            from pykorail import Card

            card = Card(
                number=self._card_field(card_payment, "card_number"),
                password=self._card_field(card_payment, "card_password"),
                verify_number=self._card_field(card_payment, "birthday"),
                expire=self._card_field(card_payment, "card_expire"),
                installment=int(self._card_field(card_payment, "installment") or 0),
                is_corporate=self._card_field(card_payment, "card_type") == "S",
            )
            log.info("Card payment started: provider=pykorail, reservation_number_present=%s", bool(number))
            try:
                self.client.reservations.pay(hold, card)
            except Exception as exc:
                log.warning("Card payment failed; unpaid reservation retained: provider=pykorail, error_type=%s", type(exc).__name__)
                return ReservationResult(
                    "예약은 완료되었지만 카드 결제에 실패했습니다. 공식 앱/웹에서 결제하세요.",
                    number,
                    PaymentStatus.FAILED,
                )
            log.info("Card payment completed: provider=pykorail, reservation_number_present=%s", bool(number))
            return ReservationResult("예약 및 카드 결제가 완료되었습니다.", number, PaymentStatus.PAID)
        return None

    def preview(self, session: ConversationSession) -> list[object]:
        self.login(session)
        if self.provider == "pykorail":
            from pykorail import AdultPassenger, TrainType

            departure = datetime.strptime(
                f"{session.departure_date}{session.start_time}", "%Y%m%d%H%M"
            ).replace(tzinfo=timezone(timedelta(hours=9)))
            train_type = getattr(TrainType, "KTX", "100") if session.train_type == "KTX" else "109"
            trains = self.client.trains.search(
                session.source_station,
                session.destination_station,
                depart_after=departure,
                train_type=train_type,
                passengers=[AdultPassenger(session.passenger_count)],
                include_no_seats=True,
                max_pages=1,
            )
            return [train for train in trains if self._within_max_time(train, session.max_time)]
        query = self.query_type(
            departure_station_code=session.source_station,
            arrival_station_code=session.destination_station,
            departure_date=session.departure_date,
            departure_time=f"{session.start_time}00",
            passengers=session.passenger_count,
            train_group_code="100" if session.train_type == "KTX" else "109",
        )
        result = self.client.search_trains(query)
        trains = list(getattr(result, "trains", result or []))
        return [train for train in trains if self._within_max_time(train, session.max_time)]

    def train_summary(self, train: object) -> str:
        departure = str(self._field(train, "departure_time") or "")[:4]
        arrival = str(self._field(train, "arrival_time") or "")[:4]
        return (
            f"{self._field(train, 'train_name') or self._field(train, 'train_group_name') or '열차'} "
            f"{self._field(train, 'train_no') or '-'} | "
            f"출발 {self._format_time(departure)} → 도착 {self._format_time(arrival)} | "
            f"{self._duration_text(departure, arrival)}"
        )

    @staticmethod
    def _format_time(value: str) -> str:
        if len(value) == 4 and value.isdigit():
            return f"{value[:2]}시 {value[2:]}분"
        return "시간 미상"

    @staticmethod
    def _duration_text(departure: str, arrival: str) -> str:
        if len(departure) != 4 or len(arrival) != 4 or not departure.isdigit() or not arrival.isdigit():
            return "소요시간 미상"
        departure_minutes = int(departure[:2]) * 60 + int(departure[2:])
        arrival_minutes = int(arrival[:2]) * 60 + int(arrival[2:])
        if arrival_minutes < departure_minutes:
            arrival_minutes += 24 * 60
        duration = arrival_minutes - departure_minutes
        return f"{duration // 60}시간 {duration % 60}분 소요"

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
        if value is None:
            aliases = {
                "train_name": "train_type_name",
                "train_no": "train_no",
                "departure_time": "dep_time",
                "arrival_time": "arr_time",
                "general_reservation_code": "general_seat",
                "special_reservation_code": "special_seat",
            }
            value = getattr(obj, aliases.get(name, name), None)
        return value if value is not None else getattr(obj, name.replace("_", ""), None)

    def _within_max_time(self, train, max_time: str) -> bool:
        if max_time == "2400":
            return True
        value = str(self._field(train, "departure_time") or "")[:4]
        return value.isdigit() and int(value) <= int(max_time)

    def _seat_available(self, train, option: str) -> bool:
        return self._seat_class_for_train(train, option) is not None

    def _seat_class_for_train(self, train, option: str) -> str | None:
        general_code = self._field(train, "general_reservation_code")
        special_code = self._field(train, "special_reservation_code")
        general_flag = self._field(train, "general_reservation_flag")
        special_flag = self._field(train, "special_reservation_flag")
        general = general_code == "11" or general_flag in {"Y", "11"} or self._seat_value_available(general_code)
        special = special_code == "11" or special_flag in {"Y", "11"} or self._seat_value_available(special_code)
        log.info("Seat availability: train_no=%s, general_code=%s, general_flag=%s, special_code=%s, special_flag=%s",
                 self._field(train, "train_no"), general_code, general_flag, special_code, special_flag)
        if option == "GENERAL_ONLY":
            return "GENERAL" if general else None
        if option == "SPECIAL_ONLY":
            return "SPECIAL" if special else None
        if option == "SPECIAL_FIRST":
            if special:
                return "SPECIAL"
            return "GENERAL" if general else None
        if general:
            return "GENERAL"
        return "SPECIAL" if special else None

    @staticmethod
    def _seat_value_available(value) -> bool:
        if value is None:
            return False
        normalized = str(value).strip().upper()
        return normalized in {"Y", "11", "가능", "AVAILABLE"} or "가능" in normalized

    @staticmethod
    def _card_field(card_payment, name: str) -> str:
        value = getattr(card_payment, name, "")
        return str(value or "").strip()

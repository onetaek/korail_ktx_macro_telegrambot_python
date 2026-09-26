from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ConversationState(str, Enum):
    IDLE = "IDLE"
    WAITING_FOR_KORAIL_ID = "WAITING_FOR_KORAIL_ID"
    WAITING_FOR_PASSWORD = "WAITING_FOR_PASSWORD"
    WAITING_FOR_DATE = "WAITING_FOR_DATE"
    WAITING_FOR_SOURCE = "WAITING_FOR_SOURCE"
    WAITING_FOR_DESTINATION = "WAITING_FOR_DESTINATION"
    WAITING_FOR_START_TIME = "WAITING_FOR_START_TIME"
    WAITING_FOR_MAX_TIME = "WAITING_FOR_MAX_TIME"
    WAITING_FOR_TRAIN_TYPE = "WAITING_FOR_TRAIN_TYPE"
    WAITING_FOR_SEAT_OPTION = "WAITING_FOR_SEAT_OPTION"
    WAITING_FOR_PASSENGER_COUNT = "WAITING_FOR_PASSENGER_COUNT"
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    RESERVING = "RESERVING"


class JobStatus(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    RESERVED = "RESERVED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class ConversationSession:
    state: ConversationState = ConversationState.IDLE
    korail_id: str | None = None
    password: str | None = None
    departure_date: str | None = None
    source_station: str | None = None
    destination_station: str | None = None
    start_time: str | None = None
    max_time: str = "2400"
    train_type: str = "KTX"
    seat_option: str = "GENERAL_FIRST"
    passenger_count: int = 1
    job_id: str | None = None


@dataclass
class ReservationJob:
    job_id: str
    chat_id: int
    session: ConversationSession
    status: JobStatus = JobStatus.CREATED
    result_message: str | None = None
    reservation_number: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    cancel_event: Any = None


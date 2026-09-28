from asyncio import Event, Task

from .models import ConversationSession, ReservationJob
from .models import ConfigSession

conversation_sessions: dict[int, ConversationSession] = {}
config_sessions: dict[int, ConfigSession] = {}
reservation_jobs: dict[str, ReservationJob] = {}
running_tasks: dict[str, Task] = {}
cancel_events: dict[str, Event] = {}

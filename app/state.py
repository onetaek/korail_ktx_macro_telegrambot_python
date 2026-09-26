from asyncio import Event, Task

from .models import ConversationSession, ReservationJob

conversation_sessions: dict[int, ConversationSession] = {}
reservation_jobs: dict[str, ReservationJob] = {}
running_tasks: dict[str, Task] = {}
cancel_events: dict[str, Event] = {}


import asyncio
import logging
import uuid
import random
from datetime import datetime, timezone

from .config import settings
from .korail_service import KorailService
from .models import JobStatus, ReservationJob, ConversationSession
from . import state

log = logging.getLogger(__name__)


class ReservationService:
    def create(self, chat_id: int, session: ConversationSession) -> ReservationJob:
        job = ReservationJob(str(uuid.uuid4()), chat_id, session, cancel_event=asyncio.Event())
        state.reservation_jobs[job.job_id] = job
        log.info("Reservation job created: job_id=%s, chat_id=%s", job.job_id, chat_id)
        return job

    def start(self, job: ReservationJob, notify) -> None:
        task = asyncio.create_task(self._run(job, notify), name=f"reservation-{job.job_id}")
        state.running_tasks[job.job_id] = task

    async def cancel(self, job_id: str) -> bool:
        job = state.reservation_jobs.get(job_id)
        if not job: return False
        job.cancel_event.set()
        task = state.running_tasks.get(job_id)
        if task and not task.done(): task.cancel()
        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.now(timezone.utc)
        log.info("Reservation job cancelled: job_id=%s", job_id)
        return True

    async def _run(self, job: ReservationJob, notify) -> None:
        job.status = JobStatus.RUNNING
        service = KorailService()
        deadline = asyncio.get_running_loop().time() + settings.korail_max_search_minutes * 60
        try:
            while asyncio.get_running_loop().time() < deadline:
                if job.cancel_event.is_set(): return
                result = await asyncio.to_thread(service.reserve_once, job.session)
                if result:
                    job.status = JobStatus.RESERVED
                    job.result_message = result.message
                    job.reservation_number = result.reservation_number
                    await notify(job)
                    return
                log.info("No available train; retrying: job_id=%s", job.job_id)
                base_interval = max(1.0, settings.korail_search_interval_seconds)
                jitter_min, jitter_max = settings.search_jitter_range()
                jitter = random.uniform(jitter_min, jitter_max)
                wait_seconds = base_interval + jitter
                log.info("Waiting before next search: base=%.3fs, jitter=%.3fs, total=%.3fs",
                         base_interval, jitter, wait_seconds)
                await asyncio.sleep(wait_seconds)
            job.status = JobStatus.FAILED
            job.result_message = "검색 시간 내 예약 가능한 열차를 찾지 못했습니다."
            await notify(job)
        except asyncio.CancelledError:
            job.status = JobStatus.CANCELLED
            raise
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.result_message = str(exc)
            log.exception("Reservation failed: job_id=%s", job.job_id)
            await notify(job)
        finally:
            job.completed_at = datetime.now(timezone.utc)
            state.running_tasks.pop(job.job_id, None)

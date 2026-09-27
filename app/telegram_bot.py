import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from . import conversation, state
from .config import settings
from .models import ConfigSession, ConfigState, ConversationState, JobStatus
from .korail_service import KorailService
from .reservation_service import ReservationService

log = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self) -> None:
        self.service = ReservationService()
        self.application = Application.builder().token(settings.telegram_bot_token).build()
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("status", self.status))
        self.application.add_handler(CommandHandler("cancel", self.cancel))
        self.application.add_handler(CommandHandler("config", self.config))
        self.application.add_handler(CommandHandler("help", self.help))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message))

    def allowed(self, chat_id: int) -> bool:
        allowed = settings.allowed_chat_ids()
        return bool(allowed) and chat_id in allowed

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        if not self.allowed(chat_id): await update.message.reply_text("허용되지 않은 사용자입니다."); return
        state.conversation_sessions[chat_id] = conversation.reset()
        log.info("Conversation started: chat_id=%s", chat_id)
        await update.message.reply_text("출발일을 YYYYMMDD 형식으로 입력하세요.")

    async def message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        if not self.allowed(chat_id): return
        if chat_id in state.config_sessions:
            await self.update_config(update, update.message.text)
            return
        session = state.conversation_sessions.get(chat_id)
        if not session: await update.message.reply_text("/start로 시작하세요."); return
        try:
            reply = conversation.accept(session, update.message.text)
            log.info("Conversation state changed: chat_id=%s, state=%s", chat_id, session.state.value)
            await update.message.reply_text(reply)
            if session.state == ConversationState.WAITING_FOR_TRAIN_SELECTION:
                await self.send_train_preview(session, chat_id)
            if session.state == ConversationState.RESERVING:
                job = self.service.create(chat_id, session)
                session.job_id = job.job_id
                self.service.start(job, self.notify)
        except ValueError as exc:
            await update.message.reply_text(str(exc))

    async def send_train_preview(self, session, chat_id: int) -> None:
        service = KorailService()
        try:
            trains = await asyncio.to_thread(service.preview, session)
            if not trains:
                session.state = ConversationState.WAITING_FOR_TRAIN_SELECTION
                await self.application.bot.send_message(chat_id, "조건에 맞는 열차가 없습니다. /start로 다시 시도하세요.")
                return
            session.candidate_train_numbers = [str(service._field(train, "train_no")) for train in trains]
            lines = ["예약을 시도할 열차 번호를 입력하세요. 예: 3 또는 1,4,6"]
            lines.extend(f"{index}. {service.train_summary(train)}" for index, train in enumerate(trains, 1))
            await self.application.bot.send_message(chat_id, "\n".join(lines))
        finally:
            await asyncio.to_thread(service.close)

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        jobs = [j for j in state.reservation_jobs.values() if j.chat_id == chat_id]
        if not jobs: await update.message.reply_text("예약 작업이 없습니다."); return
        await update.message.reply_text("\n".join(f"{j.job_id}: {j.status.value} - {j.result_message or '진행 중'}" for j in jobs[-5:]))

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        if state.config_sessions.pop(chat_id, None):
            await update.message.reply_text("설정 변경을 취소했습니다.")
            return
        session = state.conversation_sessions.get(chat_id)
        if session and session.job_id:
            await self.service.cancel(session.job_id)
            await update.message.reply_text("예약 작업을 취소했습니다.")
        else:
            state.conversation_sessions.pop(chat_id, None)
            await update.message.reply_text("현재 입력을 취소했습니다.")

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text("/start 예약 시작\n/status 상태 확인\n/config 조회 주기 설정\n/cancel 취소")

    async def config(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        if not self.allowed(chat_id):
            return
        state.config_sessions[chat_id] = ConfigSession()
        await update.message.reply_text(
            "현재 조회 설정입니다.\n"
            f"기본 주기: {settings.korail_search_interval_seconds:.3f}초\n"
            f"Jitter 최소: {settings.korail_search_jitter_min_seconds:.3f}초\n"
            f"Jitter 최대: {settings.korail_search_jitter_max_seconds:.3f}초\n\n"
            f"최대 실행 시간: {settings.korail_max_search_minutes}분\n\n"
            "변경할 기본 주기(초)를 입력하세요. 예: 0.5 또는 1"
        )

    async def update_config(self, update: Update, text: str) -> None:
        chat_id = update.effective_chat.id
        config_session = state.config_sessions.get(chat_id)
        if config_session is None:
            return
        try:
            value = float(text.strip())
            if value < 0:
                raise ValueError
            if config_session.state == ConfigState.WAITING_FOR_INTERVAL:
                if value <= 0:
                    raise ValueError("기본 주기는 0보다 큰 숫자여야 합니다.")
                config_session.interval = value
                config_session.state = ConfigState.WAITING_FOR_JITTER_MIN
                await update.message.reply_text("Jitter 최소값(초)을 입력하세요. 예: 0.1")
                return
            if config_session.state == ConfigState.WAITING_FOR_JITTER_MIN:
                config_session.jitter_min = value
                config_session.state = ConfigState.WAITING_FOR_JITTER_MAX
                await update.message.reply_text("Jitter 최대값(초)을 입력하세요. 예: 0.5")
                return
            if config_session.state == ConfigState.WAITING_FOR_JITTER_MAX:
                if value < (config_session.jitter_min or 0):
                    raise ValueError("Jitter 최대값은 최소값보다 크거나 같아야 합니다.")
                config_session.jitter_max = value
                config_session.state = ConfigState.WAITING_FOR_MAX_MINUTES
                await update.message.reply_text("예약 작업 최대 실행 시간(분)을 입력하세요. 예: 120")
                return
            if value <= 0 or not value.is_integer():
                raise ValueError("최대 실행 시간은 1 이상의 정수(분)로 입력하세요.")
            settings.korail_search_interval_seconds = config_session.interval or settings.korail_search_interval_seconds
            settings.korail_search_jitter_min_seconds = config_session.jitter_min or 0.0
            settings.korail_search_jitter_max_seconds = config_session.jitter_max or 0.0
            settings.korail_max_search_minutes = int(value)
            state.config_sessions.pop(chat_id, None)
            await update.message.reply_text(
                "조회 설정이 정상적으로 변경되었습니다.\n"
                f"기본 주기: {settings.korail_search_interval_seconds:.3f}초\n"
                f"Jitter 범위: {settings.korail_search_jitter_min_seconds:.3f}~"
                f"{settings.korail_search_jitter_max_seconds:.3f}초\n"
                f"최대 실행 시간: {settings.korail_max_search_minutes}분\n"
                f"실제 조회 간격: {settings.korail_search_interval_seconds + settings.korail_search_jitter_min_seconds:.3f}~"
                f"{settings.korail_search_interval_seconds + settings.korail_search_jitter_max_seconds:.3f}초"
            )
        except ValueError as exc:
            message = str(exc) if str(exc) else "0 이상의 숫자를 입력하세요."
            await update.message.reply_text(message)

    async def notify(self, job) -> None:
        await self.application.bot.send_message(job.chat_id, f"{job.status.value}\n{job.result_message}")
        log.info("Telegram notification sent: job_id=%s, status=%s", job.job_id, job.status.value)

    async def run(self) -> None:
        await self.application.initialize(); await self.application.start(); await self.application.updater.start_polling()

    async def stop(self) -> None:
        if self.application.updater: await self.application.updater.stop()
        await self.application.stop(); await self.application.shutdown()

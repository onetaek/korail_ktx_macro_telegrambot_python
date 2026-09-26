import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from . import conversation, state
from .config import settings
from .models import ConversationState, JobStatus
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
        session = state.conversation_sessions.get(chat_id)
        if session and session.job_id:
            await self.service.cancel(session.job_id)
            await update.message.reply_text("예약 작업을 취소했습니다.")
        else:
            state.conversation_sessions.pop(chat_id, None)
            await update.message.reply_text("현재 입력을 취소했습니다.")

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text("/start 예약 시작\n/status 상태 확인\n/cancel 취소")

    async def notify(self, job) -> None:
        await self.application.bot.send_message(job.chat_id, f"{job.status.value}\n{job.result_message}")
        log.info("Telegram notification sent: job_id=%s, status=%s", job.job_id, job.status.value)

    async def run(self) -> None:
        await self.application.initialize(); await self.application.start(); await self.application.updater.start_polling()

    async def stop(self) -> None:
        if self.application.updater: await self.application.updater.stop()
        await self.application.stop(); await self.application.shutdown()

import asyncio
import logging

from . import state
from .config import settings
from .telegram_bot import TelegramBot


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
log = logging.getLogger(__name__)


async def main() -> None:
    if not settings.telegram_bot_token or not settings.allowed_chat_ids():
        raise RuntimeError("TELEGRAM_BOT_TOKEN과 TELEGRAM_ALLOWED_CHAT_IDS를 설정해야 합니다.")
    if not settings.korail_id or not settings.korail_password:
        raise RuntimeError("KORAIL_ID와 KORAIL_PASSWORD를 설정해야 합니다.")

    telegram_bot = TelegramBot()
    await telegram_bot.run()
    log.info("Telegram long polling started")

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        for task in list(state.running_tasks.values()):
            task.cancel()
        await telegram_bot.stop()
        log.info("Application stopped")


if __name__ == "__main__":
    asyncio.run(main())

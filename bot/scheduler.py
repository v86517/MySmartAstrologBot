from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo  # для Python 3.9+
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from bot.services.gemini import GeminiService
from bot.db import get_all_subscribed_users, get_user_data, save_message_to_archive
from aiogram import Bot
import asyncio
import logging

logger = logging.getLogger(__name__)


async def send_daily_horoscopes(bot: Bot):
    logger.info("📨 Запуск проверки часовых поясов для рассылки...")
    subscribers = await get_all_subscribed_users()
    if not subscribers:
        logger.info("📭 Нет активных подписчиков")
        return

    now_utc = datetime.now(timezone.utc)
    sent = 0
    errors = 0

    for user in subscribers:
        tz_offset = user.timezone_offset  # int
        # Локальное время пользователя
        user_now = now_utc + timedelta(hours=tz_offset)
        if user_now.hour == 8 and user_now.minute == 0:
            # Отправляем гороскоп
            try:
                user_id = user.telegram_id
                user_data = await get_user_data(user_id)
                if not user_data or not user_data.get('name'):
                    continue
                today = user_now.strftime("%d.%m.%Y")
                horoscope = GeminiService().generate_horoscope(user_data, today)
                await save_message_to_archive(user_id, 'horoscope', horoscope)
                await bot.send_message(user_id, f"🔮 Ваш гороскоп на {today}\n\n{horoscope}")
                sent += 1
                await asyncio.sleep(0.5)
            except Exception as e:
                errors += 1
                logger.error(f"Ошибка отправки {user_id}: {e}")

    logger.info(f"📨 Рассылка завершена. Отправлено: {sent}, Ошибок: {errors}")


def setup_scheduler(bot: Bot):
    scheduler = AsyncIOScheduler(timezone="Asia/Vladivostok")
    scheduler.add_job(
        send_daily_horoscopes,
        CronTrigger(minute=0), # каждый час
        args=[bot],
        id="daily_horoscope",
        replace_existing=True
    )
    scheduler.start()
    logger.info("⏰ Планировщик запущен! Рассылка будет выполняться каждый день в 8:00 по Владивостоку")

    job = scheduler.get_job("daily_horoscope")
    if job and job.next_run_time:
        logger.info(f"Следующий запуск (UTC): {job.next_run_time}")
        logger.info(f"Следующий запуск (VLAT): {job.next_run_time.astimezone(ZoneInfo('Asia/Vladivostok'))}")
    else:
        logger.warning("Не удалось получить информацию о задаче планировщика")

    return scheduler
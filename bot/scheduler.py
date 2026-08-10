from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from bot.services.gemini import GeminiService
from bot.db import get_all_subscribed_users, get_user_data, save_message_to_archive, get_user_language
from bot.utils.helpers import get_text
from aiogram import Bot
import asyncio
import logging
import pytz

logger = logging.getLogger(__name__)


async def send_daily_horoscopes(bot: Bot):
    """
    Проверяет всех подписчиков и отправляет гороскоп тем,
    у кого сейчас 8:00 по их часовому поясу.
    """
    logger.info("📨 Запуск проверки часовых поясов для рассылки...")
    subscribers = await get_all_subscribed_users()
    if not subscribers:
        logger.info("📭 Нет активных подписчиков")
        return

    now_utc = datetime.now(timezone.utc)
    sent = 0
    errors = 0
    skipped_not_8 = 0
    gemini = GeminiService()

    for user in subscribers:
        tz_offset = user.timezone_offset  # int (1..12)
        # Локальное время пользователя
        user_now = now_utc + timedelta(hours=tz_offset)
        # Проверяем, что сейчас 8:00 (ровно)
        if user_now.hour == 8 and user_now.minute == 0:
            try:
                user_id = user.telegram_id
                user_data = await get_user_data(user_id)
                if not user_data or not user_data.get('name'):
                    logger.warning(f"⚠️ Нет данных для пользователя {user_id}")
                    continue

                # Определяем язык пользователя
                lang = await get_user_language(user_id)

                # Определяем правильную дату для пользователя (сегодня по его времени)
                today = user_now.strftime("%d.%m.%Y")

                # Генерируем гороскоп
                horoscope = gemini.generate_horoscope(user_data, today, lang)

                # Сохраняем в архив
                await save_message_to_archive(user_id, 'horoscope', horoscope)

                # Получаем локализованный шаблон и подставляем дату и гороскоп
                template = await get_text(user_id, 'horoscope_result')
                text = template.format(date=today, horoscope=horoscope)

                # Отправляем
                await bot.send_message(user_id, text)
                sent += 1
                logger.info(f"✅ Отправлен гороскоп пользователю {user_id} (UTC+{tz_offset})")
                await asyncio.sleep(0.5)  # небольшая задержка
            except Exception as e:
                errors += 1
                logger.error(f"❌ Ошибка отправки пользователю {user.telegram_id}: {e}")
        else:
            skipped_not_8 += 1

    logger.info(f"📨 Рассылка завершена. Отправлено: {sent}, Ошибок: {errors}, Пропущено (не 8:00): {skipped_not_8}")


def setup_scheduler(bot: Bot):
    """
    Настройка планировщика – запуск каждый час в 0 минут.
    """
    scheduler = AsyncIOScheduler(timezone="UTC")

    scheduler.add_job(
        send_daily_horoscopes,
        CronTrigger(minute=0),  # каждый час
        args=[bot],
        id="daily_horoscope",
        replace_existing=True
    )

    scheduler.start()
    logger.info("⏰ Планировщик запущен! Проверка будет выполняться каждый час.")

    job = scheduler.get_job("daily_horoscope")
    if job and job.next_run_time:
        logger.info(f"Следующий запуск (UTC): {job.next_run_time}")

    return scheduler
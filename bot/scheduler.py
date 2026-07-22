import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot

from bot.services.gemini import GeminiService
from bot.db import get_all_subscribed_users, get_user_data, save_message_to_archive

logger = logging.getLogger(__name__)

# Создаем экземпляр Gemini
gemini_service = GeminiService()


async def send_daily_horoscopes(bot: Bot):
    """
    Отправка ежедневных гороскопов всем подписчикам
    """
    logger.info("📨 Запуск ежедневной рассылки гороскопов...")

    # Получаем всех подписчиков
    subscribers = await get_all_subscribed_users()

    if not subscribers:
        logger.info("📭 Нет активных подписчиков")
        return

    today = datetime.now().strftime("%d.%m.%Y")
    sent_count = 0
    error_count = 0

    for user in subscribers:
        try:
            user_id = user.telegram_id

            # Получаем данные пользователя
            user_data = await get_user_data(user_id)

            if not user_data or not user_data.get('name'):
                logger.warning(f"⚠️ У пользователя {user_id} нет данных для гороскопа")
                continue

            # Генерируем гороскоп
            horoscope = gemini_service.generate_horoscope(user_data, today)

            # Сохраняем в архив
            await save_message_to_archive(user_id, 'horoscope', horoscope)

            # Отправляем сообщение
            await bot.send_message(
                user_id,
                f"🔮 Ваш ежедневный гороскоп на {today}\n\n{horoscope}",
                reply_markup=None
            )

            sent_count += 1
            logger.info(f"✅ Гороскоп отправлен пользователю {user_id}")

            # Небольшая задержка, чтобы не перегружать API
            await asyncio.sleep(0.5)

        except Exception as e:
            error_count += 1
            logger.error(f"❌ Ошибка отправки пользователю {user_id}: {e}")

    logger.info(f"📨 Рассылка завершена. Отправлено: {sent_count}, Ошибок: {error_count}")


def setup_scheduler(bot: Bot):
    """
    Настройка планировщика
    """
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

    # Добавляем задачу на 8:00 каждый день
    scheduler.add_job(
        send_daily_horoscopes,
        CronTrigger(hour=8, minute=0),
        args=[bot],
        id="daily_horoscope",
        replace_existing=True
    )

    scheduler.start()
    logger.info("⏰ Планировщик запущен! Рассылка будет выполняться каждый день в 8:00")

    return scheduler
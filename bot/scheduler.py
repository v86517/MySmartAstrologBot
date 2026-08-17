#bot\scheduler.py
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from bot.services.gemini import GeminiService
from bot.db import get_all_subscribed_users, get_user_data, save_message_to_archive, get_user_language
from bot.utils.helpers import get_text
from aiogram import Bot
import asyncio
import logging

logger = logging.getLogger(__name__)


async def send_long_message_direct(bot: Bot, chat_id: int, text: str, max_length: int = 4096, reply_markup=None):
    """
    Отправляет длинное сообщение напрямую (без объекта Message), разбивая на части.
    """
    if not text or not text.strip():
        logger.warning("⚠️ Попытка отправить пустое сообщение")
        return

    if len(text) <= max_length:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
        return

    # Разбиваем по строкам
    lines = text.split('\n')
    parts = []
    current_part = ""

    for line in lines:
        if len(line) > max_length:
            if current_part:
                parts.append(current_part)
                current_part = ""
            for i in range(0, len(line), max_length):
                chunk = line[i:i+max_length]
                parts.append(chunk)
            continue

        if len(current_part) + len(line) + 1 > max_length:
            parts.append(current_part)
            current_part = line
        else:
            if current_part:
                current_part += '\n' + line
            else:
                current_part = line

    if current_part:
        parts.append(current_part)

    # Финальная проверка (если какая-то часть всё ещё длиннее)
    final_parts = []
    for p in parts:
        if len(p) > max_length:
            for i in range(0, len(p), max_length):
                final_parts.append(p[i:i+max_length])
        else:
            final_parts.append(p)

    if not final_parts:
        logger.error("❌ Не удалось разбить сообщение")
        return

    total = len(final_parts)
    logger.info(f"📨 Отправка длинного сообщения: {len(text)} символов, разбито на {total} частей")

    for i, part in enumerate(final_parts, 1):
        try:
            if i == total and reply_markup is not None:
                await bot.send_message(chat_id, part, reply_markup=reply_markup)
            else:
                await bot.send_message(chat_id, part)
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"❌ Ошибка при отправке части {i}/{total}: {e}")
            try:
                short_part = part[:max_length]
                if i == total and reply_markup is not None:
                    await bot.send_message(chat_id, f"📄 Продолжение ({i}/{total}):\n\n{short_part}", reply_markup=reply_markup)
                else:
                    await bot.send_message(chat_id, f"📄 Продолжение ({i}/{total}):\n\n{short_part}")
            except:
                logger.error(f"❌ Критическая ошибка отправки части {i}/{total}, часть пропущена")


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
        user_now = now_utc + timedelta(hours=tz_offset)
        if user_now.hour == 8 and user_now.minute == 0:
            try:
                user_id = user.telegram_id
                user_data = await get_user_data(user_id)
                if not user_data or not user_data.get('name'):
                    logger.warning(f"⚠️ Нет данных для пользователя {user_id}")
                    continue

                lang = await get_user_language(user_id)
                today = user_now.strftime("%d.%m.%Y")
                horoscope = gemini.generate_horoscope(user_data, today, lang)
                await save_message_to_archive(user_id, 'horoscope', horoscope)

                template = await get_text(user_id, 'horoscope_result')
                text = template.format(date=today, horoscope=horoscope)

                # Используем функцию с разбиением
                await send_long_message_direct(bot, user_id, text)

                sent += 1
                logger.info(f"✅ Отправлен гороскоп пользователю {user_id} (UTC+{tz_offset})")
                await asyncio.sleep(0.5)
            except Exception as e:
                errors += 1
                logger.error(f"❌ Ошибка отправки пользователю {user.telegram_id}: {e}")
        else:
            skipped_not_8 += 1

    logger.info(f"📨 Рассылка завершена. Отправлено: {sent}, Ошибок: {errors}, Пропущено (не 8:00): {skipped_not_8}")


def setup_scheduler(bot: Bot):
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        send_daily_horoscopes,
        CronTrigger(minute=0),
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
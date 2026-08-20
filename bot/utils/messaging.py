#bot\utils\messaging.py
import asyncio
import logging
from aiogram.types import Message

logger = logging.getLogger(__name__)


async def send_long_message(
    message: Message,
    text: str,
    max_length: int = 4096,
    reply_markup=None
):
    """
    Отправляет длинное сообщение, разбивая его на части не длиннее max_length.
    """
    if not text or not text.strip():
        await message.answer("⚠️ Сообщение пустое. Попробуйте позже.")
        return

    if len(text) <= max_length:
        await message.answer(text, reply_markup=reply_markup)
        logger.info(f"📨 Сообщение отправлено целиком (длина {len(text)})")
        return

    # Разбиваем по строкам для сохранения целостности
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

    final_parts = []
    for p in parts:
        if len(p) > max_length:
            for i in range(0, len(p), max_length):
                final_parts.append(p[i:i+max_length])
        else:
            final_parts.append(p)

    if not final_parts:
        await message.answer("⚠️ Не удалось разбить сообщение.")
        return

    total = len(final_parts)
    logger.info(f"📨 Отправка длинного сообщения: {len(text)} символов, разбито на {total} частей")

    for i, part in enumerate(final_parts, 1):
        if len(part) > max_length:
            part = part[:max_length]
        try:
            if i == total and reply_markup is not None:
                await message.answer(part, reply_markup=reply_markup)
                logger.info(f"   ✅ Часть {i}/{total} (последняя) отправлена, длина {len(part)}")
            else:
                await message.answer(part)
                logger.info(f"   ✅ Часть {i}/{total} отправлена, длина {len(part)}")
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"❌ Ошибка при отправке части {i}/{total}: {e}")
            try:
                short_part = part[:max_length]
                if i == total and reply_markup is not None:
                    await message.answer(f"📄 Продолжение ({i}/{total}):\n\n{short_part}", reply_markup=reply_markup)
                else:
                    await message.answer(f"📄 Продолжение ({i}/{total}):\n\n{short_part}")
            except:
                logger.error(f"❌ Критическая ошибка отправки части {i}/{total}, часть пропущена")
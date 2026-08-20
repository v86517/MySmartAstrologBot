#main.py
import asyncio
import logging
import os
from dotenv import load_dotenv

# ==================== НАСТРОЙКА DJANGO ДО ИМПОРТА МОДЕЛЕЙ ====================
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django
django.setup()
# ========================================================================

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.services.gemini import GeminiService
from bot.calculators.astrology_calculator import AstrologyCalculator
from bot.scheduler import setup_scheduler

from bot.handlers import (
    start_router,
    horoscope_router,
    compatibility_router,
    numerology_router,
    astrology_router,
    profile_router,
    subscription_router,
    archive_router,
    expert_router,
    common_router,
)

from bot.handlers.horoscope import set_gemini_service as set_horoscope_gemini
from bot.handlers.compatibility import set_gemini_service as set_compatibility_gemini
from bot.handlers.numerology import set_gemini_service as set_numerology_gemini
from bot.handlers.astrology import set_gemini_service as set_astrology_gemini

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в .env файле!")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Инициализация Gemini
gemini_service = None
try:
    gemini_service = GeminiService()
    logger.info("✅ Gemini API успешно инициализирован!")
    AstrologyCalculator.gemini_service = gemini_service
except Exception as e:
    logger.error(f"❌ Ошибка инициализации Gemini: {e}")

if gemini_service:
    set_horoscope_gemini(gemini_service)
    set_compatibility_gemini(gemini_service)
    set_numerology_gemini(gemini_service)
    set_astrology_gemini(gemini_service)

dp.include_router(start_router)
dp.include_router(horoscope_router)
dp.include_router(compatibility_router)
dp.include_router(numerology_router)
dp.include_router(astrology_router)
dp.include_router(profile_router)
dp.include_router(subscription_router)
dp.include_router(archive_router)
dp.include_router(expert_router)
dp.include_router(common_router)

async def main():
    logger.info("🚀 Запуск бота MySmartAstrologBot...")
    bot_info = await bot.get_me()
    logger.info(f"🤖 Бот @{bot_info.username} готов к работе!")
    if gemini_service:
        logger.info("✅ Gemini API готов к работе!")
    else:
        logger.warning("⚠️ Gemini API НЕ ДОСТУПЕН! Проверьте API ключ в .env")
    scheduler = setup_scheduler(bot)
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
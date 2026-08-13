import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, FSInputFile, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# Импорты из наших модулей
from bot.utils.helpers import get_text

from bot.keyboards.keyboards import (
    get_main_menu,
    get_zodiac_keyboard,
    get_cancel_keyboard,
    get_compatibility_keyboard,
    get_confirm_keyboard,
    get_continue_keyboard,
    get_zodiac_keyboard_person2,
    get_expert_keyboard,
    get_subscription_keyboard,
    get_subscription_active_keyboard,
    get_archive_keyboard,
    get_payment_url_keyboard,
    get_profile_keyboard,
    get_skip_keyboard,
    get_numerology_payment_keyboard,
    get_numerology_confirm_keyboard,
    get_numerology_use_data_keyboard,
    get_astrology_payment_keyboard,
    get_astrology_confirm_keyboard,
    get_astrology_use_data_keyboard,
    get_timezone_keyboard,
    get_subscription_promo_keyboard,
    get_save_data_keyboard,
    get_after_save_keyboard,
    get_subscription_payment_keyboard, get_fill_profile_keyboard,
    get_support_keyboard, get_horoscope_confirm_keyboard,
    get_language_keyboard,
    get_main_menu_button, get_compatibility_confirm_keyboard,
)
from bot.states.states import UserDataStates, CompatibilityStates, NumerologyStates, AstrologyStates, HoroscopeStates
from bot.utils.zodiac import calculate_zodiac_sign, get_zodiac_emoji, get_zodiac_sign_localized
from bot.services.gemini import GeminiService

from bot.db import (
    get_or_create_user,
    save_user_data,
    get_user_data,
    check_subscription_db,
    activate_subscription_db,
    can_use_feature_db,
    mark_feature_used_db,
    save_message_to_archive,
    get_user_archive,
    get_archive_message,
    get_user_language,
)
from bot.scheduler import setup_scheduler, send_daily_horoscopes
from asgiref.sync import sync_to_async
from core.models import User
from bot.yookassa_client import yookassa
from bot.db import save_payment_db, activate_subscription_db, add_numerology_count, add_astrology_count
from bot.calculators.astrology_calculator import AstrologyCalculator
from bot.calculators.base_calculator import BaseCalculator
from bot.calculators.natal_calculator import NatalCalculator
from bot.calculators.transit_horoscope_calculator import TransitHoroscopeCalculator
from bot.calculators.compatibility_calculator import CompatibilityCalculator
from datetime import datetime
from bot.locales import TEXTS

MESSAGE_TYPES_DISPLAY = {
    'horoscope': '🔮 Гороскоп',
    'compatibility': '💕 Совместимость',
    'natal_chart': '🌌 Натальная карта',
}

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Токен бота
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в .env файле!")

# Создаем бота и диспетчер
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Инициализация Gemini
try:
    gemini_service = GeminiService()
    logger.info("✅ Gemini API успешно инициализирован!")
    AstrologyCalculator.gemini_service = gemini_service
except Exception as e:
    logger.error(f"❌ Ошибка инициализации Gemini: {e}")
    gemini_service = None

numerology_data = {}
astrology_data = {}


def format_parameters(prompt_data: dict, service_type: str, lang: str = 'ru') -> str:
    """Форматирует параметры для отображения пользователю."""
    from bot.locales import TEXTS
    texts = TEXTS.get(lang, TEXTS['ru'])
    lines = []

    if service_type == 'horoscope':
        lines.append("📅 Гороскоп на день")
        lines.append("")
        lines.append(f"👤 Имя: {prompt_data.get('name', '')}")
        lines.append(f"⚥ Пол: {prompt_data.get('gender_display', '')}")
        lines.append(f"📅 Дата рождения: {prompt_data.get('birth_date', '')}")
        lines.append(f"🕒 Время рождения: {prompt_data.get('birth_time', '')}")
        lines.append(f"📍 Место рождения: {prompt_data.get('birth_place', '')}")
        lines.append("")
        lines.append(f"☀️ Солнце: {prompt_data.get('sun_sign', '')}")
        lines.append(f"🌙 Луна: {prompt_data.get('moon_sign', '')}")
        lines.append(f"⬆️ Асцендент: {prompt_data.get('ascendant', '')}")
        lines.append("")
        lines.append(f"📅 Дата: {prompt_data.get('target_date', '')}")
        lines.append(f"📆 День недели: {prompt_data.get('target_weekday', '')}")
        lines.append(f"🌙 Лунный день: {prompt_data.get('lunar_day', '')}")
        lines.append(f"☀️ Освещённость Луны: {prompt_data.get('moon_illumination', '')}%")
        lines.append(f"🌙 Транзитная Луна в знаке: {prompt_data.get('transit_moon_sign', '')}")
        lines.append(f"🏠 Транзитная Луна в доме: {prompt_data.get('transit_moon_house', '')}")
        lines.append(f"🔮 Аспекты транзитной Луны:\n{prompt_data.get('transit_moon_aspects', '')}")
        lines.append(f"🔄 Ретроградные планеты: {prompt_data.get('retrograde_planets', '')}")
        # Логирование для отладки
        logger.info(f"planets_list в format_parameters: {prompt_data.get('planets_list')}")
        logger.info(f"aspects_list в format_parameters: {prompt_data.get('aspects_list')}")
        logger.info(f"transit_aspects в format_parameters: {prompt_data.get('transit_aspects')}")
        # Натальные планеты, аспекты и транзитные аспекты (только для разрешённых пользователей)
        if prompt_data.get('planets_list'):
            lines.append("")
            lines.append("🪐 Натальные планеты в знаках и домах:")
            lines.append(prompt_data.get('planets_list', ''))

        if prompt_data.get('aspects_list'):
            lines.append("")
            lines.append("🔮 Натальные аспекты:")
            lines.append(prompt_data.get('aspects_list', ''))

        if prompt_data.get('transit_aspects'):
            lines.append("")
            lines.append("🌟 Транзитные аспекты на сегодня:")
            lines.append(prompt_data.get('transit_aspects', ''))
        if prompt_data.get('cusps_list'):
            lines.append("")
            lines.append("🏠 Куспиды домов:")
            lines.append(prompt_data.get('cusps_list', ''))

    elif service_type == 'numerology':
        lines.append("🔢 Нумерологический разбор")
        lines.append("")
        lines.append(f"👤 Имя: {prompt_data.get('name', '')}")
        lines.append(f"⚥ Пол: {prompt_data.get('gender_display', '')}")
        lines.append(f"📅 Дата рождения: {prompt_data.get('birth_date', '')}")
        lines.append(f"🕒 Время рождения: {prompt_data.get('birth_time', '')}")
        lines.append(f"📍 Место рождения: {prompt_data.get('birth_place', '')}")
        lines.append("")
        lines.append(f"🔢 Число жизненного пути: {prompt_data.get('life_path', '')}")
        lines.append(f"🔢 Число экспрессии: {prompt_data.get('expression_number', '')}")
        lines.append(f"🔢 Число души: {prompt_data.get('soul_urge_number', '')}")
        lines.append(f"🔢 Число личности: {prompt_data.get('personality_number', '')}")
        lines.append(f"📅 Личный год: {prompt_data.get('personal_year', '')}")
        lines.append(f"📅 Личный месяц: {prompt_data.get('personal_month', '')}")
        lines.append(f"📅 Личный день: {prompt_data.get('personal_day', '')}")
        lines.append("")
        lines.append("🧩 Матрица судьбы (22 аркана):")
        lines.append(f"  Аркан дня (m1): {prompt_data.get('m1', '')}")
        lines.append(f"  Аркан месяца (m2): {prompt_data.get('m2', '')}")
        lines.append(f"  Аркан года (m3): {prompt_data.get('m3', '')}")
        lines.append(f"  Отношения (ОПВ): {prompt_data.get('opv', '')}")
        lines.append(f"  Судьба (СЗ): {prompt_data.get('sz', '')}")
        lines.append(f"  Препятствие: {prompt_data.get('obstacle', '')}")
        lines.append(f"  Человек-предатель: {prompt_data.get('traitor', '')}")
        lines.append(f"  Зона комфорта: {prompt_data.get('comfort', '')}")
        lines.append(f"  Левая родовая: {prompt_data.get('v_left', '')}")
        lines.append(f"  Правая родовая: {prompt_data.get('v_right', '')}")
        lines.append(f"  Кармическая (нижняя левая): {prompt_data.get('v_bottom_left', '')}")
        lines.append(f"  Кармическая (нижняя правая): {prompt_data.get('v_bottom_right', '')}")
        lines.append(f"  Багаж опыта: {prompt_data.get('v_left_side', '')}")
        lines.append(f"  Человек-предатель (правый бок): {prompt_data.get('v_right_side', '')}")
        lines.append(f"  Внутренний паспорт: {prompt_data.get('v_top', '')}")

    elif service_type == 'compatibility':
        #lines.append("💕 Анализ совместимости")
        lines.append("")
        lines.append(f"👤 Человек 1: {prompt_data.get('p1_name', '')}")
        lines.append(f"⚥ Пол: {prompt_data.get('p1_gender_text', '')}")
        lines.append(f"📅 Дата рождения: {prompt_data.get('p1_birth_date', '')}")
        lines.append(f"🕒 Время рождения: {prompt_data.get('p1_birth_time', '')}")
        lines.append(f"📍 Место рождения: {prompt_data.get('p1_birth_place', '')}")
        lines.append(f"☀️ Солнце: {prompt_data.get('p1_sun_sign', '')}")
        lines.append(f"🌙 Луна: {prompt_data.get('p1_moon_sign', '')}")
        lines.append(f"⬆️ Асцендент: {prompt_data.get('p1_ascendant', '')}")
        if prompt_data.get('p1_cusps_list'):
            lines.append("🏠 Куспиды домов:")
            lines.append(prompt_data.get('p1_cusps_list', ''))
        lines.append("")
        lines.append(f"👤 Человек 2: {prompt_data.get('p2_name', '')}")
        lines.append(f"⚥ Пол: {prompt_data.get('p2_gender_text', '')}")
        lines.append(f"📅 Дата рождения: {prompt_data.get('p2_birth_date', '')}")
        lines.append(f"🕒 Время рождения: {prompt_data.get('p2_birth_time', '')}")
        lines.append(f"📍 Место рождения: {prompt_data.get('p2_birth_place', '')}")
        lines.append(f"☀️ Солнце: {prompt_data.get('p2_sun_sign', '')}")
        lines.append(f"🌙 Луна: {prompt_data.get('p2_moon_sign', '')}")
        lines.append(f"⬆️ Асцендент: {prompt_data.get('p2_ascendant', '')}")
        if prompt_data.get('p2_cusps_list'):
            lines.append("🏠 Куспиды домов:")
            lines.append(prompt_data.get('p2_cusps_list', ''))
        lines.append("")
        lines.append(f"🔮 Синастрические аспекты:\n{prompt_data.get('aspects_synastry_list', '')}")
        lines.append(f"📅 Дата: {prompt_data.get('target_date', '')}")
        lines.append(f"📆 День недели: {prompt_data.get('target_weekday', '')}")
        lines.append(f"🌙 Лунный день: {prompt_data.get('lunar_day', '')}")
        lines.append(f"☀️ Освещённость Луны: {prompt_data.get('moon_illumination', '')}%")

    elif service_type == 'astrology':
        pass

    return "\n".join(lines)


def format_basic_horoscope_parameters(prompt_data: dict, lang: str = 'ru') -> str:
    """Форматирует базовые параметры гороскопа для обычных пользователей."""
    from bot.locales import TEXTS
    texts = TEXTS.get(lang, TEXTS['ru'])

    lines = []
    lines.append("📅 Гороскоп на день")
    lines.append("")
    lines.append(f"{texts.get('horoscope_basic_name', '👤 Имя')}: {prompt_data.get('name', '')}")
    lines.append(f"{texts.get('horoscope_basic_gender', '⚥ Пол')}: {prompt_data.get('gender_display', '')}")
    lines.append(f"{texts.get('horoscope_basic_birth_date', '📅 Дата рождения')}: {prompt_data.get('birth_date', '')}")
    lines.append(f"{texts.get('horoscope_basic_birth_time', '🕒 Время рождения')}: {prompt_data.get('birth_time', '')}")
    lines.append(
        f"{texts.get('horoscope_basic_birth_place', '📍 Место рождения')}: {prompt_data.get('birth_place', '')}")
    lines.append("")
    lines.append(f"{texts.get('horoscope_basic_sun', '☀️ Солнце')}: {prompt_data.get('sun_sign', '')}")
    lines.append(f"{texts.get('horoscope_basic_moon', '🌙 Луна')}: {prompt_data.get('moon_sign', '')}")
    lines.append(f"{texts.get('horoscope_basic_ascendant', '⬆️ Асцендент')}: {prompt_data.get('ascendant', '')}")
    lines.append("")
    lines.append(f"{texts.get('horoscope_basic_target_date', '📅 Дата')}: {prompt_data.get('target_date', '')}")
    lines.append(
        f"{texts.get('horoscope_basic_target_weekday', '📆 День недели')}: {prompt_data.get('target_weekday', '')}")
    lines.append(f"{texts.get('horoscope_basic_lunar_day', '🌙 Лунный день')}: {prompt_data.get('lunar_day', '')}")
    lines.append(
        f"{texts.get('horoscope_basic_moon_illumination', '☀️ Освещённость Луны')}: {prompt_data.get('moon_illumination', '')}%")
    lines.append(
        f"{texts.get('horoscope_basic_transit_moon_sign', '🌙 Транзитная Луна в знаке')}: {prompt_data.get('transit_moon_sign', '')}")
    lines.append(
        f"{texts.get('horoscope_basic_transit_moon_house', '🏠 Транзитная Луна в доме')}: {prompt_data.get('transit_moon_house', '')}")
    lines.append(
        f"{texts.get('horoscope_basic_retrograde', '🔄 Ретроградные планеты')}: {prompt_data.get('retrograde_planets', '')}")

    return "\n".join(lines)


def format_profile_data(data: dict, lang: str) -> str:
    """Форматирует данные пользователя для отображения с учётом языка"""
    gender_display = 'Мужской' if data.get('gender') == 'M' else 'Женский' if data.get('gender') == 'F' else 'Не указан'
    zodiac_emoji = get_zodiac_emoji(data.get('zodiac', 'Неизвестно'))
    zodiac_name = get_zodiac_sign_localized(data.get('zodiac', 'Неизвестно'), lang)
    timezone = data.get('timezone_offset', 3)
    return (
        f"👤 Имя: {data.get('name', 'Не указано')}\n"
        f"📅 Дата рождения: {data.get('birth_date', 'Не указана')}\n"
        f"🕒 Время рождения: {data.get('birth_time', 'Не указано')}\n"
        f"📍 Место рождения: {data.get('birth_place', 'Не указано')}\n"
        f"👤 Пол: {gender_display}\n"
        f"{zodiac_emoji} Знак зодиака: {zodiac_name}\n"
        f"🕒 Часовой пояс: UTC+{timezone}"
    )

# ==================== КОМАНДЫ ====================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name

    user, created = await get_or_create_user(user_id, username, first_name, last_name)
    if created:
        logger.info(f"✅ Новый пользователь: {user_id} (@{username})")

    welcome_text = await get_text(user_id, 'welcome')
    photo_path = "images/welcome.png"
    lang = await get_user_language(user_id)

    await message.answer_photo(
        photo=FSInputFile(photo_path),
        caption=welcome_text,
        reply_markup=get_main_menu(lang),
        parse_mode="HTML"
    )


@dp.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    main_menu_text = await get_text(user_id, 'main_menu_text')
    await message.answer(main_menu_text, reply_markup=get_main_menu(lang))


@dp.message(Command("test_send"))
async def test_send(message: Message):
    ADMIN_ID = 5484157606
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    await message.answer("⏳ Начинаю тестовую рассылку...")
    await send_daily_horoscopes(bot)


@dp.message(F.text == "🌐 En/Ru")
async def change_language(message: Message):
    user_id = message.from_user.id
    text = await get_text(user_id, 'choose_language')
    await message.answer(text, reply_markup=get_language_keyboard())


# ==================== ВСЕ ХЕНДЛЕРЫ СОСТОЯНИЙ (FSM) ====================

# ---- UserDataStates ----
@dp.message(UserDataStates.WAITING_NAME)
async def process_name(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    state_data = await state.get_data()
    is_edit = state_data.get('is_edit', False)
    new_data = state_data.get('new_data', {})
    old = state_data.get('old_data', {})

    logger.info(f"📝 Шаг ИМЯ, is_edit={is_edit}, new_data до: {new_data}")

    if is_edit:
        if message.text and message.text.strip():
            new_data['name'] = message.text.strip()
            logger.info(f"📝 Шаг ИМЯ, обновлено имя: {new_data['name']}")
        else:
            logger.info("📝 Шаг ИМЯ, имя не изменено")

        await state.update_data(new_data=new_data)
        await state.set_state(UserDataStates.WAITING_BIRTH_DATE)
        template = await get_text(user_id, 'skip_birth_date')
        prompt = template.format(date=old.get('birth_date', 'не указана'))
        await message.answer(prompt, reply_markup=get_skip_keyboard(lang))
        logger.info(f"📝 Шаг ИМЯ, new_data после: {new_data}")
    else:
        if len(message.text) < 2:
            await message.answer(await get_text(user_id, 'error_name_min'))
            return
        await state.update_data(name=message.text)
        await state.set_state(UserDataStates.WAITING_BIRTH_DATE)
        await message.answer(
            "📅 Шаг 2 из 5\n\nУкажите дату рождения в формате:\nДД.ММ.ГГГГ\n\nНапример: 15.03.1990"
        )


@dp.message(UserDataStates.WAITING_BIRTH_DATE)
async def process_birth_date(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    state_data = await state.get_data()
    is_edit = state_data.get('is_edit', False)
    new_data = state_data.get('new_data', {})
    old = state_data.get('old_data', {})

    logger.info(f"📝 Шаг ДАТА, is_edit={is_edit}, new_data до: {new_data}")

    if is_edit:
        if message.text and re.match(r'^\d{2}\.\d{2}\.\d{4}$', message.text):
            try:
                birth_date = datetime.strptime(message.text, "%d.%m.%Y")
                zodiac = calculate_zodiac_sign(birth_date.day, birth_date.month)
                new_data['birth_date'] = message.text
                new_data['zodiac'] = zodiac
                logger.info(f"📝 Шаг ДАТА, обновлена дата: {new_data['birth_date']}, знак: {new_data['zodiac']}")
            except ValueError:
                await message.answer(await get_text(user_id, 'error_invalid_date'), reply_markup=get_cancel_keyboard(lang))
                return
        else:
            logger.info("📝 Шаг ДАТА, дата не изменена")

        await state.update_data(new_data=new_data)
        await state.set_state(UserDataStates.WAITING_BIRTH_TIME)
        template = await get_text(user_id, 'skip_birth_time')
        prompt = template.format(time=old.get('birth_time', 'не указано'))
        await message.answer(prompt, reply_markup=get_skip_keyboard(lang))
        logger.info(f"📝 Шаг ДАТА, new_data после: {new_data}")
    else:
        date_pattern = r'^\d{2}\.\d{2}\.\d{4}$'
        if not re.match(date_pattern, message.text):
            await message.answer(await get_text(user_id, 'error_invalid_date_format'), reply_markup=get_cancel_keyboard(lang))
            return
        try:
            birth_date = datetime.strptime(message.text, "%d.%m.%Y")
            zodiac = calculate_zodiac_sign(birth_date.day, birth_date.month)
            await state.update_data(birth_date=message.text, zodiac=zodiac)
            await state.set_state(UserDataStates.WAITING_BIRTH_TIME)
            zodiac_name = get_zodiac_sign_localized(zodiac, lang)
            await message.answer(
                f"✅ Отлично! Знак зодиака: {get_zodiac_emoji(zodiac)} {zodiac_name}\n\n"
                "🕒 Шаг 3 из 5\n\nУкажите точное время рождения в формате:\nЧЧ:ММ\n\n"
                "Например: 15:30\nЕсли не знаете, напишите 00:00",
                reply_markup=get_cancel_keyboard(lang)
            )
        except ValueError:
            await message.answer(await get_text(user_id, 'error_invalid_date'), reply_markup=get_cancel_keyboard(lang))


@dp.message(UserDataStates.WAITING_BIRTH_TIME)
async def process_birth_time(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    state_data = await state.get_data()
    is_edit = state_data.get('is_edit', False)
    new_data = state_data.get('new_data', {})
    old = state_data.get('old_data', {})

    logger.info(f"📝 Шаг ВРЕМЯ, is_edit={is_edit}, new_data до: {new_data}")

    if is_edit:
        if message.text and re.match(r'^\d{2}:\d{2}$', message.text):
            try:
                datetime.strptime(message.text, "%H:%M")
                new_data['birth_time'] = message.text
                logger.info(f"📝 Шаг ВРЕМЯ, обновлено время: {new_data['birth_time']}")
            except ValueError:
                await message.answer(await get_text(user_id, 'error_invalid_time'))
                return
        else:
            logger.info("📝 Шаг ВРЕМЯ, время не изменено")

        await state.update_data(new_data=new_data)
        await state.set_state(UserDataStates.WAITING_BIRTH_PLACE)
        template = await get_text(user_id, 'skip_birth_place')
        prompt = template.format(place=old.get('birth_place', 'не указано'))
        await message.answer(prompt, reply_markup=get_skip_keyboard(lang))
        logger.info(f"📝 Шаг ВРЕМЯ, new_data после: {new_data}")
    else:
        time_pattern = r'^\d{2}:\d{2}$'
        if not re.match(time_pattern, message.text):
            await message.answer(await get_text(user_id, 'error_invalid_time_format'), reply_markup=get_cancel_keyboard(lang))
            return
        try:
            datetime.strptime(message.text, "%H:%M")
            await state.update_data(birth_time=message.text)
            await state.set_state(UserDataStates.WAITING_BIRTH_PLACE)
            await message.answer(
                "📍 Шаг 4 из 5\n\nУкажите место рождения:\nГород, Страна\n\nНапример: Москва, Россия",
                reply_markup=get_cancel_keyboard(lang)
            )
        except ValueError:
            await message.answer(await get_text(user_id, 'error_invalid_time'), reply_markup=get_cancel_keyboard(lang))


@dp.message(UserDataStates.WAITING_BIRTH_PLACE)
async def process_birth_place(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    state_data = await state.get_data()
    is_edit = state_data.get('is_edit', False)
    new_data = state_data.get('new_data', {})
    old = state_data.get('old_data', {})

    logger.info(f"📝 Шаг МЕСТО, is_edit={is_edit}, new_data до: {new_data}")

    if is_edit:
        if message.text and len(message.text.strip()) >= 3:
            new_data['birth_place'] = message.text.strip()
            logger.info(f"📝 Шаг МЕСТО, обновлено место: {new_data['birth_place']}")
        else:
            logger.info("📝 Шаг МЕСТО, место не изменено")

        await state.update_data(new_data=new_data)
        await state.set_state(UserDataStates.WAITING_GENDER)

        current_gender = old.get('gender')
        if current_gender == 'M':
            gender_display = 'Мужской'
        elif current_gender == 'F':
            gender_display = 'Женский'
        else:
            gender_display = 'не указан'

        template = await get_text(user_id, 'skip_gender')
        prompt = template.format(gender=gender_display)
        await message.answer(prompt, reply_markup=get_skip_keyboard(lang))
        logger.info(f"📝 Шаг МЕСТО, new_data после: {new_data}")
    else:
        if len(message.text) < 3:
            await message.answer(await get_text(user_id, 'error_invalid_place'), reply_markup=get_cancel_keyboard(lang))
            return
        await state.update_data(birth_place=message.text)
        await state.set_state(UserDataStates.WAITING_GENDER)
        await message.answer(
            "👤 Шаг 5 из 5 (последний!)\n\nУкажите ваш пол:\nМ - мужской\nЖ - женский\n\nНапишите: М или Ж",
            reply_markup=get_cancel_keyboard(lang)
        )


@dp.message(UserDataStates.WAITING_GENDER)
async def process_gender(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    gender = message.text.upper()
    state_data = await state.get_data()
    is_edit = state_data.get('is_edit', False)
    new_data = state_data.get('new_data', {})

    logger.info(f"📝 Шаг ПОЛ, is_edit={is_edit}, new_data до: {new_data}")

    if is_edit:
        if gender in ["М", "Ж"]:
            new_data['gender'] = 'M' if gender == 'М' else 'F'
            logger.info(f"📝 Шаг ПОЛ, обновлён пол: {new_data['gender']}")
        else:
            logger.info("📝 Шаг ПОЛ, пол не изменён")

        await state.update_data(new_data=new_data)
        await state.set_state(UserDataStates.WAITING_TIMEZONE)
        await message.answer(await get_text(user_id, 'choose_timezone'), reply_markup=get_timezone_keyboard(lang))
        return

    if gender not in ["М", "Ж"]:
        await message.answer(await get_text(user_id, 'error_gender_only'), reply_markup=get_cancel_keyboard(lang))
        return

    db_gender = 'M' if gender == 'М' else 'F'
    data = await state.get_data()
    data['gender'] = db_gender
    await state.update_data(temp_data=data)

    await state.set_state(UserDataStates.WAITING_TIMEZONE)
    await message.answer(
        "🕒 Выберите ваш часовой пояс:\nЭто нужно для точного расчёта гороскопа и отправки прогнозов.",
        reply_markup=get_timezone_keyboard(lang)
    )


# ---- CompatibilityStates ----
@dp.message(CompatibilityStates.WAITING_PERSON1_NAME)
async def process_person1_name(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    if len(message.text) < 2:
        await message.answer(await get_text(user_id, 'error_name_short'))
        return

    await state.update_data(person1_name=message.text)
    await state.set_state(CompatibilityStates.WAITING_PERSON1_BIRTH_DATE)

    template = await get_text(user_id, 'compatibility_person1_name')
    await message.answer(
        template.format(name=message.text),
        reply_markup=get_cancel_keyboard(lang)
    )


@dp.message(CompatibilityStates.WAITING_PERSON1_BIRTH_DATE)
async def process_person1_birth_date(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    date_pattern = r'^\d{2}\.\d{2}\.\d{4}$'

    if not re.match(date_pattern, message.text):
        await message.answer(
            await get_text(user_id, 'error_invalid_date_format'),
            reply_markup=get_cancel_keyboard(lang)
        )
        return

    try:
        birth_date = datetime.strptime(message.text, "%d.%m.%Y")
        zodiac = calculate_zodiac_sign(birth_date.day, birth_date.month)
        zodiac_name = get_zodiac_sign_localized(zodiac, lang)

        await state.update_data(
            person1_birth_date=message.text,
            person1_zodiac=zodiac
        )
        await state.set_state(CompatibilityStates.WAITING_PERSON1_BIRTH_TIME)

        template = await get_text(user_id, 'compatibility_person1_birth_date')
        await message.answer(
            template.format(
                emoji=get_zodiac_emoji(zodiac),
                zodiac=zodiac_name
            ),
            reply_markup=get_cancel_keyboard(lang)
        )

    except ValueError:
        await message.answer(
            await get_text(user_id, 'error_invalid_date'),
            reply_markup=get_cancel_keyboard(lang)
        )


@dp.message(CompatibilityStates.WAITING_PERSON1_BIRTH_TIME)
async def process_person1_birth_time(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    time_pattern = r'^\d{2}:\d{2}$'

    if not re.match(time_pattern, message.text):
        await message.answer(
            await get_text(user_id, 'error_invalid_time_format'),
            reply_markup=get_cancel_keyboard(lang)
        )
        return

    try:
        datetime.strptime(message.text, "%H:%M")
        await state.update_data(person1_birth_time=message.text)
        await state.set_state(CompatibilityStates.WAITING_PERSON1_BIRTH_PLACE)

        await message.answer(
            await get_text(user_id, 'compatibility_person1_birth_time'),
            reply_markup=get_cancel_keyboard(lang)
        )

    except ValueError:
        await message.answer(
            await get_text(user_id, 'error_invalid_time'),
            reply_markup=get_cancel_keyboard(lang)
        )


@dp.message(CompatibilityStates.WAITING_PERSON1_BIRTH_PLACE)
async def process_person1_birth_place(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    if len(message.text) < 3:
        await message.answer(
            await get_text(user_id, 'error_invalid_place'),
            reply_markup=get_cancel_keyboard(lang)
        )
        return

    await state.update_data(person1_birth_place=message.text)
    await state.set_state(CompatibilityStates.WAITING_PERSON1_GENDER)

    await message.answer(
        await get_text(user_id, 'compatibility_person1_gender'),
        reply_markup=get_cancel_keyboard(lang)
    )


@dp.message(CompatibilityStates.WAITING_PERSON1_GENDER)
async def process_person1_gender(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    gender = message.text.upper()

    if gender not in ["М", "Ж"]:
        await message.answer(
            await get_text(user_id, 'error_invalid_gender'),
            reply_markup=get_cancel_keyboard(lang)
        )
        return

    db_gender = 'M' if gender == 'М' else 'F'

    data = await state.get_data()
    person1 = {
        'name': data.get('person1_name'),
        'birth_date': data.get('person1_birth_date'),
        'birth_time': data.get('person1_birth_time'),
        'birth_place': data.get('person1_birth_place'),
        'gender': db_gender,
        'zodiac': data.get('person1_zodiac')
    }

    await state.update_data(person1=person1)
    await state.set_state(CompatibilityStates.WAITING_PERSON2_NAME)

    gender_display = 'Мужской' if gender == 'М' else 'Женский'
    zodiac1_name = get_zodiac_sign_localized(person1['zodiac'], lang)
    template = await get_text(user_id, 'compatibility_person1_complete')
    await message.answer(
        template.format(
            name=person1['name'],
            birth_date=person1['birth_date'],
            birth_time=person1['birth_time'],
            birth_place=person1['birth_place'],
            gender=gender_display,
            emoji=get_zodiac_emoji(person1['zodiac']),
            zodiac=zodiac1_name
        ),
        reply_markup=get_cancel_keyboard(lang)
    )


@dp.message(CompatibilityStates.WAITING_PERSON2_NAME)
async def process_person2_name(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    if len(message.text) < 2:
        await message.answer(await get_text(user_id, 'error_name_short'))
        return

    await state.update_data(person2_name=message.text)
    await state.set_state(CompatibilityStates.WAITING_PERSON2_BIRTH_DATE)

    template = await get_text(user_id, 'compatibility_person2_name')
    await message.answer(
        template.format(name=message.text),
        reply_markup=get_cancel_keyboard(lang)
    )


@dp.message(CompatibilityStates.WAITING_PERSON2_BIRTH_DATE)
async def process_person2_birth_date(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    date_pattern = r'^\d{2}\.\d{2}\.\d{4}$'

    if not re.match(date_pattern, message.text):
        await message.answer(
            await get_text(user_id, 'error_invalid_date_format'),
            reply_markup=get_cancel_keyboard(lang)
        )
        return

    try:
        birth_date = datetime.strptime(message.text, "%d.%m.%Y")
        zodiac = calculate_zodiac_sign(birth_date.day, birth_date.month)
        zodiac_name = get_zodiac_sign_localized(zodiac, lang)

        await state.update_data(
            person2_birth_date=message.text,
            person2_zodiac=zodiac
        )
        await state.set_state(CompatibilityStates.WAITING_PERSON2_BIRTH_TIME)

        template = await get_text(user_id, 'compatibility_person2_birth_date')
        await message.answer(
            template.format(
                emoji=get_zodiac_emoji(zodiac),
                zodiac=zodiac_name
            ),
            reply_markup=get_cancel_keyboard(lang)
        )

    except ValueError:
        await message.answer(
            await get_text(user_id, 'error_invalid_date'),
            reply_markup=get_cancel_keyboard(lang)
        )


@dp.message(CompatibilityStates.WAITING_PERSON2_BIRTH_TIME)
async def process_person2_birth_time(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    time_pattern = r'^\d{2}:\d{2}$'

    if not re.match(time_pattern, message.text):
        await message.answer(
            await get_text(user_id, 'error_invalid_time_format'),
            reply_markup=get_cancel_keyboard(lang)
        )
        return

    try:
        datetime.strptime(message.text, "%H:%M")
        await state.update_data(person2_birth_time=message.text)
        await state.set_state(CompatibilityStates.WAITING_PERSON2_BIRTH_PLACE)

        await message.answer(
            await get_text(user_id, 'compatibility_person2_birth_time'),
            reply_markup=get_cancel_keyboard(lang)
        )

    except ValueError:
        await message.answer(
            await get_text(user_id, 'error_invalid_time'),
            reply_markup=get_cancel_keyboard(lang)
        )


@dp.message(CompatibilityStates.WAITING_PERSON2_BIRTH_PLACE)
async def process_person2_birth_place(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    if len(message.text) < 3:
        await message.answer(
            await get_text(user_id, 'error_invalid_place'),
            reply_markup=get_cancel_keyboard(lang)
        )
        return

    await state.update_data(person2_birth_place=message.text)
    await state.set_state(CompatibilityStates.WAITING_PERSON2_GENDER)

    await message.answer(
        await get_text(user_id, 'compatibility_person2_gender'),
        reply_markup=get_cancel_keyboard(lang)
    )


@dp.message(CompatibilityStates.WAITING_PERSON2_GENDER)
async def process_person2_gender(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    gender = message.text.upper()

    if gender not in ["М", "Ж"]:
        await message.answer(
            await get_text(user_id, 'error_invalid_gender'),
            reply_markup=get_cancel_keyboard(lang)
        )
        return

    db_gender = 'M' if gender == 'М' else 'F'

    data = await state.get_data()
    person2 = {
        'name': data.get('person2_name'),
        'birth_date': data.get('person2_birth_date'),
        'birth_time': data.get('person2_birth_time'),
        'birth_place': data.get('person2_birth_place'),
        'gender': db_gender,
        'zodiac': data.get('person2_zodiac')
    }

    person1 = data.get('person1', {})

    if not person1:
        await message.answer(
            await get_text(user_id, 'error_not_found'),
            reply_markup=get_main_menu(lang)
        )
        await state.clear()
        return

    # Сохраняем данные в состояние
    await state.update_data(person1=person1, person2=person2)
    await state.set_state(CompatibilityStates.CONFIRM_BOTH)

    # Формируем текст подтверждения
    from bot.locales import TEXTS
    texts = TEXTS.get(lang, TEXTS['ru'])

    def person_text(person, num):
        gender_display = "Мужчина" if person.get('gender') == 'M' else "Женщина"
        return texts['compatibility_confirm_person'].format(
            num=num,
            name=person.get('name', ''),
            gender=gender_display,
            birth_date=person.get('birth_date', ''),
            birth_time=person.get('birth_time', ''),
            birth_place=person.get('birth_place', '')
        )

    confirm_text = (
        f"{texts.get('compatibility_confirm_title', '📋 Подтверждение данных для совместимости')}\n\n"
        f"{person_text(person1, 1)}\n\n"
        f"{person_text(person2, 2)}"
    )

    await message.answer(
        confirm_text,
        reply_markup=get_compatibility_confirm_keyboard(lang)
    )


# ---- NumerologyStates ----
@dp.message(NumerologyStates.WAITING_NAME)
async def process_numerology_name(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    if len(message.text) < 2:
        await message.answer(await get_text(user_id, 'error_name_short'))
        return
    await state.update_data(numerology_name=message.text)
    await state.set_state(NumerologyStates.WAITING_BIRTH_DATE)
    template = await get_text(user_id, 'numerology_name_prompt')
    await message.answer(
        template.format(name=message.text),
        reply_markup=get_cancel_keyboard(lang)
    )


@dp.message(NumerologyStates.WAITING_BIRTH_DATE)
async def process_numerology_birth_date(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    date_pattern = r'^\d{2}\.\d{2}\.\d{4}$'
    if not re.match(date_pattern, message.text):
        await message.answer(
            await get_text(user_id, 'error_invalid_date_format'),
            reply_markup=get_cancel_keyboard(lang)
        )
        return
    try:
        birth_date = datetime.strptime(message.text, "%d.%m.%Y")
        zodiac = calculate_zodiac_sign(birth_date.day, birth_date.month)
        zodiac_name = get_zodiac_sign_localized(zodiac, lang)
        await state.update_data(numerology_birth_date=message.text, numerology_zodiac=zodiac)
        await state.set_state(NumerologyStates.WAITING_BIRTH_TIME)
        template = await get_text(user_id, 'numerology_birth_date')
        await message.answer(
            template.format(
                emoji=get_zodiac_emoji(zodiac),
                zodiac=zodiac_name
            ),
            reply_markup=get_cancel_keyboard(lang)
        )
    except ValueError:
        await message.answer(
            await get_text(user_id, 'error_invalid_date'),
            reply_markup=get_cancel_keyboard(lang)
        )


@dp.message(NumerologyStates.WAITING_BIRTH_TIME)
async def process_numerology_birth_time(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    time_pattern = r'^\d{2}:\d{2}$'
    if not re.match(time_pattern, message.text):
        await message.answer(
            await get_text(user_id, 'error_invalid_time_format'),
            reply_markup=get_cancel_keyboard(lang)
        )
        return
    try:
        datetime.strptime(message.text, "%H:%M")
        await state.update_data(numerology_birth_time=message.text)
        await state.set_state(NumerologyStates.WAITING_BIRTH_PLACE)
        await message.answer(
            await get_text(user_id, 'numerology_birth_time'),
            reply_markup=get_cancel_keyboard(lang)
        )
    except ValueError:
        await message.answer(
            await get_text(user_id, 'error_invalid_time'),
            reply_markup=get_cancel_keyboard(lang)
        )


@dp.message(NumerologyStates.WAITING_BIRTH_PLACE)
async def process_numerology_birth_place(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    if len(message.text) < 3:
        await message.answer(
            await get_text(user_id, 'error_invalid_place'),
            reply_markup=get_cancel_keyboard(lang)
        )
        return
    await state.update_data(numerology_birth_place=message.text)
    await state.set_state(NumerologyStates.WAITING_GENDER)
    await message.answer(
        await get_text(user_id, 'numerology_gender'),
        reply_markup=get_cancel_keyboard(lang)
    )


@dp.message(NumerologyStates.WAITING_GENDER)
async def process_numerology_gender(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    gender = message.text.upper()
    if gender not in ["М", "Ж"]:
        await message.answer(
            await get_text(user_id, 'error_invalid_gender'),
            reply_markup=get_cancel_keyboard(lang)
        )
        return

    db_gender = 'M' if gender == 'М' else 'F'
    data = await state.get_data()

    user_data_from_db = await get_user_data(user_id)
    numer_count = user_data_from_db.get('numerology_count', 0) if user_data_from_db else 0

    if numer_count > 0:
        numerology_data[user_id] = {
            'name': data.get('numerology_name'),
            'birth_date': data.get('numerology_birth_date'),
            'birth_time': data.get('numerology_birth_time'),
            'birth_place': data.get('numerology_birth_place'),
            'gender': db_gender,
            'zodiac': data.get('numerology_zodiac'),
            'is_manual': True
        }

        zodiac_emoji = get_zodiac_emoji(data.get('numerology_zodiac', 'Неизвестно'))
        zodiac_name = get_zodiac_sign_localized(data.get('numerology_zodiac', 'Неизвестно'), lang)
        template = await get_text(user_id, 'numerology_confirm_data')
        profile_text = template.format(
            name=data.get('numerology_name'),
            birth_date=data.get('numerology_birth_date'),
            birth_time=data.get('numerology_birth_time'),
            birth_place=data.get('numerology_birth_place'),
            emoji=zodiac_emoji,
            zodiac=zodiac_name
        )
        await state.set_state(NumerologyStates.CONFIRM_DATA)
        await message.answer(
            profile_text,
            reply_markup=get_numerology_confirm_keyboard(lang)
        )
        return

    if not data.get('numerology_paid', False):
        await message.answer(
            await get_text(user_id, 'numerology_payment_not_confirmed'),
            reply_markup=get_numerology_payment_keyboard(lang)
        )
        await state.set_state(NumerologyStates.PAYMENT)
        return

    user_data_for_calc = {
        'name': data.get('numerology_name'),
        'birth_date': data.get('numerology_birth_date'),
        'birth_time': data.get('numerology_birth_time'),
        'birth_place': data.get('numerology_birth_place'),
        'gender': db_gender,
        'zodiac': data.get('numerology_zodiac')
    }
    numerology_data[user_id] = user_data_for_calc

    await state.clear()

    zodiac_emoji = get_zodiac_emoji(data.get('numerology_zodiac', 'Неизвестно'))
    zodiac_name = get_zodiac_sign_localized(data.get('numerology_zodiac', 'Неизвестно'), lang)
    gender_display = 'Мужской' if gender == 'М' else 'Женский'

    template = await get_text(user_id, 'numerology_data_saved')
    profile_text = template.format(
        name=data.get('numerology_name'),
        birth_date=data.get('numerology_birth_date'),
        birth_time=data.get('numerology_birth_time'),
        birth_place=data.get('numerology_birth_place'),
        gender=gender_display,
        emoji=zodiac_emoji,
        zodiac=zodiac_name
    )

    # Скрываем клавиатуру
    await message.answer("⏳ Рассчитываем нумерологию...", reply_markup=ReplyKeyboardRemove())

    status_msg = await message.answer(profile_text)

    try:
        await status_msg.edit_text(await get_text(user_id, 'numerology_status_calc'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'numerology_status_analyze'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'numerology_status_format'))
        await asyncio.sleep(2)

        if gemini_service:
            result = gemini_service.generate_numerology(numerology_data[user_id], lang)
            await save_message_to_archive(user_id, 'numerology', result)
            await add_numerology_count(user_id, -1)

            allowed_ids = [5484157606, 8790509202]
            if user_id in allowed_ids:
                from bot.calculators.base_calculator import BaseCalculator
                from bot.calculators.natal_calculator import NatalCalculator
                calc = BaseCalculator()
                user_data = numerology_data[user_id]
                prompt_data = {
                    'name': user_data.get('name', ''),
                    'gender_display': "Мужчина" if user_data.get('gender') == 'M' else "Женщина",
                    'birth_date': user_data.get('birth_date', ''),
                    'birth_time': user_data.get('birth_time', 'не указано'),
                    'birth_place': user_data.get('birth_place', 'не указано'),
                    'pronoun': "он" if user_data.get('gender') == 'M' else "она",
                    'possessive': "его" if user_data.get('gender') == 'M' else "её",
                }
                natal = NatalCalculator(
                    birth_date=user_data.get('birth_date'),
                    name=user_data.get('name'),
                    birth_time=user_data.get('birth_time'),
                    birth_place=user_data.get('birth_place'),
                    gender=user_data.get('gender')
                )
                matrix = natal.calculate()
                prompt_data.update(matrix)
                name = user_data.get('name', '')
                prompt_data['expression_number'] = calc.calculate_expression_number(name) or "не рассчитано"
                prompt_data['soul_urge_number'] = calc.calculate_soul_urge_number(name) or "не рассчитано"
                prompt_data['personality_number'] = calc.calculate_personality_number(name) or "не рассчитано"
                target_date = datetime.now().strftime('%d.%m.%Y')
                birth_date = user_data.get('birth_date')
                if birth_date:
                    prompt_data['personal_year'] = calc.calculate_personal_year(birth_date, target_date)
                    prompt_data['personal_month'] = calc.calculate_personal_month(birth_date, target_date)
                    prompt_data['personal_day'] = calc.calculate_personal_day(birth_date, target_date)
                else:
                    prompt_data['personal_year'] = prompt_data['personal_month'] = prompt_data['personal_day'] = "не рассчитано"

                parameters_text = format_parameters(prompt_data, 'numerology', lang)
                final_message = f"{parameters_text}\n\n{result}"
            else:
                final_message = result

            result_template = await get_text(user_id, 'numerology_result')
            result_text = result_template.format(result=final_message)

            # Сначала результат, потом статус
            await send_long_message(message, result_text, reply_markup=get_main_menu_button(lang))
            await status_msg.delete()
        else:
            await status_msg.edit_text(await get_text(user_id, 'error_service_unavailable'))
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
        except:
            await message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        numerology_data.pop(user_id, None)
        await state.clear()


# ---- AstrologyStates ----
@dp.message(AstrologyStates.WAITING_NAME)
async def process_astrology_name(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    logger.info(f"🟢 Вызван process_astrology_name для пользователя {user_id}, текст: {message.text}")
    if len(message.text) < 2:
        await message.answer(await get_text(user_id, 'error_name_short'))
        return
    await state.update_data(astrology_name=message.text)
    await state.set_state(AstrologyStates.WAITING_BIRTH_DATE)
    template = await get_text(user_id, 'astrology_name_prompt')
    await message.answer(
        template.format(name=message.text),
        reply_markup=get_cancel_keyboard(lang)
    )


@dp.message(AstrologyStates.WAITING_BIRTH_DATE)
async def process_astrology_birth_date(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    date_pattern = r'^\d{2}\.\d{2}\.\d{4}$'
    if not re.match(date_pattern, message.text):
        await message.answer(
            await get_text(user_id, 'error_invalid_date_format'),
            reply_markup=get_cancel_keyboard(lang)
        )
        return
    try:
        birth_date = datetime.strptime(message.text, "%d.%m.%Y")
        zodiac = calculate_zodiac_sign(birth_date.day, birth_date.month)
        zodiac_name = get_zodiac_sign_localized(zodiac, lang)
        await state.update_data(astrology_birth_date=message.text, astrology_zodiac=zodiac)
        await state.set_state(AstrologyStates.WAITING_BIRTH_TIME)
        template = await get_text(user_id, 'astrology_birth_date')
        await message.answer(
            template.format(
                emoji=get_zodiac_emoji(zodiac),
                zodiac=zodiac_name
            ),
            reply_markup=get_cancel_keyboard(lang)
        )
    except ValueError:
        await message.answer(
            await get_text(user_id, 'error_invalid_date'),
            reply_markup=get_cancel_keyboard(lang)
        )


@dp.message(AstrologyStates.WAITING_BIRTH_TIME)
async def process_astrology_birth_time(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    time_pattern = r'^\d{2}:\d{2}$'
    if not re.match(time_pattern, message.text):
        await message.answer(
            await get_text(user_id, 'error_invalid_time_format'),
            reply_markup=get_cancel_keyboard(lang)
        )
        return
    try:
        datetime.strptime(message.text, "%H:%M")
        await state.update_data(astrology_birth_time=message.text)
        await state.set_state(AstrologyStates.WAITING_BIRTH_PLACE)
        await message.answer(
            await get_text(user_id, 'astrology_birth_time'),
            reply_markup=get_cancel_keyboard(lang)
        )
    except ValueError:
        await message.answer(
            await get_text(user_id, 'error_invalid_time'),
            reply_markup=get_cancel_keyboard(lang)
        )


@dp.message(AstrologyStates.WAITING_BIRTH_PLACE)
async def process_astrology_birth_place(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    if len(message.text) < 3:
        await message.answer(
            await get_text(user_id, 'error_invalid_place'),
            reply_markup=get_cancel_keyboard(lang)
        )
        return
    await state.update_data(astrology_birth_place=message.text)
    await state.set_state(AstrologyStates.WAITING_GENDER)
    await message.answer(
        await get_text(user_id, 'astrology_gender'),
        reply_markup=get_cancel_keyboard(lang)
    )


@dp.message(AstrologyStates.WAITING_GENDER)
async def process_astrology_gender(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    gender = message.text.upper()
    if gender not in ["М", "Ж"]:
        await message.answer(
            await get_text(user_id, 'error_invalid_gender'),
            reply_markup=get_cancel_keyboard(lang)
        )
        return

    db_gender = 'M' if gender == 'М' else 'F'
    data = await state.get_data()

    user_data_from_db = await get_user_data(user_id)
    astro_count = user_data_from_db.get('astrology_count', 0) if user_data_from_db else 0

    if astro_count > 0:
        astrology_data[user_id] = {
            'name': data.get('astrology_name'),
            'birth_date': data.get('astrology_birth_date'),
            'birth_time': data.get('astrology_birth_time'),
            'birth_place': data.get('astrology_birth_place'),
            'gender': db_gender,
            'zodiac': data.get('astrology_zodiac'),
            'is_manual': True
        }

        zodiac_emoji = get_zodiac_emoji(data.get('astrology_zodiac', 'Неизвестно'))
        zodiac_name = get_zodiac_sign_localized(data.get('astrology_zodiac', 'Неизвестно'), lang)
        template = await get_text(user_id, 'astrology_confirm_data')
        profile_text = template.format(
            name=data.get('astrology_name'),
            birth_date=data.get('astrology_birth_date'),
            birth_time=data.get('astrology_birth_time'),
            birth_place=data.get('astrology_birth_place'),
            emoji=zodiac_emoji,
            zodiac=zodiac_name
        )
        await state.set_state(AstrologyStates.CONFIRM_DATA)
        await message.answer(
            profile_text,
            reply_markup=get_astrology_confirm_keyboard(lang)
        )
        return

    if not data.get('astrology_paid', False):
        await message.answer(
            await get_text(user_id, 'astrology_payment_not_confirmed'),
            reply_markup=get_astrology_payment_keyboard(lang)
        )
        await state.set_state(AstrologyStates.PAYMENT)
        return

    user_data_for_calc = {
        'name': data.get('astrology_name'),
        'birth_date': data.get('astrology_birth_date'),
        'birth_time': data.get('astrology_birth_time'),
        'birth_place': data.get('astrology_birth_place'),
        'gender': db_gender,
        'zodiac': data.get('astrology_zodiac')
    }
    astrology_data[user_id] = user_data_for_calc

    await state.clear()

    zodiac_emoji = get_zodiac_emoji(data.get('astrology_zodiac', 'Неизвестно'))
    zodiac_name = get_zodiac_sign_localized(data.get('astrology_zodiac', 'Неизвестно'), lang)
    gender_display = 'Мужской' if gender == 'М' else 'Женский'

    template = await get_text(user_id, 'astrology_data_saved')
    profile_text = template.format(
        name=data.get('astrology_name'),
        birth_date=data.get('astrology_birth_date'),
        birth_time=data.get('astrology_birth_time'),
        birth_place=data.get('astrology_birth_place'),
        gender=gender_display,
        emoji=zodiac_emoji,
        zodiac=zodiac_name
    )

    # Скрываем клавиатуру
    await message.answer("⏳ Строим натальную карту...", reply_markup=ReplyKeyboardRemove())

    status_msg = await message.answer(profile_text)

    try:
        await status_msg.edit_text(await get_text(user_id, 'astrology_status_planets'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'astrology_status_houses'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'astrology_status_final'))
        await asyncio.sleep(2)

        if gemini_service:
            calculator = AstrologyCalculator(user_data_for_calc)

            # Базовые параметры для всех пользователей
            basic = calculator.get_basic_parameters(lang)

            # Дополнительные данные (планеты, куспиды, аспекты) — только для разрешённых пользователей
            allowed_ids = [5484157606, 8790509202]
            if user_id in allowed_ids:
                extra = calculator.get_extra_parameters(lang)
                parameters_text = basic + "\n" + extra
            else:
                parameters_text = basic

            prompt = calculator.build_prompt(lang)
            interpretation = gemini_service.send_raw_prompt(prompt, lang)

            template = await get_text(user_id, 'astrology_result')
            final_message = template.format(parameters=parameters_text, interpretation=interpretation)
            await save_message_to_archive(user_id, 'astrology', final_message)
            await add_astrology_count(user_id, -1)

            # Сначала результат, потом статус
            await send_long_message(message, final_message, reply_markup=get_main_menu_button(lang))
            await status_msg.delete()
        else:
            await status_msg.edit_text(await get_text(user_id, 'error_service_unavailable'))
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
        except:
            await message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        astrology_data.pop(user_id, None)
        await state.clear()


# ---- HoroscopeStates ----
@dp.message(HoroscopeStates.CONFIRM)
async def confirm_horoscope_state(message: Message, state: FSMContext):
    # Этот хендлер не используется, т.к. подтверждение гороскопа идёт через callback
    pass


# ==================== ФУНКЦИИ-ОБРАБОТЧИКИ (без декораторов) ====================

@dp.message(F.text == "🔮 Гороскоп на сегодня")
async def start_horoscope(message: Message, state: FSMContext):
    user_id = message.from_user.id
    is_subscribed = await check_subscription_db(user_id)
    lang = await get_user_language(user_id)

    if is_subscribed:
        user_data = await get_user_data(user_id)
        if user_data and user_data.get('name'):
            zodiac_emoji = get_zodiac_emoji(user_data.get('zodiac', 'Неизвестно'))
            zodiac_name = get_zodiac_sign_localized(user_data.get('zodiac', 'Неизвестно'), lang)
            template = await get_text(user_id, 'horoscope_confirm_data')
            profile_text = template.format(
                name=user_data.get('name', 'Не указано'),
                birth_date=user_data.get('birth_date', 'Не указана'),
                birth_time=user_data.get('birth_time', 'Не указано'),
                birth_place=user_data.get('birth_place', 'Не указано'),
                emoji=zodiac_emoji,
                zodiac=zodiac_name
            )
            await state.set_state(HoroscopeStates.CONFIRM)
            await message.answer(
                profile_text,
                reply_markup=get_horoscope_confirm_keyboard(lang)
            )
        else:
            await state.set_state(UserDataStates.WAITING_NAME)
            await message.answer(await get_text(user_id, 'horoscope_intro'), reply_markup=get_cancel_keyboard(lang))
        return

    if not await can_use_feature_db(user_id, 'horoscope'):
        await message.answer(await get_text(user_id, 'horoscope_free_ready'),
                             reply_markup=get_subscription_keyboard(lang))
        return

    user_data = await get_user_data(user_id)
    if user_data and user_data.get('name'):
        if not gemini_service:
            await message.answer(await get_text(user_id, 'error_service_unavailable'))
            return

        # Скрываем клавиатуру
        await message.answer("⏳ Генерация гороскопа...", reply_markup=ReplyKeyboardRemove())

        status_msg = await message.answer(await get_text(user_id, 'horoscope_status_planets'))
        try:
            await asyncio.sleep(1)
            await status_msg.edit_text(await get_text(user_id, 'horoscope_status_chart'))
            await asyncio.sleep(1)
            await status_msg.edit_text(await get_text(user_id, 'horoscope_status_analyze'))
            await asyncio.sleep(1)

            today = datetime.now().strftime("%d.%m.%Y")
            horoscope = gemini_service.generate_horoscope(user_data, today, lang)
            await save_message_to_archive(user_id, 'horoscope', horoscope)
            await mark_feature_used_db(user_id, 'horoscope')

            allowed_ids = [5484157606, 8790509202]
            calc = TransitHoroscopeCalculator(user_data)
            prompt_data = calc.calculate()

            if user_id in allowed_ids:
                parameters_text = format_parameters(prompt_data, 'horoscope', lang)
                final_message = f"{parameters_text}\n\n{horoscope}"
            else:
                basic_params = format_basic_horoscope_parameters(prompt_data, lang)
                final_message = f"{basic_params}\n\n{horoscope}"

            result_template = await get_text(user_id, 'horoscope_result')
            result_text = result_template.format(date=today, horoscope=final_message)

            logger.info(f"📤 Отправка гороскопа, длина result_text: {len(result_text)}")
            if len(result_text) > 0:
                logger.info(f"📤 Первые 200 символов: {result_text[:200]}...")
            else:
                logger.error("❌ result_text пустой!")
                result_text = "⚠️ Сообщение пустое. Попробуйте позже."

            # Сначала отправляем результат, потом удаляем статус
            await send_long_message(message, result_text, reply_markup=get_main_menu_button(lang))
            await status_msg.delete()

            if not is_subscribed:
                await message.answer(
                    await get_text(user_id, 'horoscope_promo'),
                    reply_markup=get_subscription_promo_keyboard(lang)
                )
        except Exception as e:
            try:
                await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
            except:
                await message.answer(f"❌ Ошибка: {str(e)}")
    else:
        await state.set_state(UserDataStates.WAITING_NAME)
        await message.answer(await get_text(user_id, 'horoscope_intro'), reply_markup=get_cancel_keyboard(lang))


async def start_compatibility(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)

    if not await can_use_feature_db(user_id, 'compatibility'):
        await message.answer(
            await get_text(user_id, 'compatibility_limit'),
            reply_markup=get_subscription_keyboard(lang)
        )
        return

    user_data = await get_user_data(user_id)

    if user_data and user_data.get('name'):
        zodiac_emoji = get_zodiac_emoji(user_data.get('zodiac', 'Неизвестно'))
        zodiac_name = get_zodiac_sign_localized(user_data.get('zodiac', 'Неизвестно'), lang)
        gender_display = 'Мужской' if user_data.get('gender') == 'M' else 'Женский' if user_data.get('gender') == 'F' else 'Не указан'

        template = await get_text(user_id, 'compatibility_use_data')
        profile_text = template.format(
            name=user_data.get('name', 'Не указано'),
            birth_date=user_data.get('birth_date', 'Не указана'),
            birth_time=user_data.get('birth_time', 'Не указано'),
            birth_place=user_data.get('birth_place', 'Не указано'),
            gender=gender_display,
            emoji=zodiac_emoji,
            zodiac=zodiac_name
        )

        await message.answer(
            profile_text,
            reply_markup=get_compatibility_keyboard(lang)
        )

        await state.update_data(person1_data=user_data)
        await state.set_state(CompatibilityStates.CONFIRM_DATA)

    else:
        await state.set_state(CompatibilityStates.WAITING_PERSON1_NAME)
        await message.answer(
            await get_text(user_id, 'compatibility_intro'),
            reply_markup=get_cancel_keyboard(lang)
        )


async def start_numerology(message: Message, state: FSMContext):
    """Начало оформления нумерологии"""
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    user_data = await get_user_data(user_id)

    if user_data and user_data.get('name'):
        zodiac_emoji = get_zodiac_emoji(user_data.get('zodiac', 'Неизвестно'))
        zodiac_name = get_zodiac_sign_localized(user_data.get('zodiac', 'Неизвестно'), lang)
        numer_count = user_data.get('numerology_count', 0)

        if numer_count > 0:
            template = await get_text(user_id, 'numerology_start')
            profile_text = template.format(
                name=user_data.get('name', 'Не указано'),
                birth_date=user_data.get('birth_date', 'Не указана'),
                birth_time=user_data.get('birth_time', 'Не указано'),
                birth_place=user_data.get('birth_place', 'Не указано'),
                emoji=zodiac_emoji,
                zodiac=zodiac_name
            )
            await message.answer(
                profile_text,
                reply_markup=get_numerology_confirm_keyboard(lang)
            )
            await state.set_state(NumerologyStates.CONFIRM_DATA)
        else:
            await message.answer(
                await get_text(user_id, 'numerology_no_data'),
                reply_markup=get_numerology_payment_keyboard(lang)
            )
            await state.set_state(NumerologyStates.PAYMENT)
    else:
        await state.set_state(NumerologyStates.WAITING_NAME)
        await message.answer(
            await get_text(user_id, 'numerology_no_user_data'),
            reply_markup=get_cancel_keyboard(lang)
        )


async def start_astrology(message: Message, state: FSMContext):
    """Начало оформления астрологии"""
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    user_data = await get_user_data(user_id)

    if user_data and user_data.get('name'):
        zodiac_emoji = get_zodiac_emoji(user_data.get('zodiac', 'Неизвестно'))
        zodiac_name = get_zodiac_sign_localized(user_data.get('zodiac', 'Неизвестно'), lang)
        astro_count = user_data.get('astrology_count', 0)

        if astro_count > 0:
            template = await get_text(user_id, 'astrology_start')
            profile_text = template.format(
                name=user_data.get('name', 'Не указано'),
                birth_date=user_data.get('birth_date', 'Не указана'),
                birth_time=user_data.get('birth_time', 'Не указано'),
                birth_place=user_data.get('birth_place', 'Не указано'),
                emoji=zodiac_emoji,
                zodiac=zodiac_name
            )
            await message.answer(
                profile_text,
                reply_markup=get_astrology_confirm_keyboard(lang)
            )
            await state.set_state(AstrologyStates.CONFIRM_DATA)
        else:
            await message.answer(
                await get_text(user_id, 'astrology_no_data'),
                reply_markup=get_astrology_payment_keyboard(lang)
            )
            await state.set_state(AstrologyStates.PAYMENT)
    else:
        await state.set_state(AstrologyStates.WAITING_NAME)
        await message.answer(
            await get_text(user_id, 'astrology_no_user_data'),
            reply_markup=get_cancel_keyboard(lang)
        )


async def show_subscription(message: Message):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    is_subscribed = await check_subscription_db(user_id)

    if is_subscribed:
        await message.answer(
            await get_text(user_id, 'subscription_active'),
            reply_markup=get_subscription_active_keyboard(lang)
        )
    else:
        await message.answer(
            await get_text(user_id, 'subscription_inactive'),
            reply_markup=get_subscription_keyboard(lang)
        )


async def expert_request(message: Message):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    username = message.from_user.username or "Не указан"
    first_name = message.from_user.first_name or "Не указано"

    user_data_from_db = await get_user_data(user_id)

    user_info = ""
    if user_data_from_db:
        user_info = (
            f"\n👤 Имя: {user_data_from_db.get('name', 'Не указано')}"
            f"\n📅 Дата рождения: {user_data_from_db.get('birth_date', 'Не указана')}"
            f"\n🕒 Время рождения: {user_data_from_db.get('birth_time', 'Не указано')}"
            f"\n📍 Место рождения: {user_data_from_db.get('birth_place', 'Не указано')}"
            f"\n♈ Знак зодиака: {user_data_from_db.get('zodiac', 'Неизвестно')}"
        )

    expert_text = await get_text(user_id, 'expert_intro')

    await message.answer(
        expert_text,
        reply_markup=get_expert_keyboard(lang)
    )


async def show_archive(message: Message):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    messages = await get_user_archive(user_id, limit=10)

    if not messages:
        await message.answer(
            await get_text(user_id, 'archive_empty'),
            reply_markup=get_main_menu(lang)
        )
        return

    type_display_map = {
        'horoscope': await get_text(user_id, 'type_horoscope'),
        'compatibility': await get_text(user_id, 'type_compatibility'),
        'numerology': await get_text(user_id, 'type_numerology'),
        'astrology': await get_text(user_id, 'type_astrology'),
    }

    type_emoji_map = {
        'horoscope': '🔮',
        'compatibility': '💕',
        'numerology': '🔢',
        'astrology': '🌙',
    }

    archive_text = await get_text(user_id, 'archive_title')

    for i, msg in enumerate(messages, 1):
        date_str = msg.date.strftime("%d.%m.%Y %H:%M")
        emoji = type_emoji_map.get(msg.message_type, '📝')
        type_name = type_display_map.get(msg.message_type, msg.message_type)

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        preview = preview.replace('\n', ' ')

        template = await get_text(user_id, 'archive_item')
        archive_text += template.format(
            i=i,
            emoji=emoji,
            type=type_name,
            date=date_str,
            preview=preview
        )

    archive_text += await get_text(user_id, 'archive_footer')

    await message.answer(
        archive_text,
        reply_markup=get_archive_keyboard(messages, lang)
    )


async def profile(message: Message):
    """Показать профиль пользователя"""
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    user_data = await get_user_data(user_id)

    if user_data and user_data.get('name'):
        zodiac_emoji = get_zodiac_emoji(user_data.get('zodiac', 'Неизвестно'))
        zodiac_name = get_zodiac_sign_localized(user_data.get('zodiac', 'Неизвестно'), lang)

        if user_data.get('gender') == 'M':
            gender_display = await get_text(user_id, 'astro_gender_male')
        elif user_data.get('gender') == 'F':
            gender_display = await get_text(user_id, 'astro_gender_female')
        else:
            gender_display = await get_text(user_id, 'astro_gender_unknown')

        timezone = user_data.get('timezone_offset', 3)

        template = await get_text(user_id, 'profile_text')
        profile_text = template.format(
            name=user_data.get('name', 'Не указано'),
            birth_date=user_data.get('birth_date', 'Не указана'),
            birth_time=user_data.get('birth_time', 'Не указано'),
            birth_place=user_data.get('birth_place', 'Не указано'),
            gender=gender_display,
            emoji=zodiac_emoji,
            zodiac=zodiac_name,
            timezone=timezone
        )

        is_subscribed = await check_subscription_db(user_id)
        if is_subscribed:
            profile_text += await get_text(user_id, 'profile_subscription_active')

        await message.answer(profile_text, reply_markup=get_profile_keyboard(lang))
    else:
        consent_url = os.getenv('CONSENT_URL', 'ссылка на согласие')
        privacy_url = os.getenv('PRIVACY_POLICY_URL', 'ссылка на политику')
        can_use = await can_use_feature_db(user_id, 'horoscope')

        if can_use:
            template = await get_text(user_id, 'profile_no_data_message')
            text = template.format(consent_url=consent_url, privacy_url=privacy_url)
        else:
            template = await get_text(user_id, 'profile_no_data_message_can_use')
            text = template.format(consent_url=consent_url, privacy_url=privacy_url)
        await message.answer(text, reply_markup=get_fill_profile_keyboard(lang), parse_mode="Markdown")


def format_numerology_parameters(data: dict) -> str:
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━",
        f"👤 Имя: {data.get('name', 'Не указано')}",
        f"⚥ Пол: {data.get('gender_display', 'Не указан')}",
        f"📅 Дата рождения: {data.get('birth_date', 'Не указана')}",
        f"🕒 Время рождения: {data.get('birth_time', 'Не указано')}",
        f"📍 Место рождения: {data.get('birth_place', 'Не указано')}",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"🔢 Число жизненного пути: {data.get('life_path', '—')}",
        f"✨ Число экспрессии: {data.get('expression_number', '—')}",
        f"❤️ Число души: {data.get('soul_urge_number', '—')}",
        f"👤 Число личности: {data.get('personality_number', '—')}",
        f"📅 Личный год: {data.get('personal_year', '—')}",
        f"📆 Личный месяц: {data.get('personal_month', '—')}",
        f"📆 Личный день: {data.get('personal_day', '—')}",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"🧩 Аркан дня (m1): {data.get('m1', '—')}",
        f"🧩 Аркан месяца (m2): {data.get('m2', '—')}",
        f"🧩 Аркан года (m3): {data.get('m3', '—')}",
        f"💞 Отношения (ОПВ): {data.get('opv', '—')}",
        f"🌟 Судьба (СЗ): {data.get('sz', '—')}",
        f"⚠️ Препятствие: {data.get('obstacle', '—')}",
        f"👥 Человек-предатель: {data.get('traitor', '—')}",
        f"😌 Зона комфорта: {data.get('comfort', '—')}",
        f"👨 Левая родовая: {data.get('v_left', '—')}",
        f"👩 Правая родовая: {data.get('v_right', '—')}",
        f"🌿 Карма левая: {data.get('v_bottom_left', '—')}",
        f"🌿 Карма правая: {data.get('v_bottom_right', '—')}",
        f"🧳 Багаж опыта: {data.get('v_left_side', '—')}",
        f"🕵️ Человек-предатель (правый бок): {data.get('v_right_side', '—')}",
        f"🪪 Внутренний паспорт: {data.get('v_top', '—')}",
    ]
    return "\n".join(lines)


def prepare_numerology_prompt_data(user_data: dict) -> dict:
    from bot.calculators.base_calculator import BaseCalculator
    calc = BaseCalculator()
    birth_date = user_data.get('birth_date')
    target_date = datetime.now().strftime('%d.%m.%Y')
    name = user_data.get('name', '')

    from bot.calculators import NatalCalculator
    natal_calc = NatalCalculator(
        birth_date=birth_date,
        name=name,
        birth_time=user_data.get('birth_time'),
        birth_place=user_data.get('birth_place'),
        gender=user_data.get('gender')
    )
    matrix = natal_calc.calculate()

    prompt_data = {
        "name": name,
        "gender_display": "Мужчина" if user_data.get('gender') == 'M' else "Женщина",
        "birth_date": birth_date,
        "birth_time": user_data.get('birth_time', 'не указано'),
        "birth_place": user_data.get('birth_place', 'не указано'),
        "life_path": calc.calculate_life_path_number(birth_date),
        "expression_number": calc.calculate_expression_number(name) or "не рассчитано",
        "soul_urge_number": calc.calculate_soul_urge_number(name) or "не рассчитано",
        "personality_number": calc.calculate_personality_number(name) or "не рассчитано",
        "personal_year": calc.calculate_personal_year(birth_date, target_date),
        "personal_month": calc.calculate_personal_month(birth_date, target_date),
        "personal_day": calc.calculate_personal_day(birth_date, target_date),
        "pronoun": "он" if user_data.get('gender') == 'M' else "она",
        "possessive": "его" if user_data.get('gender') == 'M' else "её",
    }
    prompt_data.update(matrix)
    return prompt_data


def format_basic_compatibility_parameters(person1: dict, person2: dict, lang: str = 'ru') -> str:
    """Форматирует базовые данные для совместимости (для обычных пользователей)."""
    from bot.locales import TEXTS
    texts = TEXTS.get(lang, TEXTS['ru'])

    def person_text(person, num):
        gender = "Мужчина" if person.get('gender') == 'M' else "Женщина"
        return texts['compatibility_confirm_person'].format(
            num=num,
            name=person.get('name', ''),
            gender=gender,
            birth_date=person.get('birth_date', ''),
            birth_time=person.get('birth_time', ''),
            birth_place=person.get('birth_place', '')
        )

    lines = [
        texts.get('compatibility_confirm_title', '📋 Подтверждение данных для совместимости'),
        "",
        person_text(person1, 1),
        "",
        person_text(person2, 2),
    ]
    return "\n".join(lines)


# ==================== ВСЕ CALLBACK-ХЕНДЛЕРЫ ====================

@dp.callback_query(F.data == "confirm_horoscope", HoroscopeStates.CONFIRM)
async def confirm_horoscope(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.delete()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    user_data = await get_user_data(user_id)

    if not user_data or not user_data.get('name'):
        await callback.message.answer(await get_text(user_id, 'error_not_found'))
        await state.clear()
        return

    if not gemini_service:
        await callback.message.answer(await get_text(user_id, 'error_service_unavailable'))
        await state.clear()
        return

    # Скрываем клавиатуру
    await callback.message.answer("⏳ Генерация гороскопа...", reply_markup=ReplyKeyboardRemove())

    status_msg = await callback.message.answer(await get_text(user_id, 'horoscope_status_planets'))
    try:
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'horoscope_status_chart'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'horoscope_status_analyze'))
        await asyncio.sleep(1)

        today = datetime.now().strftime("%d.%m.%Y")
        horoscope = gemini_service.generate_horoscope(user_data, today, lang)
        await save_message_to_archive(user_id, 'horoscope', horoscope)

        allowed_ids = [5484157606, 8790509202]
        calc = TransitHoroscopeCalculator(user_data)
        prompt_data = calc.calculate()

        if user_id in allowed_ids:
            parameters_text = format_parameters(prompt_data, 'horoscope', lang)
            final_message = f"{parameters_text}\n\n{horoscope}"
        else:
            basic_params = format_basic_horoscope_parameters(prompt_data, lang)
            final_message = f"{basic_params}\n\n{horoscope}"

        result_template = await get_text(user_id, 'horoscope_result')
        result_text = result_template.format(date=today, horoscope=final_message)

        logger.info(f"📤 Отправка гороскопа (confirm), длина result_text: {len(result_text)}")
        if len(result_text) > 0:
            logger.info(f"📤 Первые 200 символов: {result_text[:200]}...")
        else:
            logger.error("❌ result_text пустой!")
            result_text = "⚠️ Сообщение пустое. Попробуйте позже."

        # Сначала результат, потом статус
        await send_long_message(callback.message, result_text, reply_markup=get_main_menu_button(lang))
        await status_msg.delete()

        await state.clear()
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
        except:
            await callback.message.answer(f"❌ Ошибка: {str(e)}")
        await state.clear()


@dp.callback_query(F.data == "confirm_compatibility", CompatibilityStates.CONFIRM_BOTH)
async def confirm_compatibility(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    data = await state.get_data()
    person1 = data.get('person1')
    person2 = data.get('person2')

    if not person1 or not person2:
        await callback.message.answer(await get_text(user_id, 'error_not_found'), reply_markup=get_main_menu(lang))
        await state.clear()
        return

    # Скрываем клавиатуру и показываем статус
    status_msg = await callback.message.answer("⏳ Анализируем совместимость...", reply_markup=ReplyKeyboardRemove())

    try:
        await status_msg.edit_text(await get_text(user_id, 'compatibility_status_aspects'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'compatibility_status_natal'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'compatibility_status_forecast'))
        await asyncio.sleep(1)

        if gemini_service:
            result = gemini_service.generate_compatibility_from_prompt(person1, person2, lang)

            await mark_feature_used_db(user_id, 'compatibility')
            await save_message_to_archive(user_id, 'compatibility', result)

            allowed_ids = [5484157606, 8790509202]
            if user_id in allowed_ids:
                calc = CompatibilityCalculator(person1, person2)
                prompt_data = calc.get_prompt_data()
                parameters_text = format_parameters(prompt_data, 'compatibility', lang)
                final_message = f"{parameters_text}\n\n{result}"
            else:
                basic = format_basic_compatibility_parameters(person1, person2, lang)
                final_message = f"{basic}\n\n{result}"

            result_template = await get_text(user_id, 'compatibility_result')
            result_text = result_template.format(result=final_message)

            # Сначала отправляем результат
            await send_long_message(callback.message, result_text, reply_markup=get_main_menu_button(lang))

            # Затем удаляем статусное сообщение
            await status_msg.delete()

            if not await check_subscription_db(user_id):
                await callback.message.answer(
                    await get_text(user_id, 'compatibility_promo'),
                    reply_markup=get_subscription_promo_keyboard(lang)
                )
        else:
            await status_msg.edit_text(await get_text(user_id, 'error_service_unavailable'))
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ Произошла ошибка при анализе:\n{str(e)}")
        except:
            await callback.message.answer(f"❌ Произошла ошибка при анализе:\n{str(e)}")
    finally:
        await state.clear()


@dp.callback_query(F.data == "cancel_compatibility", CompatibilityStates.CONFIRM_BOTH)
async def cancel_compatibility(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.delete()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await callback.message.answer(await get_text(user_id, 'error_cancel'), reply_markup=get_main_menu(lang))


@dp.callback_query(F.data == "use_my_data")
async def use_my_data(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    data = await state.get_data()
    person1 = data.get('person1_data', {})

    if not person1:
        await callback.message.answer(
            await get_text(user_id, 'error_not_found'),
            reply_markup=get_main_menu(lang)
        )
        await state.clear()
        return

    await state.update_data(person1=person1)
    await state.set_state(CompatibilityStates.WAITING_PERSON2_NAME)

    await callback.message.answer(
        await get_text(user_id, 'compatibility_person1_saved'),
        reply_markup=get_cancel_keyboard(lang)
    )


@dp.callback_query(F.data == "fill_person1")
async def fill_person1(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await state.set_state(CompatibilityStates.WAITING_PERSON1_NAME)

    await callback.message.answer(
        await get_text(user_id, 'compatibility_edit_name'),
        reply_markup=get_cancel_keyboard(lang)
    )
    await callback.answer()


@dp.callback_query(F.data == "numerology_use_my_data")
async def numerology_use_my_data(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    data = await state.get_data()

    if not data.get('numerology_paid', False):
        await callback.message.answer(
            await get_text(user_id, 'numerology_payment_required'),
            reply_markup=get_numerology_payment_keyboard(lang)
        )
        await state.set_state(NumerologyStates.PAYMENT)
        return

    user_data_from_db = await get_user_data(user_id)
    if not user_data_from_db or not user_data_from_db.get('name'):
        await callback.message.answer(
            await get_text(user_id, 'numerology_data_not_found'),
            reply_markup=get_main_menu(lang)
        )
        await state.clear()
        return

    numerology_data[user_id] = {
        'name': user_data_from_db.get('name'),
        'birth_date': user_data_from_db.get('birth_date'),
        'birth_time': user_data_from_db.get('birth_time'),
        'birth_place': user_data_from_db.get('birth_place'),
        'gender': user_data_from_db.get('gender'),
        'zodiac': user_data_from_db.get('zodiac'),
        'is_manual': False
    }

    await state.clear()

    zodiac_emoji = get_zodiac_emoji(user_data_from_db.get('zodiac', 'Неизвестно'))
    zodiac_name = get_zodiac_sign_localized(user_data_from_db.get('zodiac', 'Неизвестно'), lang)
    gender_display = 'Мужской' if user_data_from_db.get('gender') == 'M' else 'Женский'

    template = await get_text(user_id, 'numerology_use_data_confirm')
    profile_text = template.format(
        name=user_data_from_db.get('name'),
        birth_date=user_data_from_db.get('birth_date'),
        birth_time=user_data_from_db.get('birth_time'),
        birth_place=user_data_from_db.get('birth_place'),
        gender=gender_display,
        emoji=zodiac_emoji,
        zodiac=zodiac_name
    )

    # Скрываем клавиатуру
    await callback.message.answer("⏳ Рассчитываем нумерологию...", reply_markup=ReplyKeyboardRemove())

    status_msg = await callback.message.answer(profile_text)

    try:
        await status_msg.edit_text(await get_text(user_id, 'numerology_status_calc'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'numerology_status_analyze'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'numerology_status_format'))
        await asyncio.sleep(2)

        if gemini_service:
            result = gemini_service.generate_numerology(numerology_data[user_id], lang)
            await save_message_to_archive(user_id, 'numerology', result)
            await add_numerology_count(user_id, -1)

            allowed_ids = [5484157606, 8790509202]
            if user_id in allowed_ids:
                from bot.calculators.base_calculator import BaseCalculator
                from bot.calculators.natal_calculator import NatalCalculator
                calc = BaseCalculator()
                user_data = numerology_data[user_id]
                prompt_data = {
                    'name': user_data.get('name', ''),
                    'gender_display': "Мужчина" if user_data.get('gender') == 'M' else "Женщина",
                    'birth_date': user_data.get('birth_date', ''),
                    'birth_time': user_data.get('birth_time', 'не указано'),
                    'birth_place': user_data.get('birth_place', 'не указано'),
                    'pronoun': "он" if user_data.get('gender') == 'M' else "она",
                    'possessive': "его" if user_data.get('gender') == 'M' else "её",
                }
                natal = NatalCalculator(
                    birth_date=user_data.get('birth_date'),
                    name=user_data.get('name'),
                    birth_time=user_data.get('birth_time'),
                    birth_place=user_data.get('birth_place'),
                    gender=user_data.get('gender')
                )
                matrix = natal.calculate()
                prompt_data.update(matrix)
                name = user_data.get('name', '')
                prompt_data['expression_number'] = calc.calculate_expression_number(name) or "не рассчитано"
                prompt_data['soul_urge_number'] = calc.calculate_soul_urge_number(name) or "не рассчитано"
                prompt_data['personality_number'] = calc.calculate_personality_number(name) or "не рассчитано"
                target_date = datetime.now().strftime('%d.%m.%Y')
                birth_date = user_data.get('birth_date')
                if birth_date:
                    prompt_data['personal_year'] = calc.calculate_personal_year(birth_date, target_date)
                    prompt_data['personal_month'] = calc.calculate_personal_month(birth_date, target_date)
                    prompt_data['personal_day'] = calc.calculate_personal_day(birth_date, target_date)
                else:
                    prompt_data['personal_year'] = prompt_data['personal_month'] = prompt_data['personal_day'] = "не рассчитано"

                parameters_text = format_parameters(prompt_data, 'numerology', lang)
                final_message = f"{parameters_text}\n\n{result}"
            else:
                final_message = result

            result_template = await get_text(user_id, 'numerology_result')
            result_text = result_template.format(result=final_message)

            # Сначала результат, потом статус
            await send_long_message(callback.message, result_text, reply_markup=get_main_menu_button(lang))
            await status_msg.delete()
        else:
            await status_msg.edit_text(await get_text(user_id, 'error_service_unavailable'))
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
        except:
            await callback.message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        numerology_data.pop(user_id, None)


@dp.callback_query(F.data == "numerology_fill_new_data")
async def numerology_fill_new_data(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    data = await state.get_data()
    if not data.get('numerology_paid', False):
        await callback.message.answer(
            await get_text(user_id, 'numerology_payment_required'),
            reply_markup=get_numerology_payment_keyboard(lang)
        )
        await state.set_state(NumerologyStates.PAYMENT)
        return

    await state.set_state(NumerologyStates.WAITING_NAME)
    await callback.message.answer(
        await get_text(user_id, 'numerology_fill_new_data'),
        reply_markup=get_cancel_keyboard(lang)
    )


@dp.callback_query(F.data == "numerology_pay", NumerologyStates.PAYMENT)
async def numerology_payment(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    if not yookassa.is_configured:
        await callback.message.answer(
            await get_text(user_id, 'numerology_payment_error')
        )
        return

    result = yookassa.create_payment(
        user_id=user_id,
        amount=12.00, #amount=888.00,
        description=f"Нумерология (ID: {user_id})",
        payment_type='numerology'
    )

    if result['success']:
        await save_payment_db(user_id, result['payment_id'], 888.00, 'numerology', 'pending')
        await state.update_data(payment_id=result['payment_id'], numerology_paid=True)

        await callback.message.answer(
            await get_text(user_id, 'numerology_payment_process'),
            reply_markup=get_payment_url_keyboard(result['confirmation_url'], lang)
        )

        await state.set_state(NumerologyStates.PAYMENT)
    else:
        error_template = await get_text(user_id, 'numerology_payment_fail')
        await callback.message.answer(
            error_template.format(error=result['error'])
        )


@dp.callback_query(F.data == "numerology_confirm", NumerologyStates.CONFIRM_DATA)
async def numerology_confirm(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    manual_data = numerology_data.get(user_id)
    if manual_data and manual_data.get('is_manual') is True:
        user_data = {k: v for k, v in manual_data.items() if k != 'is_manual'}
        numerology_data.pop(user_id, None)
    else:
        user_data_from_db = await get_user_data(user_id)
        if not user_data_from_db or not user_data_from_db.get('name'):
            await callback.message.answer(
                await get_text(user_id, 'error_not_found'),
                reply_markup=get_main_menu(lang)
            )
            await state.clear()
            return
        user_data = user_data_from_db
        numerology_data.pop(user_id, None)

    # Скрываем клавиатуру
    await callback.message.answer("⏳ Рассчитываем нумерологию...", reply_markup=ReplyKeyboardRemove())

    status_msg = await callback.message.answer(await get_text(user_id, 'numerology_confirm_start'))

    try:
        await status_msg.edit_text(await get_text(user_id, 'numerology_status_calc'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'numerology_status_analyze'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'numerology_status_format'))
        await asyncio.sleep(2)

        if gemini_service:
            result = gemini_service.generate_numerology(user_data, lang)
            await save_message_to_archive(user_id, 'numerology', result)
            await add_numerology_count(user_id, -1)

            allowed_ids = [5484157606, 8790509202]
            if user_id in allowed_ids:
                from bot.calculators.base_calculator import BaseCalculator
                from bot.calculators.natal_calculator import NatalCalculator
                calc = BaseCalculator()
                prompt_data = {
                    'name': user_data.get('name', ''),
                    'gender_display': "Мужчина" if user_data.get('gender') == 'M' else "Женщина",
                    'birth_date': user_data.get('birth_date', ''),
                    'birth_time': user_data.get('birth_time', 'не указано'),
                    'birth_place': user_data.get('birth_place', 'не указано'),
                    'pronoun': "он" if user_data.get('gender') == 'M' else "она",
                    'possessive': "его" if user_data.get('gender') == 'M' else "её",
                }
                natal = NatalCalculator(
                    birth_date=user_data.get('birth_date'),
                    name=user_data.get('name'),
                    birth_time=user_data.get('birth_time'),
                    birth_place=user_data.get('birth_place'),
                    gender=user_data.get('gender')
                )
                matrix = natal.calculate()
                prompt_data.update(matrix)
                name = user_data.get('name', '')
                prompt_data['expression_number'] = calc.calculate_expression_number(name) or "не рассчитано"
                prompt_data['soul_urge_number'] = calc.calculate_soul_urge_number(name) or "не рассчитано"
                prompt_data['personality_number'] = calc.calculate_personality_number(name) or "не рассчитано"
                target_date = datetime.now().strftime('%d.%m.%Y')
                birth_date = user_data.get('birth_date')
                if birth_date:
                    prompt_data['personal_year'] = calc.calculate_personal_year(birth_date, target_date)
                    prompt_data['personal_month'] = calc.calculate_personal_month(birth_date, target_date)
                    prompt_data['personal_day'] = calc.calculate_personal_day(birth_date, target_date)
                else:
                    prompt_data['personal_year'] = prompt_data['personal_month'] = prompt_data['personal_day'] = "не рассчитано"

                parameters_text = format_parameters(prompt_data, 'numerology', lang)
                final_message = f"{parameters_text}\n\n{result}"
            else:
                final_message = result

            result_template = await get_text(user_id, 'numerology_result')
            result_text = result_template.format(result=final_message)

            # Сначала результат, потом статус
            await send_long_message(callback.message, result_text, reply_markup=get_main_menu_button(lang))
            await status_msg.delete()
        else:
            await status_msg.edit_text(await get_text(user_id, 'error_service_unavailable'))
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
        except:
            await callback.message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        numerology_data.pop(user_id, None)
        await state.clear()


@dp.callback_query(F.data == "edit_numerology_data")
async def edit_numerology_data(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.answer()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await state.update_data(is_numerology_edit=True)
    await state.set_state(NumerologyStates.WAITING_NAME)
    await callback.message.answer(
        await get_text(user_id, 'numerology_edit_name'),
        reply_markup=get_cancel_keyboard(lang)
    )


@dp.callback_query(F.data == "astrology_use_my_data")
async def astrology_use_my_data(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    data = await state.get_data()

    if not data.get('astrology_paid', False):
        await callback.message.answer(
            await get_text(user_id, 'astrology_payment_required'),
            reply_markup=get_astrology_payment_keyboard(lang)
        )
        await state.set_state(AstrologyStates.PAYMENT)
        return

    user_data_from_db = await get_user_data(user_id)
    if not user_data_from_db or not user_data_from_db.get('name'):
        await callback.message.answer(
            await get_text(user_id, 'astrology_data_not_found'),
            reply_markup=get_main_menu(lang)
        )
        await state.clear()
        return

    astrology_data[user_id] = {
        'name': user_data_from_db.get('name'),
        'birth_date': user_data_from_db.get('birth_date'),
        'birth_time': user_data_from_db.get('birth_time'),
        'birth_place': user_data_from_db.get('birth_place'),
        'gender': user_data_from_db.get('gender'),
        'zodiac': user_data_from_db.get('zodiac'),
        'is_manual': False
    }

    await state.clear()

    zodiac_emoji = get_zodiac_emoji(user_data_from_db.get('zodiac', 'Неизвестно'))
    zodiac_name = get_zodiac_sign_localized(user_data_from_db.get('zodiac', 'Неизвестно'), lang)
    gender_display = 'Мужской' if user_data_from_db.get('gender') == 'M' else 'Женский'

    template = await get_text(user_id, 'astrology_use_data_confirm')
    profile_text = template.format(
        name=user_data_from_db.get('name'),
        birth_date=user_data_from_db.get('birth_date'),
        birth_time=user_data_from_db.get('birth_time'),
        birth_place=user_data_from_db.get('birth_place'),
        gender=gender_display,
        emoji=zodiac_emoji,
        zodiac=zodiac_name
    )

    # Скрываем клавиатуру
    await callback.message.answer("⏳ Строим натальную карту...", reply_markup=ReplyKeyboardRemove())

    status_msg = await callback.message.answer(profile_text)

    try:
        await status_msg.edit_text(await get_text(user_id, 'astrology_status_planets'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'astrology_status_houses'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'astrology_status_final'))
        await asyncio.sleep(2)

        if gemini_service:
            calculator = AstrologyCalculator(user_data_from_db)

            basic = calculator.get_basic_parameters(lang)
            allowed_ids = [5484157606, 8790509202]
            if user_id in allowed_ids:
                extra = calculator.get_extra_parameters(lang)
                parameters_text = basic + "\n" + extra
            else:
                parameters_text = basic

            prompt = calculator.build_prompt(lang)
            interpretation = gemini_service.send_raw_prompt(prompt, lang)

            template = await get_text(user_id, 'astrology_result')
            final_message = template.format(parameters=parameters_text, interpretation=interpretation)
            await save_message_to_archive(user_id, 'astrology', final_message)
            await add_astrology_count(user_id, -1)

            # Сначала результат, потом статус
            await send_long_message(callback.message, final_message, reply_markup=get_main_menu_button(lang))
            await status_msg.delete()
        else:
            await status_msg.edit_text(await get_text(user_id, 'error_service_unavailable'))
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
        except:
            await callback.message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        astrology_data.pop(user_id, None)
        await state.clear()


@dp.callback_query(F.data == "astrology_fill_new_data")
async def astrology_fill_new_data(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    data = await state.get_data()
    if not data.get('astrology_paid', False):
        await callback.message.answer(
            await get_text(user_id, 'astrology_payment_required'),
            reply_markup=get_astrology_payment_keyboard(lang)
        )
        await state.set_state(AstrologyStates.PAYMENT)
        return

    await state.set_state(AstrologyStates.WAITING_NAME)
    await callback.message.answer(
        await get_text(user_id, 'astrology_fill_new_data'),
        reply_markup=get_cancel_keyboard(lang)
    )


@dp.callback_query(F.data == "astrology_pay", AstrologyStates.PAYMENT)
async def astrology_payment(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    if not yookassa.is_configured:
        await callback.message.answer(
            await get_text(user_id, 'astrology_payment_error')
        )
        return

    result = yookassa.create_payment(
        user_id=user_id,
        amount=13.00, #amount=999.00,
        description=f"Астрология (ID: {user_id})",
        payment_type='astrology'
    )

    if result['success']:
        await save_payment_db(user_id, result['payment_id'], 999.00, 'astrology', 'pending')
        await state.update_data(payment_id=result['payment_id'], astrology_paid=True)

        await callback.message.answer(
            await get_text(user_id, 'astrology_payment_process'),
            reply_markup=get_payment_url_keyboard(result['confirmation_url'], lang)
        )

        await state.set_state(AstrologyStates.PAYMENT)
    else:
        error_template = await get_text(user_id, 'astrology_payment_fail')
        await callback.message.answer(
            error_template.format(error=result['error'])
        )


@dp.callback_query(F.data == "astrology_confirm", AstrologyStates.CONFIRM_DATA)
async def astrology_confirm(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    manual_data = astrology_data.get(user_id)
    if manual_data and manual_data.get('is_manual') is True:
        user_data = {k: v for k, v in manual_data.items() if k != 'is_manual'}
        astrology_data.pop(user_id, None)
    else:
        user_data_from_db = await get_user_data(user_id)
        if not user_data_from_db or not user_data_from_db.get('name'):
            await callback.message.answer(
                await get_text(user_id, 'error_not_found'),
                reply_markup=get_main_menu(lang)
            )
            await state.clear()
            return
        user_data = user_data_from_db
        astrology_data.pop(user_id, None)

    # Скрываем клавиатуру
    await callback.message.answer("⏳ Строим натальную карту...", reply_markup=ReplyKeyboardRemove())

    status_msg = await callback.message.answer(await get_text(user_id, 'astrology_confirm_start'))

    try:
        await status_msg.edit_text(await get_text(user_id, 'astrology_status_planets'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'astrology_status_houses'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'astrology_status_final'))
        await asyncio.sleep(2)

        if gemini_service:
            calculator = AstrologyCalculator(user_data)
            basic = calculator.get_basic_parameters(lang)
            allowed_ids = [5484157606, 8790509202]
            if user_id in allowed_ids:
                extra = calculator.get_extra_parameters(lang)
                parameters_text = basic + "\n" + extra
            else:
                parameters_text = basic

            prompt = calculator.build_prompt(lang)
            interpretation = gemini_service.send_raw_prompt(prompt, lang)

            template = await get_text(user_id, 'astrology_result')
            final_message = template.format(parameters=parameters_text, interpretation=interpretation)
            await save_message_to_archive(user_id, 'astrology', final_message)
            await add_astrology_count(user_id, -1)

            # Сначала результат, потом статус
            await send_long_message(callback.message, final_message, reply_markup=get_main_menu_button(lang))
            await status_msg.delete()
        else:
            await status_msg.edit_text(await get_text(user_id, 'error_service_unavailable'))
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
        except:
            await callback.message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        astrology_data.pop(user_id, None)
        await state.clear()


@dp.callback_query(F.data == "edit_astrology_data")
async def edit_astrology_data(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.answer()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await state.update_data(is_astrology_edit=True)
    await state.set_state(AstrologyStates.WAITING_NAME)
    logger.info(f"🔵 Установлено состояние WAITING_NAME для пользователя {user_id}")
    await callback.message.answer(
        await get_text(user_id, 'astrology_edit_name'),
        reply_markup=get_cancel_keyboard(lang)
    )


@dp.callback_query(F.data == "edit_profile")
async def edit_profile(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    old = await get_user_data(user_id)
    if not old or not old.get('name'):
        await callback.message.edit_text(
            "❌ У вас нет сохраненных данных. Сначала заполните профиль через 'Гороскоп на сегодня'."
        )
        return

    await state.update_data(
        old_data=old,
        new_data=old.copy(),
        is_edit=True,
        fill_mode=False,
        is_timezone_edit=False
    )

    logger.info(f"🟢 Начало редактирования для {user_id}, старые данные: {old}")

    await state.set_state(UserDataStates.WAITING_NAME)
    template = await get_text(user_id, 'edit_name_prompt')
    prompt = template.format(name=old.get('name', 'не указано'))
    await callback.message.edit_text(
        prompt,
        reply_markup=get_skip_keyboard(lang)
    )


@dp.callback_query(F.data == "fill_and_save")
async def fill_and_save(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.delete()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await state.update_data(fill_mode=True)

    await state.set_state(UserDataStates.WAITING_NAME)
    await callback.message.answer(
        await get_text(user_id, 'profile_fill_intro'),
        reply_markup=get_cancel_keyboard(lang)
    )


@dp.callback_query(F.data == "skip_edit")
async def skip_edit_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    current_state = await state.get_state()
    state_data = await state.get_data()
    new_data = state_data.get('new_data', {})
    old = state_data.get('old_data', {})

    logger.info(f"⏩ Пропуск шага {current_state}, new_data до: {new_data}")

    if current_state == UserDataStates.WAITING_NAME:
        await state.set_state(UserDataStates.WAITING_BIRTH_DATE)
        template = await get_text(user_id, 'skip_birth_date')
        prompt = template.format(date=old.get('birth_date', 'не указана'))
        await callback.message.edit_text(prompt, reply_markup=get_skip_keyboard(lang))
    elif current_state == UserDataStates.WAITING_BIRTH_DATE:
        await state.set_state(UserDataStates.WAITING_BIRTH_TIME)
        template = await get_text(user_id, 'skip_birth_time')
        prompt = template.format(time=old.get('birth_time', 'не указано'))
        await callback.message.edit_text(prompt, reply_markup=get_skip_keyboard(lang))
    elif current_state == UserDataStates.WAITING_BIRTH_TIME:
        await state.set_state(UserDataStates.WAITING_BIRTH_PLACE)
        template = await get_text(user_id, 'skip_birth_place')
        prompt = template.format(place=old.get('birth_place', 'не указано'))
        await callback.message.edit_text(prompt, reply_markup=get_skip_keyboard(lang))
    elif current_state == UserDataStates.WAITING_BIRTH_PLACE:
        await state.set_state(UserDataStates.WAITING_GENDER)
        current_gender = old.get('gender')
        if current_gender == 'M':
            gender_display = 'Мужской'
        elif current_gender == 'F':
            gender_display = 'Женский'
        else:
            gender_display = 'не указан'
        template = await get_text(user_id, 'skip_gender')
        prompt = template.format(gender=gender_display)
        await callback.message.edit_text(prompt, reply_markup=get_skip_keyboard(lang))
    elif current_state == UserDataStates.WAITING_GENDER:
        user_id = callback.from_user.id
        logger.info(f"💾 Завершение редактирования через 'Пропустить' для {user_id}, данные: {new_data}")
        await save_user_data(user_id, new_data)
        await state.clear()

        user_obj = await sync_to_async(User.objects.get)(telegram_id=user_id)
        if user_obj.gender == 'M':
            gender_display = await get_text(user_id, 'astro_gender_male')
        elif user_obj.gender == 'F':
            gender_display = await get_text(user_id, 'astro_gender_female')
        else:
            gender_display = await get_text(user_id, 'astro_gender_unknown')
        zodiac_emoji = get_zodiac_emoji(user_obj.zodiac_sign or 'Неизвестно')
        zodiac_name = get_zodiac_sign_localized(user_obj.zodiac_sign or 'Неизвестно', lang)
        profile_text = (
            f"✅ Данные успешно обновлены!\n\n"
            f"👤 Имя: {user_obj.name or 'Не указано'}\n"
            f"📅 Дата рождения: {user_obj.date_of_birth.strftime('%d.%m.%Y') if user_obj.date_of_birth else 'Не указана'}\n"
            f"🕒 Время рождения: {user_obj.birth_time.strftime('%H:%M') if user_obj.birth_time else 'Не указано'}\n"
            f"📍 Место рождения: {user_obj.birth_place or 'Не указано'}\n"
            f"👤 Пол: {gender_display}\n"
            f"{zodiac_emoji} Знак зодиака: {zodiac_name}"
        )
        await callback.message.edit_text(profile_text, reply_markup=get_main_menu(lang))
    else:
        user_id = callback.from_user.id
        logger.info(f"💾 Завершение редактирования (неизвестное состояние) для {user_id}, данные: {new_data}")
        await save_user_data(user_id, new_data)
        await state.clear()

        user_obj = await sync_to_async(User.objects.get)(telegram_id=user_id)
        if user_obj.gender == 'M':
            gender_display = await get_text(user_id, 'astro_gender_male')
        elif user_obj.gender == 'F':
            gender_display = await get_text(user_id, 'astro_gender_female')
        else:
            gender_display = await get_text(user_id, 'astro_gender_unknown')
        zodiac_emoji = get_zodiac_emoji(user_obj.zodiac_sign or 'Неизвестно')
        zodiac_name = get_zodiac_sign_localized(user_obj.zodiac_sign or 'Неизвестно', lang)
        profile_text = (
            f"✅ Данные успешно обновлены!\n\n"
            f"👤 Имя: {user_obj.name or 'Не указано'}\n"
            f"📅 Дата рождения: {user_obj.date_of_birth.strftime('%d.%m.%Y') if user_obj.date_of_birth else 'Не указана'}\n"
            f"🕒 Время рождения: {user_obj.birth_time.strftime('%H:%M') if user_obj.birth_time else 'Не указано'}\n"
            f"📍 Место рождения: {user_obj.birth_place or 'Не указано'}\n"
            f"👤 Пол: {gender_display}\n"
            f"{zodiac_emoji} Знак зодиака: {zodiac_name}"
        )
        await callback.message.edit_text(profile_text, reply_markup=get_main_menu(lang))

    logger.info(f"⏩ После пропуска, new_data: {new_data}")


@dp.callback_query(F.data == "edit_timezone")
async def edit_timezone(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.delete()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await state.update_data(
        is_timezone_edit=True,
        is_edit=False,
        fill_mode=False
    )

    await state.set_state(UserDataStates.WAITING_TIMEZONE)
    await callback.message.answer(
        await get_text(user_id, 'choose_timezone'),
        reply_markup=get_timezone_keyboard(lang)
    )


@dp.callback_query(F.data == "expert_request")
async def send_expert_request(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    username = callback.from_user.username or "Не указан"
    first_name = callback.from_user.first_name or "Не указано"

    user_data_from_db = await get_user_data(user_id)

    user_info = ""
    if user_data_from_db:
        user_info = (
            f"\n👤 Имя: {user_data_from_db.get('name', 'Не указано')}"
            f"\n📅 Дата рождения: {user_data_from_db.get('birth_date', 'Не указана')}"
            f"\n🕒 Время рождения: {user_data_from_db.get('birth_time', 'Не указано')}"
            f"\n📍 Место рождения: {user_data_from_db.get('birth_place', 'Не указано')}"
            f"\n♈ Знак зодиака: {user_data_from_db.get('zodiac', 'Неизвестно')}"
        )

    await callback.message.answer(
        await get_text(user_id, 'expert_sent'),
        reply_markup=get_main_menu_button(lang)
    )

    expert_chat_id = os.getenv('EXPERT_CHAT_ID')
    logger.info(f"🔍 EXPERT_CHAT_ID из .env: '{expert_chat_id}'")
    if expert_chat_id:
        try:
            expert_message = (
                f"📩 НОВАЯ ЗАЯВКА НА КОНСУЛЬТАЦИЮ!\n\n"
                f"👤 Пользователь: @{username}\n"
                f"📛 Имя: {first_name}\n"
                f"🆔 ID: {user_id}{user_info}\n\n"
                f"💰 Услуга: Экспертный разбор (5000 ₽)\n"
                f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            )
            await bot.send_message(expert_chat_id, expert_message)
            logger.info(f"✅ Сообщение эксперту отправлено на {expert_chat_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки эксперту: {e}")
    else:
        logger.warning("⚠️ EXPERT_CHAT_ID не задан в .env, сообщение эксперту не отправлено")


@dp.callback_query(F.data == "subscribe_pay")
async def subscribe_payment(callback: CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    if not yookassa.is_configured:
        await callback.message.answer(
            await get_text(user_id, 'subscription_payment_error')
        )
        return

    result = yookassa.create_payment(
        user_id=user_id,
        amount=11.00, #amount=333.00,
        description=f"Подписка на астробота (ID: {user_id})",
        payment_type='subscription'
    )

    if result['success']:
        await save_payment_db(user_id, result['payment_id'], 333.00, 'subscription', 'pending')

        await callback.message.answer(
            await get_text(user_id, 'subscription_payment_process'),
            reply_markup=get_subscription_payment_keyboard(result['confirmation_url'], lang)
        )
    else:
        await callback.message.answer(
            f"❌ Ошибка при создании платежа: {result['error']}"
        )


@dp.callback_query(F.data == "subscribe_extend")
async def subscribe_extend(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await callback.message.answer(
        await get_text(user_id, 'subscription_extend'),
        reply_markup=get_subscription_keyboard(lang)
    )


@dp.callback_query(F.data == "archive_refresh")
async def refresh_archive(callback: CallbackQuery):
    await callback.answer()
    await callback.message.delete()

    class FakeMessage:
        def __init__(self, callback):
            self.from_user = callback.from_user
            self.chat = callback.message.chat
            self.answer = callback.message.answer

    fake_msg = FakeMessage(callback)
    await show_archive(fake_msg)


@dp.callback_query(F.data.startswith("archive_"))
async def show_archive_message(callback: CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    try:
        message_id = int(callback.data.replace("archive_", ""))
    except ValueError:
        await callback.message.answer(await get_text(user_id, 'error_not_found'))
        return

    try:
        from bot.db import get_archive_message
        msg = await get_archive_message(message_id, callback.from_user.id)

        if not msg:
            await callback.message.answer(
                await get_text(user_id, 'error_not_found'),
                reply_markup=get_main_menu(lang)
            )
            return

        type_emoji = {
            'horoscope': '🔮',
            'compatibility': '💕',
            'natal_chart': '🌌',
            'numerology': '🔢',
            'astrology': '🌙',
        }

        type_display = {
            'horoscope': await get_text(user_id, 'type_horoscope'),
            'compatibility': await get_text(user_id, 'type_compatibility'),
            'natal_chart': await get_text(user_id, 'type_horoscope'),
            'numerology': await get_text(user_id, 'type_numerology'),
            'astrology': await get_text(user_id, 'type_astrology'),
        }

        emoji = type_emoji.get(msg.message_type, '📝')
        type_name = type_display.get(msg.message_type, msg.message_type)

        template = await get_text(user_id, 'archive_message_header')
        full_text = template.format(
            emoji=emoji,
            type=type_name,
            date=msg.date.strftime('%d.%m.%Y %H:%M'),
            content=msg.content
        )

        await send_long_message(callback.message, full_text)

    except Exception as e:
        await callback.message.answer(
            f"❌ Ошибка: {str(e)}",
            reply_markup=get_main_menu(lang)
        )


@dp.callback_query(F.data == "cancel_subscription")
async def cancel_subscription_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    try:
        @sync_to_async
        def get_user(uid):
            try:
                return User.objects.get(telegram_id=uid)
            except User.DoesNotExist:
                return None

        user = await get_user(user_id)

        if not user:
            await callback.message.answer(
                await get_text(user_id, 'subscription_cancel_not_found'),
                reply_markup=get_main_menu(lang)
            )
            return

        if not user.is_subscribed:
            await callback.message.answer(
                await get_text(user_id, 'subscription_not_active'),
                reply_markup=get_main_menu(lang)
            )
            await callback.message.delete()
            return

        @sync_to_async
        def cancel_subscription(user_obj):
            user_obj.is_subscribed = False
            user_obj.subscription_until = None
            user_obj.save()
            return True

        await cancel_subscription(user)

        await callback.message.delete()

        await callback.message.answer(
            await get_text(user_id, 'subscription_canceled'),
            reply_markup=get_main_menu(lang)
        )

    except Exception as e:
        await callback.message.answer(
            f"❌ Ошибка при отмене подписки: {str(e)}",
            reply_markup=get_main_menu(lang)
        )


@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    support_url = os.getenv('SUPPORT_URL', 'https://t.me/ваш_username')
    text = await get_text(user_id, 'support_text')
    await callback.message.edit_text(
        text,
        reply_markup=get_support_keyboard(support_url, lang),
        parse_mode="Markdown"
    )


@dp.callback_query(F.data == "back_to_profile")
async def back_to_profile(callback: CallbackQuery):
    await callback.answer()
    await callback.message.delete()
    class FakeMessage:
        def __init__(self, callback):
            self.from_user = callback.from_user
            self.chat = callback.message.chat
            self.answer = callback.message.answer
    fake_msg = FakeMessage(callback)
    await profile(fake_msg)


@dp.callback_query(F.data == "check_payment")
async def check_payment(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    data = await state.get_data()
    payment_id = data.get('payment_id')

    if not payment_id:
        await callback.message.answer(
            await get_text(user_id, 'error_payment_not_found')
        )
        return

    result = yookassa.check_payment(payment_id)

    if result['success'] and result['paid']:
        await callback.message.answer(
            await get_text(user_id, 'payment_success'),
            reply_markup=get_main_menu(lang)
        )
        await state.clear()
    else:
        await callback.message.answer(
            await get_text(user_id, 'payment_not_confirmed'),
            reply_markup=get_payment_url_keyboard(callback.message.text, lang)
        )


@dp.callback_query(F.data == "zodiac_")
async def process_zodiac_choice(callback: CallbackQuery, state: FSMContext):
    zodiac = callback.data.replace("zodiac_", "")
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await state.update_data(zodiac=zodiac)
    await state.set_state(UserDataStates.WAITING_BIRTH_DATE)

    zodiac_name = get_zodiac_sign_localized(zodiac, lang)
    await callback.message.edit_text(
        f"✅ Выбран знак: {get_zodiac_emoji(zodiac)} {zodiac_name}\n\n📅 Теперь укажите дату рождения в формате ДД.ММ.ГГГГ"
    )
    await callback.answer()


# ==================== ОСТАЛЬНЫЕ CALLBACK ====================

@dp.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    # Отправляем Reply-клавиатуру отдельным сообщением, не удаляя предыдущее
    await callback.message.answer("🏠", reply_markup=get_main_menu(lang))


@dp.callback_query(F.data == "cancel")
async def cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await callback.message.answer(await get_text(user_id, 'error_cancel'), reply_markup=get_main_menu(lang))
    await callback.answer()


@dp.callback_query(F.data == "cancel_horoscope", HoroscopeStates.CONFIRM)
async def cancel_horoscope(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.delete()
    await state.clear()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    main_menu_text = await get_text(user_id, 'main_menu_text')
    await callback.message.answer(main_menu_text, reply_markup=get_main_menu(lang))


@dp.callback_query(F.data.startswith("tz_"), UserDataStates.WAITING_TIMEZONE)
async def process_timezone(callback: CallbackQuery, state: FSMContext):
    tz_offset = int(callback.data.split("_")[1])
    await callback.answer()

    state_data = await state.get_data()
    is_edit = state_data.get('is_edit', False)
    fill_mode = state_data.get('fill_mode', False)
    is_timezone_edit = state_data.get('is_timezone_edit', False)
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    if is_edit:
        new_data = state_data.get('new_data', {})
        new_data['timezone_offset'] = tz_offset
        await save_user_data(user_id, new_data)
        await state.clear()
        profile_text = format_profile_data(new_data, lang)
        template = await get_text(user_id, 'profile_updated')
        msg = template.format(profile=profile_text)
        await callback.message.delete()
        await callback.message.answer(msg, reply_markup=get_profile_keyboard(lang))
        return

    if fill_mode:
        temp_data = state_data.get('temp_data', {})
        temp_data['timezone_offset'] = tz_offset
        await save_user_data(user_id, temp_data)
        await state.clear()
        profile_text = format_profile_data(temp_data, lang)
        template = await get_text(user_id, 'profile_data_saved')
        msg = template.format(profile=profile_text)
        await callback.message.delete()
        await callback.message.answer(msg, reply_markup=get_profile_keyboard(lang))
        return

    if is_timezone_edit:
        user = await sync_to_async(User.objects.get)(telegram_id=user_id)
        user.timezone_offset = tz_offset
        await sync_to_async(user.save)()
        await state.clear()
        user_data = await get_user_data(user_id)
        profile_text = format_profile_data(user_data, lang)
        template = await get_text(user_id, 'timezone_updated')
        msg = template.format(profile=profile_text)
        await callback.message.delete()
        await callback.message.answer(msg, reply_markup=get_profile_keyboard(lang))
        return

    temp_data = state_data.get('temp_data', {})
    temp_data['timezone_offset'] = tz_offset
    await state.update_data(temp_data=temp_data)

    profile_text = format_profile_data(temp_data, lang)
    privacy_url = os.getenv('PRIVACY_POLICY_URL', 'ссылка на политику конфиденциальности')

    template = await get_text(user_id, 'profile_save_confirm')
    save_text = template.format(profile=profile_text, privacy_url=privacy_url)

    await state.set_state(UserDataStates.ASKING_SAVE)
    await callback.message.delete()
    await callback.message.answer(save_text, reply_markup=get_save_data_keyboard(lang), parse_mode="Markdown")


@dp.callback_query(F.data == "save_data", UserDataStates.ASKING_SAVE)
async def save_data(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    state_data = await state.get_data()
    temp_data = state_data.get('temp_data', {})
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    await save_user_data(user_id, temp_data)
    await state.clear()

    profile_text = format_profile_data(temp_data, lang)
    template = await get_text(user_id, 'profile_data_saved')
    msg = template.format(profile=profile_text)
    await callback.message.edit_text(
        f"{msg}\n\n{await get_text(user_id, 'profile_continue_prompt')}",
        reply_markup=get_after_save_keyboard(lang)
    )


@dp.callback_query(F.data == "dont_save_data", UserDataStates.ASKING_SAVE)
async def dont_save_data(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    state_data = await state.get_data()
    temp_data = state_data.get('temp_data', {})
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    await callback.message.delete()

    # Скрываем клавиатуру
    await callback.message.answer("⏳ Генерация гороскопа...", reply_markup=ReplyKeyboardRemove())

    status_msg = await callback.message.answer(await get_text(user_id, 'horoscope_status_planets'))
    try:
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'horoscope_status_chart'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'horoscope_status_analyze'))
        await asyncio.sleep(1)

        today = datetime.now().strftime("%d.%m.%Y")
        horoscope = gemini_service.generate_horoscope(temp_data, today, lang)
        await mark_feature_used_db(user_id, 'horoscope')
        await save_message_to_archive(user_id, 'horoscope', horoscope)

        allowed_ids = [5484157606, 8790509202]
        calc = TransitHoroscopeCalculator(temp_data)
        prompt_data = calc.calculate()

        if user_id in allowed_ids:
            parameters_text = format_parameters(prompt_data, 'horoscope', lang)
            final_message = f"{parameters_text}\n\n{horoscope}"
        else:
            basic_params = format_basic_horoscope_parameters(prompt_data, lang)
            final_message = f"{basic_params}\n\n{horoscope}"

        result_template = await get_text(user_id, 'horoscope_result')
        result_text = result_template.format(date=today, horoscope=final_message)

        # Сначала результат, потом статус
        await send_long_message(callback.message, result_text, reply_markup=get_main_menu_button(lang))
        await status_msg.delete()

        await state.clear()
        if not await check_subscription_db(user_id):
            await callback.message.answer(
                await get_text(user_id, 'horoscope_promo'),
                reply_markup=get_subscription_promo_keyboard(lang)
            )
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
        except:
            await callback.message.answer(f"❌ Ошибка: {str(e)}")
        await state.clear()


@dp.callback_query(F.data == "close_subscription")
async def close_subscription(callback: CallbackQuery):
    await callback.answer()
    await callback.message.delete()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    main_menu_text = await get_text(user_id, 'main_menu_text')
    await callback.message.answer(main_menu_text, reply_markup=get_main_menu(lang))


@dp.callback_query(F.data.startswith("lang_"))
async def set_language(callback: CallbackQuery):
    lang = callback.data.split("_")[1]
    user_id = callback.from_user.id

    try:
        user = await sync_to_async(User.objects.get)(telegram_id=user_id)
        user.language = lang
        await sync_to_async(user.save)()
        await callback.answer()
        confirm_text = await get_text(user_id, 'language_set')
        await callback.message.delete()
        await callback.message.answer(confirm_text, reply_markup=get_main_menu(lang))
    except User.DoesNotExist:
        await callback.answer("❌ Ошибка: пользователь не найден", show_alert=True)


# ==================== ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ====================

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
        # Если строка длиннее max_length, разбиваем её принудительно
        if len(line) > max_length:
            if current_part:
                parts.append(current_part)
                current_part = ""
            for i in range(0, len(line), max_length):
                chunk = line[i:i+max_length]
                parts.append(chunk)
            continue

        # Проверяем, влезет ли строка в текущую часть
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

    # Финальная проверка: если какая-то часть длиннее max_length – разбиваем принудительно
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
        # Обрезаем, если вдруг превышает лимит (страховка)
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

# ==================== ОБЩИЙ ОБРАБОТЧИК ТЕКСТОВЫХ КОМАНД ====================

@dp.message(F.text)
async def handle_menu_commands(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        return

    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    texts = TEXTS.get(lang, TEXTS['ru'])
    text = message.text

    logger.info(f"🔍 Общий обработчик: текст '{text}' от пользователя {user_id}, состояние: {current_state}")

    if text == texts['menu_horoscope']:
        await start_horoscope(message, state)
    elif text == texts['menu_compatibility']:
        await start_compatibility(message, state)
    elif text == texts['menu_numerology']:
        await start_numerology(message, state)
    elif text == texts['menu_astrology']:
        await start_astrology(message, state)
    elif text == texts['menu_premium']:
        await show_subscription(message)
    elif text == texts['menu_expert']:
        await expert_request(message)
    elif text == texts['menu_archive']:
        await show_archive(message)
    elif text == texts['menu_profile']:
        await profile(message)
    elif text == texts['menu_language']:
        await change_language(message)
    else:
        await handle_unknown(message)


@dp.message()
async def handle_unknown(message: Message):
    user_id = message.from_user.id
    await message.answer(
        await get_text(user_id, 'unknown_command')
    )


# ==================== ЗАПУСК ====================

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
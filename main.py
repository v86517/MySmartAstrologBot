import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, FSInputFile
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
    # Передаём ссылку в AstrologyCalculator для использования нейросети
    AstrologyCalculator.gemini_service = gemini_service
except Exception as e:
    logger.error(f"❌ Ошибка инициализации Gemini: {e}")
    gemini_service = None

numerology_data = {}
astrology_data = {}

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

# ==================== КОМАНДЫ (обрабатываются до общего обработчика) ====================

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
    """Показать главное меню"""
    await state.clear()
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    await message.answer(
        " ",
        reply_markup=get_main_menu(lang)
    )


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
    """Показать выбор языка"""
    user_id = message.from_user.id
    text = await get_text(user_id, 'choose_language')
    await message.answer(
        text,
        reply_markup=get_language_keyboard()
    )


# ==================== ВСЕ ХЕНДЛЕРЫ СОСТОЯНИЙ (FSM) ====================
# Они должны быть зарегистрированы до общего обработчика, чтобы не перехватывались

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

    # ----- Обычный режим (первое заполнение) -----
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

    await state.clear()

    zodiac1_name = get_zodiac_sign_localized(person1['zodiac'], lang)
    zodiac2_name = get_zodiac_sign_localized(person2['zodiac'], lang)
    zodiac1_emoji = get_zodiac_emoji(person1['zodiac'])
    zodiac2_emoji = get_zodiac_emoji(person2['zodiac'])

    template = await get_text(user_id, 'compatibility_summary')
    summary_text = template.format(
        name1=person1['name'],
        date1=person1['birth_date'],
        time1=person1['birth_time'],
        place1=person1['birth_place'],
        emoji1=zodiac1_emoji,
        zodiac1=zodiac1_name,
        name2=person2['name'],
        date2=person2['birth_date'],
        time2=person2['birth_time'],
        place2=person2['birth_place'],
        emoji2=zodiac2_emoji,
        zodiac2=zodiac2_name
    )

    status_msg = await message.answer(summary_text)

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

            await status_msg.delete()
            result_template = await get_text(user_id, 'compatibility_result')
            result_text = result_template.format(result=result)
            await send_long_message(message, result_text)

            if not await check_subscription_db(user_id):
                await message.answer(
                    await get_text(user_id, 'compatibility_promo'),
                    reply_markup=get_subscription_promo_keyboard(lang)
                )
        else:
            await status_msg.edit_text(await get_text(user_id, 'error_service_unavailable'))

    except Exception as e:
        await status_msg.edit_text(f"❌ Произошла ошибка при анализе:\n{str(e)}")


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
            await status_msg.delete()
            result_template = await get_text(user_id, 'numerology_result')
            result_text = result_template.format(result=result)
            await send_long_message(message, result_text)
        else:
            await status_msg.edit_text(await get_text(user_id, 'error_service_unavailable'))
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
    finally:
        numerology_data.pop(user_id, None)


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
            parameters_text = calculator.get_display_parameters(lang)
            prompt = calculator.build_prompt(lang)
            interpretation = gemini_service.send_raw_prompt(prompt, lang)

            template = await get_text(user_id, 'astrology_result')
            final_message = template.format(
                parameters=parameters_text,
                interpretation=interpretation
            )
            await save_message_to_archive(user_id, 'astrology', final_message)
            await add_astrology_count(user_id, -1)

            await status_msg.delete()
            await send_long_message(message, final_message)
        else:
            await status_msg.edit_text(await get_text(user_id, 'error_service_unavailable'))
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
    finally:
        astrology_data.pop(user_id, None)


# ---- HoroscopeStates ----
@dp.message(HoroscopeStates.CONFIRM)
async def confirm_horoscope_state(message: Message, state: FSMContext):
    # Этот хендлер не используется, т.к. подтверждение гороскопа идёт через callback
    pass


# ==================== ОБРАБОТЧИК main_menu (возврат в главное меню) — для callback ====================
# Он остаётся здесь, но callback обрабатывается позже


# ==================== ФУНКЦИИ-ОБРАБОТЧИКИ (без декораторов) ====================

async def start_horoscope(message: Message, state: FSMContext):
    """Получение гороскопа"""
    user_id = message.from_user.id
    is_subscribed = await check_subscription_db(user_id)
    lang = await get_user_language(user_id)

    # Если есть подписка – показываем подтверждение
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
            # Если данных нет – предлагаем заполнить (как обычно)
            await state.set_state(UserDataStates.WAITING_NAME)
            await message.answer(
                await get_text(user_id, 'horoscope_intro'),
                reply_markup=get_cancel_keyboard(lang)
            )
        return

    # Если подписки нет – проверяем лимит и генерируем сразу
    if not await can_use_feature_db(user_id, 'horoscope'):
        await message.answer(
            await get_text(user_id, 'horoscope_free_ready'),
            reply_markup=get_subscription_keyboard(lang)
        )
        return

    user_data = await get_user_data(user_id)
    if user_data and user_data.get('name'):
        if not gemini_service:
            await message.answer(await get_text(user_id, 'error_service_unavailable'))
            return

        status_msg = await message.answer(await get_text(user_id, 'horoscope_status_planets'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'horoscope_status_chart'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'horoscope_status_analyze'))
        await asyncio.sleep(1)

        today = datetime.now().strftime("%d.%m.%Y")
        horoscope = gemini_service.generate_horoscope(user_data, today, lang)
        await save_message_to_archive(user_id, 'horoscope', horoscope)
        await mark_feature_used_db(user_id, 'horoscope')
        await status_msg.delete()
        result_template = await get_text(user_id, 'horoscope_result')
        result_text = result_template.format(date=today, horoscope=horoscope)
        await send_long_message(message, result_text)

        if not is_subscribed:
            await message.answer(
                await get_text(user_id, 'horoscope_promo'),
                reply_markup=get_subscription_promo_keyboard(lang)
            )
    else:
        await state.set_state(UserDataStates.WAITING_NAME)
        await message.answer(
            await get_text(user_id, 'horoscope_intro'),
            reply_markup=get_cancel_keyboard(lang)
        )


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

    status_msg = await callback.message.answer(await get_text(user_id, 'horoscope_status_planets'))
    await asyncio.sleep(1)
    await status_msg.edit_text(await get_text(user_id, 'horoscope_status_chart'))
    await asyncio.sleep(1)
    await status_msg.edit_text(await get_text(user_id, 'horoscope_status_analyze'))
    await asyncio.sleep(1)

    today = datetime.now().strftime("%d.%m.%Y")
    horoscope = gemini_service.generate_horoscope(user_data, today, lang)
    await save_message_to_archive(user_id, 'horoscope', horoscope)
    await status_msg.delete()
    result_template = await get_text(user_id, 'horoscope_result')
    result_text = result_template.format(date=today, horoscope=horoscope)
    await send_long_message(callback.message, result_text)

    await state.clear()
    await callback.message.answer(" ", reply_markup=get_main_menu(lang))


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
    """Использовать сохранённые данные для нумерологии"""
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

            await status_msg.delete()
            result_template = await get_text(user_id, 'numerology_result')
            result_text = result_template.format(result=result)
            await send_long_message(callback.message, result_text)
        else:
            await status_msg.edit_text(await get_text(user_id, 'error_service_unavailable'))
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
    finally:
        numerology_data.pop(user_id, None)


@dp.callback_query(F.data == "numerology_fill_new_data")
async def numerology_fill_new_data(callback: CallbackQuery, state: FSMContext):
    """Заполнить новые данные для нумерологии"""
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
    """Обработка оплаты нумерологии"""
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
        amount=888.00,
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
    """Подтверждение данных для нумерологии"""
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

            await status_msg.delete()
            result_template = await get_text(user_id, 'numerology_result')
            result_text = result_template.format(result=result)
            await send_long_message(callback.message, result_text)
        else:
            await status_msg.edit_text(await get_text(user_id, 'error_service_unavailable'))
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
    finally:
        numerology_data.pop(user_id, None)
        await state.clear()   # <-- ОБЯЗАТЕЛЬНО сбрасываем состояние


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
    """Использовать сохранённые данные для астрологии"""
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
            parameters_text = calculator.get_display_parameters(lang)
            prompt = calculator.build_prompt(lang)
            interpretation = gemini_service.send_raw_prompt(prompt, lang)

            template = await get_text(user_id, 'astrology_result')
            final_message = template.format(
                parameters=parameters_text,
                interpretation=interpretation
            )
            await save_message_to_archive(user_id, 'astrology', final_message)
            await add_astrology_count(user_id, -1)

            await status_msg.delete()
            await send_long_message(callback.message, final_message)
        else:
            await status_msg.edit_text(await get_text(user_id, 'error_service_unavailable'))
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
    finally:
        astrology_data.pop(user_id, None)


@dp.callback_query(F.data == "astrology_fill_new_data")
async def astrology_fill_new_data(callback: CallbackQuery, state: FSMContext):
    """Заполнить новые данные для астрологии"""
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
    """Обработка оплаты астрологии"""
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
        amount=999.00,
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
    """Подтверждение данных для астрологии"""
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
            parameters_text = calculator.get_display_parameters(lang)
            prompt = calculator.build_prompt(lang)
            interpretation = gemini_service.send_raw_prompt(prompt, lang)

            template = await get_text(user_id, 'astrology_result')
            final_message = template.format(
                parameters=parameters_text,
                interpretation=interpretation
            )
            await save_message_to_archive(user_id, 'astrology', final_message)
            await add_astrology_count(user_id, -1)

            await status_msg.delete()
            await send_long_message(callback.message, final_message)
        else:
            await status_msg.edit_text(await get_text(user_id, 'error_service_unavailable'))
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
    finally:
        astrology_data.pop(user_id, None)
        await state.clear()   # <-- ОБЯЗАТЕЛЬНО сбрасываем состояние


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
    """Начать заполнение профиля"""
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
    """Начать смену часового пояса"""
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
        reply_markup=get_main_menu(lang)
    )

    expert_chat_id = os.getenv('EXPERT_CHAT_ID')
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
        except Exception as e:
            logger.error(f"Ошибка отправки эксперту: {e}")


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
        amount=333.00,
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
    """Показать полное сообщение из архива"""
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
            'natal_chart': await get_text(user_id, 'type_horoscope'),  # если используется
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
    await callback.message.delete()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await callback.message.answer(
        " ",
        reply_markup=get_main_menu(lang)
    )


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
    await callback.message.answer(" ", reply_markup=get_main_menu(lang))


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

    # ---- Режим редактирования профиля (изменение всех данных) ----
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

    # ---- Режим заполнения профиля через кнопку "Заполнить и Сохранить" ----
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

    # ---- Режим смены часового пояса (отдельная кнопка) ----
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

    # ---- Обычный режим (первое заполнение) ----
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

    status_msg = await callback.message.answer(await get_text(user_id, 'horoscope_status_planets'))
    await asyncio.sleep(1)
    await status_msg.edit_text(await get_text(user_id, 'horoscope_status_chart'))
    await asyncio.sleep(1)
    await status_msg.edit_text(await get_text(user_id, 'horoscope_status_analyze'))
    await asyncio.sleep(1)

    today = datetime.now().strftime("%d.%m.%Y")
    horoscope = gemini_service.generate_horoscope(temp_data, today, lang)
    await mark_feature_used_db(user_id, 'horoscope')
    await save_message_to_archive(user_id, 'horoscope', horoscope)
    await status_msg.delete()
    result_template = await get_text(user_id, 'horoscope_result')
    result_text = result_template.format(date=today, horoscope=horoscope)
    await callback.message.answer(result_text)

    await state.clear()

    if not await check_subscription_db(user_id):
        await callback.message.answer(
            await get_text(user_id, 'horoscope_promo'),
            reply_markup=get_subscription_promo_keyboard(lang)
        )

    await callback.message.answer(" ", reply_markup=get_main_menu(lang))


@dp.callback_query(F.data == "close_subscription")
async def close_subscription(callback: CallbackQuery):
    """Закрывает сообщение с подпиской без лишних сообщений"""
    await callback.answer()
    await callback.message.delete()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await callback.message.answer(" ", reply_markup=get_main_menu(lang))


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

async def send_long_message(message: Message, text: str, max_length: int = 4096):
    if len(text) <= max_length:
        await message.answer(text)
        return

    parts = []
    current_part = ""

    for line in text.split('\n'):
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

    for i, part in enumerate(parts, 1):
        if i == 1:
            await message.answer(part)
        else:
            user_id = message.from_user.id
            template = await get_text(user_id, 'continuation')
            continuation_text = template.format(i=i, total=len(parts), text=part)
            await message.answer(continuation_text)


# ==================== ОБЩИЙ ОБРАБОТЧИК ТЕКСТОВЫХ КОМАНД (только если нет активного состояния) ====================

@dp.message(F.text)
async def handle_menu_commands(message: Message, state: FSMContext):
    """
    Обрабатывает текстовые команды главного меню.
    Срабатывает ТОЛЬКО если нет активного FSM-состояния.
    """
    current_state = await state.get_state()
    if current_state is not None:
        # Если состояние активно, пропускаем сообщение (оно должно быть обработано хендлером состояния)
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
        # Обработка кнопки переключения языка уже есть отдельно, но продублируем на всякий случай
        await change_language(message)
    else:
        # Если текст не совпал ни с одной командой, передаём в обработчик неизвестных
        await handle_unknown(message)


# ==================== ОБРАБОТЧИК НЕИЗВЕСТНЫХ СООБЩЕНИЙ ====================

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
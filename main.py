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
    get_subscription_promo_keyboard,
    get_subscription_payment_keyboard, get_fill_profile_keyboard,
    get_support_keyboard, get_horoscope_confirm_keyboard,
)
from bot.states.states import UserDataStates, CompatibilityStates, NumerologyStates, AstrologyStates, HoroscopeStates
from bot.utils.zodiac import calculate_zodiac_sign, get_zodiac_emoji
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
    get_archive_message
)
from bot.scheduler import setup_scheduler, send_daily_horoscopes
from asgiref.sync import sync_to_async
from core.models import User
from bot.yookassa_client import yookassa
from bot.db import save_payment_db, activate_subscription_db, add_numerology_count, add_astrology_count
from bot.calculators.astrology_calculator import AstrologyCalculator

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
except Exception as e:
    logger.error(f"❌ Ошибка инициализации Gemini: {e}")
    gemini_service = None

numerology_data = {}
astrology_data = {}

def format_profile_data(data: dict) -> str:
    """Форматирует данные пользователя для отображения"""
    gender_display = 'Мужской' if data.get('gender') == 'M' else 'Женский' if data.get('gender') == 'F' else 'Не указан'
    zodiac_emoji = get_zodiac_emoji(data.get('zodiac', 'Неизвестно'))
    timezone = data.get('timezone_offset', 3)
    return (
        f"👤 Имя: {data.get('name', 'Не указано')}\n"
        f"📅 Дата рождения: {data.get('birth_date', 'Не указана')}\n"
        f"🕒 Время рождения: {data.get('birth_time', 'Не указано')}\n"
        f"📍 Место рождения: {data.get('birth_place', 'Не указано')}\n"
        f"👤 Пол: {gender_display}\n"
        f"{zodiac_emoji} Знак зодиака: {data.get('zodiac', 'Неизвестно')}\n"
        f"🕒 Часовой пояс: UTC+{timezone}"
    )

# ==================== ОБРАБОТЧИКИ КОМАНД ====================

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

    await message.answer_photo(
        photo=FSInputFile(photo_path),
        caption=welcome_text,
        reply_markup=get_main_menu(),
        parse_mode="HTML"
    )


@dp.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    """Показать главное меню"""
    await state.clear()
    await message.answer(
        " ",
        reply_markup=get_main_menu()
    )


# ==================== НАЧАЛО СБОРА ДАННЫХ ДЛЯ ГОРОСКОПА ====================

@dp.message(F.text == "🔮 Гороскоп на сегодня")
async def start_horoscope(message: Message, state: FSMContext):
    """Получение гороскопа"""
    user_id = message.from_user.id
    is_subscribed = await check_subscription_db(user_id)

    # Если есть подписка – показываем подтверждение
    if is_subscribed:
        user_data = await get_user_data(user_id)
        if user_data and user_data.get('name'):
            zodiac_emoji = get_zodiac_emoji(user_data.get('zodiac', 'Неизвестно'))
            profile_text = (
                f"🔮 Гороскоп на сегодня!\n\n"
                f"Ваши данные:\n"
                f"👤 Имя: {user_data.get('name', 'Не указано')}\n"
                f"📅 Дата рождения: {user_data.get('birth_date', 'Не указана')}\n"
                f"🕒 Время рождения: {user_data.get('birth_time', 'Не указано')}\n"
                f"📍 Место рождения: {user_data.get('birth_place', 'Не указано')}\n"
                f"{zodiac_emoji} Знак зодиака: {user_data.get('zodiac', 'Неизвестно')}"
            )
            await state.set_state(HoroscopeStates.CONFIRM)
            await message.answer(
                profile_text,
                reply_markup=get_horoscope_confirm_keyboard()
            )
        else:
            # Если данных нет – предлагаем заполнить (как обычно)
            await state.set_state(UserDataStates.WAITING_NAME)
            await message.answer(
                "🔮 Давайте познакомимся!\n\n"
                "✨ Чтобы составить персональный прогноз,\n"
                "мне нужно немного узнать о вас.\n"
                "Это займет меньше минуты.\n\n"
                "❓ Как вас зовут?",
                reply_markup=get_cancel_keyboard()
            )
        return

    # Если подписки нет – проверяем лимит и генерируем сразу
    if not await can_use_feature_db(user_id, 'horoscope'):
        await message.answer(
            "✨ Сегодняшний бесплатный прогноз уже готов.\n\n"
            "Получайте новые прогнозы без ограничений\n"
            "за 333 ₽ в месяц.",
            reply_markup=get_subscription_keyboard()
        )
        return

    user_data = await get_user_data(user_id)
    if user_data and user_data.get('name'):
        if not gemini_service:
            await message.answer("❌ Сервис астролога временно недоступен.")
            return

        status_msg = await message.answer("✨ Изучаю положение планет...")
        await asyncio.sleep(1)
        await status_msg.edit_text("🌙 Строю натальную карту...")
        await asyncio.sleep(1)
        await status_msg.edit_text("⭐ Анализирую влияние созвездий...")
        await asyncio.sleep(1)

        today = datetime.now().strftime("%d.%m.%Y")
        horoscope = gemini_service.generate_horoscope(user_data, today)
        await save_message_to_archive(user_id, 'horoscope', horoscope)
        await mark_feature_used_db(user_id, 'horoscope')
        await status_msg.delete()
        await send_long_message(message, f"🔮 Ваш гороскоп на {today}\n\n{horoscope}")

        if not is_subscribed:
            await message.answer(
                "✨ Понравился прогноз?\n\n"
                "Получайте персональный гороскоп автоматически каждое утро в 8:00 и используйте Совместимость без ограничений.",
                reply_markup=get_subscription_promo_keyboard()
            )
    else:
        await state.set_state(UserDataStates.WAITING_NAME)
        await message.answer(
            "🔮 Давайте познакомимся!\n\n"
            "✨ Чтобы составить персональный прогноз,\n"
            "мне нужно немного узнать о вас.\n"
            "Это займет меньше минуты.\n\n"
            "❓ Как вас зовут?",
            reply_markup=get_cancel_keyboard()
        )


# ==================== ШАГ 1: ИМЯ ====================

@dp.message(UserDataStates.WAITING_NAME)
async def process_name(message: Message, state: FSMContext):
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
        await message.answer(
            f"✏️ Текущая дата рождения: {old.get('birth_date', 'не указана')}\n\n"
            "Введите новую дату в формате ДД.ММ.ГГГГ или нажмите «Пропустить».",
            reply_markup=get_skip_keyboard()
        )
        logger.info(f"📝 Шаг ИМЯ, new_data после: {new_data}")
    else:
        if len(message.text) < 2:
            await message.answer("❌ Имя должно содержать хотя бы 2 символа. Попробуйте еще раз:")
            return
        await state.update_data(name=message.text)
        await state.set_state(UserDataStates.WAITING_BIRTH_DATE)
        await message.answer(
            "📅 Шаг 2 из 5\n\n"
            "Укажите дату рождения в формате:\n"
            "ДД.ММ.ГГГГ\n\n"
            "Например: 15.03.1990"
        )


# ==================== ШАГ 2: ДАТА РОЖДЕНИЯ ====================

@dp.message(UserDataStates.WAITING_BIRTH_DATE)
async def process_birth_date(message: Message, state: FSMContext):
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
                await message.answer(
                    "❌ Неверная дата! Попробуйте еще раз.",
                    reply_markup=get_cancel_keyboard()  # <-- добавлено
                )
                return
        else:
            logger.info("📝 Шаг ДАТА, дата не изменена")

        await state.update_data(new_data=new_data)

        await state.set_state(UserDataStates.WAITING_BIRTH_TIME)
        await message.answer(
            f"✏️ Текущее время рождения: {old.get('birth_time', 'не указано')}\n\n"
            "Введите новое время в формате ЧЧ:ММ или нажмите «Пропустить».",
            reply_markup=get_skip_keyboard()
        )
        logger.info(f"📝 Шаг ДАТА, new_data после: {new_data}")
    else:
        date_pattern = r'^\d{2}\.\d{2}\.\d{4}$'
        if not re.match(date_pattern, message.text):
            await message.answer(
                "❌ Неверный формат!\n\n"
                "Используйте формат ДД.ММ.ГГГГ\n"
                "Например: 15.03.1990",
                reply_markup=get_cancel_keyboard()
            )
            return
        try:
            birth_date = datetime.strptime(message.text, "%d.%m.%Y")
            zodiac = calculate_zodiac_sign(birth_date.day, birth_date.month)
            await state.update_data(birth_date=message.text, zodiac=zodiac)
            await state.set_state(UserDataStates.WAITING_BIRTH_TIME)
            await message.answer(
                f"✅ Отлично! Знак зодиака: {get_zodiac_emoji(zodiac)} {zodiac}\n\n"
                "🕒 Шаг 3 из 5\n\n"
                "Укажите точное время рождения в формате:\n"
                "ЧЧ:ММ\n\n"
                "Например: 15:30\n"
                "Если не знаете, напишите 00:00",
                reply_markup=get_cancel_keyboard()
            )
        except ValueError:
            await message.answer(
                "❌ Неверная дата! Попробуйте еще раз:",
                reply_markup=get_cancel_keyboard()  # <-- добавлено
            )


# ==================== ШАГ 3: ВРЕМЯ РОЖДЕНИЯ ====================

@dp.message(UserDataStates.WAITING_BIRTH_TIME)
async def process_birth_time(message: Message, state: FSMContext):
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
                await message.answer("❌ Неверное время! Попробуйте еще раз.")
                return
        else:
            logger.info("📝 Шаг ВРЕМЯ, время не изменено")

        await state.update_data(new_data=new_data)

        await state.set_state(UserDataStates.WAITING_BIRTH_PLACE)
        await message.answer(
            f"✏️ Текущее место рождения: {old.get('birth_place', 'не указано')}\n\n"
            "Введите новое место (город, страна) или нажмите «Пропустить».",
            reply_markup=get_skip_keyboard()
        )
        logger.info(f"📝 Шаг ВРЕМЯ, new_data после: {new_data}")
    else:
        time_pattern = r'^\d{2}:\d{2}$'
        if not re.match(time_pattern, message.text):
            await message.answer(
                "❌ Неверный формат!\n\n"
                "Используйте формат ЧЧ:ММ\n"
                "Например: 15:30",
                reply_markup=get_cancel_keyboard()
            )
            return
        try:
            datetime.strptime(message.text, "%H:%M")
            await state.update_data(birth_time=message.text)
            await state.set_state(UserDataStates.WAITING_BIRTH_PLACE)
            await message.answer(
                "📍 Шаг 4 из 5\n\n"
                "Укажите место рождения:\n"
                "Город, Страна\n\n"
                "Например: Москва, Россия",
                reply_markup=get_cancel_keyboard()  # <-- добавлено
            )
        except ValueError:
            await message.answer(
                "❌ Неверное время! Попробуйте еще раз:",
                reply_markup=get_cancel_keyboard()
            )


# ==================== ШАГ 4: МЕСТО РОЖДЕНИЯ ====================

@dp.message(UserDataStates.WAITING_BIRTH_PLACE)
async def process_birth_place(message: Message, state: FSMContext):
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

        await message.answer(
            f"✏️ Текущий пол: {gender_display}\n\n"
            "Введите новый пол (М или Ж) или нажмите «Пропустить».",
            reply_markup=get_skip_keyboard()
        )
        logger.info(f"📝 Шаг МЕСТО, new_data после: {new_data}")
    else:
        if len(message.text) < 3:
            await message.answer(
                "❌ Укажите город и страну (минимум 3 символа):",
                reply_markup=get_cancel_keyboard()
            )
            return
        await state.update_data(birth_place=message.text)
        await state.set_state(UserDataStates.WAITING_GENDER)
        await message.answer(
            "👤 Шаг 5 из 5 (последний!)\n\n"
            "Укажите ваш пол:\n"
            "М - мужской\n"
            "Ж - женский\n\n"
            "Напишите: М или Ж",
            reply_markup=get_cancel_keyboard()
        )


# ==================== ШАГ 5: ПОЛ ====================

@dp.message(UserDataStates.WAITING_GENDER)
async def process_gender(message: Message, state: FSMContext):
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

        # Сохраняем обновлённые данные в состояние
        await state.update_data(new_data=new_data)

        # Переходим к выбору часового пояса (с флагом is_edit=True)
        await state.set_state(UserDataStates.WAITING_TIMEZONE)
        await message.answer(
            "🕒 Выберите ваш часовой пояс:",
            reply_markup=get_timezone_keyboard()
        )
        return

    # ----- Обычный режим (первое заполнение) -----
    if gender not in ["М", "Ж"]:
        await message.answer(
            "❌ Пожалуйста, напишите только одну букву:\nМ - мужской\nЖ - женский",
            reply_markup=get_cancel_keyboard()  # <-- добавлено
        )
        return

    db_gender = 'M' if gender == 'М' else 'F'
    data = await state.get_data()
    data['gender'] = db_gender
    await state.update_data(temp_data=data)

    await state.set_state(UserDataStates.WAITING_TIMEZONE)
    await message.answer(
        "🕒 Выберите ваш часовой пояс:\nЭто нужно для точного расчёта гороскопа и отправки прогнозов.",
        reply_markup=get_timezone_keyboard()
    )


@dp.callback_query(F.data == "confirm_horoscope", HoroscopeStates.CONFIRM)
async def confirm_horoscope(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.delete()

    user_id = callback.from_user.id
    user_data = await get_user_data(user_id)

    if not user_data or not user_data.get('name'):
        await callback.message.answer("❌ Данные не найдены. Начните заново.")
        await state.clear()
        return

    if not gemini_service:
        await callback.message.answer("❌ Сервис астролога временно недоступен.")
        await state.clear()
        return

    status_msg = await callback.message.answer("✨ Изучаю положение планет...")
    await asyncio.sleep(1)
    await status_msg.edit_text("🌙 Строю натальную карту...")
    await asyncio.sleep(1)
    await status_msg.edit_text("⭐ Анализирую влияние созвездий...")
    await asyncio.sleep(1)

    today = datetime.now().strftime("%d.%m.%Y")
    horoscope = gemini_service.generate_horoscope(user_data, today)
    await save_message_to_archive(user_id, 'horoscope', horoscope)
    await status_msg.delete()
    await send_long_message(callback.message, f"🔮 Ваш гороскоп на {today}\n\n{horoscope}")

    await state.clear()
    # Показываем главное меню
    await callback.message.answer(" ", reply_markup=get_main_menu())


# ==================== ОТМЕНА ====================

@dp.callback_query(F.data == "cancel")
async def cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer(
        "❌ Сбор данных отменен.\n"
        "Вы можете начать заново, нажав на нужную кнопку в меню",
        reply_markup=get_main_menu()
    )
    await callback.answer()


@dp.callback_query(F.data == "cancel_horoscope", HoroscopeStates.CONFIRM)
async def cancel_horoscope(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.delete()
    await state.clear()
    await callback.message.answer(" ", reply_markup=get_main_menu())


@dp.callback_query(F.data.startswith("tz_"), UserDataStates.WAITING_TIMEZONE)
async def process_timezone(callback: CallbackQuery, state: FSMContext):
    tz_offset = int(callback.data.split("_")[1])
    await callback.answer()

    state_data = await state.get_data()
    is_edit = state_data.get('is_edit', False)
    fill_mode = state_data.get('fill_mode', False)
    is_timezone_edit = state_data.get('is_timezone_edit', False)
    user_id = callback.from_user.id

    # ---- Режим редактирования профиля (изменение всех данных) ----
    if is_edit:
        new_data = state_data.get('new_data', {})
        new_data['timezone_offset'] = tz_offset
        await save_user_data(user_id, new_data)
        await state.clear()
        profile_text = format_profile_data(new_data)
        await callback.message.delete()
        await callback.message.answer(
            f"✅ Данные успешно обновлены!\n\n{profile_text}",
            reply_markup=get_profile_keyboard()
        )
        return

    # ---- Режим заполнения профиля через кнопку "Заполнить и Сохранить" ----
    if fill_mode:
        temp_data = state_data.get('temp_data', {})
        temp_data['timezone_offset'] = tz_offset
        await save_user_data(user_id, temp_data)
        await state.clear()
        profile_text = format_profile_data(temp_data)
        await callback.message.delete()
        await callback.message.answer(
            f"✅ Данные сохранены!\n\n{profile_text}",
            reply_markup=get_profile_keyboard()
        )
        return

    # ---- Режим смены часового пояса (отдельная кнопка) ----
    if is_timezone_edit:
        from core.models import User
        from asgiref.sync import sync_to_async
        user = await sync_to_async(User.objects.get)(telegram_id=user_id)
        user.timezone_offset = tz_offset
        await sync_to_async(user.save)()
        await state.clear()
        user_data = await get_user_data(user_id)
        profile_text = format_profile_data(user_data)
        await callback.message.delete()
        await callback.message.answer(
            f"✅ Часовой пояс обновлён!\n\n{profile_text}",
            reply_markup=get_profile_keyboard()
        )
        return

    # ---- Обычный режим (первое заполнение) ----
    temp_data = state_data.get('temp_data', {})
    temp_data['timezone_offset'] = tz_offset
    await state.update_data(temp_data=temp_data)

    profile_text = format_profile_data(temp_data)
    privacy_url = os.getenv('PRIVACY_POLICY_URL', 'ссылка на политику конфиденциальности')

    save_text = (
        f"🔐 Сохранить данные в ваш профиль чтобы не заполнять их каждый раз?\n\n"
        f"{profile_text}\n\n"
        f"📄 Нажимая «**Сохранить**», вы даёте согласие на обработку персональных данных в соответствии с "
        f"[Политикой конфиденциальности]({privacy_url})."
    )

    await state.set_state(UserDataStates.ASKING_SAVE)
    await callback.message.delete()
    await callback.message.answer(
        save_text,
        reply_markup=get_save_data_keyboard(),
        parse_mode="Markdown"
    )


@dp.callback_query(F.data.startswith("zodiac_"))
async def process_zodiac_choice(callback: CallbackQuery, state: FSMContext):
    zodiac = callback.data.replace("zodiac_", "")
    await state.update_data(zodiac=zodiac)
    await state.set_state(UserDataStates.WAITING_BIRTH_DATE)

    await callback.message.edit_text(
        f"✅ Выбран знак: {get_zodiac_emoji(zodiac)} {zodiac}\n\n"
        "📅 Теперь укажите дату рождения в формате ДД.ММ.ГГГГ"
    )
    await callback.answer()

@dp.callback_query(F.data == "save_data", UserDataStates.ASKING_SAVE)
async def save_data(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    state_data = await state.get_data()
    temp_data = state_data.get('temp_data', {})
    user_id = callback.from_user.id

    # Сохраняем все данные в БД
    await save_user_data(user_id, temp_data)

    # Очищаем состояние
    await state.clear()

    # Показываем сообщение с профилем и кнопкой "Отмена"
    profile_text = format_profile_data(temp_data)
    await callback.message.edit_text(
        f"✅ Данные сохранены!\n\n{profile_text}\n\n"
        "Чтобы продолжить нажмите ещё раз \"🔮 Гороскоп на сегодня\".",
        reply_markup=get_after_save_keyboard()
    )

@dp.callback_query(F.data == "dont_save_data", UserDataStates.ASKING_SAVE)
async def dont_save_data(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    state_data = await state.get_data()
    temp_data = state_data.get('temp_data', {})
    user_id = callback.from_user.id

    # Удаляем сообщение с вопросом
    await callback.message.delete()

    # Показываем статус
    status_msg = await callback.message.answer("✨ Изучаю положение планет...")
    await asyncio.sleep(1)
    await status_msg.edit_text("🌙 Строю натальную карту...")
    await asyncio.sleep(1)
    await status_msg.edit_text("⭐ Анализирую влияние созвездий...")
    await asyncio.sleep(1)

    # Генерируем гороскоп на основе временных данных
    today = datetime.now().strftime("%d.%m.%Y")
    horoscope = gemini_service.generate_horoscope(temp_data, today)

    # Отмечаем использование гороскопа (для лимитов)
    await mark_feature_used_db(user_id, 'horoscope')

    # Сохраняем в архив
    await save_message_to_archive(user_id, 'horoscope', horoscope)

    # Удаляем статусное сообщение и отправляем результат
    await status_msg.delete()
    await callback.message.answer(
        f"🔮 Ваш гороскоп на {today}\n\n{horoscope}"
    )

    # Очищаем состояние
    await state.clear()

    # Если нет подписки – показываем промо с инлайн-кнопкой
    if not await check_subscription_db(user_id):
        await callback.message.answer(
            "✨ Понравился прогноз?\n\n"
            "Получайте персональный гороскоп автоматически каждое утро в 8:00 и используйте Совместимость без ограничений.",
            reply_markup=get_subscription_promo_keyboard()
        )

    # Показываем главное меню с минимальным текстом (пробел)
    await callback.message.answer(" ", reply_markup=get_main_menu())

@dp.callback_query(F.data == "close_subscription")
async def close_subscription(callback: CallbackQuery):
    """Закрывает сообщение с подпиской без лишних сообщений"""
    await callback.answer()
    await callback.message.delete()
    await callback.message.answer(
        " ",
        reply_markup=get_main_menu()
    )


# ==================== СОВМЕСТИМОСТЬ ====================

@dp.message(F.text == "💕 Совместимость")
async def start_compatibility(message: Message, state: FSMContext):
    user_id = message.from_user.id

    # Проверка лимита
    if not await can_use_feature_db(user_id, 'compatibility'):
        await message.answer(
            "✨ Сегодняшний бесплатный анализ совместимости уже использован.\n\n"
            "Получайте неограниченный доступ\n"
            "за 333 ₽ в месяц.",
            reply_markup=get_subscription_keyboard()
        )
        return

    user_data = await get_user_data(user_id)

    if user_data and user_data.get('name'):
        # Данные есть – предлагаем использовать их или заполнить заново
        zodiac_emoji = get_zodiac_emoji(user_data.get('zodiac', 'Неизвестно'))

        profile_text = (
            f"💕 Анализ совместимости\n\n"
            f"👤 Ваши данные (Человек 1):\n"
            f"Имя: {user_data.get('name', 'Не указано')}\n"
            f"📅 Дата рождения: {user_data.get('birth_date', 'Не указана')}\n"
            f"🕒 Время рождения: {user_data.get('birth_time', 'Не указано')}\n"
            f"📍 Место рождения: {user_data.get('birth_place', 'Не указано')}\n"
            f"👤 Пол: {'Мужской' if user_data.get('gender') == 'M' else 'Женский' if user_data.get('gender') == 'F' else 'Не указан'}\n"
            f"{zodiac_emoji} Знак зодиака: {user_data.get('zodiac', 'Неизвестно')}\n\n"
            "Хотите использовать эти данные для анализа совместимости?"
        )

        await message.answer(
            profile_text,
            reply_markup=get_compatibility_keyboard()
        )

        # Сохраняем данные в состояние для дальнейшего использования
        await state.update_data(person1_data=user_data)
        await state.set_state(CompatibilityStates.CONFIRM_DATA)

    else:
        # Данных нет – начинаем сбор
        await state.set_state(CompatibilityStates.WAITING_PERSON1_NAME)
        await message.answer(
            "💕 Анализ совместимости двух людей\n\n"
            "Узнайте, насколько вы подходите друг другу в общении, работе, дружбе, семье или отношениях.\n\n"
            "Вы получите:\n"
            "💫 Энергетическую совместимость\n"
            "🔥 Психологическую совместимость\n"
            "💼 Финансовую и деловую совместимость\n"
            "❤️ Любовную совместимость\n"
            "🌿 Кармическую связь\n"
            "📅 Прогноз на сегодня\n"
            "⭐ Итоговую оценку и советы\n\n"
            "✨ Персональный разбор готовится меньше минуты.\n\n"
            "💕 Давайте заполним данные для анализа совместимости.\n"
            "Сначала введите имя человека 1 (это вы):",
            reply_markup=get_cancel_keyboard()
        )


@dp.callback_query(F.data == "use_my_data")
async def use_my_data(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id

    data = await state.get_data()
    person1 = data.get('person1_data', {})

    if not person1:
        await callback.message.answer(
            "❌ Данные не найдены. Пожалуйста, заполните заново.",
            reply_markup=get_main_menu()
        )
        await state.clear()
        return

    await state.update_data(person1=person1)

    await state.set_state(CompatibilityStates.WAITING_PERSON2_NAME)

    await callback.message.answer(
        "✅ Отлично! Данные человека 1 сохранены.\n\n"
        "Теперь введите данные человека 2:\n"
        "❓ Как зовут человека 2?",
        reply_markup=get_cancel_keyboard()
    )


@dp.callback_query(F.data == "fill_person1")
async def fill_person1(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await state.set_state(CompatibilityStates.WAITING_PERSON1_NAME)

    await callback.message.answer(
        "✏️ Введите имя человека 1:",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


# ==================== СБОР ДАННЫХ ЧЕЛОВЕКА 1 ДЛЯ СОВМЕСТИМОСТИ ====================

@dp.message(CompatibilityStates.WAITING_PERSON1_NAME)
async def process_person1_name(message: Message, state: FSMContext):
    if len(message.text) < 2:
        await message.answer("❌ Имя должно содержать хотя бы 2 символа:")
        return

    await state.update_data(person1_name=message.text)
    await state.set_state(CompatibilityStates.WAITING_PERSON1_BIRTH_DATE)

    await message.answer(
        f"✅ Имя: {message.text}\n\n"
        "📅 Введите дату рождения человека 1 в формате ДД.ММ.ГГГГ\n"
        "Например: 15.03.1990",
        reply_markup=get_cancel_keyboard()
    )


@dp.message(CompatibilityStates.WAITING_PERSON1_BIRTH_DATE)
async def process_person1_birth_date(message: Message, state: FSMContext):
    date_pattern = r'^\d{2}\.\d{2}\.\d{4}$'

    if not re.match(date_pattern, message.text):
        await message.answer(
            "❌ Неверный формат! Используйте ДД.ММ.ГГГГ\n"
            "Например: 15.03.1990",
            reply_markup=get_cancel_keyboard()
        )
        return

    try:
        birth_date = datetime.strptime(message.text, "%d.%m.%Y")
        zodiac = calculate_zodiac_sign(birth_date.day, birth_date.month)

        await state.update_data(
            person1_birth_date=message.text,
            person1_zodiac=zodiac
        )
        await state.set_state(CompatibilityStates.WAITING_PERSON1_BIRTH_TIME)

        await message.answer(
            f"✅ Знак зодиака: {get_zodiac_emoji(zodiac)} {zodiac}\n\n"
            "🕒 Введите время рождения человека 1 (ЧЧ:ММ)\n"
            "Например: 15:30\n"
            "Если не знаете - напишите 00:00",
            reply_markup=get_cancel_keyboard()
        )

    except ValueError:
        await message.answer(
            "❌ Неверная дата! Попробуйте еще раз:",
            reply_markup=get_cancel_keyboard()
        )


@dp.message(CompatibilityStates.WAITING_PERSON1_BIRTH_TIME)
async def process_person1_birth_time(message: Message, state: FSMContext):
    time_pattern = r'^\d{2}:\d{2}$'

    if not re.match(time_pattern, message.text):
        await message.answer(
            "❌ Неверный формат! Используйте ЧЧ:ММ\n"
            "Например: 15:30",
            reply_markup=get_cancel_keyboard()
        )
        return

    try:
        datetime.strptime(message.text, "%H:%M")
        await state.update_data(person1_birth_time=message.text)
        await state.set_state(CompatibilityStates.WAITING_PERSON1_BIRTH_PLACE)

        await message.answer(
            "📍 Введите место рождения человека 1:\n"
            "Город, Страна\n"
            "Например: Москва, Россия",
            reply_markup=get_cancel_keyboard()
        )

    except ValueError:
        await message.answer(
            "❌ Неверное время! Попробуйте еще раз:",
            reply_markup=get_cancel_keyboard()
        )


@dp.message(CompatibilityStates.WAITING_PERSON1_BIRTH_PLACE)
async def process_person1_birth_place(message: Message, state: FSMContext):
    if len(message.text) < 3:
        await message.answer(
            "❌ Укажите город и страну (минимум 3 символа):",
            reply_markup=get_cancel_keyboard()
        )
        return

    await state.update_data(person1_birth_place=message.text)
    await state.set_state(CompatibilityStates.WAITING_PERSON1_GENDER)

    await message.answer(
        "👤 Укажите пол человека 1:\n"
        "М - мужской\n"
        "Ж - женский\n\n"
        "Напишите: М или Ж",
        reply_markup=get_cancel_keyboard()
    )


@dp.message(CompatibilityStates.WAITING_PERSON1_GENDER)
async def process_person1_gender(message: Message, state: FSMContext):
    gender = message.text.upper()

    if gender not in ["М", "Ж"]:
        await message.answer(
            "❌ Напишите М или Ж:",
            reply_markup=get_cancel_keyboard()
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

    await message.answer(
        f"✅ Данные человека 1 сохранены!\n\n"
        f"👤 Имя: {person1['name']}\n"
        f"📅 Дата рождения: {person1['birth_date']}\n"
        f"🕒 Время рождения: {person1['birth_time']}\n"
        f"📍 Место рождения: {person1['birth_place']}\n"
        f"👤 Пол: {'Мужской' if gender == 'М' else 'Женский'}\n"
        f"{get_zodiac_emoji(person1['zodiac'])} Знак зодиака: {person1['zodiac']}\n\n"
        "💕 Теперь введите данные человека 2.\n\n"
        "❓ Как зовут человека 2?",
        reply_markup=get_cancel_keyboard()
    )


# ==================== СБОР ДАННЫХ ЧЕЛОВЕКА 2 ДЛЯ СОВМЕСТИМОСТИ ====================

@dp.message(CompatibilityStates.WAITING_PERSON2_NAME)
async def process_person2_name(message: Message, state: FSMContext):
    if len(message.text) < 2:
        await message.answer("❌ Имя должно содержать хотя бы 2 символа:")
        return

    await state.update_data(person2_name=message.text)
    await state.set_state(CompatibilityStates.WAITING_PERSON2_BIRTH_DATE)

    await message.answer(
        f"✅ Имя человека 2: {message.text}\n\n"
        "📅 Введите дату рождения человека 2 в формате ДД.ММ.ГГГГ",
        reply_markup=get_cancel_keyboard()
    )


@dp.message(CompatibilityStates.WAITING_PERSON2_BIRTH_DATE)
async def process_person2_birth_date(message: Message, state: FSMContext):
    date_pattern = r'^\d{2}\.\d{2}\.\d{4}$'

    if not re.match(date_pattern, message.text):
        await message.answer(
            "❌ Неверный формат! Используйте ДД.ММ.ГГГГ",
            reply_markup=get_cancel_keyboard()
        )
        return

    try:
        birth_date = datetime.strptime(message.text, "%d.%m.%Y")
        zodiac = calculate_zodiac_sign(birth_date.day, birth_date.month)

        await state.update_data(
            person2_birth_date=message.text,
            person2_zodiac=zodiac
        )
        await state.set_state(CompatibilityStates.WAITING_PERSON2_BIRTH_TIME)

        await message.answer(
            f"✅ Знак зодиака: {get_zodiac_emoji(zodiac)} {zodiac}\n\n"
            "🕒 Введите время рождения человека 2 (ЧЧ:ММ)\n"
            "Например: 02:15\n"
            "Если не знаете - напишите 00:00",
            reply_markup=get_cancel_keyboard()
        )

    except ValueError:
        await message.answer(
            "❌ Неверная дата! Попробуйте еще раз:",
            reply_markup=get_cancel_keyboard()
        )


@dp.message(CompatibilityStates.WAITING_PERSON2_BIRTH_TIME)
async def process_person2_birth_time(message: Message, state: FSMContext):
    time_pattern = r'^\d{2}:\d{2}$'

    if not re.match(time_pattern, message.text):
        await message.answer(
            "❌ Неверный формат! Используйте ЧЧ:ММ",
            reply_markup=get_cancel_keyboard()
        )
        return

    try:
        datetime.strptime(message.text, "%H:%M")
        await state.update_data(person2_birth_time=message.text)
        await state.set_state(CompatibilityStates.WAITING_PERSON2_BIRTH_PLACE)

        await message.answer(
            "📍 Введите место рождения человека 2:\n"
            "Город, Страна",
            reply_markup=get_cancel_keyboard()
        )

    except ValueError:
        await message.answer(
            "❌ Неверное время! Попробуйте еще раз:",
            reply_markup=get_cancel_keyboard()
        )


@dp.message(CompatibilityStates.WAITING_PERSON2_BIRTH_PLACE)
async def process_person2_birth_place(message: Message, state: FSMContext):
    if len(message.text) < 3:
        await message.answer(
            "❌ Укажите город и страну (минимум 3 символа):",
            reply_markup=get_cancel_keyboard()
        )
        return

    await state.update_data(person2_birth_place=message.text)
    await state.set_state(CompatibilityStates.WAITING_PERSON2_GENDER)

    await message.answer(
        "👤 Укажите пол человека 2:\n"
        "М - мужской\n"
        "Ж - женский\n\n"
        "Напишите: М или Ж",
        reply_markup=get_cancel_keyboard()
    )


@dp.message(CompatibilityStates.WAITING_PERSON2_GENDER)
async def process_person2_gender(message: Message, state: FSMContext):
    gender = message.text.upper()

    if gender not in ["М", "Ж"]:
        await message.answer(
            "❌ Напишите М или Ж:",
            reply_markup=get_cancel_keyboard()
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
            "❌ Данные человека 1 не найдены. Начните заново.",
            reply_markup=get_main_menu()
        )
        await state.clear()
        return

    await state.clear()

    zodiac1_emoji = get_zodiac_emoji(person1['zodiac'])
    zodiac2_emoji = get_zodiac_emoji(person2['zodiac'])

    summary_text = (
        f"💕 Данные для анализа совместимости\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 ЧЕЛОВЕК 1\n"
        f"Имя: {person1['name']}\n"
        f"📅 {person1['birth_date']}\n"
        f"🕒 {person1['birth_time']}\n"
        f"📍 {person1['birth_place']}\n"
        f"{zodiac1_emoji} {person1['zodiac']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 ЧЕЛОВЕК 2\n"
        f"Имя: {person2['name']}\n"
        f"📅 {person2['birth_date']}\n"
        f"🕒 {person2['birth_time']}\n"
        f"📍 {person2['birth_place']}\n"
        f"{zodiac2_emoji} {person2['zodiac']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        "✅ Данные собраны! Начинаю анализ совместимости... 🔮"
    )

    status_msg = await message.answer(summary_text)

    try:
        await status_msg.edit_text("✨ Изучаю совместимость знаков...")
        await asyncio.sleep(1)
        await status_msg.edit_text("💫 Анализирую натальные карты...")
        await asyncio.sleep(1)
        await status_msg.edit_text("⭐ Составляю прогноз совместимости...")
        await asyncio.sleep(1)

        if gemini_service:
            result = gemini_service.generate_compatibility_from_prompt(person1, person2)

            user_id = message.from_user.id

            # --- Отмечаем использование совместимости ---
            await mark_feature_used_db(user_id, 'compatibility')

            # --- Сохраняем в архив ---
            await save_message_to_archive(user_id, 'compatibility', result)

            # --- Удаляем статусное сообщение и отправляем результат ---
            await status_msg.delete()
            await send_long_message(message, f"💕 Анализ совместимости\n\n{result}")

            # --- Промо-сообщение, если нет подписки ---
            if not await check_subscription_db(user_id):
                await message.answer(
                    "✨ Понравился разбор?\n\n"
                    "Получайте Совместимость без ограничений и персональный гороскоп автоматически каждое утро в 8:00.",
                    reply_markup=get_subscription_promo_keyboard()
                )
        else:
            await status_msg.edit_text("❌ Сервис астролога временно недоступен.")

    except Exception as e:
        await status_msg.edit_text(f"❌ Произошла ошибка при анализе:\n{str(e)}")


# ==================== НУМЕРОЛОГИЯ ====================

@dp.message(F.text == "🔢 Нумерология")
async def start_numerology(message: Message, state: FSMContext):
    """Начало оформления нумерологии"""
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)

    if user_data and user_data.get('name'):
        zodiac_emoji = get_zodiac_emoji(user_data.get('zodiac', 'Неизвестно'))
        numer_count = user_data.get('numerology_count', 0)

        if numer_count > 0:
            profile_text = (
                f"🌌 Нумерология — познай себя\n\n"
                f"Ваши данные:\n"
                f"👤 Имя: {user_data.get('name', 'Не указано')}\n"
                f"📅 Дата рождения: {user_data.get('birth_date', 'Не указана')}\n"
                f"🕒 Время рождения: {user_data.get('birth_time', 'Не указано')}\n"
                f"📍 Место рождения: {user_data.get('birth_place', 'Не указано')}\n"
                f"{zodiac_emoji} Знак зодиака: {user_data.get('zodiac', 'Неизвестно')}\n\n"
                "Хотите получить числовой разбор?"
            )
            await message.answer(
                profile_text,
                reply_markup=get_numerology_confirm_keyboard()
            )
            await state.set_state(NumerologyStates.CONFIRM_DATA)
        else:
            await message.answer(
                "🔢 Раскройте свой код судьбы\n\n"
                "Узнайте, что скрывает ваша дата рождения:\n\n"
                "✨ Ваш характер и таланты\n"
                "🌌 Предназначение и кармическая задача\n"
                "💼 Деньги и карьерный путь\n"
                "❤️ Любовь и отношения\n"
                "🌿 Энергия и ресурсы\n"
                "⭐ Важные этапы жизни и советы\n\n"
                "💰 Стоимость: 888 ₽",
                reply_markup=get_numerology_payment_keyboard()
            )
            await state.set_state(NumerologyStates.PAYMENT)
    else:
        await state.set_state(NumerologyStates.WAITING_NAME)
        await message.answer(
            "🌌 Для расчёта нумерологии мне нужно узнать вас получше.\n\n"
            "❓ Как вас зовут?",
            reply_markup=get_cancel_keyboard()
        )


# ==================== НУМЕРОЛОГИЯ (ПОЛНЫЙ НАБОР) ====================

@dp.callback_query(F.data == "numerology_use_my_data")
async def numerology_use_my_data(callback: CallbackQuery, state: FSMContext):
    """Использовать сохранённые данные для нумерологии"""
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id
    data = await state.get_data()

    if not data.get('numerology_paid', False):
        await callback.message.answer(
            "⚠️ Сначала необходимо оплатить нумерологию.\n\n"
            "💰 Стоимость: 888 ₽",
            reply_markup=get_numerology_payment_keyboard()
        )
        await state.set_state(NumerologyStates.PAYMENT)
        return

    user_data_from_db = await get_user_data(user_id)
    if not user_data_from_db or not user_data_from_db.get('name'):
        await callback.message.answer(
            "❌ Данные не найдены. Пожалуйста, заполните заново.",
            reply_markup=get_main_menu()
        )
        await state.clear()
        return

    # Сохраняем с флагом is_manual=False (данные из профиля)
    numerology_data[user_id] = {
        'name': user_data_from_db.get('name'),
        'birth_date': user_data_from_db.get('birth_date'),
        'birth_time': user_data_from_db.get('birth_time'),
        'birth_place': user_data_from_db.get('birth_place'),
        'gender': user_data_from_db.get('gender'),
        'zodiac': user_data_from_db.get('zodiac'),
        'is_manual': False   # <-- флаг
    }

    await state.clear()

    zodiac_emoji = get_zodiac_emoji(user_data_from_db.get('zodiac', 'Неизвестно'))
    profile_text = (
        f"✅ Используем ваши данные:\n\n"
        f"👤 Имя: {user_data_from_db.get('name')}\n"
        f"📅 Дата рождения: {user_data_from_db.get('birth_date')}\n"
        f"🕒 Время рождения: {user_data_from_db.get('birth_time')}\n"
        f"📍 Место рождения: {user_data_from_db.get('birth_place')}\n"
        f"👤 Пол: {'Мужской' if user_data_from_db.get('gender') == 'M' else 'Женский'}\n"
        f"{zodiac_emoji} Знак зодиака: {user_data_from_db.get('zodiac')}\n\n"
        "🌌 Начинаю расчёт нумерологии... 🔮"
    )

    status_msg = await callback.message.answer(profile_text)

    try:
        await status_msg.edit_text("✨ Вычисляю числовой код судьбы...")
        await asyncio.sleep(1)
        await status_msg.edit_text("🔢 Анализирую числа жизненного пути...")
        await asyncio.sleep(1)
        await status_msg.edit_text("📊 Формирую полный разбор...")
        await asyncio.sleep(2)

        if gemini_service:
            result = gemini_service.generate_numerology(numerology_data[user_id])

            # Сохраняем в архив
            await save_message_to_archive(user_id, 'numerology', result)

            # Уменьшаем количество доступных нумерологий
            await add_numerology_count(user_id, -1)

            await status_msg.delete()
            await send_long_message(callback.message, f"🌌 Ваш нумерологический разбор\n\n{result}")
        else:
            await status_msg.edit_text("❌ Сервис временно недоступен.")
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
    finally:
        # Удаляем временные данные, если они остались
        numerology_data.pop(user_id, None)


@dp.callback_query(F.data == "numerology_fill_new_data")
async def numerology_fill_new_data(callback: CallbackQuery, state: FSMContext):
    """Заполнить новые данные для нумерологии"""
    await callback.message.delete()
    await callback.answer()

    data = await state.get_data()
    if not data.get('numerology_paid', False):
        await callback.message.answer(
            "⚠️ Сначала необходимо оплатить нумерологию.\n\n"
            "💰 Стоимость: 888 ₽",
            reply_markup=get_numerology_payment_keyboard()
        )
        await state.set_state(NumerologyStates.PAYMENT)
        return

    await state.set_state(NumerologyStates.WAITING_NAME)
    await callback.message.answer(
        "✏️ Введите имя для нумерологии:",
        reply_markup=get_cancel_keyboard()
    )


@dp.callback_query(F.data == "numerology_pay", NumerologyStates.PAYMENT)
async def numerology_payment(callback: CallbackQuery, state: FSMContext):
    """Обработка оплаты нумерологии"""
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id

    if not yookassa.is_configured:
        await callback.message.answer(
            "⚠️ Платежная система временно недоступна.\n"
            "Пожалуйста, попробуйте позже."
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
            "💳 Оплата 888 ₽\n\n"
            "Нажмите на кнопку ниже, чтобы перейти к оплате.\n\n"
            "⚠️ После оплаты нумерология будет доступна сразу.\n"
            "Это может занять до 1 минуты.",
            reply_markup=get_payment_url_keyboard(result['confirmation_url'])
        )

        await state.set_state(NumerologyStates.PAYMENT)
    else:
        await callback.message.answer(
            f"❌ Ошибка при создании платежа: {result['error']}"
        )


@dp.callback_query(F.data == "numerology_confirm", NumerologyStates.CONFIRM_DATA)
async def numerology_confirm(callback: CallbackQuery, state: FSMContext):
    """Подтверждение данных для нумерологии"""
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id

    # Проверяем, есть ли временные ручные данные
    manual_data = numerology_data.get(user_id)
    if manual_data and manual_data.get('is_manual') is True:
        # Используем ручные данные
        user_data = {k: v for k, v in manual_data.items() if k != 'is_manual'}
        # Удаляем временные данные, чтобы они не использовались повторно
        numerology_data.pop(user_id, None)
    else:
        # Используем данные из БД
        user_data_from_db = await get_user_data(user_id)
        if not user_data_from_db or not user_data_from_db.get('name'):
            await callback.message.answer(
                "❌ Данные не найдены. Пожалуйста, начните заново.",
                reply_markup=get_main_menu()
            )
            await state.clear()
            return
        user_data = user_data_from_db
        # Если были временные данные (например, от use_my_data), удаляем их
        numerology_data.pop(user_id, None)

    # Генерация
    status_msg = await callback.message.answer(
        "🌌 Начинаю расчёт нумерологии... 🔮"
    )

    try:
        await status_msg.edit_text("✨ Вычисляю числовой код судьбы...")
        await asyncio.sleep(1)
        await status_msg.edit_text("🔢 Анализирую числа жизненного пути...")
        await asyncio.sleep(1)
        await status_msg.edit_text("📊 Формирую полный разбор...")
        await asyncio.sleep(2)

        if gemini_service:
            result = gemini_service.generate_numerology(user_data)

            # Сохраняем в архив
            await save_message_to_archive(user_id, 'numerology', result)

            # Уменьшаем количество доступных нумерологий
            await add_numerology_count(user_id, -1)

            await status_msg.delete()
            await send_long_message(callback.message, f"🌌 Ваш нумерологический разбор\n\n{result}")
        else:
            await status_msg.edit_text("❌ Сервис временно недоступен.")
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
    finally:
        # Очистка на всякий случай
        numerology_data.pop(user_id, None)


# Сбор данных для нумерологии (аналогично натальной карте)
@dp.message(NumerologyStates.WAITING_NAME)
async def process_numerology_name(message: Message, state: FSMContext):
    if len(message.text) < 2:
        await message.answer("❌ Имя должно содержать хотя бы 2 символа:")
        return
    await state.update_data(numerology_name=message.text)
    await state.set_state(NumerologyStates.WAITING_BIRTH_DATE)
    await message.answer(
        f"✅ Имя: {message.text}\n\n"
        "📅 Введите дату рождения в формате ДД.ММ.ГГГГ",
        reply_markup=get_cancel_keyboard()
    )


@dp.message(NumerologyStates.WAITING_BIRTH_DATE)
async def process_numerology_birth_date(message: Message, state: FSMContext):
    date_pattern = r'^\d{2}\.\d{2}\.\d{4}$'
    if not re.match(date_pattern, message.text):
        await message.answer(
            "❌ Неверный формат! Используйте ДД.ММ.ГГГГ",
            reply_markup=get_cancel_keyboard()
        )
        return
    try:
        birth_date = datetime.strptime(message.text, "%d.%m.%Y")
        zodiac = calculate_zodiac_sign(birth_date.day, birth_date.month)
        await state.update_data(numerology_birth_date=message.text, numerology_zodiac=zodiac)
        await state.set_state(NumerologyStates.WAITING_BIRTH_TIME)
        await message.answer(
            f"✅ Знак зодиака: {get_zodiac_emoji(zodiac)} {zodiac}\n\n"
            "🕒 Введите время рождения (ЧЧ:ММ)\n"
            "Например: 15:30\n"
            "Если не знаете - напишите 00:00",
            reply_markup=get_cancel_keyboard()
        )
    except ValueError:
        await message.answer("❌ Неверная дата! Попробуйте еще раз:")


@dp.message(NumerologyStates.WAITING_BIRTH_TIME)
async def process_numerology_birth_time(message: Message, state: FSMContext):
    time_pattern = r'^\d{2}:\d{2}$'
    if not re.match(time_pattern, message.text):
        await message.answer(
            "❌ Неверный формат! Используйте ЧЧ:ММ",
            reply_markup=get_cancel_keyboard()
        )
        return
    try:
        datetime.strptime(message.text, "%H:%M")
        await state.update_data(numerology_birth_time=message.text)
        await state.set_state(NumerologyStates.WAITING_BIRTH_PLACE)
        await message.answer(
            "📍 Введите место рождения:\n"
            "Город, Страна",
            reply_markup=get_cancel_keyboard()
        )
    except ValueError:
        await message.answer("❌ Неверное время! Попробуйте еще раз:")


@dp.message(NumerologyStates.WAITING_BIRTH_PLACE)
async def process_numerology_birth_place(message: Message, state: FSMContext):
    if len(message.text) < 3:
        await message.answer("❌ Укажите город и страну (минимум 3 символа):")
        return
    await state.update_data(numerology_birth_place=message.text)
    await state.set_state(NumerologyStates.WAITING_GENDER)
    await message.answer(
        "👤 Укажите пол:\n"
        "М - мужской\n"
        "Ж - женский\n\n"
        "Напишите: М или Ж",
        reply_markup=get_cancel_keyboard()
    )


@dp.message(NumerologyStates.WAITING_GENDER)
async def process_numerology_gender(message: Message, state: FSMContext):
    gender = message.text.upper()
    if gender not in ["М", "Ж"]:
        await message.answer("❌ Напишите М или Ж:", reply_markup=get_cancel_keyboard())
        return

    db_gender = 'M' if gender == 'М' else 'F'
    data = await state.get_data()
    user_id = message.from_user.id

    # Получаем данные пользователя из БД (для проверки количества доступных нумерологий)
    user_data_from_db = await get_user_data(user_id)
    numer_count = user_data_from_db.get('numerology_count', 0) if user_data_from_db else 0

    # Если есть доступные нумерологии – показываем подтверждение
    if numer_count > 0:
        # Сохраняем введённые данные с флагом is_manual=True
        numerology_data[user_id] = {
            'name': data.get('numerology_name'),
            'birth_date': data.get('numerology_birth_date'),
            'birth_time': data.get('numerology_birth_time'),
            'birth_place': data.get('numerology_birth_place'),
            'gender': db_gender,
            'zodiac': data.get('numerology_zodiac'),
            'is_manual': True   # <-- флаг: ручные данные
        }

        zodiac_emoji = get_zodiac_emoji(data.get('numerology_zodiac', 'Неизвестно'))
        profile_text = (
            f"🔢 Нумерология — познай себя\n\n"
            f"Введенные данные:\n"
            f"👤 Имя: {data.get('numerology_name')}\n"
            f"📅 Дата рождения: {data.get('numerology_birth_date')}\n"
            f"🕒 Время рождения: {data.get('numerology_birth_time')}\n"
            f"📍 Место рождения: {data.get('numerology_birth_place')}\n"
            f"{zodiac_emoji} Знак зодиака: {data.get('numerology_zodiac')}\n\n"
            "Получить нумерологический разбор?"
        )
        await state.set_state(NumerologyStates.CONFIRM_DATA)
        await message.answer(
            profile_text,
            reply_markup=get_numerology_confirm_keyboard()
        )
        return

    # Если нет доступных нумерологий – показываем оплату
    if not data.get('numerology_paid', False):
        await message.answer(
            "⚠️ Оплата не подтверждена. Пожалуйста, оплатите 888 ₽.",
            reply_markup=get_numerology_payment_keyboard()
        )
        await state.set_state(NumerologyStates.PAYMENT)
        return

    # Старая логика (если оплата есть, но это уже не требуется, но оставим для надёжности)
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
    profile_text = (
        f"✅ Данные сохранены!\n\n"
        f"👤 Имя: {data.get('numerology_name')}\n"
        f"📅 Дата рождения: {data.get('numerology_birth_date')}\n"
        f"🕒 Время рождения: {data.get('numerology_birth_time')}\n"
        f"📍 Место рождения: {data.get('numerology_birth_place')}\n"
        f"👤 Пол: {'Мужской' if gender == 'М' else 'Женский'}\n"
        f"{zodiac_emoji} Знак зодиака: {data.get('numerology_zodiac')}\n\n"
        "🌌 Начинаю расчёт нумерологии... 🔮"
    )

    status_msg = await message.answer(profile_text)

    try:
        await status_msg.edit_text("✨ Вычисляю числовой код судьбы...")
        await asyncio.sleep(1)
        await status_msg.edit_text("🔢 Анализирую числа жизненного пути...")
        await asyncio.sleep(1)
        await status_msg.edit_text("📊 Формирую полный разбор...")
        await asyncio.sleep(2)

        if gemini_service:
            result = gemini_service.generate_numerology(numerology_data[user_id])
            await save_message_to_archive(user_id, 'numerology', result)
            await add_numerology_count(user_id, -1)
            await status_msg.delete()
            await send_long_message(message, f"🌌 Ваш нумерологический разбор\n\n{result}")
        else:
            await status_msg.edit_text("❌ Сервис временно недоступен.")
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
    finally:
        numerology_data.pop(user_id, None)


@dp.callback_query(F.data == "edit_numerology_data")
async def edit_numerology_data(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.answer()
    await state.update_data(is_numerology_edit=True)
    await state.set_state(NumerologyStates.WAITING_NAME)
    await callback.message.answer(
        "✏️ Введите ваше имя для нумерологии:",
        reply_markup=get_cancel_keyboard()
    )


@dp.callback_query(F.data == "edit_timezone")
async def edit_timezone(callback: CallbackQuery, state: FSMContext):
    """Начать смену часового пояса"""
    await callback.answer()
    await callback.message.delete()

    await state.update_data(
        is_timezone_edit=True,
        is_edit=False,
        fill_mode=False
    )

    await state.set_state(UserDataStates.WAITING_TIMEZONE)
    await callback.message.answer(
        "🕒 Выберите ваш часовой пояс:",
        reply_markup=get_timezone_keyboard()
    )


# ==================== АСТРОЛОГИЯ ====================

@dp.message(F.text == "🌌 Натальная карта")
async def start_astrology(message: Message, state: FSMContext):
    """Начало оформления астрологии"""
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)

    if user_data and user_data.get('name'):
        zodiac_emoji = get_zodiac_emoji(user_data.get('zodiac', 'Неизвестно'))
        astro_count = user_data.get('astrology_count', 0)

        if astro_count > 0:
            profile_text = (
                f"🌙 Астрология — узнай судьбу\n\n"
                f"Ваши данные:\n"
                f"👤 Имя: {user_data.get('name', 'Не указано')}\n"
                f"📅 Дата рождения: {user_data.get('birth_date', 'Не указана')}\n"
                f"🕒 Время рождения: {user_data.get('birth_time', 'Не указано')}\n"
                f"📍 Место рождения: {user_data.get('birth_place', 'Не указано')}\n"
                f"{zodiac_emoji} Знак зодиака: {user_data.get('zodiac', 'Неизвестно')}\n\n"
                "Хотите получить астрологический разбор?"
            )
            await message.answer(
                profile_text,
                reply_markup=get_astrology_confirm_keyboard()
            )
            await state.set_state(AstrologyStates.CONFIRM_DATA)
        else:
            await message.answer(
                "🌌 Натальная карта — ваш личный астрологический портрет\n\n"
                "Узнайте, что говорят звёзды о вашем характере, эмоциях, отношениях и предназначении:\n\n"
                "✨ Портрет личности\n"
                "🌙 Эмоциональный мир\n"
                "🗣 Общение и отношения\n"
                "⭐ Сильные стороны\n"
                "🌱 Зоны роста\n"
                "🎯 Таланты и интересы\n"
                "💡 Практические рекомендации\n\n"
                "✨ Персональный разбор составляется по дате, времени и месту рождения.\n\n"
                "💰 Стоимость: 999 ₽",
                reply_markup=get_astrology_payment_keyboard()
            )
            await state.set_state(AstrologyStates.PAYMENT)
    else:
        await state.set_state(AstrologyStates.WAITING_NAME)
        await message.answer(
            "🌙 Для астрологического расчёта мне нужно узнать вас получше.\n\n"
            "❓ Как вас зовут?",
            reply_markup=get_cancel_keyboard()
        )


# ==================== АСТРОЛОГИЯ (ПОЛНЫЙ НАБОР) ====================

@dp.callback_query(F.data == "astrology_use_my_data")
async def astrology_use_my_data(callback: CallbackQuery, state: FSMContext):
    """Использовать сохранённые данные для астрологии"""
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id
    data = await state.get_data()

    if not data.get('astrology_paid', False):
        await callback.message.answer(
            "⚠️ Сначала необходимо оплатить астрологию.\n\n"
            "💰 Стоимость: 999 ₽",
            reply_markup=get_astrology_payment_keyboard()
        )
        await state.set_state(AstrologyStates.PAYMENT)
        return

    user_data_from_db = await get_user_data(user_id)
    if not user_data_from_db or not user_data_from_db.get('name'):
        await callback.message.answer(
            "❌ Данные не найдены. Пожалуйста, заполните заново.",
            reply_markup=get_main_menu()
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
        'is_manual': False   # <-- флаг: данные из профиля
    }

    await state.clear()

    zodiac_emoji = get_zodiac_emoji(user_data_from_db.get('zodiac', 'Неизвестно'))
    profile_text = (
        f"✅ Используем ваши данные:\n\n"
        f"👤 Имя: {user_data_from_db.get('name')}\n"
        f"📅 Дата рождения: {user_data_from_db.get('birth_date')}\n"
        f"🕒 Время рождения: {user_data_from_db.get('birth_time')}\n"
        f"📍 Место рождения: {user_data_from_db.get('birth_place')}\n"
        f"👤 Пол: {'Мужской' if user_data_from_db.get('gender') == 'M' else 'Женский'}\n"
        f"{zodiac_emoji} Знак зодиака: {user_data_from_db.get('zodiac')}\n\n"
        "🌙 Начинаю астрологический расчёт... ✨"
    )

    status_msg = await callback.message.answer(profile_text)

    try:
        await status_msg.edit_text("✨ Изучаю положение планет...")
        await asyncio.sleep(1)
        await status_msg.edit_text("🌙 Анализирую дома и аспекты...")
        await asyncio.sleep(1)
        await status_msg.edit_text("⭐ Формирую полный разбор...")
        await asyncio.sleep(2)

        if gemini_service:
            calculator = AstrologyCalculator(user_data_from_db)
            parameters_text = calculator.get_display_parameters()
            prompt = calculator.build_prompt()
            interpretation = gemini_service.send_raw_prompt(prompt)

            final_message = f"🌙 Ваш астрологический разбор\n\n{parameters_text}\n\n{interpretation}"
            await save_message_to_archive(user_id, 'astrology', final_message)

            await add_astrology_count(user_id, -1)
            await status_msg.delete()
            await send_long_message(callback.message, final_message)
        else:
            await status_msg.edit_text("❌ Сервис временно недоступен.")
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
    finally:
        # Очищаем временные данные, если они остались
        astrology_data.pop(user_id, None)


@dp.callback_query(F.data == "astrology_fill_new_data")
async def astrology_fill_new_data(callback: CallbackQuery, state: FSMContext):
    """Заполнить новые данные для астрологии"""
    await callback.message.delete()
    await callback.answer()

    data = await state.get_data()
    if not data.get('astrology_paid', False):
        await callback.message.answer(
            "⚠️ Сначала необходимо оплатить астрологию.\n\n"
            "💰 Стоимость: 999 ₽",
            reply_markup=get_astrology_payment_keyboard()
        )
        await state.set_state(AstrologyStates.PAYMENT)
        return

    await state.set_state(AstrologyStates.WAITING_NAME)
    await callback.message.answer(
        "✏️ Введите имя для астрологии:",
        reply_markup=get_cancel_keyboard()
    )


@dp.callback_query(F.data == "astrology_pay", AstrologyStates.PAYMENT)
async def astrology_payment(callback: CallbackQuery, state: FSMContext):
    """Обработка оплаты астрологии"""
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id

    if not yookassa.is_configured:
        await callback.message.answer(
            "⚠️ Платежная система временно недоступна.\n"
            "Пожалуйста, попробуйте позже."
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
            "💳 Оплата 999 ₽\n\n"
            "Нажмите на кнопку ниже, чтобы перейти к оплате.\n\n"
            "⚠️ После оплаты астрология будет доступна сразу.\n"
            "Это может занять до 1 минуты.",
            reply_markup=get_payment_url_keyboard(result['confirmation_url'])
        )

        await state.set_state(AstrologyStates.PAYMENT)
    else:
        await callback.message.answer(
            f"❌ Ошибка при создании платежа: {result['error']}"
        )


@dp.callback_query(F.data == "astrology_confirm", AstrologyStates.CONFIRM_DATA)
async def astrology_confirm(callback: CallbackQuery, state: FSMContext):
    """Подтверждение данных для астрологии"""
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id

    # Проверяем, есть ли временные ручные данные
    manual_data = astrology_data.get(user_id)
    if manual_data and manual_data.get('is_manual') is True:
        # Используем ручные данные
        user_data = {k: v for k, v in manual_data.items() if k != 'is_manual'}
        # Удаляем временные данные, чтобы они не использовались повторно
        astrology_data.pop(user_id, None)
    else:
        # Используем данные из БД
        user_data_from_db = await get_user_data(user_id)
        if not user_data_from_db or not user_data_from_db.get('name'):
            await callback.message.answer(
                "❌ Данные не найдены. Пожалуйста, начните заново.",
                reply_markup=get_main_menu()
            )
            await state.clear()
            return
        user_data = user_data_from_db
        # Если были временные данные (например, от use_my_data), удаляем их
        astrology_data.pop(user_id, None)

    # Генерация
    status_msg = await callback.message.answer(
        "🌙 Начинаю астрологический расчёт... ✨"
    )

    try:
        await status_msg.edit_text("✨ Изучаю положение планет...")
        await asyncio.sleep(1)
        await status_msg.edit_text("🌙 Анализирую дома и аспекты...")
        await asyncio.sleep(1)
        await status_msg.edit_text("⭐ Формирую полный разбор...")
        await asyncio.sleep(2)

        if gemini_service:
            calculator = AstrologyCalculator(user_data)
            parameters_text = calculator.get_display_parameters()
            prompt = calculator.build_prompt()
            interpretation = gemini_service.send_raw_prompt(prompt)

            final_message = f"🌙 Ваш астрологический разбор\n\n{parameters_text}\n\n💬 Интерпретация нейросети:\n\n{interpretation}"
            await save_message_to_archive(user_id, 'astrology', final_message)

            await add_astrology_count(user_id, -1)
            await status_msg.delete()
            await send_long_message(callback.message, final_message)
        else:
            await status_msg.edit_text("❌ Сервис временно недоступен.")
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
    finally:
        # Очистка на всякий случай
        astrology_data.pop(user_id, None)


# Сбор данных для астрологии
@dp.message(AstrologyStates.WAITING_NAME)
async def process_astrology_name(message: Message, state: FSMContext):
    if len(message.text) < 2:
        await message.answer("❌ Имя должно содержать хотя бы 2 символа:")
        return
    await state.update_data(astrology_name=message.text)
    await state.set_state(AstrologyStates.WAITING_BIRTH_DATE)
    await message.answer(
        f"✅ Имя: {message.text}\n\n"
        "📅 Введите дату рождения в формате ДД.ММ.ГГГГ",
        reply_markup=get_cancel_keyboard()
    )


@dp.message(AstrologyStates.WAITING_BIRTH_DATE)
async def process_astrology_birth_date(message: Message, state: FSMContext):
    date_pattern = r'^\d{2}\.\d{2}\.\d{4}$'
    if not re.match(date_pattern, message.text):
        await message.answer(
            "❌ Неверный формат! Используйте ДД.ММ.ГГГГ",
            reply_markup=get_cancel_keyboard()
        )
        return
    try:
        birth_date = datetime.strptime(message.text, "%d.%m.%Y")
        zodiac = calculate_zodiac_sign(birth_date.day, birth_date.month)
        await state.update_data(astrology_birth_date=message.text, astrology_zodiac=zodiac)
        await state.set_state(AstrologyStates.WAITING_BIRTH_TIME)
        await message.answer(
            f"✅ Знак зодиака: {get_zodiac_emoji(zodiac)} {zodiac}\n\n"
            "🕒 Введите время рождения (ЧЧ:ММ)\n"
            "Например: 15:30\n"
            "Если не знаете - напишите 00:00",
            reply_markup=get_cancel_keyboard()
        )
    except ValueError:
        await message.answer("❌ Неверная дата! Попробуйте еще раз:")


@dp.message(AstrologyStates.WAITING_BIRTH_TIME)
async def process_astrology_birth_time(message: Message, state: FSMContext):
    time_pattern = r'^\d{2}:\d{2}$'
    if not re.match(time_pattern, message.text):
        await message.answer(
            "❌ Неверный формат! Используйте ЧЧ:ММ",
            reply_markup=get_cancel_keyboard()
        )
        return
    try:
        datetime.strptime(message.text, "%H:%M")
        await state.update_data(astrology_birth_time=message.text)
        await state.set_state(AstrologyStates.WAITING_BIRTH_PLACE)
        await message.answer(
            "📍 Введите место рождения:\n"
            "Город, Страна",
            reply_markup=get_cancel_keyboard()
        )
    except ValueError:
        await message.answer("❌ Неверное время! Попробуйте еще раз:")


@dp.message(AstrologyStates.WAITING_BIRTH_PLACE)
async def process_astrology_birth_place(message: Message, state: FSMContext):
    if len(message.text) < 3:
        await message.answer("❌ Укажите город и страну (минимум 3 символа):")
        return
    await state.update_data(astrology_birth_place=message.text)
    await state.set_state(AstrologyStates.WAITING_GENDER)
    await message.answer(
        "👤 Укажите пол:\n"
        "М - мужской\n"
        "Ж - женский\n\n"
        "Напишите: М или Ж",
        reply_markup=get_cancel_keyboard()
    )


@dp.message(AstrologyStates.WAITING_GENDER)
async def process_astrology_gender(message: Message, state: FSMContext):
    gender = message.text.upper()
    if gender not in ["М", "Ж"]:
        await message.answer(
            "❌ Напишите М или Ж:",
            reply_markup=get_cancel_keyboard()
        )
        return

    db_gender = 'M' if gender == 'М' else 'F'
    data = await state.get_data()
    user_id = message.from_user.id

    # Получаем данные пользователя из БД (для проверки количества доступных астрологий)
    user_data_from_db = await get_user_data(user_id)
    astro_count = user_data_from_db.get('astrology_count', 0) if user_data_from_db else 0

    # Если есть доступные астрологии – показываем подтверждение
    if astro_count > 0:
        # Сохраняем введённые данные во временное хранилище с флагом is_manual=True
        astrology_data[user_id] = {
            'name': data.get('astrology_name'),
            'birth_date': data.get('astrology_birth_date'),
            'birth_time': data.get('astrology_birth_time'),
            'birth_place': data.get('astrology_birth_place'),
            'gender': db_gender,
            'zodiac': data.get('astrology_zodiac'),
            'is_manual': True   # <-- флаг: ручные данные
        }

        zodiac_emoji = get_zodiac_emoji(data.get('astrology_zodiac', 'Неизвестно'))
        profile_text = (
            f"🌙 Астрология — узнай судьбу\n\n"
            f"Введенные данные:\n"
            f"👤 Имя: {data.get('astrology_name')}\n"
            f"📅 Дата рождения: {data.get('astrology_birth_date')}\n"
            f"🕒 Время рождения: {data.get('astrology_birth_time')}\n"
            f"📍 Место рождения: {data.get('astrology_birth_place')}\n"
            f"{zodiac_emoji} Знак зодиака: {data.get('astrology_zodiac')}\n\n"
            "Получить астрологический разбор?"
        )
        await state.set_state(AstrologyStates.CONFIRM_DATA)
        await message.answer(
            profile_text,
            reply_markup=get_astrology_confirm_keyboard()
        )
        return

    # Если нет доступных астрологий – показываем оплату
    if not data.get('astrology_paid', False):
        await message.answer(
            "⚠️ Оплата не подтверждена. Пожалуйста, оплатите 999 ₽.",
            reply_markup=get_astrology_payment_keyboard()
        )
        await state.set_state(AstrologyStates.PAYMENT)
        return

    # Старая логика (если оплата есть, но это уже не требуется, но оставим для надёжности)
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
    profile_text = (
        f"✅ Данные сохранены!\n\n"
        f"👤 Имя: {data.get('astrology_name')}\n"
        f"📅 Дата рождения: {data.get('astrology_birth_date')}\n"
        f"🕒 Время рождения: {data.get('astrology_birth_time')}\n"
        f"📍 Место рождения: {data.get('astrology_birth_place')}\n"
        f"👤 Пол: {'Мужской' if gender == 'М' else 'Женский'}\n"
        f"{zodiac_emoji} Знак зодиака: {data.get('astrology_zodiac')}\n\n"
        "🌙 Начинаю астрологический расчёт... ✨"
    )

    status_msg = await message.answer(profile_text)

    try:
        await status_msg.edit_text("✨ Изучаю положение планет...")
        await asyncio.sleep(1)
        await status_msg.edit_text("🌙 Анализирую дома и аспекты...")
        await asyncio.sleep(1)
        await status_msg.edit_text("⭐ Формирую полный разбор...")
        await asyncio.sleep(2)

        if gemini_service:
            calculator = AstrologyCalculator(user_data_for_calc)
            parameters_text = calculator.get_display_parameters()
            prompt = calculator.build_prompt()
            interpretation = gemini_service.send_raw_prompt(prompt)

            final_message = f"🌙 Ваш астрологический разбор\n\n{parameters_text}\n\n💬 Интерпретация нейросети:\n\n{interpretation}"
            await save_message_to_archive(user_id, 'astrology', final_message)

            await add_astrology_count(user_id, -1)
            await status_msg.delete()
            await send_long_message(message, final_message)
        else:
            await status_msg.edit_text("❌ Сервис временно недоступен.")
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
    finally:
        # Очистка временных данных
        astrology_data.pop(user_id, None)


@dp.callback_query(F.data == "edit_astrology_data")
async def edit_astrology_data(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.answer()
    await state.update_data(is_astrology_edit=True)
    await state.set_state(AstrologyStates.WAITING_NAME)
    await callback.message.answer(
        "✏️ Введите ваше имя для астрологии:",
        reply_markup=get_cancel_keyboard()
    )


# ==================== ОБРАБОТКА ДРУГИХ КНОПОК МЕНЮ ====================

@dp.message(F.text.in_([
    "📖 Мои прогнозы",
    "👤 Мой профиль"
]))
async def handle_menu_buttons(message: Message, state: FSMContext):
    text = message.text
    if text == "📖 Мои прогнозы":
        await show_archive(message)
    elif text == "👤 Мой профиль":
        await profile(message)


# ==================== ПРОФИЛЬ ====================

async def profile(message: Message):
    """Показать профиль пользователя"""
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)

    if user_data and user_data.get('name'):
        # ... (существующий код показа профиля)
        zodiac_emoji = get_zodiac_emoji(user_data.get('zodiac', 'Неизвестно'))
        gender_display = 'Мужской' if user_data.get('gender') == 'M' else 'Женский' if user_data.get('gender') == 'F' else 'Не указан'
        timezone = user_data.get('timezone_offset', 3)
        profile_text = (
            f"👤 Ваш профиль\n\n"
            f"Имя: {user_data.get('name', 'Не указано')}\n"
            f"📅 Дата рождения: {user_data.get('birth_date', 'Не указана')}\n"
            f"🕒 Время рождения: {user_data.get('birth_time', 'Не указано')}\n"
            f"📍 Место рождения: {user_data.get('birth_place', 'Не указано')}\n"
            f"👤 Пол: {gender_display}\n"
            f"{zodiac_emoji} Знак зодиака: {user_data.get('zodiac', 'Неизвестно')}\n"
            f"🕒 Часовой пояс: UTC+{timezone}"
        )
        is_subscribed = await check_subscription_db(user_id)
        if is_subscribed:
            profile_text += "\n\n⭐ Подписка: **Активна** ✅"
        await message.answer(profile_text, reply_markup=get_profile_keyboard())
    else:
        # Нет данных – предлагаем заполнить
        consent_url = os.getenv('CONSENT_URL', 'ссылка на согласие')
        privacy_url = os.getenv('PRIVACY_POLICY_URL', 'ссылка на политику')
        can_use = await can_use_feature_db(user_id, 'horoscope')

        if can_use:
            text = (
                "📝 У вас пока нет сохраненных данных.\n"
                "Чтобы заполнить профиль, нажмите 🔮 **Гороскоп на сегодня** или **Заполнить и Сохранить**.\n\n"
                f"📄 Нажимая «**Заполнить и Сохранить**», вы даёте [согласие на обработку персональных данных]({consent_url}) "
                f"в соответствии с [Политикой конфиденциальности]({privacy_url})."
            )
        else:
            text = (
                "📝 У вас пока нет сохраненных данных.\n"
                "Чтобы заполнить профиль, нажмите **Заполнить и Сохранить**.\n\n"
                f"📄 Нажимая «Заполнить и Сохранить», вы даёте [согласие на обработку персональных данных]({consent_url}) "
                f"в соответствии с [Политикой конфиденциальности]({privacy_url})."
            )
        await message.answer(text, reply_markup=get_fill_profile_keyboard(), parse_mode="Markdown")


@dp.callback_query(F.data == "edit_profile")
async def edit_profile(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id

    old = await get_user_data(user_id)
    if not old or not old.get('name'):
        await callback.message.edit_text(
            "❌ У вас нет сохраненных данных. Сначала заполните профиль через 'Гороскоп на сегодня'."
        )
        return

    # Сохраняем флаг редактирования
    await state.update_data(
        old_data=old,
        new_data=old.copy(),
        is_edit=True,
        fill_mode=False,
        is_timezone_edit=False
    )

    logger.info(f"🟢 Начало редактирования для {user_id}, старые данные: {old}")

    await state.set_state(UserDataStates.WAITING_NAME)
    await callback.message.edit_text(
        f"✏️ Текущее имя: {old.get('name', 'не указано')}\n\n"
        "Введите новое имя или нажмите «Пропустить».",
        reply_markup=get_skip_keyboard()
    )


@dp.callback_query(F.data == "fill_and_save")
async def fill_and_save(callback: CallbackQuery, state: FSMContext):
    """Начать заполнение профиля"""
    await callback.answer()
    await callback.message.delete()

    # Устанавливаем флаг, что это заполнение профиля
    await state.update_data(fill_mode=True)

    await state.set_state(UserDataStates.WAITING_NAME)
    await callback.message.answer(
        "📝 Давайте заполним ваш профиль.\n\n"
        "❓ Как вас зовут?",
        reply_markup=get_cancel_keyboard()  # ← добавлено
    )



@dp.callback_query(F.data == "skip_edit")
async def skip_edit_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    current_state = await state.get_state()
    state_data = await state.get_data()
    new_data = state_data.get('new_data', {})
    old = state_data.get('old_data', {})

    logger.info(f"⏩ Пропуск шага {current_state}, new_data до: {new_data}")

    if current_state == UserDataStates.WAITING_NAME:
        await state.set_state(UserDataStates.WAITING_BIRTH_DATE)
        await callback.message.edit_text(
            f"✏️ Текущая дата рождения: {old.get('birth_date', 'не указана')}\n\n"
            "Введите новую дату в формате ДД.ММ.ГГГГ или нажмите «Пропустить».",
            reply_markup=get_skip_keyboard()
        )
    elif current_state == UserDataStates.WAITING_BIRTH_DATE:
        await state.set_state(UserDataStates.WAITING_BIRTH_TIME)
        await callback.message.edit_text(
            f"✏️ Текущее время рождения: {old.get('birth_time', 'не указано')}\n\n"
            "Введите новое время в формате ЧЧ:ММ или нажмите «Пропустить».",
            reply_markup=get_skip_keyboard()
        )
    elif current_state == UserDataStates.WAITING_BIRTH_TIME:
        await state.set_state(UserDataStates.WAITING_BIRTH_PLACE)
        await callback.message.edit_text(
            f"✏️ Текущее место рождения: {old.get('birth_place', 'не указано')}\n\n"
            "Введите новое место (город, страна) или нажмите «Пропустить».",
            reply_markup=get_skip_keyboard()
        )
    elif current_state == UserDataStates.WAITING_BIRTH_PLACE:
        await state.set_state(UserDataStates.WAITING_GENDER)
        await callback.message.edit_text(
            f"✏️ Текущий пол: {'Мужской' if old.get('gender') == 'М' else 'Женский' if old.get('gender') == 'Ж' else 'не указан'}\n\n"
            "Введите новый пол (М или Ж) или нажмите «Пропустить».",
            reply_markup=get_skip_keyboard()
        )
    elif current_state == UserDataStates.WAITING_GENDER:
        user_id = callback.from_user.id
        logger.info(f"💾 Завершение редактирования через 'Пропустить' для {user_id}, данные: {new_data}")
        await save_user_data(user_id, new_data)
        await state.clear()

        from core.models import User
        from asgiref.sync import sync_to_async
        user_obj = await sync_to_async(User.objects.get)(telegram_id=user_id)
        gender_display = 'Мужской' if user_obj.gender == 'M' else 'Женский'

        zodiac_emoji = get_zodiac_emoji(user_obj.zodiac_sign or 'Неизвестно')
        profile_text = (
            f"✅ Данные успешно обновлены!\n\n"
            f"👤 Имя: {user_obj.name or 'Не указано'}\n"
            f"📅 Дата рождения: {user_obj.date_of_birth.strftime('%d.%m.%Y') if user_obj.date_of_birth else 'Не указана'}\n"
            f"🕒 Время рождения: {user_obj.birth_time.strftime('%H:%M') if user_obj.birth_time else 'Не указано'}\n"
            f"📍 Место рождения: {user_obj.birth_place or 'Не указано'}\n"
            f"👤 Пол: {gender_display}\n"
            f"{zodiac_emoji} Знак зодиака: {user_obj.zodiac_sign or 'Неизвестно'}"
        )
        await callback.message.edit_text(profile_text, reply_markup=get_main_menu())
    else:
        user_id = callback.from_user.id
        logger.info(f"💾 Завершение редактирования (неизвестное состояние) для {user_id}, данные: {new_data}")
        await save_user_data(user_id, new_data)
        await state.clear()

        from core.models import User
        from asgiref.sync import sync_to_async
        user_obj = await sync_to_async(User.objects.get)(telegram_id=user_id)
        gender_display = 'Мужской' if user_obj.gender == 'M' else 'Женский'

        zodiac_emoji = get_zodiac_emoji(user_obj.zodiac_sign or 'Неизвестно')
        profile_text = (
            f"✅ Данные успешно обновлены!\n\n"
            f"👤 Имя: {user_obj.name or 'Не указано'}\n"
            f"📅 Дата рождения: {user_obj.date_of_birth.strftime('%d.%m.%Y') if user_obj.date_of_birth else 'Не указана'}\n"
            f"🕒 Время рождения: {user_obj.birth_time.strftime('%H:%M') if user_obj.birth_time else 'Не указано'}\n"
            f"📍 Место рождения: {user_obj.birth_place or 'Не указано'}\n"
            f"👤 Пол: {gender_display}\n"
            f"{zodiac_emoji} Знак зодиака: {user_obj.zodiac_sign or 'Неизвестно'}"
        )
        await callback.message.edit_text(profile_text, reply_markup=get_main_menu())

    logger.info(f"⏩ После пропуска, new_data: {new_data}")


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
            await message.answer(f"📄 Продолжение ({i}/{len(parts)}):\n\n{part}")


# ==================== ЭКСПЕРТ ====================

@dp.message(F.text == "👩‍🏫 Личный астролог")
async def expert_request(message: Message):
    user_id = message.from_user.id
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

    expert_text = (
        "👩‍🏫 Личный астролог\n\n"
        "Индивидуальный разбор от эксперта по астрологии.\n\n"
        "Вы сможете задать вопросы и получить детальный анализ по интересующим вас темам. "
        "Эксперт подготовит персональные рекомендации именно для вашей ситуации.\n\n"
        "💰 Стоимость: 5000 ₽\n\n"
        "Нажмите кнопку ниже, чтобы отправить заявку эксперту."
    )

    await message.answer(
        expert_text,
        reply_markup=get_expert_keyboard()
    )


@dp.callback_query(F.data == "expert_request")
async def send_expert_request(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id
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
        "✅ Заявка отправлена! 📩\n\n"
        "Эксперт свяжется с вами в ближайшее время.",
        reply_markup=get_main_menu()
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


# ==================== ПОДПИСКА ====================

@dp.message(F.text == "⭐ Premium")
async def show_subscription(message: Message):
    user_id = message.from_user.id
    is_subscribed = await check_subscription_db(user_id)

    if is_subscribed:
        await message.answer(
            "⭐ Ваша подписка активна!\n\n"
            "✅ Доступны все функции Premium\n"
            "📅 Подписка активна\n\n"
            "Хотите продлить подписку?",
            reply_markup=get_subscription_active_keyboard()
        )
    else:
        await message.answer(
            "⭐ Подписка 333 ₽/МЕС\n\n"
            "✨ Что вы получите:\n"
            "✓ Ежедневный персональный гороскоп\n"
            "✓ Авто отправка гороскопа в 8:00\n"
            "✓ Совместимость без ограничений\n"
            "✓ Архив прогнозов\n"
            "💰 333 ₽ / месяц\n\n"
            "Нажмите кнопку ниже, чтобы оформить подписку.",
            reply_markup=get_subscription_keyboard()
        )


@dp.callback_query(F.data == "subscribe_pay")
async def subscribe_payment(callback: CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id

    if not yookassa.is_configured:
        await callback.message.answer(
            "⚠️ Платежная система временно недоступна.\n"
            "Пожалуйста, попробуйте позже или свяжитесь с поддержкой."
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
            "💳 Оплата 333 ₽\n\n"
            "Нажмите на кнопку ниже, чтобы перейти к оплате.\n\n"
            "⚠️ После оплаты подписка активируется автоматически.\n"
            "Это может занять до 1 минуты.",
            reply_markup=get_subscription_payment_keyboard(result['confirmation_url'])
        )
    else:
        await callback.message.answer(
            f"❌ Ошибка при создании платежа: {result['error']}"
        )


@dp.callback_query(F.data == "subscribe_extend")
async def subscribe_extend(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

    await callback.message.answer(
        "🔄 Продление подписки\n\n"
        "💰 333 ₽ / месяц\n\n"
        "Нажмите кнопку ниже для продления.",
        reply_markup=get_subscription_keyboard()
    )


# ==================== АРХИВ ====================

async def show_archive(message: Message):
    user_id = message.from_user.id
    messages = await get_user_archive(user_id, limit=10)

    if not messages:
        await message.answer(
            "📚 Архив пуст\n\n"
            "У вас пока нет сохранённых прогнозов.",
            reply_markup=get_main_menu()
        )
        return

    type_display_map = {
        'horoscope': 'Гороскоп',
        'compatibility': 'Совместимость',
        'numerology': 'Нумерология',
        'astrology': 'Астрология',
    }

    type_emoji_map = {
        'horoscope': '🔮',
        'compatibility': '💕',
        'numerology': '🔢',
        'astrology': '🌙',
    }

    archive_text = "📚 Ваш архив прогнозов\n\n"

    for i, msg in enumerate(messages, 1):
        date_str = msg.date.strftime("%d.%m.%Y %H:%M")
        emoji = type_emoji_map.get(msg.message_type, '📝')
        type_name = type_display_map.get(msg.message_type, msg.message_type)

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        preview = preview.replace('\n', ' ')

        archive_text += f"{i}. {emoji} {type_name} — {date_str}\n"
        archive_text += f"   📄 {preview}\n\n"

    archive_text += "━━━━━━━━━━━━━━━━━━━━━\n"
    archive_text += "💡 Нажмите на кнопку ниже, чтобы посмотреть полный прогноз."

    await message.answer(
        archive_text,
        reply_markup=get_archive_keyboard(messages)
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


@dp.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: CallbackQuery):
    await callback.answer()
    await callback.message.delete()
    await callback.message.answer(
        " ",
        reply_markup=get_main_menu()
    )


@dp.callback_query(F.data.startswith("archive_"))
async def show_archive_message(callback: CallbackQuery):
    """Показать полное сообщение из архива"""
    await callback.answer()

    try:
        message_id = int(callback.data.replace("archive_", ""))
    except ValueError:
        await callback.message.answer("❌ Неверный формат запроса.")
        return

    try:
        from bot.db import get_archive_message
        msg = await get_archive_message(message_id, callback.from_user.id)

        if not msg:
            await callback.message.answer(
                "❌ Сообщение не найдено или у вас нет доступа.",
                reply_markup=get_main_menu()
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
            'horoscope': 'Гороскоп',
            'compatibility': 'Совместимость',
            'natal_chart': 'Натальная карта',
            'numerology': 'Нумерология',
            'astrology': 'Астрология',
        }

        emoji = type_emoji.get(msg.message_type, '📝')
        type_name = type_display.get(msg.message_type, msg.message_type)

        full_text = (
            f"{emoji} {type_name}\n"
            f"📅 {msg.date.strftime('%d.%m.%Y %H:%M')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{msg.content}"
        )

        # --- Используем send_long_message для длинных сообщений ---
        await send_long_message(callback.message, full_text)

    except Exception as e:
        await callback.message.answer(
            f"❌ Ошибка: {str(e)}",
            reply_markup=get_main_menu()
        )


@dp.callback_query(F.data == "cancel_subscription")
async def cancel_subscription_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id

    try:
        from core.models import User

        @sync_to_async
        def get_user(uid):
            try:
                return User.objects.get(telegram_id=uid)
            except User.DoesNotExist:
                return None

        user = await get_user(user_id)

        if not user:
            await callback.message.answer(
                "❌ Пользователь не найден в базе данных.",
                reply_markup=get_main_menu()
            )
            return

        if not user.is_subscribed:
            await callback.message.answer(
                "📌 У вас нет активной подписки.\n"
                "Оформить подписку можно в разделе ⭐ Подписка.",
                reply_markup=get_main_menu()
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
            "❌ Ваша подписка отменена.\n\n"
            "Вы больше не будете получать ежедневные гороскопы.\n"
            "Вы можете оформить подписку снова в любой момент в разделе ⭐ Подписка.",
            reply_markup=get_main_menu()
        )

    except Exception as e:
        await callback.message.answer(
            f"❌ Ошибка при отмене подписки: {str(e)}",
            reply_markup=get_main_menu()
        )


@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery):
    await callback.answer()
    support_url = os.getenv('SUPPORT_URL', 'https://t.me/ваш_username')
    text = (
        "🆘 **Поддержка**\n\n"
        "Если у вас возникли вопросы по работе бота, оплате, подписке или вы заметили ошибку, напишите администратору.\n\n"
        "Мы постараемся ответить как можно быстрее 👇"
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_support_keyboard(support_url),
        parse_mode="Markdown"
    )


@dp.callback_query(F.data == "back_to_profile")
async def back_to_profile(callback: CallbackQuery):
    await callback.answer()
    await callback.message.delete()
    # Создаём фейковое сообщение для вызова profile
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

    data = await state.get_data()
    payment_id = data.get('payment_id')

    if not payment_id:
        await callback.message.answer(
            "❌ Информация о платеже не найдена."
        )
        return

    result = yookassa.check_payment(payment_id)

    if result['success'] and result['paid']:
        await callback.message.answer(
            "✅ Оплата прошла успешно!\n\n"
            "Теперь вы можете получить натальную карту.",
            reply_markup=get_main_menu()
        )

        user_id = callback.from_user.id

        # Временно оставляем задел для будущих активаций
        # Здесь будет логика для нумерологии или астрологии

        await state.clear()
    else:
        await callback.message.answer(
            "⏳ Оплата пока не подтверждена.\n"
            "Пожалуйста, завершите оплату или проверьте статус позже.",
            reply_markup=get_payment_url_keyboard(callback.message.text)
        )


@dp.message(Command("test_send"))
async def test_send(message: Message):
    ADMIN_ID = 5484157606

    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return

    await message.answer("⏳ Начинаю тестовую рассылку...")
    await send_daily_horoscopes(bot)


# ==================== ОБРАБОТКА НЕИЗВЕСТНЫХ СООБЩЕНИЙ ====================

@dp.message()
async def handle_unknown(message: Message):
    await message.answer(
        "❓ Я не понял вашу команду.\n"
        "Используйте кнопки меню или напишите /start"
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
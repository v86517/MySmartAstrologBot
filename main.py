import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# Импорты из наших модулей
from bot.keyboards.keyboards import (
    get_main_menu,
    get_zodiac_keyboard,
    get_cancel_keyboard,
    get_compatibility_keyboard,
    get_confirm_keyboard,
    get_continue_keyboard,
    get_zodiac_keyboard_person2,
    get_natal_payment_keyboard,
    get_natal_confirm_keyboard,
    get_natal_use_data_keyboard,
    get_expert_keyboard,
    get_subscription_keyboard,
    get_subscription_active_keyboard,
    get_archive_keyboard,
)
from bot.states.states import UserDataStates, CompatibilityStates, NatalStates
from bot.utils.zodiac import calculate_zodiac_sign, get_zodiac_emoji
from bot.services.gemini import GeminiService

from bot.db import (
    get_or_create_user,
    save_user_data,
    get_user_data,
    check_subscription_db,      # ← ЭТО ИСПОЛЬЗУЙТЕ
    activate_subscription_db,
    can_use_feature_db,         # ← ЭТО ИСПОЛЬЗУЙТЕ
    mark_feature_used_db,       # ← ЭТО ИСПОЛЬЗУЙТЕ
    save_message_to_archive,
    get_user_archive,
    get_archive_message
)
from bot.scheduler import setup_scheduler, send_daily_horoscopes


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

# Хранилище временных данных пользователей
#user_data = {}

# Хранилище данных для совместимости
#compatibility_data = {}

# Хранилище для данных натальной карты
natal_data = {}

# Хранилище статуса оплаты для натальной карты
#natal_payment_status = {}

# Хранилище подписок
#subscriptions = {}  # {user_id: {'until': datetime, 'active': True}}

# Хранилище дневных лимитов
#daily_usage = {}  # {user_id: {date: {'horoscope': count, 'compatibility': count}}}

# Инициализация Gemini
try:
    gemini_service = GeminiService()
    logger.info("✅ Gemini API успешно инициализирован!")
except Exception as e:
    logger.error(f"❌ Ошибка инициализации Gemini: {e}")
    gemini_service = None


# ==================== ОБРАБОТЧИКИ КОМАНД ====================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Приветственное сообщение с главным меню"""
    await state.clear()

    # Сохраняем пользователя в БД
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name

    user, created = await get_or_create_user(user_id, username, first_name, last_name)

    if created:
        logger.info(f"✅ Новый пользователь: {user_id} (@{username})")

    welcome_text = (
        "✨ Добро пожаловать в MySmartAstrologBot!\n\n"
        "🌙 Я - ваш личный цифровой астролог.\n"
        "🔮 Готов составить персональный прогноз и ответить на вопросы судьбы.\n\n"
        "📌 Чем займемся сегодня?"
    )

    await message.answer(
        welcome_text,
        reply_markup=get_main_menu()
    )


@dp.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    """Показать главное меню"""
    await state.clear()
    await message.answer(
        "📌 Главное меню:",
        reply_markup=get_main_menu()
    )


# ==================== НАЧАЛО СБОРА ДАННЫХ ДЛЯ ГОРОСКОПА ====================

@dp.message(F.text == "🔮 Гороскоп на сегодня")
async def start_horoscope(message: Message, state: FSMContext):
    """Получение гороскопа"""
    user_id = message.from_user.id

    # ✅ Используем БД
    if not await can_use_feature_db(user_id, 'horoscope'):
        await message.answer(
            "✨ Сегодняшний бесплатный прогноз уже готов.\n\n"
            "Получайте новые прогнозы без ограничений\n"
            "за 299 ₽ в месяц.",
            reply_markup=get_subscription_keyboard()
        )
        return

    user_data = await get_user_data(user_id)

    if user_data and user_data.get('name'):
        if not gemini_service:
            await message.answer(
                "❌ Извините, сервис астролога временно недоступен."
            )
            return

        status_msg = await message.answer("✨ Изучаю положение планет...")
        await asyncio.sleep(1)
        await status_msg.edit_text("🌙 Строю натальную карту...")
        await asyncio.sleep(1)
        await status_msg.edit_text("⭐ Анализирую влияние созвездий...")
        await asyncio.sleep(1)

        today = datetime.now().strftime("%d.%m.%Y")
        horoscope = gemini_service.generate_horoscope(user_data, today)

        # ✅ Отмечаем использование
        await mark_feature_used_db(user_id, 'horoscope')

        await status_msg.edit_text(
            f"🔮 Ваш гороскоп на {today}\n\n{horoscope}"
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
    """Обработка имени"""
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
    """Обработка даты рождения"""
    date_pattern = r'^\d{2}\.\d{2}\.\d{4}$'

    if not re.match(date_pattern, message.text):
        await message.answer(
            "❌ Неверный формат!\n\n"
            "Используйте формат ДД.ММ.ГГГГ\n"
            "Например: 15.03.1990"
        )
        return

    try:
        birth_date = datetime.strptime(message.text, "%d.%m.%Y")

        # Рассчитываем знак зодиака
        zodiac = calculate_zodiac_sign(birth_date.day, birth_date.month)

        await state.update_data(
            birth_date=message.text,
            zodiac=zodiac
        )

        await state.set_state(UserDataStates.WAITING_BIRTH_TIME)

        await message.answer(
            f"✅ Отлично! Знак зодиака: {get_zodiac_emoji(zodiac)} {zodiac}\n\n"
            "🕒 Шаг 3 из 5\n\n"
            "Укажите точное время рождения в формате:\n"
            "ЧЧ:ММ\n\n"
            "Например: 15:30\n"
            "Если не знаете, напишите 00:00"
        )

    except ValueError:
        await message.answer("❌ Неверная дата! Попробуйте еще раз:")


# ==================== ШАГ 3: ВРЕМЯ РОЖДЕНИЯ ====================

@dp.message(UserDataStates.WAITING_BIRTH_TIME)
async def process_birth_time(message: Message, state: FSMContext):
    """Обработка времени рождения"""
    time_pattern = r'^\d{2}:\d{2}$'

    if not re.match(time_pattern, message.text):
        await message.answer(
            "❌ Неверный формат!\n\n"
            "Используйте формат ЧЧ:ММ\n"
            "Например: 15:30"
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
            "Например: Москва, Россия"
        )

    except ValueError:
        await message.answer("❌ Неверное время! Попробуйте еще раз:")


# ==================== ШАГ 4: МЕСТО РОЖДЕНИЯ ====================

@dp.message(UserDataStates.WAITING_BIRTH_PLACE)
async def process_birth_place(message: Message, state: FSMContext):
    """Обработка места рождения"""
    if len(message.text) < 3:
        await message.answer("❌ Укажите город и страну (минимум 3 символа):")
        return

    await state.update_data(birth_place=message.text)
    await state.set_state(UserDataStates.WAITING_GENDER)

    await message.answer(
        "👤 Шаг 5 из 5 (последний!)\n\n"
        "Укажите ваш пол:\n"
        "М - мужской\n"
        "Ж - женский\n\n"
        "Напишите: М или Ж"
    )


# ==================== ШАГ 5: ПОЛ ====================

@dp.message(UserDataStates.WAITING_GENDER)
async def process_gender(message: Message, state: FSMContext):
    """Обработка пола"""
    gender = message.text.upper()

    if gender not in ["М", "Ж"]:
        await message.answer(
            "❌ Пожалуйста, напишите только одну букву:\n"
            "М - мужской\n"
            "Ж - женский"
        )
        return

    # Получаем данные из состояния
    data = await state.get_data()
    data['gender'] = gender

    # Сохраняем в БД
    user_id = message.from_user.id
    await save_user_data(user_id, data)

    # Очищаем состояние
    await state.clear()

    # Показываем собранные данные
    zodiac_emoji = get_zodiac_emoji(data.get('zodiac', 'Неизвестно'))

    profile_text = (
        f"✅ Данные сохранены!\n\n"
        f"👤 Имя: {data.get('name', 'Не указано')}\n"
        f"📅 Дата рождения: {data.get('birth_date', 'Не указана')}\n"
        f"🕒 Время рождения: {data.get('birth_time', 'Не указано')}\n"
        f"📍 Место рождения: {data.get('birth_place', 'Не указано')}\n"
        f"👤 Пол: {'Мужской' if gender == 'М' else 'Женский'}\n"
        f"{zodiac_emoji} Знак зодиака: {data.get('zodiac', 'Неизвестно')}\n\n"
        "✨ Теперь я готов составить ваш персональный гороскоп!\n"
        "Нажмите на кнопку 🔮 Гороскоп на сегодня еще раз, чтобы получить прогноз."
    )

    await message.answer(
        profile_text,
        reply_markup=get_main_menu()
    )

# ==================== ОТМЕНА ====================

@dp.callback_query(F.data == "cancel")
async def cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена сбора данных"""
    await state.clear()
    await callback.message.delete()
    await callback.message.answer(
        "❌ Сбор данных отменен.\n"
        "Вы можете начать заново, нажав на нужную кнопку в меню",
        reply_markup=get_main_menu()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("zodiac_"))
async def process_zodiac_choice(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора знака зодиака (если дата не указана)"""
    zodiac = callback.data.replace("zodiac_", "")
    await state.update_data(zodiac=zodiac)
    await state.set_state(UserDataStates.WAITING_BIRTH_DATE)

    await callback.message.edit_text(
        f"✅ Выбран знак: {get_zodiac_emoji(zodiac)} {zodiac}\n\n"
        "📅 Теперь укажите дату рождения в формате ДД.ММ.ГГГГ"
    )
    await callback.answer()


# ==================== СОВМЕСТИМОСТЬ ====================

@dp.message(F.text == "💕 Совместимость")
async def start_compatibility(message: Message, state: FSMContext):
    """Начало анализа совместимости"""
    user_id = message.from_user.id

    # ✅ Используем БД
    if not await can_use_feature_db(user_id, 'compatibility'):
        await message.answer(
            "✨ Сегодняшний бесплатный анализ совместимости уже использован.\n\n"
            "Получайте неограниченный доступ\n"
            "за 299 ₽ в месяц.",
            reply_markup=get_subscription_keyboard()
        )
        return

    # Проверяем, есть ли данные пользователя
    user_data = await get_user_data(user_id)

    if user_data and user_data.get('name'):
        zodiac_emoji = get_zodiac_emoji(user_data.get('zodiac', 'Неизвестно'))

        profile_text = (
            f"💕 Анализ совместимости\n\n"
            f"👤 Ваши данные (Человек 1):\n"
            f"Имя: {user_data.get('name', 'Не указано')}\n"
            f"📅 Дата рождения: {user_data.get('birth_date', 'Не указана')}\n"
            f"🕒 Время рождения: {user_data.get('birth_time', 'Не указано')}\n"
            f"📍 Место рождения: {user_data.get('birth_place', 'Не указано')}\n"
            f"👤 Пол: {'Мужской' if user_data.get('gender') == 'М' else 'Женский'}\n"
            f"{zodiac_emoji} Знак зодиака: {user_data.get('zodiac', 'Неизвестно')}\n\n"
            "Хотите использовать эти данные для анализа совместимости?"
        )

        await message.answer(
            profile_text,
            reply_markup=get_compatibility_keyboard()
        )

        await state.update_data(person1_data=user_data)
        await state.set_state(CompatibilityStates.CONFIRM_DATA)

    else:
        await state.set_state(CompatibilityStates.WAITING_PERSON1_NAME)
        await message.answer(
            "💕 Давайте заполним данные для анализа совместимости.\n\n"
            "Сначала введите имя человека 1 (это вы):",
            reply_markup=get_cancel_keyboard()
        )


@dp.callback_query(F.data == "use_my_data")
async def use_my_data(callback: CallbackQuery, state: FSMContext):
    """Использовать сохраненные данные пользователя"""
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id

    # Получаем данные из состояния
    data = await state.get_data()
    person1 = data.get('person1_data', {})

    if not person1:
        await callback.message.answer(
            "❌ Данные не найдены. Пожалуйста, заполните заново.",
            reply_markup=get_main_menu()
        )
        await state.clear()
        return

    # Сохраняем данные в состояние для дальнейшего использования
    await state.update_data(person1=person1)

    # Переходим к сбору данных человека 2
    await state.set_state(CompatibilityStates.WAITING_PERSON2_NAME)

    await callback.message.answer(
        "✅ Отлично! Данные человека 1 сохранены.\n\n"
        "Теперь введите данные человека 2:\n"
        "❓ Как зовут человека 2?",
        reply_markup=get_cancel_keyboard()
    )


@dp.callback_query(F.data == "fill_person1")
async def fill_person1(callback: CallbackQuery, state: FSMContext):
    """Заполнить данные человека 1 заново"""
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
    """Имя человека 1"""
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
    """Дата рождения человека 1"""
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
    """Время рождения человека 1"""
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
    """Место рождения человека 1"""
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
    """Пол человека 1"""
    gender = message.text.upper()

    if gender not in ["М", "Ж"]:
        await message.answer(
            "❌ Напишите М или Ж:",
            reply_markup=get_cancel_keyboard()
        )
        return

    # Сохраняем данные
    data = await state.get_data()
    person1 = {
        'name': data.get('person1_name'),
        'birth_date': data.get('person1_birth_date'),
        'birth_time': data.get('person1_birth_time'),
        'birth_place': data.get('person1_birth_place'),
        'gender': gender,
        'zodiac': data.get('person1_zodiac')
    }

    # ✅ Сохраняем в состояние, а не в compatibility_data
    await state.update_data(person1=person1)

    # Переходим к сбору данных человека 2
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
    """Имя человека 2"""
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
    """Дата рождения человека 2"""
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
            "🕒 Введите время рождения человека 2 (ЧЧ:ММ)",
            reply_markup=get_cancel_keyboard()
        )

    except ValueError:
        await message.answer(
            "❌ Неверная дата! Попробуйте еще раз:",
            reply_markup=get_cancel_keyboard()
        )


@dp.message(CompatibilityStates.WAITING_PERSON2_BIRTH_TIME)
async def process_person2_birth_time(message: Message, state: FSMContext):
    """Время рождения человека 2"""
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
    """Место рождения человека 2"""
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
    """Пол человека 2"""
    gender = message.text.upper()

    if gender not in ["М", "Ж"]:
        await message.answer(
            "❌ Напишите М или Ж:",
            reply_markup=get_cancel_keyboard()
        )
        return

    data = await state.get_data()
    person2 = {
        'name': data.get('person2_name'),
        'birth_date': data.get('person2_birth_date'),
        'birth_time': data.get('person2_birth_time'),
        'birth_place': data.get('person2_birth_place'),
        'gender': gender,
        'zodiac': data.get('person2_zodiac')
    }

    # Получаем человека 1 из состояния
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
            await save_message_to_archive(user_id, 'compatibility', result)

            await status_msg.edit_text(
                f"💕 Анализ совместимости\n\n{result}",
                reply_markup=None
            )
        else:
            await status_msg.edit_text(
                "❌ Сервис астролога временно недоступен."
            )

    except Exception as e:
        await status_msg.edit_text(
            f"❌ Произошла ошибка при анализе:\n{str(e)}"
        )


# ==================== НАТАЛЬНАЯ КАРТА ====================

@dp.message(F.text == "🌌 Натальная карта")
async def start_natal(message: Message, state: FSMContext):
    """Начало оформления натальной карты"""
    user_id = message.from_user.id

    # ✅ Получаем данные пользователя из БД
    user_data_from_db = await get_user_data(user_id)

    # Проверяем, есть ли данные пользователя
    if user_data_from_db and user_data_from_db.get('name'):
        zodiac_emoji = get_zodiac_emoji(user_data_from_db.get('zodiac', 'Неизвестно'))

        # Проверяем, есть ли уже натальная карта
        natal_count = 0  # TODO: заменить на проверку из БД

        if natal_count > 0:
            profile_text = (
                f"🌌 Натальная карта\n\n"
                f"Ваши данные:\n"
                f"👤 Имя: {user_data_from_db.get('name', 'Не указано')}\n"
                f"📅 Дата рождения: {user_data_from_db.get('birth_date', 'Не указана')}\n"
                f"🕒 Время рождения: {user_data_from_db.get('birth_time', 'Не указано')}\n"
                f"📍 Место рождения: {user_data_from_db.get('birth_place', 'Не указано')}\n"
                f"{zodiac_emoji} Знак зодиака: {user_data_from_db.get('zodiac', 'Неизвестно')}\n\n"
                "Хотите получить разбор натальной карты?"
            )

            await message.answer(
                profile_text,
                reply_markup=get_natal_confirm_keyboard()
            )
            await state.set_state(NatalStates.CONFIRM_DATA)

        else:
            await message.answer(
                "🌌 Получить чёткий и пошаговый разбор вашего гороскопа\n\n"
                "Что вы получите:\n"
                "✓ Полный анализ личности\n"
                "✓ Предназначение и таланты\n"
                "✓ Отношения и совместимость\n"
                "✓ Карьера и финансы\n"
                "✓ Сильные и слабые стороны\n"
                "✓ Практические рекомендации\n\n"
                "💰 Стоимость: 999 ₽",
                reply_markup=get_natal_payment_keyboard()
            )
            await state.set_state(NatalStates.PAYMENT)
    else:
        await state.set_state(NatalStates.WAITING_NAME)
        await message.answer(
            "🌌 Для оформления натальной карты мне нужно узнать вас получше.\n\n"
            "❓ Как вас зовут?",
            reply_markup=get_cancel_keyboard()
        )


@dp.callback_query(F.data == "natal_use_my_data")
async def natal_use_my_data(callback: CallbackQuery, state: FSMContext):
    """Использовать сохраненные данные для натальной карты"""
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id

    # ✅ Проверяем оплату через состояние
    data = await state.get_data()
    if not data.get('natal_paid', False):
        await callback.message.answer(
            "⚠️ Сначала необходимо оплатить натальную карту.\n\n"
            "💰 Стоимость: 999 ₽",
            reply_markup=get_natal_payment_keyboard()
        )
        await state.set_state(NatalStates.PAYMENT)
        return

    user_data_from_db = await get_user_data(user_id)

    if not user_data_from_db or not user_data_from_db.get('name'):
        await callback.message.answer(
            "❌ Данные не найдены. Пожалуйста, заполните заново.",
            reply_markup=get_main_menu()
        )
        await state.clear()
        return

    natal_data[user_id] = {
        'name': user_data_from_db.get('name'),
        'birth_date': user_data_from_db.get('birth_date'),
        'birth_time': user_data_from_db.get('birth_time'),
        'birth_place': user_data_from_db.get('birth_place'),
        'gender': user_data_from_db.get('gender'),
        'zodiac': user_data_from_db.get('zodiac')
    }

    await state.clear()

    zodiac_emoji = get_zodiac_emoji(user_data_from_db.get('zodiac', 'Неизвестно'))
    profile_text = (
        f"✅ Используем ваши данные:\n\n"
        f"👤 Имя: {user_data_from_db.get('name')}\n"
        f"📅 Дата рождения: {user_data_from_db.get('birth_date')}\n"
        f"🕒 Время рождения: {user_data_from_db.get('birth_time')}\n"
        f"📍 Место рождения: {user_data_from_db.get('birth_place')}\n"
        f"👤 Пол: {'Мужской' if user_data_from_db.get('gender') == 'М' else 'Женский'}\n"
        f"{zodiac_emoji} Знак зодиака: {user_data_from_db.get('zodiac')}\n\n"
        "🌌 Начинаю построение натальной карты... 🔮"
    )

    status_msg = await callback.message.answer(profile_text)

    try:
        await status_msg.edit_text("✨ Изучаю положение планет в момент рождения...")
        await asyncio.sleep(1)
        await status_msg.edit_text("🌙 Анализирую аспекты и дома...")
        await asyncio.sleep(1)
        await status_msg.edit_text("⭐ Формирую полный разбор натальной карты...")
        await asyncio.sleep(2)

        if gemini_service:
            result = gemini_service.generate_natal_chart(natal_data[user_id])

            await status_msg.delete()
            await send_long_message(callback.message, f"🌌 Ваша натальная карта\n\n{result}")
        else:
            await status_msg.edit_text(
                "❌ Сервис астролога временно недоступен."
            )

    except Exception as e:
        await status_msg.edit_text(
            f"❌ Произошла ошибка при построении карты:\n{str(e)}"
        )

@dp.callback_query(F.data == "natal_fill_new_data")
async def natal_fill_new_data(callback: CallbackQuery, state: FSMContext):
    """Заполнить новые данные для натальной карты"""
    await callback.message.delete()
    await callback.answer()

    # Проверяем оплату
    user_id = callback.from_user.id
    if not natal_payment_status.get(user_id, False):
        await callback.message.answer(
            "⚠️ Сначала необходимо оплатить натальную карту.\n\n"
            "💰 Стоимость: 999 ₽",
            reply_markup=get_natal_payment_keyboard()
        )
        await state.set_state(NatalStates.PAYMENT)
        return

    await state.set_state(NatalStates.WAITING_NAME)
    await callback.message.answer(
        "✏️ Введите имя для натальной карты:",
        reply_markup=get_cancel_keyboard()
    )

# ==================== ОПЛАТА НАТАЛЬНОЙ КАРТЫ ====================

@dp.callback_query(F.data == "natal_pay", NatalStates.PAYMENT)
async def natal_payment(callback: CallbackQuery, state: FSMContext):
    """Обработка оплаты натальной карты"""
    await callback.message.delete()
    await callback.answer()

    # ✅ Сохраняем статус оплаты в состояние
    await state.update_data(natal_paid=True)

    await callback.message.answer(
        "✅ Оплата прошла успешно!\n\n"
        "🌌 Теперь выберите, какие данные использовать для натальной карты."
    )

    user_id = callback.from_user.id
    user_data_from_db = await get_user_data(user_id)

    if user_data_from_db and user_data_from_db.get('name'):
        zodiac_emoji = get_zodiac_emoji(user_data_from_db.get('zodiac', 'Неизвестно'))

        profile_text = (
            f"👤 Ваши сохраненные данные:\n"
            f"Имя: {user_data_from_db.get('name', 'Не указано')}\n"
            f"📅 Дата рождения: {user_data_from_db.get('birth_date', 'Не указана')}\n"
            f"🕒 Время рождения: {user_data_from_db.get('birth_time', 'Не указано')}\n"
            f"📍 Место рождения: {user_data_from_db.get('birth_place', 'Не указано')}\n"
            f"👤 Пол: {'Мужской' if user_data_from_db.get('gender') == 'М' else 'Женский'}\n"
            f"{zodiac_emoji} Знак зодиака: {user_data_from_db.get('zodiac', 'Неизвестно')}\n\n"
            "Хотите использовать эти данные?"
        )

        await callback.message.answer(
            profile_text,
            reply_markup=get_natal_use_data_keyboard()
        )
        await state.update_data(natal_data_from_profile=user_data_from_db)
        await state.set_state(NatalStates.CONFIRM_DATA)
    else:
        await state.set_state(NatalStates.WAITING_NAME)
        await callback.message.answer(
            "❓ Как вас зовут?",
            reply_markup=get_cancel_keyboard()
        )

# ==================== СБОР ДАННЫХ ДЛЯ НАТАЛЬНОЙ КАРТЫ ====================

@dp.message(NatalStates.WAITING_NAME)
async def process_natal_name(message: Message, state: FSMContext):
    """Имя для натальной карты"""
    if len(message.text) < 2:
        await message.answer("❌ Имя должно содержать хотя бы 2 символа:")
        return

    await state.update_data(name=message.text)
    await state.set_state(NatalStates.WAITING_BIRTH_DATE)

    await message.answer(
        f"✅ Имя: {message.text}\n\n"
        "📅 Введите дату рождения в формате ДД.ММ.ГГГГ",
        reply_markup=get_cancel_keyboard()
    )


@dp.message(NatalStates.WAITING_BIRTH_DATE)
async def process_natal_birth_date(message: Message, state: FSMContext):
    """Дата рождения для натальной карты"""
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
            birth_date=message.text,
            zodiac=zodiac
        )
        await state.set_state(NatalStates.WAITING_BIRTH_TIME)

        await message.answer(
            f"✅ Знак зодиака: {get_zodiac_emoji(zodiac)} {zodiac}\n\n"
            "🕒 Введите время рождения (ЧЧ:ММ)\n"
            "Например: 15:30",
            reply_markup=get_cancel_keyboard()
        )

    except ValueError:
        await message.answer(
            "❌ Неверная дата! Попробуйте еще раз:",
            reply_markup=get_cancel_keyboard()
        )


@dp.message(NatalStates.WAITING_BIRTH_TIME)
async def process_natal_birth_time(message: Message, state: FSMContext):
    """Время рождения для натальной карты"""
    time_pattern = r'^\d{2}:\d{2}$'

    if not re.match(time_pattern, message.text):
        await message.answer(
            "❌ Неверный формат! Используйте ЧЧ:ММ",
            reply_markup=get_cancel_keyboard()
        )
        return

    try:
        datetime.strptime(message.text, "%H:%M")
        await state.update_data(birth_time=message.text)
        await state.set_state(NatalStates.WAITING_BIRTH_PLACE)

        await message.answer(
            "📍 Введите место рождения:\n"
            "Город, Страна",
            reply_markup=get_cancel_keyboard()
        )

    except ValueError:
        await message.answer(
            "❌ Неверное время! Попробуйте еще раз:",
            reply_markup=get_cancel_keyboard()
        )


@dp.message(NatalStates.WAITING_BIRTH_PLACE)
async def process_natal_birth_place(message: Message, state: FSMContext):
    """Место рождения для натальной карты"""
    if len(message.text) < 3:
        await message.answer(
            "❌ Укажите город и страну (минимум 3 символа):",
            reply_markup=get_cancel_keyboard()
        )
        return

    await state.update_data(birth_place=message.text)
    await state.set_state(NatalStates.WAITING_GENDER)

    await message.answer(
        "👤 Укажите пол:\n"
        "М - мужской\n"
        "Ж - женский\n\n"
        "Напишите: М или Ж",
        reply_markup=get_cancel_keyboard()
    )


@dp.message(NatalStates.WAITING_GENDER)
async def process_natal_gender(message: Message, state: FSMContext):
    """Пол для натальной карты"""
    gender = message.text.upper()

    if gender not in ["М", "Ж"]:
        await message.answer(
            "❌ Напишите М или Ж:",
            reply_markup=get_cancel_keyboard()
        )
        return

    data = await state.get_data()

    # ✅ Проверяем оплату через состояние
    if not data.get('natal_paid', False):
        await message.answer(
            "⚠️ Оплата не подтверждена. Пожалуйста, оплатите 999 ₽.",
            reply_markup=get_natal_payment_keyboard()
        )
        await state.set_state(NatalStates.PAYMENT)
        return

    if not data.get('name'):
        await message.answer(
            "❌ Данные не найдены. Пожалуйста, начните заново.",
            reply_markup=get_main_menu()
        )
        await state.clear()
        return

    data['gender'] = gender

    user_id = message.from_user.id
    natal_data[user_id] = {
        'name': data.get('name'),
        'birth_date': data.get('birth_date'),
        'birth_time': data.get('birth_time'),
        'birth_place': data.get('birth_place'),
        'gender': gender,
        'zodiac': data.get('zodiac')
    }

    await state.clear()

    zodiac_emoji = get_zodiac_emoji(data.get('zodiac', 'Неизвестно'))
    profile_text = (
        f"✅ Данные сохранены!\n\n"
        f"👤 Имя: {data.get('name')}\n"
        f"📅 Дата рождения: {data.get('birth_date')}\n"
        f"🕒 Время рождения: {data.get('birth_time')}\n"
        f"📍 Место рождения: {data.get('birth_place')}\n"
        f"👤 Пол: {'Мужской' if gender == 'М' else 'Женский'}\n"
        f"{zodiac_emoji} Знак зодиака: {data.get('zodiac')}\n\n"
        "🌌 Начинаю построение натальной карты... 🔮"
    )

    status_msg = await message.answer(profile_text)

    try:
        await status_msg.edit_text("✨ Изучаю положение планет в момент рождения...")
        await asyncio.sleep(1)
        await status_msg.edit_text("🌙 Анализирую аспекты и дома...")
        await asyncio.sleep(1)
        await status_msg.edit_text("⭐ Формирую полный разбор натальной карты...")
        await asyncio.sleep(2)

        if gemini_service:
            result = gemini_service.generate_natal_chart(natal_data[user_id])

            await status_msg.delete()
            await send_long_message(message, f"🌌 Ваша натальная карта\n\n{result}")
        else:
            await status_msg.edit_text(
                "❌ Сервис астролога временно недоступен."
            )

    except Exception as e:
        await status_msg.edit_text(
            f"❌ Произошла ошибка при построении карты:\n{str(e)}"
        )

# ==================== ПОДТВЕРЖДЕНИЕ НАТАЛЬНОЙ КАРТЫ ====================

@dp.callback_query(F.data == "natal_confirm", NatalStates.CONFIRM_DATA)
async def natal_confirm(callback: CallbackQuery, state: FSMContext):
    """Подтверждение данных для натальной карты"""
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id

    # ✅ Получаем данные из БД
    user_data_from_db = await get_user_data(user_id)

    if not user_data_from_db or not user_data_from_db.get('name'):
        await callback.message.answer(
            "❌ Данные не найдены. Пожалуйста, начните заново.",
            reply_markup=get_main_menu()
        )
        await state.clear()
        return

    # Сохраняем данные
    natal_data[user_id] = user_data_from_db

    await state.clear()

    status_msg = await callback.message.answer(
        "🌌 Начинаю построение натальной карты... 🔮"
    )

    try:
        await status_msg.edit_text("✨ Изучаю положение планет в момент рождения...")
        await asyncio.sleep(1)
        await status_msg.edit_text("🌙 Анализирую аспекты и дома...")
        await asyncio.sleep(1)
        await status_msg.edit_text("⭐ Формирую полный разбор натальной карты...")
        await asyncio.sleep(2)

        if gemini_service:
            result = gemini_service.generate_natal_chart(natal_data[user_id])

            await status_msg.delete()
            await send_long_message(callback.message, f"🌌 Ваша натальная карта\n\n{result}")
        else:
            await status_msg.edit_text(
                "❌ Сервис астролога временно недоступен."
            )

    except Exception as e:
        await status_msg.edit_text(
            f"❌ Ошибка: {str(e)}"
        )


# ==================== ОБРАБОТКА ДРУГИХ КНОПОК МЕНЮ ====================

@dp.message(F.text.in_([
    "📚 Архив",
    "⚙️ Мой профиль"
]))
async def handle_menu_buttons(message: Message, state: FSMContext):
    """Обработка остальных кнопок меню (кроме гороскопа, совместимости, натальной карты и эксперта)"""
    text = message.text

    if text == "📚 Архив":
        await show_archive(message)
    elif text == "⚙️ Мой профиль":
        await profile(message)

# ==================== ПРОФИЛЬ ====================

async def profile(message: Message):
    """Показать профиль пользователя"""
    user_id = message.from_user.id

    # Получаем данные из БД
    user_data = await get_user_data(user_id)

    if user_data and user_data.get('name'):
        zodiac_emoji = get_zodiac_emoji(user_data.get('zodiac', 'Неизвестно'))

        profile_text = (
            f"👤 Ваш профиль\n\n"
            f"Имя: {user_data.get('name', 'Не указано')}\n"
            f"📅 Дата рождения: {user_data.get('birth_date', 'Не указана')}\n"
            f"🕒 Время рождения: {user_data.get('birth_time', 'Не указано')}\n"
            f"📍 Место рождения: {user_data.get('birth_place', 'Не указано')}\n"
            f"👤 Пол: {'Мужской' if user_data.get('gender') == 'М' else 'Женский'}\n"
            f"{zodiac_emoji} Знак зодиака: {user_data.get('zodiac', 'Неизвестно')}\n\n"
            "📌 Нажмите 🔮 Гороскоп на сегодня, чтобы получить новый прогноз."
        )
        await message.answer(profile_text)
    else:
        await message.answer(
            "📝 У вас пока нет сохраненных данных.\n"
            "Нажмите 🔮 Гороскоп на сегодня, чтобы заполнить профиль."
        )

async def send_long_message(message: Message, text: str, max_length: int = 4096):
    """
    Отправка длинного сообщения с разбивкой на части
    """
    if len(text) <= max_length:
        await message.answer(text)
        return

    # Разбиваем по частям
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

    # Отправляем каждую часть
    for i, part in enumerate(parts, 1):
        if i == 1:
            await message.answer(part)
        else:
            await message.answer(f"📄 Продолжение ({i}/{len(parts)}):\n\n{part}")


# ==================== ЭКСПЕРТ ====================

@dp.message(F.text == "👤 Эксперт")
async def expert_request(message: Message):
    """Обработка запроса к эксперту"""
    user_id = message.from_user.id
    username = message.from_user.username or "Не указан"
    first_name = message.from_user.first_name or "Не указано"

    # Получаем данные пользователя, если есть
    user_info = ""
    if user_id in user_data:
        data = user_data[user_id]
        user_info = (
            f"\n👤 Имя: {data.get('name', 'Не указано')}"
            f"\n📅 Дата рождения: {data.get('birth_date', 'Не указана')}"
            f"\n🕒 Время рождения: {data.get('birth_time', 'Не указано')}"
            f"\n📍 Место рождения: {data.get('birth_place', 'Не указано')}"
            f"\n♈ Знак зодиака: {data.get('zodiac', 'Неизвестно')}"
        )

    expert_text = (
        "👤 Экспертный разбор гороскопа\n\n"
        "Индивидуальный разбор гороскопа экспертом.\n"
        "Получите детальный анализ вашей натальной карты.\n\n"
        "💰 Стоимость: 5000 ₽\n\n"
        "Нажмите кнопку ниже, чтобы отправить заявку эксперту."
    )

    await message.answer(
        expert_text,
        reply_markup=get_expert_keyboard()
    )


@dp.callback_query(F.data == "expert_request")
async def send_expert_request(callback: CallbackQuery):
    """Отправка заявки эксперту"""
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id
    username = callback.from_user.username or "Не указан"
    first_name = callback.from_user.first_name or "Не указано"

    # Получаем данные пользователя
    user_info = ""
    if user_id in user_data:
        data = user_data[user_id]
        user_info = (
            f"\n👤 Имя: {data.get('name', 'Не указано')}"
            f"\n📅 Дата рождения: {data.get('birth_date', 'Не указана')}"
            f"\n🕒 Время рождения: {data.get('birth_time', 'Не указано')}"
            f"\n📍 Место рождения: {data.get('birth_place', 'Не указано')}"
            f"\n♈ Знак зодиака: {data.get('zodiac', 'Неизвестно')}"
        )

    # Сообщение пользователю
    await callback.message.answer(
        "✅ Заявка отправлена! 📩\n\n"
        "Эксперт свяжется с вами в ближайшее время.",
        reply_markup=get_main_menu()
    )

    # Отправляем уведомление эксперту
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

@dp.message(F.text == "⭐ Подписка")
async def show_subscription(message: Message):
    """Показать информацию о подписке"""
    user_id = message.from_user.id

    # Проверяем подписку через БД
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
            "⭐ Подписка 299 ₽/МЕС\n\n"
            "✨ Что вы получите:\n"
            "✓ Ежедневный персональный гороскоп\n"
            "✓ Совместимость без ограничений\n"
            "✓ Архив всех прогнозов\n"
            "✓ Автоматическая отправка в 8:00\n"
            "✓ Приоритетная поддержка\n\n"
            "💰 299 ₽ / месяц\n\n"
            "Нажмите кнопку ниже, чтобы оформить подписку.",
            reply_markup=get_subscription_keyboard()
        )


@dp.callback_query(F.data == "subscribe_pay")
async def subscribe_payment(callback: CallbackQuery):
    """Обработка оплаты подписки"""
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id

    # TODO: Интеграция с ЮKassa
    await callback.message.answer(
        "💳 Оплата 299 ₽\n\n"
        "⚠️ Это демо-версия. Считаем, что оплата прошла успешно!"
    )

    # Активируем подписку в БД
    await activate_subscription_db(user_id, days=30)

    await callback.message.answer(
        "🎉 Поздравляем! Подписка активирована!\n\n"
        "Теперь вам доступны все функции Premium:\n"
        "✓ Ежедневный гороскоп\n"
        "✓ Совместимость без ограничений\n"
        "✓ Архив прогнозов\n"
        "✓ Автоматическая отправка в 8:00\n\n"
        "📅 Подписка активна на 30 дней",
        reply_markup=get_main_menu()
    )

@dp.callback_query(F.data == "subscribe_extend")
async def subscribe_extend(callback: CallbackQuery):
    """Продление подписки"""
    await callback.message.delete()
    await callback.answer()

    await callback.message.answer(
        "🔄 Продление подписки\n\n"
        "💰 299 ₽ / месяц\n\n"
        "Нажмите кнопку ниже для продления.",
        reply_markup=get_subscription_keyboard()
    )


def activate_subscription(user_id: int, days: int = 30):
    """Активация подписки"""
    until = datetime.now() + timedelta(days=days)

    if user_id not in subscriptions:
        subscriptions[user_id] = {}

    subscriptions[user_id]['active'] = True
    subscriptions[user_id]['until'] = until

    logger.info(f"✅ Подписка активирована для пользователя {user_id} до {until}")

# ==================== ОБРАБОТКА НЕИЗВЕСТНЫХ СООБЩЕНИЙ ====================

@dp.message()
async def handle_unknown(message: Message):
    """Обработка неизвестных сообщений"""
    await message.answer(
        "❓ Я не понял вашу команду.\n"
        "Используйте кнопки меню или напишите /start"
    )


# ==================== АРХИВ ====================

async def show_archive(message: Message):
    """Показать архив прогнозов пользователя"""
    user_id = message.from_user.id

    messages = await get_user_archive(user_id, limit=10)

    if not messages:
        await message.answer(
            "📚 Архив пуст\n\n"
            "У вас пока нет сохранённых прогнозов.",
            reply_markup=get_main_menu()
        )
        return

    # Словарь для отображения типов
    type_display_map = {
        'horoscope': 'Гороскоп',
        'compatibility': 'Совместимость',
        'natal_chart': 'Натальная карта',
    }

    type_emoji_map = {
        'horoscope': '🔮',
        'compatibility': '💕',
        'natal_chart': '🌌'
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
    """Обновить архив"""
    await callback.answer()
    await callback.message.delete()

    # Создаём новое сообщение с архивом
    # Передаём callback.message как объект, который можно использовать как Message
    class FakeMessage:
        def __init__(self, callback):
            self.from_user = callback.from_user
            self.chat = callback.message.chat
            self.answer = callback.message.answer

    fake_msg = FakeMessage(callback)
    await show_archive(fake_msg)


@dp.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: CallbackQuery):
    """Вернуться в главное меню"""
    await callback.answer()
    await callback.message.delete()
    await callback.message.answer(
        "📌 Главное меню:",
        reply_markup=get_main_menu()
    )


#from asgiref.sync import sync_to_async


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
        # Получаем сообщение через db.py
        from bot.db import get_archive_message
        msg = await get_archive_message(message_id, callback.from_user.id)

        if not msg:
            await callback.message.answer(
                "❌ Сообщение не найдено или у вас нет доступа.",
                reply_markup=get_main_menu()
            )
            return

        # Словари для отображения (без импорта UserMessage)
        type_emoji = {
            'horoscope': '🔮',
            'compatibility': '💕',
            'natal_chart': '🌌'
        }

        type_display = {
            'horoscope': 'Гороскоп',
            'compatibility': 'Совместимость',
            'natal_chart': 'Натальная карта'
        }

        emoji = type_emoji.get(msg.message_type, '📝')
        type_name = type_display.get(msg.message_type, msg.message_type)

        full_text = (
            f"{emoji} {type_name}\n"
            f"📅 {msg.date.strftime('%d.%m.%Y %H:%M')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{msg.content}"
        )

        await callback.message.answer(full_text, reply_markup=get_main_menu())

    except Exception as e:
        await callback.message.answer(
            f"❌ Ошибка: {str(e)}",
            reply_markup=get_main_menu()
        )


@dp.callback_query(F.data == "archive_refresh")
async def refresh_archive(callback: CallbackQuery):
    """Обновить архив"""
    await callback.answer()
    await callback.message.delete()

    # ✅ Используем show_archive с правильным объектом
    class FakeMessage:
        def __init__(self, callback):
            self.from_user = callback.from_user
            self.chat = callback.message.chat
            self.answer = callback.message.answer

    fake_msg = FakeMessage(callback)
    await show_archive(fake_msg)


#@dp.message(Command("test_send"))
#async def test_send(message: Message):
#    """Тестовая отправка гороскопа (только для админа)"""
#    # Проверяем, что пользователь админ (замените на свой ID)
#    ADMIN_ID = 123456789  # ← ВАШ ID
#
#    if message.from_user.id != ADMIN_ID:
#        await message.answer("❌ У вас нет доступа к этой команде.")
#        return
#
#    await message.answer("⏳ Начинаю тестовую рассылку...")
#    await send_daily_horoscopes(bot)

# ==================== ЗАПУСК ====================

async def main():
    """Запуск бота"""
    logger.info("🚀 Запуск бота MySmartAstrologBot...")

    bot_info = await bot.get_me()
    logger.info(f"🤖 Бот @{bot_info.username} готов к работе!")

    if gemini_service:
        logger.info("✅ Gemini API готов к работе!")
    else:
        logger.warning("⚠️ Gemini API НЕ ДОСТУПЕН! Проверьте API ключ в .env")

    # ✅ Запускаем планировщик
    scheduler = setup_scheduler(bot)

    try:
        await dp.start_polling(bot)
    finally:
        # Останавливаем планировщик при завершении
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
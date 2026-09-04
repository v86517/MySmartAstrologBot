# bot/handlers/astrology.py
import asyncio
import logging
import re
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext

from bot.utils.helpers import get_text
from bot.utils.messaging import send_long_message
from bot.keyboards.keyboards import (
    get_main_menu,
    get_cancel_keyboard,
    get_astrology_payment_keyboard,
    get_astrology_confirm_keyboard,
    #get_astrology_use_data_keyboard,
    get_payment_url_keyboard,
    get_main_menu_button,
)
from bot.states.states import AstrologyStates
from bot.utils.zodiac import calculate_zodiac_sign, get_zodiac_emoji, get_zodiac_sign_localized
from bot.utils.validators import normalize_gender
from bot.db import (
    get_user_data,
    check_subscription_db,
    can_use_feature_db,
    mark_feature_used_db,
    save_message_to_archive,
    get_user_language,
    is_user_admin,
    add_astrology_count,
    save_payment_db,
    get_service_price,
)
from bot.yookassa_client import yookassa
from bot.calculators.astrology_calculator import AstrologyCalculator
from bot.db import get_emulation_mode

logger = logging.getLogger(__name__)
router = Router()

_gemini_service = None

def set_gemini_service(service):
    global _gemini_service
    _gemini_service = service

# Глобальный словарь для временного хранения данных астрологии
astrology_data = {}

# ==================== ФУНКЦИЯ-СТАРТЕР ДЛЯ КНОПКИ МЕНЮ ====================
async def start_astrology(message: Message, state: FSMContext):
    """Начало процесса астрологии (вызывается из handle_menu_commands)"""
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    user_data = await get_user_data(user_id)
    astro_count = user_data.get('astrology_count', 0) if user_data else 0

    if astro_count == 0:
        await state.set_state(AstrologyStates.PAYMENT)
        await message.answer(
            await get_text(user_id, 'astrology_no_data'),
            reply_markup=get_astrology_payment_keyboard(lang)
        )
        return

    if user_data and user_data.get('name'):
        zodiac_emoji = get_zodiac_emoji(user_data.get('zodiac', 'Неизвестно'))
        zodiac_name = get_zodiac_sign_localized(user_data.get('zodiac', 'Неизвестно'), lang)
        template = await get_text(user_id, 'astrology_start')
        profile_text = template.format(
            name=user_data.get('name', 'Не указано'),
            birth_date=user_data.get('birth_date', 'Не указана'),
            birth_time=user_data.get('birth_time', 'Не указано'),
            birth_place=user_data.get('birth_place', 'Не указано'),
            emoji=zodiac_emoji,
            zodiac=zodiac_name
        )
        await state.set_state(AstrologyStates.CONFIRM_DATA)
        await message.answer(
            profile_text,
            reply_markup=get_astrology_confirm_keyboard(lang)
        )
    else:
        await state.set_state(AstrologyStates.WAITING_NAME)
        await message.answer(
            await get_text(user_id, 'astrology_no_user_data'),
            reply_markup=get_cancel_keyboard(lang)
        )


# ==================== ОБРАБОТЧИКИ СОСТОЯНИЙ ====================

@router.message(AstrologyStates.WAITING_NAME)
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


@router.message(AstrologyStates.WAITING_BIRTH_DATE)
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


@router.message(AstrologyStates.WAITING_BIRTH_TIME)
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


@router.message(AstrologyStates.WAITING_BIRTH_PLACE)
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


@router.message(AstrologyStates.WAITING_GENDER)
async def process_astrology_gender(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    gender = normalize_gender(message.text)

    if gender is None:
        await message.answer(
            await get_text(user_id, 'error_invalid_gender'),
            reply_markup=get_cancel_keyboard(lang)
        )
        return

    data = await state.get_data()

    # Сохраняем данные во временное хранилище
    astrology_data[user_id] = {
        'name': data.get('astrology_name'),
        'birth_date': data.get('astrology_birth_date'),
        'birth_time': data.get('astrology_birth_time'),
        'birth_place': data.get('astrology_birth_place'),
        'gender': gender,
        'zodiac': data.get('astrology_zodiac'),
        'is_manual': True
    }

    # Показываем подтверждение
    zodiac_emoji = get_zodiac_emoji(data.get('astrology_zodiac', 'Неизвестно'))
    zodiac_name = get_zodiac_sign_localized(data.get('astrology_zodiac', 'Неизвестно'), lang)
    gender_display = await get_text(user_id, 'astro_gender_male') if gender == 'M' else await get_text(user_id, 'astro_gender_female')
    template = await get_text(user_id, 'astrology_confirm_data')
    profile_text = template.format(
        name=data.get('astrology_name'),
        gender=gender_display,
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


# ==================== CALLBACK-ХЕНДЛЕРЫ ====================

@router.callback_query(F.data == "astrology_use_my_data")
async def astrology_use_my_data(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    # 1. Проверяем, есть ли сохранённые данные
    user_data_from_db = await get_user_data(user_id)
    if not user_data_from_db or not user_data_from_db.get('name'):
        await callback.message.answer(await get_text(user_id, 'astrology_data_not_found'), reply_markup=get_main_menu(lang))
        await state.clear()
        return

    # 2. Проверяем оплату
    astro_count = user_data_from_db.get('astrology_count', 0)
    if astro_count <= 0:
        await callback.message.answer(await get_text(user_id, 'astrology_payment_required'), reply_markup=get_astrology_payment_keyboard(lang))
        await state.set_state(AstrologyStates.PAYMENT)
        return

    # 3. Режим эмуляции
    emulation = await get_emulation_mode(user_id)

    # 4. Создаём калькулятор
    calc = AstrologyCalculator(
        user_data=user_data_from_db,
        lang=lang,
        telegram_id=user_id,
        coords=None,
        emulation_mode=emulation,
        gemini_service=_gemini_service
    )

    await callback.message.answer("⏳ Строим натальную карту...", reply_markup=ReplyKeyboardRemove())

    try:
        # 5. Генерируем результат – сохраняем в БД (данные из профиля)
        result = await calc.generate(save_to_db=True)
        basic = calc.get_basic_parameters()

        if emulation:
            final_text = result
        else:
            basic_text = (
                f"🌙 Ваш астрологический разбор\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Имя: {basic['name']}\n"
                f"⚥ Пол: {basic['gender']}\n"
                f"📅 Дата рождения: {basic['birth_date']}\n"
                f"🕒 Время рождения: {basic['birth_time']}\n"
                f"📍 Место рождения: {basic['birth_place']}\n"
                f"🌐 Координаты: {basic['lat']}, {basic['lng']}\n"
                f"🕒 UTC время рождения: {basic['utc_datetime']}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
            )
            final_text = f"{basic_text}\n\n{result}"

        # Если администратор, добавляем натальный контекст
        if await is_user_admin(user_id):
            natal_context = calc.get_natal_context(lang)
            final_text += f"\n\n━━━━━━━━━━━━━━━━━━━━━\n📊 **Натальный контекст (для администратора):**\n{natal_context}"

        await save_message_to_archive(user_id, 'astrology', final_text)
        await add_astrology_count(user_id, -1)

        await send_long_message(callback.message, final_text, reply_markup=get_main_menu_button(lang))

    except Exception as e:
        logger.error(f"Ошибка в astrology_use_my_data: {e}", exc_info=True)
        await callback.message.answer(f"❌ Ошибка: {str(e)}", reply_markup=get_main_menu(lang))

    await state.clear()


@router.callback_query(F.data == "astrology_fill_new_data")
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


@router.callback_query(F.data == "astrology_pay", AstrologyStates.PAYMENT)
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

    price = await get_service_price('astrology')
    if price is None:
        price = 999.00

    result = yookassa.create_payment(
        user_id=user_id,
        amount=float(price),
        description=f"Астрология (ID: {user_id})",
        payment_type='astrology'
    )

    if result['success']:
        await save_payment_db(user_id, result['payment_id'], float(price), 'astrology', 'pending')
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


@router.callback_query(F.data == "astrology_confirm", AstrologyStates.CONFIRM_DATA)
async def astrology_confirm(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.answer()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    # 1. Получаем данные пользователя (из БД или из временного хранилища)
    manual_data = astrology_data.get(user_id)
    if manual_data and manual_data.get('is_manual'):
        # Данные введены вручную
        user_data = {k: v for k, v in manual_data.items() if k != 'is_manual'}
        astrology_data.pop(user_id, None)
        save_to_db = False  # ручной ввод – не сохраняем в БД
    else:
        # Берём из БД
        user_data = await get_user_data(user_id)
        if not user_data or not user_data.get('name'):
            await callback.message.answer(await get_text(user_id, 'error_not_found'), reply_markup=get_main_menu(lang))
            await state.clear()
            return
        save_to_db = True   # данные из профиля – сохраняем/обновляем

    # 2. Проверяем наличие оплаченных сессий (всегда из БД)
    user_data_from_db = await get_user_data(user_id)
    astro_count = user_data_from_db.get('astrology_count', 0) if user_data_from_db else 0
    if astro_count <= 0:
        await callback.message.answer(await get_text(user_id, 'astrology_payment_required'), reply_markup=get_astrology_payment_keyboard(lang))
        await state.set_state(AstrologyStates.PAYMENT)
        return

    # 3. Режим эмуляции
    emulation = await get_emulation_mode(user_id)

    # 4. Создаём калькулятор
    calc = AstrologyCalculator(
        user_data=user_data,
        lang=lang,
        telegram_id=user_id,
        coords=None,
        emulation_mode=emulation,
        gemini_service=_gemini_service
    )

    await callback.message.answer("⏳ Строим натальную карту...", reply_markup=ReplyKeyboardRemove())

    try:
        # 5. Генерируем результат с учётом флага сохранения
        result = await calc.generate(save_to_db=save_to_db)
        basic = calc.get_basic_parameters()

        # 6. Формируем вывод
        if emulation:
            final_text = result
        else:
            basic_text = (
                f"🌙 Ваш астрологический разбор\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Имя: {basic['name']}\n"
                f"⚥ Пол: {basic['gender']}\n"
                f"📅 Дата рождения: {basic['birth_date']}\n"
                f"🕒 Время рождения: {basic['birth_time']}\n"
                f"📍 Место рождения: {basic['birth_place']}\n"
                f"🌐 Координаты: {basic['lat']}, {basic['lng']}\n"
                f"🕒 UTC время рождения: {basic['utc_datetime']}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
            )
            final_text = f"{basic_text}\n\n{result}"

        # Если администратор, добавляем натальный контекст
        if await is_user_admin(user_id):
            natal_context = calc.get_natal_context(lang)
            final_text += f"\n\n━━━━━━━━━━━━━━━━━━━━━\n📊 **Натальный контекст (для администратора):**\n{natal_context}"

        # 7. Сохраняем в архив и списываем сессию
        await save_message_to_archive(user_id, 'astrology', final_text)
        await add_astrology_count(user_id, -1)

        # 8. Отправляем
        await send_long_message(callback.message, final_text, reply_markup=get_main_menu_button(lang))

    except Exception as e:
        logger.error(f"Ошибка в astrology_confirm: {e}", exc_info=True)
        await callback.message.answer(f"❌ Ошибка: {str(e)}", reply_markup=get_main_menu(lang))

    await state.clear()


@router.callback_query(F.data == "edit_astrology_data")
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
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
    get_astrology_use_data_keyboard,
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

    user_data_from_db = await get_user_data(user_id)
    astro_count = user_data_from_db.get('astrology_count', 0) if user_data_from_db else 0

    if astro_count > 0:
        astrology_data[user_id] = {
            'name': data.get('astrology_name'),
            'birth_date': data.get('astrology_birth_date'),
            'birth_time': data.get('astrology_birth_time'),
            'birth_place': data.get('astrology_birth_place'),
            'gender': gender,
            'zodiac': data.get('astrology_zodiac'),
            'is_manual': True
        }

        zodiac_emoji = get_zodiac_emoji(data.get('astrology_zodiac', 'Неизвестно'))
        zodiac_name = get_zodiac_sign_localized(data.get('astrology_zodiac', 'Неизвестно'), lang)
        if gender == 'M':
            gender_display = await get_text(user_id, 'astro_gender_male')
        else:
            gender_display = await get_text(user_id, 'astro_gender_female')
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
        'gender': gender,
        'zodiac': data.get('astrology_zodiac')
    }
    astrology_data[user_id] = user_data_for_calc

    await state.clear()

    zodiac_emoji = get_zodiac_emoji(data.get('astrology_zodiac', 'Неизвестно'))
    zodiac_name = get_zodiac_sign_localized(data.get('astrology_zodiac', 'Неизвестно'), lang)
    gender_display = 'Мужской' if gender == 'M' else 'Женский'

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

    await message.answer(await get_text(user_id, 'astrology_status_building'), reply_markup=ReplyKeyboardRemove())

    status_msg = await message.answer(profile_text)

    try:
        await status_msg.edit_text(await get_text(user_id, 'astrology_status_planets'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'astrology_status_houses'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'astrology_status_final'))
        await asyncio.sleep(2)

        if _gemini_service:
            user_data_for_calc['telegram_id'] = user_id
            interpretation, coords = await _gemini_service.generate_astrology_v2(user_data_for_calc, lang, telegram_id=user_id)
            if coords:
                from bot.db import save_user_coords
                await save_user_coords(user_id, coords[0], coords[1], coords[2])
            is_admin = await is_user_admin(user_id)
            display_data = _gemini_service.get_astrology_display_data(
                user_data_for_calc, lang, is_admin=is_admin, telegram_id=user_id
            )

            if is_admin:
                final_message = f"{display_data['basic']}\n\n{display_data['full']}\n\n{interpretation}"
            else:
                final_message = f"{display_data['basic']}\n\n{interpretation}"

            await save_message_to_archive(user_id, 'astrology', final_message)
            await add_astrology_count(user_id, -1)

            await status_msg.delete()
            await send_long_message(message, final_message, reply_markup=get_main_menu_button(lang))
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


# ==================== CALLBACK-ХЕНДЛЕРЫ ====================

@router.callback_query(F.data == "astrology_use_my_data")
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

    await callback.message.answer(
        await get_text(user_id, 'astrology_status_building'),
        reply_markup=ReplyKeyboardRemove()
    )

    status_msg = await callback.message.answer(profile_text)

    try:
        await status_msg.edit_text(await get_text(user_id, 'astrology_status_planets'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'astrology_status_houses'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'astrology_status_final'))
        await asyncio.sleep(2)

        if _gemini_service:
            user_data_from_db['telegram_id'] = user_id
            interpretation, coords = await _gemini_service.generate_astrology_v2(user_data_from_db, lang, telegram_id=user_id)
            if coords:
                from bot.db import save_user_coords
                await save_user_coords(user_id, coords[0], coords[1], coords[2])
            is_admin = await is_user_admin(user_id)
            display_data = _gemini_service.get_astrology_display_data(
                user_data_from_db, lang, is_admin=is_admin, telegram_id=user_id
            )

            if is_admin:
                final_message = f"{display_data['basic']}\n\n{display_data['full']}\n\n{interpretation}"
            else:
                final_message = f"{display_data['basic']}\n\n{interpretation}"

            await save_message_to_archive(user_id, 'astrology', final_message)
            await add_astrology_count(user_id, -1)

            await status_msg.delete()
            await send_long_message(callback.message, final_message, reply_markup=get_main_menu_button(lang))
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

    await callback.message.answer(
        await get_text(user_id, 'astrology_status_building'),
        reply_markup=ReplyKeyboardRemove()
    )

    status_msg = await callback.message.answer(await get_text(user_id, 'astrology_confirm_start'))

    try:
        await status_msg.edit_text(await get_text(user_id, 'astrology_status_planets'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'astrology_status_houses'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'astrology_status_final'))
        await asyncio.sleep(2)

        if _gemini_service:
            user_data['telegram_id'] = user_id
            interpretation, coords = await _gemini_service.generate_astrology_v2(user_data, lang, telegram_id=user_id)
            if coords:
                from bot.db import save_user_coords
                await save_user_coords(user_id, coords[0], coords[1], coords[2])
            is_admin = await is_user_admin(user_id)
            display_data = _gemini_service.get_astrology_display_data(
                user_data, lang, is_admin=is_admin, telegram_id=user_id
            )

            if is_admin:
                final_message = f"{display_data['basic']}\n\n{display_data['full']}\n\n{interpretation}"
            else:
                final_message = f"{display_data['basic']}\n\n{interpretation}"

            await save_message_to_archive(user_id, 'astrology', final_message)
            await add_astrology_count(user_id, -1)

            await status_msg.delete()
            await send_long_message(callback.message, final_message, reply_markup=get_main_menu_button(lang))
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
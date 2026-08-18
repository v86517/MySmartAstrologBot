import asyncio
import logging
import re
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext

from bot.utils.helpers import get_text
from bot.utils.formatters import format_parameters, prepare_numerology_prompt_data
from bot.utils.messaging import send_long_message
from bot.keyboards.keyboards import (
    get_main_menu,
    get_cancel_keyboard,
    get_numerology_payment_keyboard,
    get_numerology_confirm_keyboard,
    get_numerology_use_data_keyboard,
    get_payment_url_keyboard,
    get_main_menu_button,
)
from bot.states.states import NumerologyStates
from bot.utils.zodiac import calculate_zodiac_sign, get_zodiac_emoji, get_zodiac_sign_localized
from bot.utils.validators import normalize_gender
from bot.db import (
    get_user_data,
    save_user_data,
    check_subscription_db,
    can_use_feature_db,
    mark_feature_used_db,
    save_message_to_archive,
    get_user_language,
    is_user_admin,
    add_numerology_count,
    save_payment_db,
    get_service_price,
)
from bot.yookassa_client import yookassa
from bot.calculators.base_calculator import BaseCalculator
from bot.calculators.natal_calculator import NatalCalculator

logger = logging.getLogger(__name__)
router = Router()

_gemini_service = None

def set_gemini_service(service):
    global _gemini_service
    _gemini_service = service

# Глобальный словарь для временного хранения данных нумерологии
numerology_data = {}

# ==================== ФУНКЦИЯ-СТАРТЕР ДЛЯ КНОПКИ МЕНЮ ====================
async def start_numerology(message: Message, state: FSMContext):
    """Начало процесса нумерологии (вызывается из handle_menu_commands)"""
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    user_data = await get_user_data(user_id)
    numer_count = user_data.get('numerology_count', 0) if user_data else 0

    if numer_count == 0:
        await state.set_state(NumerologyStates.PAYMENT)
        await message.answer(
            await get_text(user_id, 'numerology_no_data'),
            reply_markup=get_numerology_payment_keyboard(lang)
        )
        return

    if user_data and user_data.get('name'):
        zodiac_emoji = get_zodiac_emoji(user_data.get('zodiac', 'Неизвестно'))
        zodiac_name = get_zodiac_sign_localized(user_data.get('zodiac', 'Неизвестно'), lang)
        template = await get_text(user_id, 'numerology_start')
        profile_text = template.format(
            name=user_data.get('name', 'Не указано'),
            birth_date=user_data.get('birth_date', 'Не указана'),
            birth_time=user_data.get('birth_time', 'Не указано'),
            birth_place=user_data.get('birth_place', 'Не указано'),
            emoji=zodiac_emoji,
            zodiac=zodiac_name
        )
        await state.set_state(NumerologyStates.CONFIRM_DATA)
        await message.answer(
            profile_text,
            reply_markup=get_numerology_confirm_keyboard(lang)
        )
    else:
        await state.set_state(NumerologyStates.WAITING_NAME)
        await message.answer(
            await get_text(user_id, 'numerology_no_user_data'),
            reply_markup=get_cancel_keyboard(lang)
        )


# ==================== ОБРАБОТЧИКИ СОСТОЯНИЙ ====================

@router.message(NumerologyStates.WAITING_NAME)
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


@router.message(NumerologyStates.WAITING_BIRTH_DATE)
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


@router.message(NumerologyStates.WAITING_BIRTH_TIME)
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


@router.message(NumerologyStates.WAITING_BIRTH_PLACE)
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


@router.message(NumerologyStates.WAITING_GENDER)
async def process_numerology_gender(message: Message, state: FSMContext):
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
    numer_count = user_data_from_db.get('numerology_count', 0) if user_data_from_db else 0

    if numer_count > 0:
        numerology_data[user_id] = {
            'name': data.get('numerology_name'),
            'birth_date': data.get('numerology_birth_date'),
            'birth_time': data.get('numerology_birth_time'),
            'birth_place': data.get('numerology_birth_place'),
            'gender': gender,
            'zodiac': data.get('numerology_zodiac'),
            'is_manual': True
        }

        zodiac_emoji = get_zodiac_emoji(data.get('numerology_zodiac', 'Неизвестно'))
        zodiac_name = get_zodiac_sign_localized(data.get('numerology_zodiac', 'Неизвестно'), lang)
        if gender == 'M':
            gender_display = await get_text(user_id, 'astro_gender_male')
        else:
            gender_display = await get_text(user_id, 'astro_gender_female')
        template = await get_text(user_id, 'numerology_confirm_data')
        profile_text = template.format(
            name=data.get('numerology_name'),
            gender=gender_display,
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
        'gender': gender,
        'zodiac': data.get('numerology_zodiac')
    }
    numerology_data[user_id] = user_data_for_calc

    await state.clear()

    zodiac_emoji = get_zodiac_emoji(data.get('numerology_zodiac', 'Неизвестно'))
    zodiac_name = get_zodiac_sign_localized(data.get('numerology_zodiac', 'Неизвестно'), lang)
    gender_display = 'Мужской' if gender == 'M' else 'Женский'

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

    await message.answer(await get_text(user_id, 'numerology_status_calculating'), reply_markup=ReplyKeyboardRemove())

    status_msg = await message.answer(profile_text)

    try:
        await status_msg.edit_text(await get_text(user_id, 'numerology_status_calc'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'numerology_status_analyze'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'numerology_status_format'))
        await asyncio.sleep(2)

        if _gemini_service:
            result = _gemini_service.generate_numerology(numerology_data[user_id], lang)

            if await is_user_admin(user_id):
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
                final_message = f"{parameters_text}\n\n💬 Интерпретация:\n{result}"
            else:
                final_message = result

            await save_message_to_archive(user_id, 'numerology', final_message)
            await add_numerology_count(user_id, -1)

            await status_msg.delete()
            result_template = await get_text(user_id, 'numerology_result')
            result_text = result_template.format(result=final_message)
            await send_long_message(message, result_text, reply_markup=get_main_menu_button(lang))
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


# ==================== CALLBACK-ХЕНДЛЕРЫ ====================

@router.callback_query(F.data == "numerology_use_my_data")
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

    await callback.message.answer(await get_text(user_id, 'numerology_status_calculating'),
                                  reply_markup=ReplyKeyboardRemove())

    status_msg = await callback.message.answer(profile_text)

    try:
        await status_msg.edit_text(await get_text(user_id, 'numerology_status_calc'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'numerology_status_analyze'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'numerology_status_format'))
        await asyncio.sleep(2)

        if _gemini_service:
            result = _gemini_service.generate_numerology(numerology_data[user_id], lang)

            if await is_user_admin(user_id):
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

            await save_message_to_archive(user_id, 'numerology', final_message)
            await add_numerology_count(user_id, -1)

            result_template = await get_text(user_id, 'numerology_result')
            result_text = result_template.format(result=final_message)

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


@router.callback_query(F.data == "numerology_fill_new_data")
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


@router.callback_query(F.data == "numerology_pay", NumerologyStates.PAYMENT)
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

    price = await get_service_price('numerology')
    if price is None:
        price = 888.00

    result = yookassa.create_payment(
        user_id=user_id,
        amount=float(price),
        description=f"Нумерология (ID: {user_id})",
        payment_type='numerology'
    )

    if result['success']:
        await save_payment_db(user_id, result['payment_id'], float(price), 'numerology', 'pending')
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


@router.callback_query(F.data == "numerology_confirm", NumerologyStates.CONFIRM_DATA)
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

    await callback.message.answer(await get_text(user_id, 'numerology_status_calculating'),
                                  reply_markup=ReplyKeyboardRemove())

    status_msg = await callback.message.answer(await get_text(user_id, 'numerology_confirm_start'))

    try:
        await status_msg.edit_text(await get_text(user_id, 'numerology_status_calc'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'numerology_status_analyze'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'numerology_status_format'))
        await asyncio.sleep(2)

        if _gemini_service:
            result = _gemini_service.generate_numerology(user_data, lang)

            if await is_user_admin(user_id):
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

            await save_message_to_archive(user_id, 'numerology', final_message)
            await add_numerology_count(user_id, -1)

            result_template = await get_text(user_id, 'numerology_result')
            result_text = result_template.format(result=final_message)

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


@router.callback_query(F.data == "edit_numerology_data")
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
# bot/handlers/compatibility.py
import asyncio
import logging
import re
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext

from bot.utils.helpers import get_text
from bot.utils.formatters import format_basic_astrology_parameters, format_full_astrology_parameters
from bot.utils.messaging import send_long_message
from bot.keyboards.keyboards import (
    get_main_menu,
    get_cancel_keyboard,
    get_compatibility_keyboard,
    get_subscription_keyboard,
    get_subscription_promo_keyboard,
    get_main_menu_button,
    get_compatibility_confirm_keyboard,
)
from bot.states.states import CompatibilityStates
from bot.utils.zodiac import calculate_zodiac_sign, get_zodiac_emoji, get_zodiac_sign_localized
from bot.utils.validators import normalize_gender
from bot.db import (
    get_user_data,
    check_subscription_db,
    can_use_feature_db,
    mark_feature_used_db,
    save_message_to_archive,
    get_user_language,
    is_user_admin, save_user_coords,
)
from bot.calculators.compatibility_calculator import CompatibilityCalculator
from bot.calculators.astrology_data_builder import AstrologyDataBuilder
from bot.db import get_emulation_mode


logger = logging.getLogger(__name__)
router = Router()

_gemini_service = None

def set_gemini_service(service):
    global _gemini_service
    _gemini_service = service


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
        if user_data.get('gender') == 'M':
            gender_display = await get_text(user_id, 'astro_gender_male')
        elif user_data.get('gender') == 'F':
            gender_display = await get_text(user_id, 'astro_gender_female')
        else:
            gender_display = await get_text(user_id, 'astro_gender_unknown')

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


# ==================== ОБРАБОТЧИКИ СОСТОЯНИЙ ====================

@router.message(CompatibilityStates.WAITING_PERSON1_NAME)
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


@router.message(CompatibilityStates.WAITING_PERSON1_BIRTH_DATE)
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


@router.message(CompatibilityStates.WAITING_PERSON1_BIRTH_TIME)
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


@router.message(CompatibilityStates.WAITING_PERSON1_BIRTH_PLACE)
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


@router.message(CompatibilityStates.WAITING_PERSON1_GENDER)
async def process_person1_gender(message: Message, state: FSMContext):
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
    person1 = {
        'name': data.get('person1_name'),
        'birth_date': data.get('person1_birth_date'),
        'birth_time': data.get('person1_birth_time'),
        'birth_place': data.get('person1_birth_place'),
        'gender': gender,
        'zodiac': data.get('person1_zodiac')
    }

    await state.update_data(person1=person1)
    await state.set_state(CompatibilityStates.WAITING_PERSON2_NAME)

    gender_display = await get_text(user_id, 'astro_gender_male') if gender == 'M' else await get_text(user_id, 'astro_gender_female')
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


@router.message(CompatibilityStates.WAITING_PERSON2_NAME)
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


@router.message(CompatibilityStates.WAITING_PERSON2_BIRTH_DATE)
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


@router.message(CompatibilityStates.WAITING_PERSON2_BIRTH_TIME)
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


@router.message(CompatibilityStates.WAITING_PERSON2_BIRTH_PLACE)
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


@router.message(CompatibilityStates.WAITING_PERSON2_GENDER)
async def process_person2_gender(message: Message, state: FSMContext):
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
    person2 = {
        'name': data.get('person2_name'),
        'birth_date': data.get('person2_birth_date'),
        'birth_time': data.get('person2_birth_time'),
        'birth_place': data.get('person2_birth_place'),
        'gender': gender,
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

    await state.update_data(person1=person1, person2=person2)
    await state.set_state(CompatibilityStates.CONFIRM_BOTH)

    from bot.locales import TEXTS
    texts = TEXTS.get(lang, TEXTS['ru'])

    async def person_text(person, num):
        if person.get('gender') == 'M':
            gender_display = await get_text(user_id, 'astro_gender_male')
        else:
            gender_display = await get_text(user_id, 'astro_gender_female')
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
        f"{await person_text(person1, 1)}\n\n"
        f"{await person_text(person2, 2)}"
    )

    await message.answer(
        confirm_text,
        reply_markup=get_compatibility_confirm_keyboard(lang)
    )


# ==================== CALLBACK-ХЕНДЛЕРЫ ====================

@router.callback_query(F.data == "confirm_compatibility", CompatibilityStates.CONFIRM_BOTH)
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

    # Проверка подписки или бесплатного лимита
    is_subscribed = await check_subscription_db(user_id)
    if not is_subscribed and not await can_use_feature_db(user_id, 'compatibility'):
        await callback.message.answer(
            await get_text(user_id, 'compatibility_limit'),
            reply_markup=get_subscription_keyboard(lang)
        )
        await state.clear()
        return

    # Режим эмуляции
    emulation = await get_emulation_mode(user_id)

    status_msg = await callback.message.answer(
        await get_text(user_id, 'compatibility_status_analyzing'),
        reply_markup=ReplyKeyboardRemove()
    )

    try:
        # 1. Создаём калькулятор и строим контекст
        calc = CompatibilityCalculator(person1, person2, lang=lang)
        context = calc.build()

        # 2. Формируем промпт для LLM
        if emulation:
            # В режиме эмуляции возвращаем контекст как есть
            final_text = f"🔍 РЕЖИМ ЭМУЛЯЦИИ (промпт не отправлен в нейросеть):\n\n{context}"
        else:
            # Отправляем в Gemini
            system_prompt = (
                "Ты — профессиональный астролог. Проведи анализ совместимости двух людей, используя предоставленные данные.\n\n"
                "Опиши сильные стороны, конфликты, притяжение, эмоциональную совместимость, коммуникацию и долгосрочный потенциал.\n"
                "Дай практические советы. Ответ должен быть структурированным, с заголовками и абзацами.\n\n"
            )
            if lang == 'en':
                system_prompt += "IMPORTANT: Respond in English only."
            else:
                system_prompt += "ВАЖНО: Отвечай только на русском языке."

            prompt = system_prompt + "\n\n" + context

            if _gemini_service:
                result = _gemini_service.send_raw_prompt(prompt)
                final_text = result
            else:
                final_text = "❌ Gemini сервис недоступен."

        # 3. Сохраняем в архив и отмечаем использование
        await save_message_to_archive(user_id, 'compatibility', final_text)
        if not is_subscribed:
            await mark_feature_used_db(user_id, 'compatibility')

        # 4. Отправляем результат (длинное сообщение)
        await status_msg.delete()
        await send_long_message(callback.message, final_text, reply_markup=get_main_menu_button(lang))

        # 5. Если не подписан, показываем промо-сообщение
        if not is_subscribed:
            await callback.message.answer(
                await get_text(user_id, 'compatibility_promo'),
                reply_markup=get_subscription_promo_keyboard(lang)
            )

    except Exception as e:
        logger.error(f"Ошибка в confirm_compatibility: {e}", exc_info=True)
        try:
            await status_msg.edit_text(f"❌ Произошла ошибка при анализе совместимости. Пожалуйста, попробуйте позже.")
        except:
            await callback.message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        await state.clear()


@router.callback_query(F.data == "use_my_data")
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


@router.callback_query(F.data == "fill_person1")
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
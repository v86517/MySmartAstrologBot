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
from pathlib import Path


logger = logging.getLogger(__name__)
router = Router()

_gemini_service = None

async def load_prompt_template(filename: str) -> str:
    """Загружает шаблон промпта из папки prompts."""
    base = Path(__file__).parent.parent.parent / 'prompts' / filename
    try:
        with open(base, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"Шаблон {filename} не найден")
        return ""

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

    # Определяем, являются ли данные person1 данными из БД
    is_person1_from_db = (
        person1.get('birth_lat') is not None and
        person1.get('birth_lng') is not None and
        person1.get('birth_timezone') is not None
    )

    emulation = await get_emulation_mode(user_id)

    status_msg = await callback.message.answer(
        await get_text(user_id, 'compatibility_status_analyzing'),
        reply_markup=ReplyKeyboardRemove()
    )

    try:
        # 1. Создаём калькулятор
        calc = CompatibilityCalculator(
            person_a_data=person1,
            person_b_data=person2,
            lang=lang,
            telegram_id=user_id if is_person1_from_db else None,
            save_for_person_a=is_person1_from_db
        )

        # 2. Сохраняем координаты, если они были вычислены
        if hasattr(calc, '_computed_coords_for_db') and calc._computed_coords_for_db:
            lat, lng, utc_str = calc._computed_coords_for_db
            logger.info(f"💾 Сохраняем координаты и UTC в БД для {user_id}: lat={lat}, lng={lng}, utc={utc_str}")
            result = await save_user_coords(user_id, lat, lng, utc_str)
            if result:
                logger.info(f"✅ Координаты и UTC сохранены в БД для {user_id}")
            else:
                logger.error(f"❌ Ошибка сохранения координат для {user_id}")

        # 3. Строим контекст (новый формат)
        context = calc.build_context()

        # 4. Загружаем шаблон промпта из файла
        prompt_template = await load_prompt_template('prompt_connect.txt')
        if not prompt_template:
            await callback.message.answer("❌ Шаблон промпта не найден.")
            return

        # 5. Языковая инструкция
        if lang == 'en':
            language_instruction = "IMPORTANT: Respond in English only."
        else:
            language_instruction = "ВАЖНО: Отвечай только на русском языке."

        # 6. Подставляем в шаблон
        prompt = prompt_template.replace('{language_instruction}', language_instruction)
        prompt = prompt.replace('{context}', context)
        name1 = person1.get('name', 'Человек 1')
        name2 = person2.get('name', 'Человек 2')
        prompt = prompt.replace('{name1}', name1)
        prompt = prompt.replace('{name2}', name2)

        # 7. Режим эмуляции или реальный запрос
        if emulation:
            result_text = f"🔍 РЕЖИМ ЭМУЛЯЦИИ (промпт не отправлен в нейросеть):\n\n{prompt}"
        else:
            if _gemini_service:
                result_text = _gemini_service.send_raw_prompt(prompt)
            else:
                result_text = "❌ Gemini сервис недоступен."

        # ---- Добавленный блок: параметры двух людей ----
        # Получаем данные для отображения из калькулятора
        person1_display = calc.get_person_display_data('1')
        person2_display = calc.get_person_display_data('2')

        def format_person(p):
            lines = []
            lines.append(f"👤 Имя: {p.get('name', 'Не указано')}")
            gender = p.get('gender', 'Не указан')
            if gender == 'M':
                gender_display = 'Мужчина'
            elif gender == 'F':
                gender_display = 'Женщина'
            else:
                gender_display = 'Не указан'
            lines.append(f"⚥ Пол: {gender_display}")
            lines.append(f"📅 Дата рождения: {p.get('birth_date', 'Не указана')}")
            lines.append(f"🕒 Время рождения: {p.get('birth_time', 'Не указано')}")
            lines.append(f"📍 Место рождения: {p.get('birth_place', 'Не указано')}")
            if p.get('lat') and p.get('lng'):
                lines.append(f"🌐 Координаты: {p['lat']}, {p['lng']}")
            if p.get('utc'):
                lines.append(f"🕒 UTC время рождения: {p['utc']}")
            return "\n".join(lines)

        params_block = (
            f"💕 Анализ совместимости\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **Человек 1**\n"
            f"{format_person(person1_display)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **Человек 2**\n"
            f"{format_person(person2_display)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
        )

        # Вставляем блок перед результатом
        final_text = f"{params_block}\n{result_text}"
        # -----------------------------------------------

        # 8. Сохраняем в архив и отмечаем использование
        await save_message_to_archive(user_id, 'compatibility', final_text)
        if not is_subscribed:
            await mark_feature_used_db(user_id, 'compatibility')

        # 9. Отправляем результат
        await status_msg.delete()
        await send_long_message(callback.message, final_text, reply_markup=get_main_menu_button(lang))

        # 10. Если не подписан, показываем промо-сообщение
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
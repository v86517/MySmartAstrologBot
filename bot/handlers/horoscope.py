import asyncio
import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext

from bot.utils.helpers import get_text
from bot.utils.formatters import format_basic_astrology_parameters, format_full_astrology_parameters
from bot.utils.messaging import send_long_message
from bot.keyboards.keyboards import (
    get_subscription_keyboard,
    get_horoscope_confirm_keyboard,
    get_main_menu_button,
    get_subscription_promo_keyboard,
    get_cancel_keyboard,
)
from bot.states.states import HoroscopeStates, UserDataStates
from bot.utils.zodiac import get_zodiac_emoji, get_zodiac_sign_localized
from bot.db import (
    get_user_data,
    check_subscription_db,
    can_use_feature_db,
    mark_feature_used_db,
    save_message_to_archive,
    get_user_language,
    is_user_admin,
)
from bot.calculators.transit_horoscope_calculator import TransitHoroscopeCalculator
from bot.calculators.astrology_data_builder import AstrologyDataBuilder

logger = logging.getLogger(__name__)
router = Router()

_gemini_service = None

def set_gemini_service(service):
    global _gemini_service
    _gemini_service = service


@router.message(F.text == "🔮 Гороскоп на сегодня")
async def start_horoscope(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    is_subscribed = await check_subscription_db(user_id)

    if is_subscribed:
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

            template = await get_text(user_id, 'horoscope_confirm_data')
            profile_text = template.format(
                name=user_data.get('name', 'Не указано'),
                gender=gender_display,
                birth_date=user_data.get('birth_date', 'Не указана'),
                birth_time=user_data.get('birth_time', 'Не указано'),
                birth_place=user_data.get('birth_place', 'Не указано'),
                emoji=zodiac_emoji,
                zodiac=zodiac_name
            )

            await state.update_data(user_data=user_data)
            await state.set_state(HoroscopeStates.CONFIRM)
            await message.answer(profile_text, reply_markup=get_horoscope_confirm_keyboard(lang))
            return
        else:
            await state.set_state(UserDataStates.WAITING_NAME)
            await message.answer(await get_text(user_id, 'horoscope_intro'), reply_markup=get_cancel_keyboard(lang))
            return

    if not await can_use_feature_db(user_id, 'horoscope'):
        await message.answer(
            await get_text(user_id, 'horoscope_free_ready'),
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

        template = await get_text(user_id, 'horoscope_confirm_data')
        profile_text = template.format(
            name=user_data.get('name', 'Не указано'),
            gender=gender_display,
            birth_date=user_data.get('birth_date', 'Не указана'),
            birth_time=user_data.get('birth_time', 'Не указано'),
            birth_place=user_data.get('birth_place', 'Не указано'),
            emoji=zodiac_emoji,
            zodiac=zodiac_name
        )

        await state.update_data(user_data=user_data)
        await state.set_state(HoroscopeStates.CONFIRM)
        await message.answer(profile_text, reply_markup=get_horoscope_confirm_keyboard(lang))
    else:
        await state.set_state(UserDataStates.WAITING_NAME)
        await message.answer(await get_text(user_id, 'horoscope_intro'), reply_markup=get_cancel_keyboard(lang))


@router.callback_query(F.data == "confirm_horoscope", HoroscopeStates.CONFIRM)
async def confirm_horoscope(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.delete()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    user_data = await state.get_data()
    user_data = user_data.get('user_data') or await get_user_data(user_id)

    if not user_data or not user_data.get('name'):
        await callback.message.answer(await get_text(user_id, 'error_not_found'))
        await state.clear()
        return

    if not _gemini_service:
        await callback.message.answer(await get_text(user_id, 'error_service_unavailable'))
        await state.clear()
        return

    is_subscribed = await check_subscription_db(user_id)

    if not is_subscribed and not await can_use_feature_db(user_id, 'horoscope'):
        await callback.message.answer(
            await get_text(user_id, 'horoscope_free_ready'),
            reply_markup=get_subscription_keyboard(lang)
        )
        await state.clear()
        return

    await callback.message.answer(
        await get_text(user_id, 'horoscope_generating'),
        reply_markup=ReplyKeyboardRemove()
    )

    status_msg = await callback.message.answer(await get_text(user_id, 'horoscope_status_planets'))
    try:
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'horoscope_status_chart'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'horoscope_status_analyze'))
        await asyncio.sleep(1)

        # --- НОВАЯ ЛОГИКА С ИСПОЛЬЗОВАНИЕМ ТРАНЗИТОВ И НАТАЛЬНЫХ ДАННЫХ ---
        # 1. Получаем натальные данные (JSON v2)
        natal_builder = AstrologyDataBuilder(user_data, lang)
        natal_data = natal_builder.build()

        # 2. Получаем транзитные данные
        transit_calc = TransitHoroscopeCalculator(user_data, lang)
        transit_data = transit_calc.get_full_transit_data()

        # 3. Генерируем текст через Gemini (новый метод)
        horoscope_text = await _gemini_service.generate_horoscope_with_data(user_id, user_data, natal_data, transit_data, lang)

        # 4. Формируем вывод
        is_admin = await is_user_admin(user_id)

        # Базовые параметры (для всех)
        basic_params = format_basic_astrology_parameters(user_data, lang)

        if is_admin:
            # Полные параметры для администратора
            full_params = format_full_astrology_parameters(natal_data, transit_data, lang)
            final_message = (
                f"🔮 Ваш гороскоп на {transit_data.get('target_date', datetime.now().strftime('%d.%m.%Y'))}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{basic_params}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{full_params}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{horoscope_text}"
            )
        else:
            final_message = (
                f"🔮 Ваш гороскоп на {transit_data.get('target_date', datetime.now().strftime('%d.%m.%Y'))}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{basic_params}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{horoscope_text}"
            )

        # Сохраняем в архив
        await save_message_to_archive(user_id, 'horoscope', final_message)

        if not is_subscribed:
            await mark_feature_used_db(user_id, 'horoscope')

        await status_msg.delete()

        # Отправляем пользователю
        await send_long_message(callback.message, final_message, reply_markup=get_main_menu_button(lang))

        if not is_subscribed:
            await callback.message.answer(
                await get_text(user_id, 'horoscope_promo'),
                reply_markup=get_subscription_promo_keyboard(lang)
            )

        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка в confirm_horoscope: {e}", exc_info=True)
        try:
            await status_msg.edit_text(f"❌ Произошла ошибка при генерации гороскопа. Пожалуйста, попробуйте позже.")
        except:
            await callback.message.answer(f"❌ Произошла ошибка: {str(e)}")
        await state.clear()


@router.callback_query(F.data == "cancel_horoscope", HoroscopeStates.CONFIRM)
async def cancel_horoscope(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.delete()
    await state.clear()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await callback.message.answer("🏠", reply_markup=get_main_menu_button(lang))
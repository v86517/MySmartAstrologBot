# bot/handlers/horoscope.py
import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
import pytz

from bot.utils.helpers import get_text
from bot.utils.formatters import format_basic_astrology_parameters, format_full_astrology_parameters
from bot.utils.messaging import send_long_message
from bot.keyboards.keyboards import (
    get_subscription_keyboard,
    get_horoscope_confirm_keyboard,
    get_horoscope_period_keyboard,
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


@router.message(F.text == "🔮 Гороскоп")  # <-- изменено с "🔮 Гороскоп на сегодня"
async def start_horoscope(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    user_data = await get_user_data(user_id)

    if user_data and user_data.get('name'):
        # Данные есть, показываем выбор периода (без отмены)
        await message.answer(
            await get_text(user_id, 'horoscope_period_choice'),
            reply_markup=get_horoscope_period_keyboard(lang)
        )
        await state.set_state(HoroscopeStates.SELECT_PERIOD)
    else:
        # Данных нет, запрашиваем ввод
        await state.set_state(UserDataStates.WAITING_NAME)
        await message.answer(
            await get_text(user_id, 'horoscope_intro'),
            reply_markup=get_cancel_keyboard(lang)
        )


@router.callback_query(F.data.startswith("horoscope_"), HoroscopeStates.SELECT_PERIOD)
async def select_horoscope_period(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    period = callback.data.split("_")[1]  # today, month, year
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    user_data = await get_user_data(user_id)

    if not user_data or not user_data.get('name'):
        # Если данных нет (на всякий случай)
        await state.set_state(UserDataStates.WAITING_NAME)
        await callback.message.answer(
            await get_text(user_id, 'horoscope_intro'),
            reply_markup=get_cancel_keyboard(lang)
        )
        await callback.message.delete()
        return

    # Сохраняем период
    await state.update_data(period=period, user_data=user_data)
    await state.set_state(HoroscopeStates.CONFIRM)

    # Показываем подтверждение данных
    zodiac_emoji = get_zodiac_emoji(user_data.get('zodiac', 'Неизвестно'))
    zodiac_name = get_zodiac_sign_localized(user_data.get('zodiac', 'Неизвестно'), lang)
    gender_display = await get_text(user_id, 'astro_gender_male') if user_data.get('gender') == 'M' else await get_text(
        user_id, 'astro_gender_female')
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
    # Убираем кнопку "Отмена", так как данные уже есть
    await callback.message.delete()
    await callback.message.answer(
        profile_text,
        reply_markup=get_horoscope_confirm_keyboard(lang, show_cancel=False)
    )


@router.callback_query(F.data == "confirm_horoscope", HoroscopeStates.CONFIRM)
async def confirm_horoscope(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.delete()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    data = await state.get_data()
    period = data.get('period', 'today')
    user_data = data.get('user_data') or await get_user_data(user_id)

    if not user_data or not user_data.get('name'):
        await callback.message.answer(await get_text(user_id, 'error_not_found'))
        await state.clear()
        return

    if not _gemini_service:
        await callback.message.answer(await get_text(user_id, 'error_service_unavailable'))
        await state.clear()
        return

    is_subscribed = await check_subscription_db(user_id)

    # Проверка лимитов: если не подписка и сегодня уже использован гороскоп (любой период)
    if not is_subscribed and not await can_use_feature_db(user_id, 'horoscope'):
        await callback.message.answer(
            await get_text(user_id, 'horoscope_limit_reached'),
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

        # Вычисляем даты начала и конца в локальном времени пользователя и в UTC
        tz_offset = user_data.get('timezone_offset', 3)
        now_local = datetime.now(pytz.UTC) + timedelta(hours=tz_offset)

        if period == 'today':
            start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            end_local = start_local + timedelta(days=1) - timedelta(seconds=1)
            display_date = start_local.strftime('%d.%m.%Y')
            start_utc = start_local - timedelta(hours=tz_offset)
            end_utc = end_local - timedelta(hours=tz_offset)
        elif period == 'month':
            start_local = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            next_month = start_local.replace(day=28) + timedelta(days=4)
            end_local = next_month - timedelta(days=next_month.day)
            end_local = end_local.replace(hour=23, minute=59, second=59)
            display_date = start_local.strftime('%B %Y')  # месяц год, можно локализовать позже
            start_utc = start_local - timedelta(hours=tz_offset)
            end_utc = end_local - timedelta(hours=tz_offset)
        else:  # year
            start_local = now_local.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end_local = now_local.replace(month=12, day=31, hour=23, minute=59, second=59)
            display_date = now_local.strftime('%Y')
            start_utc = start_local - timedelta(hours=tz_offset)
            end_utc = end_local - timedelta(hours=tz_offset)

        # Получаем натальные данные
        natal_builder = AstrologyDataBuilder(user_data, lang)
        natal_data = natal_builder.build()

        # Транзитные данные с учётом периода
        transit_calc = TransitHoroscopeCalculator(
            user_data, lang,
            period=period,
            start_utc=start_utc,
            end_utc=end_utc
        )
        transit_data = transit_calc.get_full_transit_data()

        # Генерируем текст через Gemini
        horoscope_text = await _gemini_service.generate_horoscope_with_data(
            user_id,
            user_data,
            natal_data,
            transit_data,
            lang,
            period=period,
            display_date=display_date,
            start_utc=start_utc,
            end_utc=end_utc
        )

        # Формируем вывод
        is_admin = await is_user_admin(user_id)
        basic_params = format_basic_astrology_parameters(user_data, lang)

        if is_admin:
            full_params = format_full_astrology_parameters(natal_data, transit_data, lang)
            final_message = (
                f"{basic_params}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{full_params}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{horoscope_text}"
            )
        else:
            final_message = f"{basic_params}\n━━━━━━━━━━━━━━━━━━━━━\n\n{horoscope_text}"

        # Сохраняем в архив
        await save_message_to_archive(user_id, 'horoscope', final_message)

        if not is_subscribed:
            await mark_feature_used_db(user_id, 'horoscope')

        await status_msg.delete()

        # Формируем заголовок в зависимости от периода
        if period == 'today':
            result_header = await get_text(user_id, 'horoscope_result_today').format(date=display_date)
        elif period == 'month':
            # Локализуем название месяца
            month_names_ru = {
                'January': 'Январь', 'February': 'Февраль', 'March': 'Март',
                'April': 'Апрель', 'May': 'Май', 'June': 'Июнь',
                'July': 'Июль', 'August': 'Август', 'September': 'Сентябрь',
                'October': 'Октябрь', 'November': 'Ноябрь', 'December': 'Декабрь'
            }
            month_name = start_local.strftime('%B')
            if lang == 'ru':
                month_name = month_names_ru.get(month_name, month_name)
            result_header = await get_text(user_id, 'horoscope_result_month').format(month=month_name,
                                                                                     year=start_local.year)
        else:  # year
            result_header = await get_text(user_id, 'horoscope_result_year').format(year=display_date)

        result_text = f"{result_header}\n\n{final_message}"

        await send_long_message(callback.message, result_text, reply_markup=get_main_menu_button(lang))

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
# bot/handlers/horoscope.py
import asyncio
import logging
from datetime import datetime, timedelta
import pytz
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
    get_horoscope_period_keyboard,
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


@router.message(F.text == "🔮 Гороскоп")
async def start_horoscope(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    user_data = await get_user_data(user_id)

    if user_data and user_data.get('name'):
        await message.answer(
            await get_text(user_id, 'horoscope_period_choice'),
            reply_markup=get_horoscope_period_keyboard(lang)
        )
        await state.set_state(HoroscopeStates.SELECT_PERIOD)
    else:
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
        await state.set_state(UserDataStates.WAITING_NAME)
        await callback.message.answer(
            await get_text(user_id, 'horoscope_intro'),
            reply_markup=get_cancel_keyboard(lang)
        )
        await callback.message.delete()
        return

    # Заголовок в зависимости от периода
    if period == 'today':
        header = await get_text(user_id, 'horoscope_period_today')
    elif period == 'month':
        header = await get_text(user_id, 'horoscope_period_month')
    else:
        header = await get_text(user_id, 'horoscope_period_year')

    # Данные пользователя (без дублирования заголовка)
    zodiac_emoji = get_zodiac_emoji(user_data.get('zodiac', 'Неизвестно'))
    zodiac_name = get_zodiac_sign_localized(user_data.get('zodiac', 'Неизвестно'), lang)
    gender_display = await get_text(user_id, 'astro_gender_male') if user_data.get('gender') == 'M' else await get_text(user_id, 'astro_gender_female')
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

    # Финальное сообщение: только заголовок и данные
    final_text = f"🔮 {header}\n\n{profile_text}"

    await callback.message.delete()
    await callback.message.answer(
        final_text,
        reply_markup=get_horoscope_confirm_keyboard(lang, period, show_cancel=False)
    )
    await state.clear()  # не нужен FSM, так как период уже в callback


@router.callback_query(F.data.startswith("confirm_horoscope_"))
async def confirm_horoscope(callback: CallbackQuery):
    """Генерация гороскопа для выбранного периода."""
    await callback.answer()
    await callback.message.delete()

    period = callback.data.split("_")[2]  # today, month, year
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    user_data = await get_user_data(user_id)

    if not user_data or not user_data.get('name'):
        await callback.message.answer(await get_text(user_id, 'error_not_found'))
        return

    if not _gemini_service:
        await callback.message.answer(await get_text(user_id, 'error_service_unavailable'))
        return

    is_subscribed = await check_subscription_db(user_id)

    if not is_subscribed and not await can_use_feature_db(user_id, 'horoscope'):
        await callback.message.answer(
            await get_text(user_id, 'horoscope_limit_reached'),
            reply_markup=get_subscription_keyboard(lang)
        )
        return

    await callback.message.answer(
        await get_text(user_id, 'horoscope_generating'),
        reply_markup=ReplyKeyboardRemove()
    )

    status_msg = await callback.message.answer(await get_text(user_id, 'horoscope_status_planets'))

    try:
        # Расчёт временных границ в локальном времени пользователя
        tz_offset = user_data.get('timezone_offset', 3)
        now_utc = datetime.now(pytz.UTC)
        now_local = now_utc + timedelta(hours=tz_offset)

        if period == 'today':
            start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            end_local = start_local + timedelta(days=1) - timedelta(seconds=1)
            display_date = start_local.strftime('%d.%m.%Y')
        elif period == 'month':
            start_local = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            next_month = start_local.replace(day=28) + timedelta(days=4)
            end_local = next_month - timedelta(days=next_month.day)
            end_local = end_local.replace(hour=23, minute=59, second=59)
            # Отображаем месяц и год
            month_names_ru = {
                1: 'январь', 2: 'февраль', 3: 'март', 4: 'апрель',
                5: 'май', 6: 'июнь', 7: 'июль', 8: 'август',
                9: 'сентябрь', 10: 'октябрь', 11: 'ноябрь', 12: 'декабрь'
            }
            month_names_en = {
                1: 'January', 2: 'February', 3: 'March', 4: 'April',
                5: 'May', 6: 'June', 7: 'July', 8: 'August',
                9: 'September', 10: 'October', 11: 'November', 12: 'December'
            }
            if lang == 'ru':
                display_date = f"{month_names_ru[start_local.month]} {start_local.year}"
            else:
                display_date = f"{month_names_en[start_local.month]} {start_local.year}"
        else:  # year
            start_local = now_local.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end_local = now_local.replace(month=12, day=31, hour=23, minute=59, second=59)
            display_date = str(start_local.year)

        # Преобразуем локальные даты в UTC (с часовым поясом)
        start_utc = start_local.replace(tzinfo=pytz.UTC)
        end_utc = end_local.replace(tzinfo=pytz.UTC)

        # Прогресс-сообщения
        await status_msg.edit_text(await get_text(user_id, 'horoscope_status_chart'))
        await asyncio.sleep(1)
        await status_msg.edit_text(await get_text(user_id, 'horoscope_status_analyze'))
        await asyncio.sleep(1)

        # Получаем натальные данные
        natal_builder = AstrologyDataBuilder(user_data, lang, telegram_id=user_id)
        natal_data = natal_builder.build()

        # Получаем транзитные данные с учётом периода
        transit_calc = TransitHoroscopeCalculator(
            user_data,
            lang,
            period=period,
            start_utc=start_utc,
            end_utc=end_utc,
            telegram_id=user_id
        )
        transit_data = transit_calc.get_full_transit_data()

        # ---- НОВАЯ ЛОГИКА С КОНТЕКСТНЫМ БИЛДЕРОМ ----
        from bot.calculators.context_builder import AstrologyContextBuilder

        builder = AstrologyContextBuilder(user_data, natal_data, transit_data, lang)
        if period == 'today':
            context = builder.build_day_context()
        elif period == 'month':
            context = builder.build_month_context()
        else:
            context = builder.build_year_context()

        horoscope_text = await _gemini_service.generate_horoscope_with_context(
            user_id, context, lang, period=period, display_date=display_date
        )
        # ---- КОНЕЦ НОВОЙ ЛОГИКИ ----

        # Формируем вывод
        # is_admin = await is_user_admin(user_id)
        # basic_params = format_basic_astrology_parameters(user_data, lang)
        #
        # # Заголовок результата
        # if period == 'today':
        #     header_template = await get_text(user_id, 'horoscope_result_today')
        #     header = header_template.format(date=display_date)
        # elif period == 'month':
        #     header_template = await get_text(user_id, 'horoscope_result_month')
        #     month_part, year_part = display_date.split()
        #     header = header_template.format(month=month_part, year=year_part)
        # else:
        #     header_template = await get_text(user_id, 'horoscope_result_year')
        #     header = header_template.format(year=display_date)
        #
        # if is_admin:
        #     full_params = format_full_astrology_parameters(natal_data, transit_data, lang)
        #     final_message = (
        #         f"{header}\n"
        #         f"━━━━━━━━━━━━━━━━━━━━━\n"
        #         f"{basic_params}\n"
        #         f"━━━━━━━━━━━━━━━━━━━━━\n"
        #         f"{full_params}\n"
        #         f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        #         f"{horoscope_text}"
        #     )
        # else:
        #     final_message = (
        #         f"{header}\n"
        #         f"━━━━━━━━━━━━━━━━━━━━━\n"
        #         f"{basic_params}\n"
        #         f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        #         f"{horoscope_text}"
        #     )

        basic_params = format_basic_astrology_parameters(user_data, lang)

        if period == 'today':
            header_template = await get_text(user_id, 'horoscope_result_today')
            header = header_template.format(date=display_date)
        elif period == 'month':
            header_template = await get_text(user_id, 'horoscope_result_month')
            month_part, year_part = display_date.split()
            header = header_template.format(month=month_part, year=year_part)
        else:
            header_template = await get_text(user_id, 'horoscope_result_year')
            header = header_template.format(year=display_date)

        final_message = (
            f"{header}\n"
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

        await send_long_message(callback.message, final_message, reply_markup=get_main_menu_button(lang))

        if not is_subscribed:
            await callback.message.answer(
                await get_text(user_id, 'horoscope_promo'),
                reply_markup=get_subscription_promo_keyboard(lang)
            )

    except Exception as e:
        logger.error(f"Ошибка в confirm_horoscope: {e}", exc_info=True)
        try:
            await status_msg.edit_text(f"❌ Произошла ошибка при генерации гороскопа. Пожалуйста, попробуйте позже.")
        except:
            await callback.message.answer(f"❌ Произошла ошибка: {str(e)}")


@router.callback_query(F.data == "cancel_horoscope")
async def cancel_horoscope(callback: CallbackQuery):
    await callback.answer()
    await callback.message.delete()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await callback.message.answer("🏠", reply_markup=get_main_menu_button(lang))
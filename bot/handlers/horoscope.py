import asyncio
import logging
from datetime import datetime, timedelta
import pytz
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext

from bot.utils.helpers import get_text
from bot.utils.formatters import format_basic_astrology_parameters
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
    save_user_coords,
)
from bot.calculators.transit_horoscope_calculator import TransitHoroscopeCalculator
from bot.calculators.astrology_data_builder import AstrologyDataBuilder
from bot.calculators.context_builder import AstrologyContextBuilder

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

    final_text = f"🔮 {header}\n\n{profile_text}"

    await callback.message.delete()
    await callback.message.answer(
        final_text,
        reply_markup=get_horoscope_confirm_keyboard(lang, period, show_cancel=False)
    )
    await state.clear()


from bot.calculators.horoscope_calculator import TransitCalculator
from pathlib import Path

async def load_prompt_template(filename: str) -> str:
    base = Path(__file__).parent.parent.parent / 'prompts' / filename
    try:
        with open(base, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"Шаблон {filename} не найден")
        return ""

@router.callback_query(F.data.startswith("confirm_horoscope_"))
async def confirm_horoscope(callback: CallbackQuery):
    await callback.answer()
    await callback.message.delete()

    period = callback.data.split("_")[2]
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

    emulation = await get_emulation_mode(user_id)

    await callback.message.answer(
        await get_text(user_id, 'horoscope_generating'),
        reply_markup=ReplyKeyboardRemove()
    )

    status_msg = await callback.message.answer(await get_text(user_id, 'horoscope_status_planets'))

    try:
        # 1. Создаём калькулятор транзитов
        calc = TransitCalculator(
            user_data=user_data,
            lang=lang,
            telegram_id=user_id,
            coords=None,
            emulation_mode=emulation
        )

        # 2. Определяем даты для расчёта
        # Для простоты используем текущую дату (UTC)
        target_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        # 3. Строим контекст
        context = calc.build_context(period=period, target_date=target_date)

        # 4. Загружаем шаблон
        template = await load_prompt_template('prompt_horoscope.txt')
        if not template:
            await callback.message.answer("❌ Шаблон промпта не найден.")
            return

        # 5. Языковая инструкция
        if lang == 'en':
            language_instruction = "IMPORTANT: Respond in English only."
        else:
            language_instruction = "ВАЖНО: Отвечай только на русском языке."

        # 6. Период в текстовом виде
        period_name = "день" if period == 'today' else "месяц" if period == 'month' else "год"

        # 7. Подставляем в шаблон
        prompt = template.replace('{language_instruction}', language_instruction)
        prompt = prompt.replace('{period}', period_name)
        prompt = prompt.replace('{context}', context)

        # 8. Режим эмуляции или реальный запрос
        if emulation:
            final_text = f"🔍 РЕЖИМ ЭМУЛЯЦИИ (промпт не отправлен в нейросеть):\n\n{prompt}"
        else:
            result_text = _gemini_service.send_raw_prompt(prompt)
            final_text = result_text

        # 9. Сохраняем в архив
        await save_message_to_archive(user_id, 'horoscope', final_text)
        if not is_subscribed:
            await mark_feature_used_db(user_id, 'horoscope')

        await status_msg.delete()
        await send_long_message(callback.message, final_text, reply_markup=get_main_menu_button(lang))

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
            await callback.message.answer(f"❌ Ошибка: {str(e)}")


@router.callback_query(F.data == "cancel_horoscope")
async def cancel_horoscope(callback: CallbackQuery):
    await callback.answer()
    await callback.message.delete()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await callback.message.answer("🏠", reply_markup=get_main_menu_button(lang))
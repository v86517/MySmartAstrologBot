# bot/handlers/horoscope.py
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext

from bot.utils.helpers import get_text
from bot.utils.messaging import send_long_message
from bot.utils.zodiac import get_zodiac_emoji, get_zodiac_sign_localized
from bot.keyboards.keyboards import (
    get_subscription_keyboard,
    get_horoscope_confirm_keyboard,
    get_main_menu_button,
    get_subscription_promo_keyboard,
    get_cancel_keyboard,
    get_horoscope_period_keyboard,
    get_main_menu,
)
from bot.states.states import HoroscopeStates, UserDataStates
from bot.db import (
    get_user_data,
    check_subscription_db,
    can_use_feature_db,
    mark_feature_used_db,
    save_message_to_archive,
    get_user_language,
    get_emulation_mode,
)
from bot.calculators.horoscope_calculator import HoroscopeCalculator
from bot.services.gemini import GeminiService

logger = logging.getLogger(__name__)
router = Router()

_gemini_service = None


def set_gemini_service(service):
    global _gemini_service
    _gemini_service = service


async def load_prompt_template(filename: str) -> str:
    """Загружает шаблон промпта из папки prompts."""
    base = Path(__file__).parent.parent.parent / 'prompts' / filename
    try:
        with open(base, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"Шаблон {filename} не найден")
        return ""


# ====================== СТАРТ ГОРОСКОПА ======================

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


# ====================== ВЫБОР ПЕРИОДА ======================

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

    # Заголовок
    if period == 'today':
        header = await get_text(user_id, 'horoscope_period_today')
    elif period == 'month':
        header = await get_text(user_id, 'horoscope_period_month')
    else:
        header = await get_text(user_id, 'horoscope_period_year')

    # Показываем подтверждение
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


# ====================== ГЕНЕРАЦИЯ ГОРОСКОПА ======================

def compute_period_bounds(period: str, target_date: datetime, timezone_offset: int = 3):
    """
    Вычисляет начало и конец периода в UTC.
    """
    target_date = target_date.astimezone(timezone.utc) if target_date.tzinfo else target_date.replace(tzinfo=timezone.utc)

    if period == "today":
        # Учитываем часовой пояс пользователя
        user_tz = timezone(timedelta(hours=timezone_offset))
        local_now = target_date.astimezone(user_tz)
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        local_end = local_start + timedelta(days=1)
        start_utc = local_start.astimezone(timezone.utc)
        end_utc = local_end.astimezone(timezone.utc)
        return start_utc, end_utc

    elif period == "month":
        year, month = target_date.year, target_date.month
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        if month == 12:
            end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
        return start, end

    elif period == "year":
        year = target_date.year
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        return start, end

    else:
        raise ValueError(f"Unsupported period: {period}")


@router.callback_query(F.data.startswith("confirm_horoscope_"))
async def confirm_horoscope(callback: CallbackQuery):
    await callback.answer()
    await callback.message.delete()

    period = callback.data.split("_")[2]  # "today", "month", "year"
    period_type = "day" if period == "today" else period

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
        target_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        timezone_offset = user_data.get('timezone_offset', 3)
        start_utc, end_utc = compute_period_bounds(period, target_date, timezone_offset)

        calc = HoroscopeCalculator(
            user_data=user_data,
            lang=lang,
            telegram_id=user_id,
            coords=None,
            emulation_mode=emulation,
            gemini_service=_gemini_service
        )

        # Определяем max_display в зависимости от периода
        if period == 'today':
            max_display = 12
        elif period == 'month':
            max_display = 15
        else:  # year
            max_display = 20

        # 1. Получаем астрологический контекст (без инструкций)
        horoscope_context = calc.build_horoscope_context(
            period_type=period_type,
            period_start_utc=start_utc,
            period_end_utc=end_utc,
            max_display=max_display
        )

        # 2. Загружаем шаблон промпта
        from pathlib import Path
        template_path = Path(__file__).parent.parent.parent / 'prompts' / 'prompt_horoscope.txt'
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                template = f.read()
        except FileNotFoundError:
            logger.error(f"Шаблон {template_path} не найден")
            await callback.message.answer("❌ Ошибка: шаблон промпта не найден.")
            return

        # 3. Определяем период для вывода
        if period == 'today':
            user_tz = timezone(timedelta(hours=timezone_offset))
            local_start = start_utc.astimezone(user_tz)
            horoscope_period = local_start.strftime("%d.%m.%Y")
        elif period == 'month':
            # Можно вывести конкретный месяц и год
            month_name = target_date.strftime("%B %Y")
            horoscope_period = month_name
        else:  # year
            horoscope_period = str(target_date.year)

        # Определяем акцент для прогноза
        if period == 'today':
            horoscope_accent = "Делай акцент на конкретных периодах дня, настроении, взаимодействии, решениях и ситуациях."
        elif period == 'month':
            horoscope_accent = "Выделяй наиболее значимые даты и этапы месяца, объединяя повторяющиеся влияния в общие темы."
        else:  # year
            horoscope_accent = "Делай акцент на долгосрочных изменениях, важных этапах, повторяющихся периодах и главных направлениях развития."

        # 4. Языковая инструкция
        if lang == 'en':
            language_instruction = "IMPORTANT: Respond in English only. All your output must be in English."
        else:
            language_instruction = "ВАЖНО: Отвечай только на русском языке. Весь твой ответ должен быть на русском."

        # 5. Имя пользователя
        name = user_data.get('name', 'Пользователь')

        # 6. Подставляем в шаблон
        prompt = template.replace('{horoscope_period}', horoscope_period)
        prompt = prompt.replace('{horoscope_accent}', horoscope_accent)
        prompt = prompt.replace('{language_instruction}', language_instruction)
        prompt = prompt.replace('{name}', name)
        prompt = prompt.replace('{horoscope_context}', horoscope_context)

        # 7. Режим эмуляции или реальный запрос
        if emulation:
            final_text = f"🔍 РЕЖИМ ЭМУЛЯЦИИ (промпт не отправлен в нейросеть):\n\n{prompt}"
        else:
            final_text = _gemini_service.send_raw_prompt(prompt)

        # 8. Сохраняем в архив
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


# ====================== ОТМЕНА ======================

@router.callback_query(F.data == "cancel_horoscope")
async def cancel_horoscope(callback: CallbackQuery):
    await callback.answer()
    await callback.message.delete()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await callback.message.answer("🏠", reply_markup=get_main_menu_button(lang))
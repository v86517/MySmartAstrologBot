import logging
import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from asgiref.sync import sync_to_async

from bot.utils.helpers import get_text
from bot.utils.formatters import format_profile_data
from bot.keyboards.keyboards import (
    get_main_menu,
    get_profile_keyboard,
    get_skip_keyboard,
    get_cancel_keyboard,
    get_fill_profile_keyboard,
    get_timezone_keyboard,
    get_save_data_keyboard,
    get_main_menu_button,
)
from bot.states.states import UserDataStates
from bot.utils.zodiac import get_zodiac_emoji, get_zodiac_sign_localized
from bot.db import (
    get_user_data,
    save_user_data,
    can_use_feature_db,
    get_user_language,
)
from core.models import User

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "edit_profile")
async def edit_profile(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    old = await get_user_data(user_id)
    if not old or not old.get('name'):
        await callback.message.edit_text(
            "❌ У вас нет сохраненных данных. Сначала заполните профиль через 'Гороскоп на сегодня'."
        )
        return

    await state.update_data(
        old_data=old,
        new_data=old.copy(),
        is_edit=True,
        fill_mode=False,
        is_timezone_edit=False
    )

    logger.info(f"🟢 Начало редактирования для {user_id}, старые данные: {old}")

    await state.set_state(UserDataStates.WAITING_NAME)
    template = await get_text(user_id, 'edit_name_prompt')
    prompt = template.format(name=old.get('name', 'не указано'))
    await callback.message.edit_text(
        prompt,
        reply_markup=get_skip_keyboard(lang)
    )


@router.callback_query(F.data == "fill_and_save")
async def fill_and_save(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.delete()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await state.update_data(fill_mode=True)

    await state.set_state(UserDataStates.WAITING_NAME)
    await callback.message.answer(
        await get_text(user_id, 'profile_fill_intro'),
        reply_markup=get_cancel_keyboard(lang)
    )


@router.callback_query(F.data == "skip_edit")
async def skip_edit_step(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    current_state = await state.get_state()
    state_data = await state.get_data()
    new_data = state_data.get('new_data', {})
    old = state_data.get('old_data', {})

    logger.info(f"⏩ Пропуск шага {current_state}, new_data до: {new_data}")

    if current_state == UserDataStates.WAITING_NAME:
        await state.set_state(UserDataStates.WAITING_BIRTH_DATE)
        template = await get_text(user_id, 'skip_birth_date')
        prompt = template.format(date=old.get('birth_date', 'не указана'))
        await callback.message.edit_text(prompt, reply_markup=get_skip_keyboard(lang))
    elif current_state == UserDataStates.WAITING_BIRTH_DATE:
        await state.set_state(UserDataStates.WAITING_BIRTH_TIME)
        template = await get_text(user_id, 'skip_birth_time')
        prompt = template.format(time=old.get('birth_time', 'не указано'))
        await callback.message.edit_text(prompt, reply_markup=get_skip_keyboard(lang))
    elif current_state == UserDataStates.WAITING_BIRTH_TIME:
        await state.set_state(UserDataStates.WAITING_BIRTH_PLACE)
        template = await get_text(user_id, 'skip_birth_place')
        prompt = template.format(place=old.get('birth_place', 'не указано'))
        await callback.message.edit_text(prompt, reply_markup=get_skip_keyboard(lang))
    elif current_state == UserDataStates.WAITING_BIRTH_PLACE:
        await state.set_state(UserDataStates.WAITING_GENDER)
        current_gender = old.get('gender')
        if current_gender == 'M':
            gender_display = 'Мужской'
        elif current_gender == 'F':
            gender_display = 'Женский'
        else:
            gender_display = 'не указан'
        template = await get_text(user_id, 'skip_gender')
        prompt = template.format(gender=gender_display)
        await callback.message.edit_text(prompt, reply_markup=get_skip_keyboard(lang))
    elif current_state == UserDataStates.WAITING_GENDER:
        user_id = callback.from_user.id
        logger.info(f"💾 Завершение редактирования через 'Пропустить' для {user_id}, данные: {new_data}")
        await save_user_data(user_id, new_data)
        await state.clear()

        user_obj = await sync_to_async(User.objects.get)(telegram_id=user_id)
        if user_obj.gender == 'M':
            gender_display = await get_text(user_id, 'astro_gender_male')
        elif user_obj.gender == 'F':
            gender_display = await get_text(user_id, 'astro_gender_female')
        else:
            gender_display = await get_text(user_id, 'astro_gender_unknown')
        zodiac_emoji = get_zodiac_emoji(user_obj.zodiac_sign or 'Неизвестно')
        zodiac_name = get_zodiac_sign_localized(user_obj.zodiac_sign or 'Неизвестно', lang)
        profile_text = (
            f"✅ Данные успешно обновлены!\n\n"
            f"👤 Имя: {user_obj.name or 'Не указано'}\n"
            f"📅 Дата рождения: {user_obj.date_of_birth.strftime('%d.%m.%Y') if user_obj.date_of_birth else 'Не указана'}\n"
            f"🕒 Время рождения: {user_obj.birth_time.strftime('%H:%M') if user_obj.birth_time else 'Не указано'}\n"
            f"📍 Место рождения: {user_obj.birth_place or 'Не указано'}\n"
            f"👤 Пол: {gender_display}\n"
            f"{zodiac_emoji} Знак зодиака: {zodiac_name}"
        )
        await callback.message.edit_text(profile_text, reply_markup=get_main_menu(lang))
    else:
        user_id = callback.from_user.id
        logger.info(f"💾 Завершение редактирования (неизвестное состояние) для {user_id}, данные: {new_data}")
        await save_user_data(user_id, new_data)
        await state.clear()

        user_obj = await sync_to_async(User.objects.get)(telegram_id=user_id)
        if user_obj.gender == 'M':
            gender_display = await get_text(user_id, 'astro_gender_male')
        elif user_obj.gender == 'F':
            gender_display = await get_text(user_id, 'astro_gender_female')
        else:
            gender_display = await get_text(user_id, 'astro_gender_unknown')
        zodiac_emoji = get_zodiac_emoji(user_obj.zodiac_sign or 'Неизвестно')
        zodiac_name = get_zodiac_sign_localized(user_obj.zodiac_sign or 'Неизвестно', lang)
        profile_text = (
            f"✅ Данные успешно обновлены!\n\n"
            f"👤 Имя: {user_obj.name or 'Не указано'}\n"
            f"📅 Дата рождения: {user_obj.date_of_birth.strftime('%d.%m.%Y') if user_obj.date_of_birth else 'Не указана'}\n"
            f"🕒 Время рождения: {user_obj.birth_time.strftime('%H:%M') if user_obj.birth_time else 'Не указано'}\n"
            f"📍 Место рождения: {user_obj.birth_place or 'Не указано'}\n"
            f"👤 Пол: {gender_display}\n"
            f"{zodiac_emoji} Знак зодиака: {zodiac_name}"
        )
        await callback.message.edit_text(profile_text, reply_markup=get_main_menu(lang))

    logger.info(f"⏩ После пропуска, new_data: {new_data}")


@router.callback_query(F.data == "edit_timezone")
async def edit_timezone(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.delete()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await state.update_data(
        is_timezone_edit=True,
        is_edit=False,
        fill_mode=False
    )

    await state.set_state(UserDataStates.WAITING_TIMEZONE)
    await callback.message.answer(
        await get_text(user_id, 'choose_timezone'),
        reply_markup=get_timezone_keyboard(lang)
    )


async def profile_func(message: Message):
    """Показать профиль пользователя (экспортируется для вызова из других модулей)"""
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
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

        timezone = user_data.get('timezone_offset', 3)

        template = await get_text(user_id, 'profile_text')
        profile_text = template.format(
            name=user_data.get('name', 'Не указано'),
            birth_date=user_data.get('birth_date', 'Не указана'),
            birth_time=user_data.get('birth_time', 'Не указано'),
            birth_place=user_data.get('birth_place', 'Не указано'),
            gender=gender_display,
            emoji=zodiac_emoji,
            zodiac=zodiac_name,
            timezone=timezone
        )

        # Проверка подписки - используем check_subscription_db
        from bot.db import check_subscription_db
        is_subscribed = await check_subscription_db(user_id)
        if is_subscribed:
            profile_text += await get_text(user_id, 'profile_subscription_active')

        await message.answer(profile_text, reply_markup=get_profile_keyboard(lang))
    else:
        consent_url = os.getenv('CONSENT_URL', 'ссылка на согласие')
        privacy_url = os.getenv('PRIVACY_POLICY_URL', 'ссылка на политику')
        can_use = await can_use_feature_db(user_id, 'horoscope')

        if can_use:
            template = await get_text(user_id, 'profile_no_data_message')
            text = template.format(consent_url=consent_url, privacy_url=privacy_url)
        else:
            template = await get_text(user_id, 'profile_no_data_message_can_use')
            text = template.format(consent_url=consent_url, privacy_url=privacy_url)
        await message.answer(text, reply_markup=get_fill_profile_keyboard(lang), parse_mode="Markdown")


# Экспортируем profile_func для использования в других модулях
import logging
import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from asgiref.sync import sync_to_async

from bot.utils.helpers import get_text
from bot.keyboards.keyboards import get_main_menu, get_cancel_keyboard, get_support_keyboard, get_main_menu_button
from bot.states.states import (
    UserDataStates, CompatibilityStates, NumerologyStates, AstrologyStates,
    HoroscopeStates, SubscriptionStates
)
from bot.db import get_user_language, save_user_data, get_user_data
from bot.handlers.profile import profile_func
from bot.handlers.subscription import show_subscription_func
from bot.handlers.archive import show_archive_func
from bot.handlers.expert import expert_request_func
from bot.handlers.horoscope import start_horoscope
from bot.handlers.compatibility import start_compatibility
from bot.handlers.numerology import start_numerology
from bot.handlers.astrology import start_astrology
from bot.handlers.start import change_language
from core.models import User
from bot.locales import TEXTS

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.text)
async def handle_menu_commands(message: Message, state: FSMContext):
    """
    Обрабатывает текстовые команды главного меню.
    """
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    texts = TEXTS.get(lang, TEXTS['ru'])
    text = message.text

    logger.info(f"🔍 handle_menu_commands: user_id={user_id}, lang={lang}, text='{text}'")
    menu_commands = [
        texts['menu_horoscope'],
        texts['menu_compatibility'],
        texts['menu_numerology'],
        texts['menu_astrology'],
        texts['menu_premium'],
        texts['menu_expert'],
        texts['menu_archive'],
        texts['menu_profile'],
        texts['menu_language'],
    ]
    logger.info(f"📋 menu_commands: {menu_commands}")

    if text not in menu_commands:
        return

    if text != texts['menu_language']:
        await state.clear()

    if text == texts['menu_horoscope']:
        logger.info("➡️ Вызов start_horoscope")
        await start_horoscope(message, state)
    elif text == texts['menu_compatibility']:
        logger.info("➡️ Вызов start_compatibility")
        await start_compatibility(message, state)
    elif text == texts['menu_numerology']:
        logger.info("➡️ Вызов start_numerology")
        await start_numerology(message, state)
    elif text == texts['menu_astrology']:
        logger.info("➡️ Вызов start_astrology")
        await start_astrology(message, state)
    elif text == texts['menu_premium']:
        logger.info("➡️ Вызов show_subscription")
        await show_subscription_func(message)
    elif text == texts['menu_expert']:
        logger.info("➡️ Вызов expert_request")
        await expert_request_func(message)
    elif text == texts['menu_archive']:
        logger.info("➡️ Вызов show_archive")
        await show_archive_func(message)
    elif text == texts['menu_profile']:
        logger.info("➡️ Вызов profile")
        await profile_func(message)
    elif text == texts['menu_language']:
        logger.info("➡️ Вызов change_language")
        await change_language(message)


@router.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("🏠", reply_markup=get_main_menu(lang))


# ==================== ОБРАБОТЧИКИ ОТМЕНЫ ====================

@router.callback_query(F.data == "cancel", UserDataStates.WAITING_NAME)
@router.callback_query(F.data == "cancel", UserDataStates.WAITING_BIRTH_DATE)
@router.callback_query(F.data == "cancel", UserDataStates.WAITING_BIRTH_TIME)
@router.callback_query(F.data == "cancel", UserDataStates.WAITING_BIRTH_PLACE)
@router.callback_query(F.data == "cancel", UserDataStates.WAITING_GENDER)
async def cancel_data_entry(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await callback.message.answer(
        await get_text(user_id, 'error_cancel'),
        reply_markup=get_main_menu(lang)
    )
    await callback.answer()


@router.callback_query(F.data == "cancel", CompatibilityStates.WAITING_PERSON1_NAME)
@router.callback_query(F.data == "cancel", CompatibilityStates.WAITING_PERSON1_BIRTH_DATE)
@router.callback_query(F.data == "cancel", CompatibilityStates.WAITING_PERSON1_BIRTH_TIME)
@router.callback_query(F.data == "cancel", CompatibilityStates.WAITING_PERSON1_BIRTH_PLACE)
@router.callback_query(F.data == "cancel", CompatibilityStates.WAITING_PERSON1_GENDER)
@router.callback_query(F.data == "cancel", CompatibilityStates.WAITING_PERSON2_NAME)
@router.callback_query(F.data == "cancel", CompatibilityStates.WAITING_PERSON2_BIRTH_DATE)
@router.callback_query(F.data == "cancel", CompatibilityStates.WAITING_PERSON2_BIRTH_TIME)
@router.callback_query(F.data == "cancel", CompatibilityStates.WAITING_PERSON2_BIRTH_PLACE)
@router.callback_query(F.data == "cancel", CompatibilityStates.WAITING_PERSON2_GENDER)
async def cancel_compatibility_data(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await callback.message.answer(
        await get_text(user_id, 'error_cancel'),
        reply_markup=get_main_menu(lang)
    )
    await callback.answer()


@router.callback_query(F.data == "cancel", NumerologyStates.WAITING_NAME)
@router.callback_query(F.data == "cancel", NumerologyStates.WAITING_BIRTH_DATE)
@router.callback_query(F.data == "cancel", NumerologyStates.WAITING_BIRTH_TIME)
@router.callback_query(F.data == "cancel", NumerologyStates.WAITING_BIRTH_PLACE)
@router.callback_query(F.data == "cancel", NumerologyStates.WAITING_GENDER)
@router.callback_query(F.data == "cancel", AstrologyStates.WAITING_NAME)
@router.callback_query(F.data == "cancel", AstrologyStates.WAITING_BIRTH_DATE)
@router.callback_query(F.data == "cancel", AstrologyStates.WAITING_BIRTH_TIME)
@router.callback_query(F.data == "cancel", AstrologyStates.WAITING_BIRTH_PLACE)
@router.callback_query(F.data == "cancel", AstrologyStates.WAITING_GENDER)
async def cancel_numerology_astrology_data(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await callback.message.answer(
        await get_text(user_id, 'error_cancel'),
        reply_markup=get_main_menu(lang)
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_expert")
async def cancel_expert(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    if lang == 'ru':
        text = "Вы вышли из «<b>👩‍🏫 Личный астролог</b>»\nВыберите раздел ниже <b>👇</b>"
    else:
        text = "You have exited «<b>👩‍🏫 Personal astrologer</b>»\nChoose a section below <b>👇</b>"

    await callback.message.answer(text, reply_markup=get_main_menu(lang), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "cancel", SubscriptionStates.WAITING_TIMEZONE)
async def cancel_subscription_timezone(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await callback.message.answer("🏠", reply_markup=get_main_menu(lang))
    await callback.answer()


@router.callback_query(F.data == "cancel", NumerologyStates.PAYMENT)
@router.callback_query(F.data == "cancel", AstrologyStates.PAYMENT)
async def cancel_payment(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await callback.message.answer("🏠", reply_markup=get_main_menu(lang))
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def cancel_fallback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await callback.message.answer(
        await get_text(user_id, 'error_cancel'),
        reply_markup=get_main_menu(lang)
    )
    await callback.answer()


@router.callback_query(F.data == "support")
async def support(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    support_url = os.getenv('SUPPORT_URL', 'https://t.me/ваш_username')
    text = await get_text(user_id, 'support_text')
    await callback.message.edit_text(
        text,
        reply_markup=get_support_keyboard(support_url, lang),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "back_to_profile")
async def back_to_profile(callback: CallbackQuery):
    await callback.answer()
    await callback.message.delete()
    class FakeMessage:
        def __init__(self, callback):
            self.from_user = callback.from_user
            self.chat = callback.message.chat
            self.answer = callback.message.answer
    fake_msg = FakeMessage(callback)
    await profile_func(fake_msg)


@router.message()
async def handle_unknown(message: Message):
    user_id = message.from_user.id
    await message.answer(
        await get_text(user_id, 'unknown_command')
    )
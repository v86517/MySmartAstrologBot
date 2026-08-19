import logging
import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.utils.helpers import get_text
from bot.keyboards.keyboards import get_main_menu, get_support_keyboard, get_main_menu_button
from bot.states.states import (
    UserDataStates, CompatibilityStates, NumerologyStates, AstrologyStates,
    HoroscopeStates, SubscriptionStates
)
from bot.db import get_user_language
from bot.handlers.profile import profile_func
from bot.handlers.subscription import show_subscription_func
from bot.handlers.archive import show_archive_func
from bot.handlers.expert import expert_request_func
from bot.handlers.horoscope import start_horoscope
from bot.handlers.compatibility import start_compatibility
from bot.handlers.numerology import start_numerology
from bot.handlers.astrology import start_astrology
from bot.handlers.start import change_language
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
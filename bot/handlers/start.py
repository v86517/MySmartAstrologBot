import logging
import os
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, FSInputFile
from aiogram.fsm.context import FSMContext

from bot.utils.helpers import get_text
from bot.keyboards.keyboards import get_main_menu, get_language_keyboard
from bot.db import get_or_create_user, get_user_language
from bot.scheduler import send_daily_horoscopes

logger = logging.getLogger(__name__)
router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name

    user, created = await get_or_create_user(user_id, username, first_name, last_name)
    if created:
        logger.info(f"✅ Новый пользователь: {user_id} (@{username})")

    welcome_text = await get_text(user_id, 'welcome')
    photo_path = "images/welcome.png"
    lang = await get_user_language(user_id)

    await message.answer_photo(
        photo=FSInputFile(photo_path),
        caption=welcome_text,
        reply_markup=get_main_menu(lang),
        parse_mode="HTML"
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    await message.answer("🏠", reply_markup=get_main_menu(lang))


@router.message(Command("test_send"))
async def test_send(message: Message):
    ADMIN_ID = 5484157606  # можно вынести в конфиг
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    await message.answer("⏳ Начинаю тестовую рассылку...")
    # Здесь нужен bot – мы его передадим глобально, но пока используем message.bot
    await send_daily_horoscopes(message.bot)


@router.message(F.text == "🌐 En/Ru")
async def change_language(message: Message):
    user_id = message.from_user.id
    text = await get_text(user_id, 'choose_language')
    await message.answer(text, reply_markup=get_language_keyboard())
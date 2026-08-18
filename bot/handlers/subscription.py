import logging
import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from asgiref.sync import sync_to_async

from bot.utils.helpers import get_text
from bot.keyboards.keyboards import (
    get_main_menu,
    get_subscription_keyboard,
    get_subscription_active_keyboard,
    get_payment_url_keyboard,
    get_timezone_keyboard,
)
from bot.states.states import SubscriptionStates
from bot.db import (
    check_subscription_db,
    get_user_language,
    save_payment_db,
    get_service_price,
)
from bot.yookassa_client import yookassa
from core.models import User

logger = logging.getLogger(__name__)
router = Router()


async def show_subscription_func(message: Message):
    """Показать информацию о подписке (экспортируется для вызова из других модулей)"""
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    is_subscribed = await check_subscription_db(user_id)

    if is_subscribed:
        await message.answer(
            await get_text(user_id, 'subscription_active'),
            reply_markup=get_subscription_active_keyboard(lang)
        )
    else:
        await message.answer(
            await get_text(user_id, 'subscription_inactive'),
            reply_markup=get_subscription_keyboard(lang)
        )


@router.callback_query(F.data == "subscribe_pay")
async def subscribe_payment(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    await state.set_state(SubscriptionStates.WAITING_TIMEZONE)
    await state.update_data(subscription_flow=True)

    await callback.message.delete()
    await callback.message.answer(
        await get_text(user_id, 'choose_timezone'),
        reply_markup=get_timezone_keyboard(lang)
    )


@router.callback_query(F.data == "close_subscription")
async def close_subscription(callback: CallbackQuery):
    await callback.answer()
    await callback.message.delete()
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    await callback.message.answer("🏠", reply_markup=get_main_menu(lang))


@router.callback_query(F.data == "cancel_subscription")
async def cancel_subscription_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    try:
        @sync_to_async
        def get_user(uid):
            try:
                return User.objects.get(telegram_id=uid)
            except User.DoesNotExist:
                return None

        user = await get_user(user_id)

        if not user:
            await callback.message.answer(
                await get_text(user_id, 'subscription_cancel_not_found'),
                reply_markup=get_main_menu(lang)
            )
            return

        if not user.is_subscribed:
            await callback.message.answer(
                await get_text(user_id, 'subscription_not_active'),
                reply_markup=get_main_menu(lang)
            )
            await callback.message.delete()
            return

        @sync_to_async
        def cancel_subscription(user_obj):
            user_obj.is_subscribed = False
            user_obj.subscription_until = None
            user_obj.save()
            return True

        await cancel_subscription(user)

        await callback.message.delete()

        await callback.message.answer(
            await get_text(user_id, 'subscription_canceled'),
            reply_markup=get_main_menu(lang)
        )

    except Exception as e:
        await callback.message.answer(
            f"❌ Ошибка при отмене подписки: {str(e)}",
            reply_markup=get_main_menu(lang)
        )
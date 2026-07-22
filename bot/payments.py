import os
import uuid
import logging
from datetime import datetime, timedelta
from yookassa import Configuration, Payment
from yookassa.domain.models import PaymentStatus

from bot.db import activate_subscription_db, save_payment_db

logger = logging.getLogger(__name__)

# Настройка ЮKassa
SHOP_ID = os.getenv('YKASSA_SHOP_ID')
SECRET_KEY = os.getenv('YKASSA_SECRET_KEY')

if SHOP_ID and SECRET_KEY:
    Configuration.account_id = SHOP_ID
    Configuration.secret_key = SECRET_KEY


def create_subscription_payment(user_id: int, amount: float = 299.00) -> dict:
    """
    Создание платежа для подписки
    """
    try:
        payment = Payment.create({
            "amount": {
                "value": f"{amount:.2f}",
                "currency": "RUB"
            },
            "payment_method_data": {
                "type": "bank_card"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": "https://t.me/MySmartAstrologBot"
            },
            "description": f"Подписка на астробота (ID: {user_id})",
            "metadata": {
                "user_id": str(user_id),
                "type": "subscription"
            }
        })

        return {
            "success": True,
            "payment_id": payment.id,
            "confirmation_url": payment.confirmation.confirmation_url,
            "payment": payment
        }
    except Exception as e:
        logger.error(f"Ошибка создания платежа: {e}")
        return {"success": False, "error": str(e)}


def create_natal_payment(user_id: int, amount: float = 999.00) -> dict:
    """
    Создание платежа для натальной карты
    """
    try:
        payment = Payment.create({
            "amount": {
                "value": f"{amount:.2f}",
                "currency": "RUB"
            },
            "payment_method_data": {
                "type": "bank_card"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": "https://t.me/MySmartAstrologBot"
            },
            "description": f"Натальная карта (ID: {user_id})",
            "metadata": {
                "user_id": str(user_id),
                "type": "natal_chart"
            }
        })

        return {
            "success": True,
            "payment_id": payment.id,
            "confirmation_url": payment.confirmation.confirmation_url,
            "payment": payment
        }
    except Exception as e:
        logger.error(f"Ошибка создания платежа: {e}")
        return {"success": False, "error": str(e)}


def check_payment_status(payment_id: str) -> dict:
    """
    Проверка статуса платежа
    """
    try:
        payment = Payment.find_one(payment_id)

        return {
            "success": True,
            "status": payment.status,
            "paid": payment.status == PaymentStatus.SUCCEEDED,
            "payment": payment
        }
    except Exception as e:
        logger.error(f"Ошибка проверки платежа: {e}")
        return {"success": False, "error": str(e)}


async def handle_successful_payment(payment_id: str):
    """
    Обработка успешного платежа
    """
    try:
        payment = Payment.find_one(payment_id)
        metadata = payment.metadata

        user_id = int(metadata.get('user_id', 0))
        payment_type = metadata.get('type', '')

        if not user_id:
            logger.error(f"Не найден user_id в метаданных платежа {payment_id}")
            return False

        # Сохраняем платеж в БД
        await save_payment_db(
            user_id=user_id,
            payment_id=payment_id,
            amount=float(payment.amount.value),
            payment_type=payment_type,
            status='success'
        )

        # Активируем подписку или натальную карту
        if payment_type == 'subscription':
            await activate_subscription_db(user_id, days=30)
            logger.info(f"✅ Подписка активирована для пользователя {user_id}")
        elif payment_type == 'natal_chart':
            # Добавляем 1 натальную карту
            await add_natal_chart_db(user_id)
            logger.info(f"✅ Натальная карта активирована для пользователя {user_id}")

        return True

    except Exception as e:
        logger.error(f"Ошибка обработки платежа {payment_id}: {e}")
        return False
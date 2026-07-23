import os
import uuid
import logging
from datetime import datetime
from yookassa import Configuration, Payment
from yookassa.domain import models
from yookassa.domain.exceptions import BadRequestError, UnauthorizedError

logger = logging.getLogger(__name__)

# Настройка ЮKassa из .env
SHOP_ID = os.getenv('YKASSA_SHOP_ID')
SECRET_KEY = os.getenv('YKASSA_SECRET_KEY')
RETURN_URL = os.getenv('YKASSA_RETURN_URL', 'https://t.me/MySmartAstrologBot')


class YooKassaClient:
    """Клиент для работы с ЮKassa"""

    def __init__(self):
        self.is_configured = False

        if SHOP_ID and SECRET_KEY:
            try:
                Configuration.account_id = SHOP_ID
                Configuration.secret_key = SECRET_KEY
                self.is_configured = True
                logger.info("✅ ЮKassa настроена успешно!")
            except Exception as e:
                logger.error(f"❌ Ошибка настройки ЮKassa: {e}")
        else:
            logger.warning("⚠️ ЮKassa не настроена! Проверьте YKASSA_SHOP_ID и YKASSA_SECRET_KEY")

    def create_payment(self, user_id: int, amount: float, description: str, payment_type: str) -> dict:
        """
        Создание платежа

        Args:
            user_id: ID пользователя в Telegram
            amount: Сумма платежа
            description: Описание платежа
            payment_type: Тип платежа (subscription, natal_chart, expert)

        Returns:
            dict: {success, payment_id, confirmation_url, error}
        """
        if not self.is_configured:
            return {
                'success': False,
                'error': 'ЮKassa не настроена. Проверьте ключи в .env'
            }

        try:
            # Генерируем уникальный ID платежа
            idempotence_key = str(uuid.uuid4())

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
                    "return_url": RETURN_URL
                },
                "description": description,
                "metadata": {
                    "user_id": str(user_id),
                    "type": payment_type
                }
            }, idempotence_key)

            logger.info(f"✅ Создан платеж {payment.id} для пользователя {user_id} на {amount}₽")

            return {
                'success': True,
                'payment_id': payment.id,
                'confirmation_url': payment.confirmation.confirmation_url,
                'payment': payment
            }

        except BadRequestError as e:
            logger.error(f"❌ Ошибка запроса к ЮKassa: {e}")
            return {'success': False, 'error': f'Ошибка запроса: {str(e)}'}
        except UnauthorizedError as e:
            logger.error(f"❌ Ошибка авторизации в ЮKassa: {e}")
            return {'success': False, 'error': 'Ошибка авторизации. Проверьте ключи.'}
        except Exception as e:
            logger.error(f"❌ Ошибка создания платежа: {e}")
            return {'success': False, 'error': str(e)}

    def check_payment(self, payment_id: str) -> dict:
        """
        Проверка статуса платежа

        Args:
            payment_id: ID платежа

        Returns:
            dict: {success, status, paid, payment}
        """
        if not self.is_configured:
            return {'success': False, 'error': 'ЮKassa не настроена'}

        try:
            payment = Payment.find_one(payment_id)

            # ✅ Используем правильную константу
            is_paid = payment.status == models.PaymentStatus.SUCCEEDED

            return {
                'success': True,
                'status': payment.status,
                'paid': is_paid,
                'payment': payment
            }

        except Exception as e:
            logger.error(f"❌ Ошибка проверки платежа {payment_id}: {e}")
            return {'success': False, 'error': str(e)}

    def handle_successful_payment(self, payment_id: str) -> dict:
        """
        Обработка успешного платежа

        Args:
            payment_id: ID платежа

        Returns:
            dict: {success, user_id, payment_type, amount}
        """
        try:
            payment = Payment.find_one(payment_id)

            # ✅ Используем правильную константу
            if payment.status != models.PaymentStatus.SUCCEEDED:
                return {'success': False, 'error': f'Платеж не завершен. Статус: {payment.status}'}

            metadata = payment.metadata
            user_id = int(metadata.get('user_id', 0))
            payment_type = metadata.get('type', '')
            amount = float(payment.amount.value)

            if not user_id:
                return {'success': False, 'error': 'user_id не найден в метаданных'}

            logger.info(f"✅ Успешный платеж {payment_id}: пользователь {user_id}, тип {payment_type}, сумма {amount}₽")

            return {
                'success': True,
                'user_id': user_id,
                'payment_type': payment_type,
                'amount': amount,
                'payment_id': payment_id
            }

        except Exception as e:
            logger.error(f"❌ Ошибка обработки платежа {payment_id}: {e}")
            return {'success': False, 'error': str(e)}


# Создаем глобальный экземпляр
yookassa = YooKassaClient()
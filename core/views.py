import os
import json
import logging
import traceback
import asyncio
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from aiogram import Bot
from asgiref.sync import async_to_sync

from bot.yookassa_client import yookassa
from bot.db import save_payment_db, activate_subscription_db, add_numerology_count, add_astrology_count

logger = logging.getLogger(__name__)


def send_payment_notification(user_id: int, payment_type: str, amount: float):
    """
    Отправляет пользователю уведомление об успешной оплате в Telegram.
    """
    token = os.getenv('BOT_TOKEN')
    if not token:
        logger.error("❌ BOT_TOKEN не найден в .env, уведомление не отправлено")
        return

    try:
        bot = Bot(token=token)

        if payment_type == 'subscription':
            text = (
                "🎉 Оплата прошла успешно!\n\n"
                "⭐ Ваша подписка активирована!\n"
                "Теперь вам доступны все функции Premium:\n"
                "✓ Ежедневный персональный гороскоп\n"
                "✓ Авто отправка гороскопа в 8:00\n\n"
                "✓ Совместимость без ограничений\n"
                "✓ Архив прогнозов\n"
                f"💰 Сумма: {amount} ₽\n"
                "📅 Подписка активна 30 дней.\n\n"
                "Спасибо, что выбрали нас! 🌟"
            )
        elif payment_type == 'natal_chart':
            text = (
                "🎉 Оплата прошла успешно!\n\n"
                "🌌 Ваша натальная карта готова к построению!\n"
                f"💰 Сумма: {amount} ₽\n\n"
                "Нажмите кнопку '🌌 Натальная карта', чтобы получить разбор."
            )
        elif payment_type == 'numerology':
            text = (
                "🎉 Оплата прошла успешно!\n\n"
                "🔢 Ваш нумерологический разбор готов!\n"
                "Вы можете получить его, нажав кнопку '🌌 Нумерология — познай себя'.\n"
                f"💰 Сумма: {amount} ₽\n\n"
                "Благодарим за доверие!"
            )
        elif payment_type == 'astrology':
            text = (
                "🎉 Оплата прошла успешно!\n\n"
                "🌙 Ваш астрологический разбор готов!\n"
                "Вы можете получить его, нажав кнопку '🌙 Астрология — узнай судьбу'.\n"
                f"💰 Сумма: {amount} ₽\n\n"
                "Благодарим за доверие!"
            )
        else:
            text = (
                f"🎉 Оплата прошла успешно!\n"
                f"💰 Сумма: {amount} ₽\n"
                "Благодарим за доверие!"
            )

        asyncio.create_task(bot.send_message(user_id, text))
        logger.info(f"✅ Уведомление отправлено пользователю {user_id}")

    except Exception as e:
        logger.error(f"❌ Ошибка отправки уведомления пользователю {user_id}: {e}")


@csrf_exempt
@require_POST
def yookassa_webhook(request):
    """
    Обработчик вебхуков от ЮKassa.
    Поддерживает события:
    - payment.waiting_for_capture
    - payment.succeeded
    """
    logger.info(f"📨 Входящий вебхук от {request.META.get('REMOTE_ADDR')}, метод {request.method}")

    try:
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка парсинга JSON: {e}, тело: {request.body[:200]}")
            return HttpResponse('Bad Request', status=400)

        event = data.get('event')
        logger.info(f"📨 Вебхук получен, событие: {event}")

        if event in ('payment.waiting_for_capture', 'payment.succeeded'):
            logger.debug(f"Данные вебхука: {json.dumps(data, indent=2)[:500]}...")

        # ---- 1. Обработка ожидания захвата ----
        if event == 'payment.waiting_for_capture':
            payment_id = data['object']['id']
            logger.info(f"⏳ Платёж ожидает захвата: {payment_id}")

            try:
                amount = float(data['object']['amount']['value'])
                currency = data['object']['amount']['currency']
            except (KeyError, ValueError) as e:
                logger.error(f"❌ Ошибка извлечения суммы из вебхука: {e}")
                return HttpResponse('Bad Request', status=400)

            result = yookassa.capture_payment(payment_id, amount, currency)
            if result['success']:
                logger.info(f"✅ Платёж {payment_id} захвачен")
            else:
                logger.error(f"❌ Ошибка захвата платежа {payment_id}: {result.get('error')}")

            return HttpResponse('OK', status=200)

        # ---- 2. Обработка успешного платежа ----
        elif event == 'payment.succeeded':
            payment_id = data['object']['id']
            logger.info(f"✅ Платёж успешен: {payment_id}")

            try:
                result = yookassa.handle_successful_payment(payment_id)
                logger.info(f"Результат обработки: {result}")
            except Exception as e:
                logger.error(f"❌ Исключение при вызове handle_successful_payment: {e}")
                logger.error(traceback.format_exc())
                return HttpResponse('OK', status=200)

            if result['success']:
                user_id = result['user_id']
                payment_type = result['payment_type']
                amount = result['amount']

                logger.info(f"👤 Пользователь {user_id}, тип {payment_type}, сумма {amount}")

                # Сохраняем платёж в БД
                try:
                    async_to_sync(save_payment_db)(user_id, payment_id, amount, payment_type, 'success')
                except Exception as e:
                    logger.error(f"❌ Ошибка сохранения платежа в БД: {e}")
                    logger.error(traceback.format_exc())

                # Активируем продукт и отправляем уведомление
                try:
                    if payment_type == 'subscription':
                        async_to_sync(activate_subscription_db)(user_id, 30)
                        logger.info(f"✅ Подписка активирована для {user_id}")
                        send_payment_notification(user_id, payment_type, amount)

                    elif payment_type == 'natal_chart':
                        # Для обратной совместимости (если ещё есть старые платежи)
                        # Но мы заменили add_natal_chart_db на новые функции, поэтому этот блок можно удалить,
                        # но оставим на всякий случай, если кто-то оплатит старую натальную карту.
                        # Вместо этого лучше использовать нумерологию или астрологию.
                        # Если у вас есть ещё старая логика, вы можете её здесь заменить или удалить.
                        logger.warning(f"⚠️ Получен платёж типа 'natal_chart' (устаревший). Ничего не активируем.")
                        send_payment_notification(user_id, 'unknown', amount)

                    elif payment_type == 'numerology':
                        async_to_sync(add_numerology_count)(user_id, 1)
                        logger.info(f"✅ Нумерология добавлена для {user_id}")
                        send_payment_notification(user_id, payment_type, amount)

                    elif payment_type == 'astrology':
                        async_to_sync(add_astrology_count)(user_id, 1)
                        logger.info(f"✅ Астрология добавлена для {user_id}")
                        send_payment_notification(user_id, payment_type, amount)

                    else:
                        logger.warning(f"⚠️ Неизвестный тип платежа: {payment_type}")
                        send_payment_notification(user_id, 'unknown', amount)

                except Exception as e:
                    logger.error(f"❌ Ошибка активации продукта для пользователя {user_id}: {e}")
                    logger.error(traceback.format_exc())

                return HttpResponse('OK', status=200)
            else:
                logger.error(f"❌ Ошибка обработки платежа: {result.get('error')}")
                return HttpResponse('OK', status=200)

        # ---- 3. Другие события ----
        logger.info(f"ℹ️ Событие '{event}' проигнорировано")
        return HttpResponse('OK', status=200)

    except Exception as e:
        logger.error(f"❌ Необработанное исключение в вебхуке: {e}")
        logger.error(traceback.format_exc())
        return HttpResponse('Error', status=500)
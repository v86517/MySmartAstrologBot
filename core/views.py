import json
import logging
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def yookassa_webhook(request):
    """
    Обработка вебхука от ЮKassa
    """
    try:
        data = json.loads(request.body)
        logger.info(f"📨 Получен вебхук от ЮKassa: {data.get('event')}")

        # Проверяем, что это уведомление об успешном платеже
        if data.get('event') == 'payment.succeeded':
            payment_id = data['object']['id']

            # Обрабатываем платеж
            import asyncio
            from bot.yookassa_client import yookassa
            from bot.db import save_payment_db, activate_subscription_db, add_natal_chart_db

            # Получаем информацию о платеже
            result = yookassa.handle_successful_payment(payment_id)

            if result['success']:
                user_id = result['user_id']
                payment_type = result['payment_type']
                amount = result['amount']

                # Сохраняем платеж в БД
                # Используем sync_to_async для вызова в синхронном контексте
                from asgiref.sync import async_to_sync

                # Сохраняем платеж
                async_to_sync(save_payment_db)(
                    user_id,
                    payment_id,
                    amount,
                    payment_type,
                    'success'
                )

                # Активируем соответствующий продукт
                if payment_type == 'subscription':
                    async_to_sync(activate_subscription_db)(user_id, days=30)
                    logger.info(f"✅ Подписка активирована для пользователя {user_id}")
                elif payment_type == 'natal_chart':
                    async_to_sync(add_natal_chart_db)(user_id, 1)
                    logger.info(f"✅ Натальная карта добавлена пользователю {user_id}")
                elif payment_type == 'expert':
                    # Для эксперта ничего не активируем, просто уведомление
                    logger.info(f"✅ Оплачен экспертный разбор для пользователя {user_id}")

                return HttpResponse('OK', status=200)
            else:
                logger.error(f"❌ Ошибка обработки платежа {payment_id}: {result.get('error')}")
                return HttpResponse('OK', status=200)  # Возвращаем OK, чтобы ЮKassa не повторяла запрос

        return HttpResponse('OK', status=200)

    except json.JSONDecodeError as e:
        logger.error(f"❌ Ошибка парсинга JSON: {e}")
        return HttpResponse('Bad Request', status=400)
    except Exception as e:
        logger.error(f"❌ Ошибка обработки вебхука: {e}")
        return HttpResponse('Internal Server Error', status=500)
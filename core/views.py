import json
import logging
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from bot.payments import handle_successful_payment

logger = logging.getLogger(__name__)


@csrf_exempt
def yookassa_webhook(request):
    """
    Обработка вебхука от ЮKassa
    """
    if request.method != 'POST':
        return HttpResponse('Method not allowed', status=405)

    try:
        data = json.loads(request.body)

        # Проверяем, что это уведомление об успешном платеже
        if data.get('event') == 'payment.succeeded':
            payment_id = data['object']['id']

            # Обрабатываем платеж
            import asyncio
            asyncio.run(handle_successful_payment(payment_id))

            return HttpResponse('OK', status=200)

        return HttpResponse('OK', status=200)

    except Exception as e:
        logger.error(f"Ошибка обработки вебхука: {e}")
        return HttpResponse('Error', status=500)
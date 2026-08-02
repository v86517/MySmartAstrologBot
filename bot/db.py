import os
import django
from datetime import datetime, timedelta
from django.utils import timezone
from asgiref.sync import sync_to_async
import logging

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from core.models import User, DailyUsage, UserMessage, Payment

logger = logging.getLogger(__name__)

# ==================== СИНХРОННЫЕ ФУНКЦИИ ====================

def _get_or_create_user(telegram_id, username=None, first_name=None, last_name=None):
    user, created = User.objects.get_or_create(
        telegram_id=telegram_id,
        defaults={
            'username': username,
            'first_name': first_name,
            'last_name': last_name,
        }
    )
    return user, created


def _save_user_data(telegram_id, data):
    logger.info(f"📝 Сохранение данных для пользователя {telegram_id}: {data}")
    try:
        user = User.objects.get(telegram_id=telegram_id)
    except User.DoesNotExist:
        user = User(telegram_id=telegram_id)
        logger.info(f"👤 Создан новый пользователь {telegram_id}")

    if data.get('name'):
        user.name = data.get('name')
    if data.get('birth_date'):
        user.date_of_birth = datetime.strptime(data.get('birth_date'), '%d.%m.%Y').date()
    if data.get('birth_time'):
        user.birth_time = datetime.strptime(data.get('birth_time'), '%H:%M').time()
    if data.get('birth_place'):
        user.birth_place = data.get('birth_place')
    if data.get('gender'):
        user.gender = data.get('gender')
    if data.get('zodiac'):
        user.zodiac_sign = data.get('zodiac')
    user.save()
    logger.info(f"✅ Данные пользователя {telegram_id} сохранены")
    return True


def _get_user_data(telegram_id):
    try:
        user = User.objects.get(telegram_id=telegram_id)
        return {
            'name': user.name,
            'birth_date': user.date_of_birth.strftime('%d.%m.%Y') if user.date_of_birth else None,
            'birth_time': user.birth_time.strftime('%H:%M') if user.birth_time else None,
            'birth_place': user.birth_place,
            'gender': user.gender,
            'zodiac': user.zodiac_sign,
            'is_subscribed': user.is_subscribed,
            'subscription_until': user.subscription_until,
            'numerology_count': user.numerology_count,
            'astrology_count': user.astrology_count,
        }
    except User.DoesNotExist:
        return None


def _check_subscription(telegram_id):
    try:
        user = User.objects.get(telegram_id=telegram_id)
        if not user.is_subscribed:
            return False
        if user.subscription_until and user.subscription_until < timezone.now():
            user.is_subscribed = False
            user.save()
            return False
        return True
    except User.DoesNotExist:
        return False


def _activate_subscription(telegram_id, days=30):
    try:
        user = User.objects.get(telegram_id=telegram_id)
        user.is_subscribed = True
        user.subscription_until = timezone.now() + timedelta(days=days)
        user.save()
        return True
    except User.DoesNotExist:
        return False


def _can_use_feature(telegram_id, feature):
    if _check_subscription(telegram_id):
        return True

    try:
        user = User.objects.get(telegram_id=telegram_id)
    except User.DoesNotExist:
        return True

    today = timezone.now().date()
    usage, created = DailyUsage.objects.get_or_create(
        user=user,
        date=today,
        defaults={
            'horoscope_used': False,
            'compatibility_used': False
        }
    )

    if feature == 'horoscope':
        return not usage.horoscope_used
    elif feature == 'compatibility':
        return not usage.compatibility_used
    return False


def _mark_feature_used(telegram_id, feature):
    try:
        user = User.objects.get(telegram_id=telegram_id)
        today = timezone.now().date()

        usage, created = DailyUsage.objects.get_or_create(
            user=user,
            date=today,
            defaults={
                'horoscope_used': False,
                'compatibility_used': False
            }
        )

        if feature == 'horoscope':
            usage.horoscope_used = True
        elif feature == 'compatibility':
            usage.compatibility_used = True

        usage.save()
        return True
    except User.DoesNotExist:
        return False


def _save_message_to_archive(telegram_id, message_type, content):
    try:
        user = User.objects.get(telegram_id=telegram_id)
        UserMessage.objects.create(
            user=user,
            message_type=message_type,
            content=content
        )
        return True
    except User.DoesNotExist:
        return False


def _get_user_archive(telegram_id, limit=10):
    try:
        user = User.objects.get(telegram_id=telegram_id)
        messages = list(UserMessage.objects.filter(user=user)[:limit])
        return messages
    except User.DoesNotExist:
        return []


def _get_archive_message(message_id, user_id):
    try:
        msg = UserMessage.objects.get(id=message_id)
        if msg.user.telegram_id == user_id:
            return msg
        return None
    except UserMessage.DoesNotExist:
        return None


def _save_payment_db(user_id, payment_id, amount, payment_type, status):
    """Сохранить или обновить платеж в БД"""
    try:
        user = User.objects.get(telegram_id=user_id)
        obj, created = Payment.objects.update_or_create(
            payment_id=payment_id,
            defaults={
                'user': user,
                'amount': amount,
                'payment_type': payment_type,
                'status': status,
            }
        )
        if created:
            logger.info(f"✅ Платёж {payment_id} сохранён")
        else:
            logger.info(f"🔄 Платёж {payment_id} уже существовал, обновлён")
        return True
    except Exception as e:
        logger.error(f"Ошибка сохранения платежа: {e}")
        return False


def _add_numerology_count(telegram_id, count=1):
    """Добавить нумерологию пользователю"""
    try:
        user = User.objects.get(telegram_id=telegram_id)
        user.numerology_count += count
        user.save()
        return True
    except User.DoesNotExist:
        return False


def _add_astrology_count(telegram_id, count=1):
    """Добавить астрологию пользователю"""
    try:
        user = User.objects.get(telegram_id=telegram_id)
        user.astrology_count += count
        user.save()
        return True
    except User.DoesNotExist:
        return False


def _get_numerology_count(telegram_id):
    try:
        user = User.objects.get(telegram_id=telegram_id)
        return user.numerology_count
    except User.DoesNotExist:
        return 0


def _get_astrology_count(telegram_id):
    try:
        user = User.objects.get(telegram_id=telegram_id)
        return user.astrology_count
    except User.DoesNotExist:
        return 0


def _get_all_subscribed_users():
    try:
        users = list(User.objects.filter(
            is_subscribed=True,
            subscription_until__gt=timezone.now()
        ))
        return users
    except Exception as e:
        return []


# ==================== АСИНХРОННЫЕ ОБЁРТКИ ====================

get_or_create_user = sync_to_async(_get_or_create_user)
save_user_data = sync_to_async(_save_user_data)
get_user_data = sync_to_async(_get_user_data)
check_subscription_db = sync_to_async(_check_subscription)
activate_subscription_db = sync_to_async(_activate_subscription)
can_use_feature_db = sync_to_async(_can_use_feature)
mark_feature_used_db = sync_to_async(_mark_feature_used)
save_message_to_archive = sync_to_async(_save_message_to_archive)
get_user_archive = sync_to_async(_get_user_archive)
get_archive_message = sync_to_async(_get_archive_message)
save_payment_db = sync_to_async(_save_payment_db)
add_numerology_count = sync_to_async(_add_numerology_count)
add_astrology_count = sync_to_async(_add_astrology_count)
get_numerology_count = sync_to_async(_get_numerology_count)
get_astrology_count = sync_to_async(_get_astrology_count)
get_all_subscribed_users = sync_to_async(_get_all_subscribed_users)
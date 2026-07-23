import os
import django
from datetime import datetime, timedelta
from django.utils import timezone  # ← ДОБАВЬТЕ ЭТОТ ИМПОРТ
from asgiref.sync import sync_to_async

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from core.models import User, DailyUsage, UserMessage, Payment


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
    try:
        user = User.objects.get(telegram_id=telegram_id)
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
        return True
    except User.DoesNotExist:
        return False


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
        }
    except User.DoesNotExist:
        return None


def _check_subscription(telegram_id):
    try:
        user = User.objects.get(telegram_id=telegram_id)
        if not user.is_subscribed:
            return False
        # ✅ Используем timezone.now() вместо datetime.now()
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
        # ✅ Используем timezone.now() вместо datetime.now()
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
        # ✅ Используем timezone.now() вместо datetime.now()
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

    except User.DoesNotExist:
        return False


def _mark_feature_used(telegram_id, feature):
    try:
        user = User.objects.get(telegram_id=telegram_id)
        # ✅ Используем timezone.now() вместо datetime.now()
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
    try:
        user = User.objects.get(telegram_id=user_id)
        Payment.objects.create(
            user=user,
            payment_id=payment_id,
            amount=amount,
            payment_type=payment_type,
            status=status
        )
        return True
    except Exception as e:
        return False


def _add_natal_chart_db(user_id, count=1):
    try:
        user = User.objects.get(telegram_id=user_id)
        user.natal_chart_count += count
        user.save()
        return True
    except Exception as e:
        return False


def _get_all_subscribed_users():
    try:
        # ✅ Используем timezone.now() вместо datetime.now()
        users = list(User.objects.filter(
            is_subscribed=True,
            subscription_until__gt=timezone.now()
        ))
        return users
    except Exception as e:
        return []


def _save_payment_db(user_id, payment_id, amount, payment_type, status):
    """Сохранить платеж в БД"""
    try:
        user = User.objects.get(telegram_id=user_id)
        Payment.objects.create(
            user=user,
            payment_id=payment_id,
            amount=amount,
            payment_type=payment_type,
            status=status
        )
        return True
    except Exception as e:
        logger.error(f"Ошибка сохранения платежа: {e}")
        return False

def _add_natal_chart_db(user_id, count=1):
    """Добавить натальные карты пользователю"""
    try:
        user = User.objects.get(telegram_id=user_id)
        user.natal_chart_count += count
        user.save()
        return True
    except Exception as e:
        logger.error(f"Ошибка добавления натальной карты: {e}")
        return False


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
add_natal_chart_db = sync_to_async(_add_natal_chart_db)
get_all_subscribed_users = sync_to_async(_get_all_subscribed_users)
save_payment_db = sync_to_async(_save_payment_db)
add_natal_chart_db = sync_to_async(_add_natal_chart_db)
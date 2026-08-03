from django.contrib import admin
from .models import User, DailyUsage, UserMessage, Payment

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = [
        'telegram_id', 'username', 'name', 'zodiac_sign',
        'numerology_count', 'astrology_count',
        'is_subscribed', 'timezone_offset', 'created_at'
    ]
    search_fields = ['telegram_id', 'username', 'name']
    list_filter = ['is_subscribed', 'zodiac_sign', 'gender', 'timezone_offset']

    # Поля, доступные только для чтения
    readonly_fields = ('created_at', 'updated_at')

    # Группировка полей в форме редактирования (без created_at/updated_at в редактируемых)
    fieldsets = (
        (None, {'fields': ('telegram_id', 'username', 'first_name', 'last_name')}),
        ('Личные данные', {'fields': ('name', 'date_of_birth', 'birth_time', 'birth_place', 'gender', 'zodiac_sign')}),
        ('Статусы', {'fields': ('is_subscribed', 'subscription_until', 'numerology_count', 'astrology_count', 'timezone_offset')}),
        # created_at и updated_at будут показаны только для чтения (readonly_fields)
    )

@admin.register(DailyUsage)
class DailyUsageAdmin(admin.ModelAdmin):
    list_display = ['user', 'date', 'horoscope_used', 'compatibility_used']
    list_filter = ['date', 'horoscope_used', 'compatibility_used']

@admin.register(UserMessage)
class UserMessageAdmin(admin.ModelAdmin):
    list_display = ['user', 'message_type', 'date']
    list_filter = ['message_type', 'date']
    search_fields = ['content']

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['user', 'amount', 'payment_type', 'status', 'created_at']
    list_filter = ['payment_type', 'status', 'created_at']
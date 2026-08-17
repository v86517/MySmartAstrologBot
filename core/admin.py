# core/admin.py

from django.contrib import admin
from .models import User, DailyUsage, UserMessage, Payment, ServicePrice


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = [
        'telegram_id', 'username', 'name', 'zodiac_sign',
        'numerology_count', 'astrology_count',
        'is_subscribed', 'timezone_offset', 'language',
        'is_admin', 'emulation_mode',  # новые поля
        'created_at'
    ]
    list_filter = [
        'is_subscribed', 'zodiac_sign', 'gender',
        'timezone_offset', 'language', 'is_admin', 'emulation_mode'
    ]
    search_fields = ['telegram_id', 'username', 'name']
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        (None, {'fields': ('telegram_id', 'username', 'first_name', 'last_name')}),
        ('Личные данные', {'fields': ('name', 'date_of_birth', 'birth_time', 'birth_place', 'gender', 'zodiac_sign')}),
        ('Статусы', {'fields': ('is_subscribed', 'subscription_until', 'numerology_count', 'astrology_count', 'timezone_offset', 'language')}),
        ('Администрирование', {'fields': ('is_admin', 'emulation_mode')}),  # новая секция
    )


@admin.register(DailyUsage)
class DailyUsageAdmin(admin.ModelAdmin):
    list_display = [
        'user_id',
        'user_username',
        'user_language',
        'date',
        'horoscope_used',
        'compatibility_used'
    ]
    list_filter = ['date', 'horoscope_used', 'compatibility_used']
    search_fields = ['user__telegram_id', 'user__username']
    list_select_related = ('user',)

    def user_id(self, obj):
        return obj.user.telegram_id
    user_id.short_description = 'Telegram ID'

    def user_username(self, obj):
        return obj.user.username or obj.user.telegram_id
    user_username.short_description = 'Пользователь'

    def user_language(self, obj):
        return obj.user.get_language_display() or obj.user.language
    user_language.short_description = 'Язык'


@admin.register(UserMessage)
class UserMessageAdmin(admin.ModelAdmin):
    list_display = [
        'user_id',
        'user_username',
        'user_language',
        'message_type',
        'date'
    ]
    list_filter = ['message_type', 'date']
    search_fields = ['user__telegram_id', 'user__username', 'content']
    list_select_related = ('user',)

    def user_id(self, obj):
        return obj.user.telegram_id
    user_id.short_description = 'Telegram ID'

    def user_username(self, obj):
        return obj.user.username or obj.user.telegram_id
    user_username.short_description = 'Пользователь'

    def user_language(self, obj):
        return obj.user.get_language_display() or obj.user.language
    user_language.short_description = 'Язык'


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        'user_id',
        'user_username',
        'user_language',
        'amount',
        'payment_type',
        'status',
        'created_at'
    ]
    list_filter = ['payment_type', 'status', 'created_at']
    search_fields = ['user__telegram_id', 'user__username']
    list_select_related = ('user',)

    def user_id(self, obj):
        return obj.user.telegram_id
    user_id.short_description = 'Telegram ID'

    def user_username(self, obj):
        return obj.user.username or obj.user.telegram_id
    user_username.short_description = 'Пользователь'

    def user_language(self, obj):
        return obj.user.get_language_display() or obj.user.language
    user_language.short_description = 'Язык'


@admin.register(ServicePrice)
class ServicePriceAdmin(admin.ModelAdmin):
    list_display = ('service', 'price', 'currency')
    list_editable = ('price', 'currency')  # можно редактировать прямо в списке
    search_fields = ('service',)
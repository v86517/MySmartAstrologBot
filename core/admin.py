from django.contrib import admin
from .models import User, DailyUsage, UserMessage, Payment

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['telegram_id', 'username', 'name', 'zodiac_sign', 'is_subscribed', 'created_at']
    search_fields = ['telegram_id', 'username', 'name']
    list_filter = ['is_subscribed', 'zodiac_sign', 'gender']

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
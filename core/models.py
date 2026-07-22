from django.db import models
from django.utils import timezone


class User(models.Model):
    """Модель пользователя"""
    GENDER_CHOICES = [
        ('M', 'Мужской'),
        ('F', 'Женский'),
    ]

    telegram_id = models.BigIntegerField(unique=True, db_index=True)
    username = models.CharField(max_length=100, null=True, blank=True)
    first_name = models.CharField(max_length=100, null=True, blank=True)
    last_name = models.CharField(max_length=100, null=True, blank=True)

    name = models.CharField(max_length=100, null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    birth_time = models.TimeField(null=True, blank=True)
    birth_place = models.CharField(max_length=200, null=True, blank=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, null=True, blank=True)
    zodiac_sign = models.CharField(max_length=20, null=True, blank=True)
    extra_info = models.TextField(null=True, blank=True)

    is_remembered = models.BooleanField(default=False)
    is_subscribed = models.BooleanField(default=False)
    subscription_until = models.DateTimeField(null=True, blank=True)
    natal_chart_count = models.IntegerField(default=0)
    expert_count = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'users'
        verbose_name = 'Пользователь'
        verbose_name_plural = 'Пользователи'

    def __str__(self):
        return f"{self.username or self.telegram_id}"


class DailyUsage(models.Model):
    """Ежедневное использование функций"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='daily_usage')
    date = models.DateField(default=timezone.now)
    horoscope_used = models.BooleanField(default=False)
    compatibility_used = models.BooleanField(default=False)

    class Meta:
        db_table = 'daily_usage'
        unique_together = ['user', 'date']
        verbose_name = 'Ежедневное использование'
        verbose_name_plural = 'Ежедневные использования'

    def __str__(self):
        return f"{self.user.username} - {self.date}"


class UserMessage(models.Model):
    """Сохраненные сообщения пользователя (архив)"""
    MESSAGE_TYPES = [
        ('horoscope', 'Гороскоп'),
        ('compatibility', 'Совместимость'),
        ('natal_chart', 'Натальная карта'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='messages')
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPES)
    content = models.TextField()
    date = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'user_messages'
        ordering = ['-date']
        verbose_name = 'Сообщение пользователя'
        verbose_name_plural = 'Сообщения пользователей'

    def __str__(self):
        return f"{self.user.username} - {self.message_type} - {self.date.strftime('%Y-%m-%d')}"


class Payment(models.Model):
    """Платежи"""
    PAYMENT_TYPES = [
        ('subscription', 'Подписка'),
        ('natal_chart', 'Натальная карта'),
        ('expert', 'Экспертный разбор'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Ожидает'),
        ('success', 'Успешно'),
        ('failed', 'Ошибка'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payments')
    payment_id = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payments'
        verbose_name = 'Платеж'
        verbose_name_plural = 'Платежи'

    def __str__(self):
        return f"{self.user.username} - {self.payment_type} - {self.amount}₽"
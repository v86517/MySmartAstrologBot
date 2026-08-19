#bot\states\states.py
from aiogram.fsm.state import State, StatesGroup

class UserDataStates(StatesGroup):
    """Состояния для сбора данных пользователя"""
    WAITING_NAME = State()
    WAITING_BIRTH_DATE = State()
    WAITING_BIRTH_TIME = State()
    WAITING_BIRTH_PLACE = State()
    WAITING_GENDER = State()
    WAITING_ZODIAC = State()
    WAITING_TIMEZONE = State()
    ASKING_SAVE = State()

class CompatibilityStates(StatesGroup):
    """Состояния для сбора данных совместимости"""
    WAITING_PERSON1_NAME = State()
    WAITING_PERSON1_BIRTH_DATE = State()
    WAITING_PERSON1_BIRTH_TIME = State()
    WAITING_PERSON1_BIRTH_PLACE = State()
    WAITING_PERSON1_GENDER = State()
    WAITING_PERSON1_ZODIAC = State()
    WAITING_PERSON2_NAME = State()
    WAITING_PERSON2_BIRTH_DATE = State()
    WAITING_PERSON2_BIRTH_TIME = State()
    WAITING_PERSON2_BIRTH_PLACE = State()
    WAITING_PERSON2_GENDER = State()
    WAITING_PERSON2_ZODIAC = State()
    CONFIRM_DATA = State()
    CONFIRM_BOTH = State()

class NumerologyStates(StatesGroup):
    """Состояния для нумерологии"""
    WAITING_NAME = State()
    WAITING_BIRTH_DATE = State()
    WAITING_BIRTH_TIME = State()
    WAITING_BIRTH_PLACE = State()
    WAITING_GENDER = State()
    WAITING_ZODIAC = State()
    CONFIRM_DATA = State()
    PAYMENT = State()

class AstrologyStates(StatesGroup):
    """Состояния для астрологии"""
    WAITING_NAME = State()
    WAITING_BIRTH_DATE = State()
    WAITING_BIRTH_TIME = State()
    WAITING_BIRTH_PLACE = State()
    WAITING_GENDER = State()
    WAITING_ZODIAC = State()
    CONFIRM_DATA = State()
    PAYMENT = State()

class HoroscopeStates(StatesGroup):
    CONFIRM = State()          # подтверждение данных перед генерацией
    SELECT_PERIOD = State()    # выбор периода (день/месяц/год)

class SubscriptionStates(StatesGroup):
    WAITING_TIMEZONE = State()
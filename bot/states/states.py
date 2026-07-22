from aiogram.fsm.state import State, StatesGroup

class UserDataStates(StatesGroup):
    """Состояния для сбора данных пользователя"""
    WAITING_NAME = State()
    WAITING_BIRTH_DATE = State()
    WAITING_BIRTH_TIME = State()
    WAITING_BIRTH_PLACE = State()
    WAITING_GENDER = State()
    WAITING_ZODIAC = State()

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

class NatalStates(StatesGroup):
    """Состояния для натальной карты"""
    WAITING_NAME = State()
    WAITING_BIRTH_DATE = State()
    WAITING_BIRTH_TIME = State()
    WAITING_BIRTH_PLACE = State()
    WAITING_GENDER = State()
    WAITING_ZODIAC = State()
    CONFIRM_DATA = State()
    PAYMENT = State()
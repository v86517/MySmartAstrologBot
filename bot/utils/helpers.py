from bot.locales import TEXTS
from bot.db import get_user_language

async def get_text(user_id, key, **kwargs):
    """
    Возвращает текст на языке пользователя.
    user_id: Telegram ID
    key: ключ в словаре TEXTS
    kwargs: параметры для подстановки (форматирование)
    """
    lang = await get_user_language(user_id)
    text = TEXTS.get(lang, {}).get(key, TEXTS['ru'].get(key, key))
    if kwargs:
        text = text.format(**kwargs)
    return text
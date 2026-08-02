import os
import requests
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from kerykeion import AstrologicalSubject
from timezonefinder import TimezoneFinder

logger = logging.getLogger(__name__)


class AstrologyCalculator:
    """
    Класс для расчёта астрологических параметров с помощью kerykeion и формирования промпта.
    Все недостающие данные заменяются значениями по умолчанию, чтобы расчёт всегда выполнялся.
    Часовой пояс определяется автоматически по координатам места рождения.
    """

    # Значения по умолчанию
    DEFAULT_LAT = 55.7558
    DEFAULT_LNG = 37.6173
    DEFAULT_TZ = "Europe/Moscow"

    def __init__(self, user_data: Dict[str, Any]):
        """
        Инициализация с данными пользователя из БД.

        Ожидаемые ключи в user_data:
            - name (str) — если нет, будет "Человек"
            - birth_date (str) в формате 'dd.mm.yyyy' — если нет, используется 01.01.2000
            - birth_time (str) в формате 'HH:MM' — если нет, используется 12:00
            - birth_place (str) — если нет, используется "Москва, Россия"
            - gender (str) 'M' или 'F' — если нет, используется 'M'
            - extra_info (str) — опционально
        """
        self.user_data = user_data
        self.name = user_data.get('name', 'Человек')
        self.gender = user_data.get('gender', 'M')
        self.birth_date_str = user_data.get('birth_date')
        self.birth_time_str = user_data.get('birth_time')
        self.birth_place = user_data.get('birth_place', '')
        self.extra_info = user_data.get('extra_info', '')

        # Кешируем координаты, карту и часовой пояс
        self._coords = None
        self._chart_data = None
        self._timezone = None

        # Инициализируем TimezoneFinder (один раз, он довольно тяжёлый)
        self._tf = TimezoneFinder()

    # ---------- Парсинг данных с подстановкой значений по умолчанию ----------
    def _parse_birth_datetime(self) -> tuple:
        """
        Парсит дату и время рождения.
        Если данные отсутствуют или невалидны, использует значения по умолчанию:
        дата: 01.01.2000, время: 12:00.
        Возвращает (year, month, day, hour, minute).
        """
        date_str = self.birth_date_str or "01.01.2000"
        time_str = self.birth_time_str or "12:00"

        try:
            dt = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
            return dt.year, dt.month, dt.day, dt.hour, dt.minute
        except ValueError:
            logger.warning(f"Неверный формат даты/времени: {date_str} {time_str}. Используем 01.01.2000 12:00")
            return 2000, 1, 1, 12, 0

    def _parse_birth_place(self) -> tuple:
        """
        Разбирает место рождения на город и страну.
        Если место не указано, возвращает ("Москва", "RU").
        """
        place = self.birth_place.strip()
        if not place:
            logger.warning("Место рождения не указано. Используем 'Москва, Россия'")
            return "Москва", "RU"
        parts = [p.strip() for p in place.split(',') if p.strip()]
        city = parts[0] if parts else "Москва"
        country = parts[1] if len(parts) > 1 else "RU"
        return city, country

    # ---------- Геокодирование с fallback ----------
    def _get_coordinates(self, city: str, country: str = None) -> Dict[str, float]:
        """
        Получает координаты через Open-Meteo Geocoding API.
        В случае неудачи возвращает координаты Москвы.
        """
        url = "https://geocoding-api.open-meteo.com/v1/search"
        params = {
            "name": city,
            "count": 1,
            "format": "json",
            "language": "ru"
        }
        if country:
            params["countryCode"] = country.upper()

        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results")
            if not results:
                logger.warning(f"Город '{city}' не найден. Используем координаты Москвы.")
                return {"lat": self.DEFAULT_LAT, "lng": self.DEFAULT_LNG}
            loc = results[0]
            return {"lat": loc["latitude"], "lng": loc["longitude"]}
        except Exception as e:
            logger.error(f"Ошибка геокодирования: {e}. Используем координаты Москвы.")
            return {"lat": self.DEFAULT_LAT, "lng": self.DEFAULT_LNG}

    # ---------- Определение часового пояса ----------
    def _get_timezone(self, lat: float, lng: float) -> str:
        """
        Определяет часовой пояс по координатам с помощью timezonefinder.
        Если не удаётся — возвращает DEFAULT_TZ.
        """
        try:
            tz_name = self._tf.timezone_at(lat=lat, lng=lng)
            if tz_name:
                return tz_name
            else:
                logger.warning(f"Не удалось определить часовой пояс для координат ({lat}, {lng}). Используем {self.DEFAULT_TZ}")
                return self.DEFAULT_TZ
        except Exception as e:
            logger.error(f"Ошибка определения часового пояса: {e}. Используем {self.DEFAULT_TZ}")
            return self.DEFAULT_TZ

    # ---------- Расчёт карты ----------
    def _calculate_chart(self) -> Dict[str, Any]:
        """
        Выполняет расчёт натальной карты с помощью kerykeion (AstrologicalSubject).
        Все недостающие данные подставлены ранее.
        """
        if self._chart_data is not None:
            return self._chart_data

        # Разбираем дату/время
        year, month, day, hour, minute = self._parse_birth_datetime()

        # Получаем координаты
        city, country = self._parse_birth_place()
        coords = self._get_coordinates(city, country)
        self._coords = coords

        # Определяем часовой пояс по координатам
        tz_str = self._get_timezone(coords['lat'], coords['lng'])
        self._timezone = tz_str

        # Создаём объект AstrologicalSubject напрямую
        subject = AstrologicalSubject(
            name=self.name,
            year=year,
            month=month,
            day=day,
            hour=hour,
            minute=minute,
            lat=coords['lat'],
            lng=coords['lng'],
            tz_str=tz_str,
            # city и country не обязательны, но можно передать для отладки
            city=city,
            country=country,
        )

        # Извлекаем данные из subject
        houses = []
        for h in subject.houses:
            houses.append({
                "number": h.number,
                "sign": h.sign,
                "degree": h.position,
            })

        planets = []
        for p in subject.planets:
            planets.append({
                "name": p.name,
                "sign": p.sign,
                "degree": p.position,
                "house": p.house,
            })

        aspects = []
        if hasattr(subject, 'aspects') and subject.aspects:
            for a in subject.aspects:
                aspects.append({
                    "p1": a.p1_name,
                    "p2": a.p2_name,
                    "aspect": a.aspect,
                    "orb": a.orb,
                })

        result = {
            "name": subject.name,
            "datetime": f"{year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}",
            "timezone": tz_str,
            "location": {"lat": coords['lat'], "lng": coords['lng']},
            "houses": houses,
            "planets": planets,
            "aspects": aspects,
        }

        self._chart_data = result
        return result

    # ---------- Формирование промпта ----------
    def _load_prompt_template(self) -> Optional[str]:
        """Загружает шаблон промпта из файла prompts/prompt_astrology.txt."""
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        filepath = os.path.join(base_dir, 'prompts', 'prompt_astrology.txt')
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            logger.error("Файл prompt_astrology.txt не найден")
            return None

    def build_prompt(self) -> str:
        """
        Строит текстовый промпт для нейросети на основе рассчитанной карты.
        Всегда возвращает строку (даже если шаблон не найден — использует fallback).
        """
        chart = self._calculate_chart()

        # Извлекаем знаки Солнца, Луны и Асцендент
        sun_sign = None
        moon_sign = None
        ascendant = None
        for planet in chart['planets']:
            if planet['name'] == 'Sun':
                sun_sign = planet['sign']
            elif planet['name'] == 'Moon':
                moon_sign = planet['sign']
        if chart['houses']:
            ascendant = chart['houses'][0]['sign']

        planets_str = "\n".join(
            f"- {p['name']} в {p['sign']} ({p['degree']:.2f}°) в {p['house']} доме"
            for p in chart['planets']
        )

        gender_display = "Мужчина" if self.gender == 'M' else "Женщина"
        pronoun = "он" if self.gender == 'M' else "она"
        possessive = "его" if self.gender == 'M' else "её"

        # Загружаем шаблон
        template = self._load_prompt_template()
        if not template:
            return self._build_fallback_prompt(chart)

        # Заменяем плейсхолдеры
        replacements = {
            "name": chart['name'],
            "gender_display": gender_display,
            "birth_date": self.birth_date_str or "не указана (используем 01.01.2000)",
            "birth_time": self.birth_time_str or "не указано (используем 12:00)",
            "birth_place": self.birth_place or "не указано (используем Москва)",
            "sun_sign": sun_sign or "не известно",
            "moon_sign": moon_sign or "не известно",
            "ascendant": ascendant or "не известно",
            "planets_list": planets_str,
            "extra_info": self.extra_info,
            "pronoun": pronoun,
            "possessive": possessive,
        }

        prompt = template
        for key, value in replacements.items():
            prompt = prompt.replace(f"{{{key}}}", str(value))

        return prompt

    def _build_fallback_prompt(self, chart: dict) -> str:
        """Встроенный промпт на случай отсутствия файла шаблона."""
        planets_str = "\n".join(
            f"- {p['name']} в {p['sign']} ({p['degree']:.2f}°) в {p['house']} доме"
            for p in chart['planets']
        )
        pronoun = "он" if self.gender == 'M' else "она"
        possessive = "его" if self.gender == 'M' else "её"
        return f"""
Ты — профессиональный астролог. Проведи интерпретацию натальной карты для {chart['name']} ({pronoun}).

Данные рождения:
- Дата и время: {chart['datetime']}
- Место: широта {chart['location']['lat']}, долгота {chart['location']['lng']}

Планеты в знаках и домах:
{planets_str}

Опиши характер, эмоции, общение, сильные стороны, зоны роста, таланты и дай практические советы.
"""
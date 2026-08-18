# bot/handlers/__init__.py
from .start import router as start_router
from .horoscope import router as horoscope_router
from .compatibility import router as compatibility_router
from .numerology import router as numerology_router
from .astrology import router as astrology_router
from .profile import router as profile_router
from .subscription import router as subscription_router
from .archive import router as archive_router
from .expert import router as expert_router
from .common import router as common_router

__all__ = [
    'start_router',
    'horoscope_router',
    'compatibility_router',
    'numerology_router',
    'astrology_router',
    'profile_router',
    'subscription_router',
    'archive_router',
    'expert_router',
    'common_router',
]
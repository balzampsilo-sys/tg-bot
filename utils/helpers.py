"""Вспомогательные функции"""

from datetime import datetime

from config import DAY_NAMES, TIMEZONE


def now_local() -> datetime:
    """Текущее время в московской таймзоне"""
    return datetime.now(TIMEZONE)


def format_date(date_obj: datetime) -> str:
    """Форматирование даты для отображения"""
    day_name = DAY_NAMES[date_obj.weekday()]
    return f"{date_obj.strftime('%d.%m.%Y')} ({day_name})"


def create_ascii_chart(data: list, width: int = 7) -> str:
    """Создать ASCII-график для дашборда"""
    if not data or max(data) == 0:
        return "▁▁▁▁▁▁▁"

    max_val = max(data)
    bars = []
    bar_chars = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"]

    for val in data:
        height = int((val / max_val) * 7)
        bars.append(bar_chars[min(height, 7)])

    return "".join(bars)


def is_admin(user_id: int) -> bool:
    """Проверка прав администратора (поддержка нескольких админов)"""
    from config import ADMIN_IDS  # ИСПРАВЛЕНО: множественное число
    return user_id in ADMIN_IDS

"""Система локализации (i18n)"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional

# По умолчанию русский язык
DEFAULT_LOCALE = "ru"
LOCALES_DIR = Path(__file__).parent.parent / "locales"


class I18n:
    """Менеджер локализации"""

    _instance: Optional["I18n"] = None
    _translations: Dict[str, dict] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_translations()
        return cls._instance

    def _load_translations(self):
        """Загрузить все переводы"""
        try:
            for locale_file in LOCALES_DIR.glob("*.json"):
                locale_code = locale_file.stem
                with open(locale_file, "r", encoding="utf-8") as f:
                    self._translations[locale_code] = json.load(f)
                logging.info(f"Loaded translations for locale: {locale_code}")
        except Exception as e:
            logging.error(f"Error loading translations: {e}")

    def get(self, key: str, locale: str = DEFAULT_LOCALE, **kwargs) -> str:
        """
        Получить перевод по ключу

        Args:
            key: Ключ в формате "section.key" (например, "booking.step_1_title")
            locale: Код языка (ru, en)
            **kwargs: Параметры для форматирования

        Returns:
            Переведенная строка
        """
        # Получаем переводы для языка
        translations = self._translations.get(locale)
        if not translations:
            logging.warning(f"Locale {locale} not found, using default {DEFAULT_LOCALE}")
            translations = self._translations.get(DEFAULT_LOCALE, {})

        # Разбиваем ключ на части
        keys = key.split(".")
        value = translations

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                logging.warning(f"Translation key not found: {key}")
                return key

        if value is None:
            logging.warning(f"Translation key not found: {key}")
            return key

        # Форматирование параметров
        if kwargs:
            try:
                return value.format(**kwargs)
            except KeyError as e:
                logging.warning(f"Missing formatting parameter {e} for key {key}")
                return value

        return value

    def get_days(self, locale: str = DEFAULT_LOCALE) -> list:
        """Получить названия дней недели"""
        return [
            self.get(f"days.{day}", locale)
            for day in [
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            ]
        ]

    def get_months(self, locale: str = DEFAULT_LOCALE) -> list:
        """Получить названия месяцев"""
        return [
            self.get(f"months.{month}", locale)
            for month in [
                "january",
                "february",
                "march",
                "april",
                "may",
                "june",
                "july",
                "august",
                "september",
                "october",
                "november",
                "december",
            ]
        ]


# Синглтон
i18n = I18n()


# Удобная функция для импорта
def t(key: str, locale: str = DEFAULT_LOCALE, **kwargs) -> str:
    """
    Короткий алиас для получения перевода

    Пример:
        t("booking.step_1_title")  # русский
        t("booking.step_1_title", locale="en")  # английский
        t("booking.slots_available", free=5, total=10)
    """
    return i18n.get(key, locale, **kwargs)

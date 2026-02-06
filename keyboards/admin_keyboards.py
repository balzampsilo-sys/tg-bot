"""Клавиатуры для администратора"""
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


ADMIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Dashboard"), KeyboardButton(text="💡 Рекомендации")],
        [KeyboardButton(text="📅 Расписание"), KeyboardButton(text="👥 Клиенты")],
        [KeyboardButton(text="⚡ Массовые операции"), KeyboardButton(text="📊 Экспорт данных")],
        [KeyboardButton(text="🔙 Выход из админки")]
    ],
    resize_keyboard=True
)

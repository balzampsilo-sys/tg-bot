"""Клавиатуры для выбора услуг"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.repositories.service_repository import ServiceRepository


async def get_services_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора услуги"""
    services = await ServiceRepository.get_all_services(active_only=True)
    
    buttons = []
    for service in services:
        # Эмодзи в зависимости от длительности
        if service.duration_minutes <= 60:
            emoji = "⚡"
        elif service.duration_minutes <= 90:
            emoji = "⏱"
        else:
            emoji = "🕐"
        
        button_text = (
            f"{emoji} {service.name} "
            f"({service.get_duration_display()}, {service.price})"
        )
        
        buttons.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"service:select:{service.id}"
            )
        ])
    
    buttons.append([
        InlineKeyboardButton(text="« Назад", callback_data="cancel_booking_flow")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

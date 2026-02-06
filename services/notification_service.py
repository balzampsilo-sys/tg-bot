"""Сервис уведомлений"""
import logging
from datetime import datetime
from aiogram import Bot

from config import ADMIN_ID


class NotificationService:
    """Сервис для отправки уведомлений"""
    
    def __init__(self, bot: Bot):
        self.bot = bot
    
    async def notify_admin_new_booking(
        self, 
        date_str: str, 
        time_str: str, 
        user_id: int, 
        username: str
    ):
        """Уведомление админу о новой записи"""
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            await self.bot.send_message(
                ADMIN_ID,
                f"🔔 Новая запись\n\n"
                f"{date_obj.strftime('%d.%m')} в {time_str}\n"
                f"@{username}"
            )
        except Exception as e:
            logging.error(f"Error notifying admin about booking: {e}")
    
    async def notify_admin_cancellation(
        self, 
        date_str: str, 
        time_str: str, 
        user_id: int
    ):
        """Уведомление админу об отмене"""
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            await self.bot.send_message(
                ADMIN_ID,
                f"❌ Отмена\n\n"
                f"{date_obj.strftime('%d.%m')} в {time_str}\n"
                f"ID: {user_id}"
            )
        except Exception as e:
            logging.error(f"Error notifying admin about cancellation: {e}")

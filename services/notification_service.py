"""Сервис уведомлений"""

import logging
from datetime import datetime

from aiogram import Bot

from config import ADMIN_IDS  # ИСПРАВЛЕНО: множественное число


class NotificationService:
    """Сервис для отправки уведомлений"""

    def __init__(self, bot: Bot):
        self.bot = bot

    async def notify_admin_new_booking(
        self, date_str: str, time_str: str, user_id: int, username: str
    ):
        """Уведомление админам о новой записи"""
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            message_text = (
                "🔔 Новая запись\n\n"
                f"{date_obj.strftime('%d.%m')} в {time_str}\n"
                f"@{username}"
            )
            
            # Отправляем всем админам
            for admin_id in ADMIN_IDS:
                try:
                    await self.bot.send_message(admin_id, message_text)
                except Exception as e:
                    logging.error(f"Failed to notify admin {admin_id}: {e}")
        except Exception as e:
            logging.error(f"Error notifying admins about booking: {e}")

    async def notify_admin_cancellation(
        self, date_str: str, time_str: str, user_id: int
    ):
        """Уведомление админам об отмене"""
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            message_text = (
                "❌ Отмена\n\n"
                f"{date_obj.strftime('%d.%m')} в {time_str}\n"
                f"ID: {user_id}"
            )
            
            # Отправляем всем админам
            for admin_id in ADMIN_IDS:
                try:
                    await self.bot.send_message(admin_id, message_text)
                except Exception as e:
                    logging.error(f"Failed to notify admin {admin_id}: {e}")
        except Exception as e:
            logging.error(f"Error notifying admins about cancellation: {e}")

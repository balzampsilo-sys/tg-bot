"""Сервис управления бронированием"""
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Tuple

import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import DATABASE_PATH, TIMEZONE
from utils.helpers import now_local
from database.queries import Database


class BookingService:
    """Сервис для работы с бронированием"""
    
    def __init__(self, scheduler: AsyncIOScheduler, bot):
        self.scheduler = scheduler
        self.bot = bot
    
    async def create_booking(
        self, 
        date_str: str, 
        time_str: str, 
        user_id: int, 
        username: str
    ) -> bool:
        """Создание записи с напоминаниями"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                cursor = await db.execute(
                    "INSERT INTO bookings (date, time, user_id, username, created_at) VALUES (?, ?, ?, ?, ?)",
                    (date_str, time_str, user_id, username, now_local().isoformat())
                )
                booking_id = cursor.lastrowid
                await db.commit()
            
            # Умная логика напоминаний
            booking_datetime = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            booking_datetime = booking_datetime.replace(tzinfo=TIMEZONE)
            now = now_local()
            time_until_booking = booking_datetime - now
            
            # Напоминание
            if time_until_booking > timedelta(hours=24):
                reminder_time = booking_datetime - timedelta(hours=24)
                self.scheduler.add_job(
                    self._send_reminder,
                    'date',
                    run_date=reminder_time,
                    args=[user_id, date_str, time_str],
                    id=f"reminder_{booking_id}",
                    replace_existing=True
                )
            elif time_until_booking > timedelta(hours=2):
                reminder_time = booking_datetime - timedelta(hours=2)
                self.scheduler.add_job(
                    self._send_reminder,
                    'date',
                    run_date=reminder_time,
                    args=[user_id, date_str, time_str],
                    id=f"reminder_{booking_id}",
                    replace_existing=True
                )
            elif time_until_booking > timedelta(hours=1):
                reminder_time = booking_datetime - timedelta(hours=1)
                self.scheduler.add_job(
                    self._send_reminder,
                    'date',
                    run_date=reminder_time,
                    args=[user_id, date_str, time_str],
                    id=f"reminder_{booking_id}",
                    replace_existing=True
                )
            
            # Запрос обратной связи через 2 часа после встречи
            feedback_time = booking_datetime + timedelta(hours=2)
            self.scheduler.add_job(
                self._send_feedback_request,
                'date',
                run_date=feedback_time,
                args=[user_id, booking_id, date_str, time_str],
                id=f"feedback_{booking_id}",
                replace_existing=True
            )
            
            await Database.log_event(user_id, "booking_created", f"{date_str} {time_str}")
            return True
            
        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            logging.error(f"Error in create_booking: {e}")
            return False
    
    async def cancel_booking(
        self, 
        date_str: str, 
        time_str: str, 
        user_id: int
    ) -> Tuple[bool, int]:
        """Отмена записи"""
        async with aiosqlite.connect(DATABASE_PATH) as db:
            async with db.execute(
                "SELECT id FROM bookings WHERE date=? AND time=? AND user_id=?",
                (date_str, time_str, user_id)
            ) as cursor:
                result = await cursor.fetchone()
                if not result:
                    return False, 0
                
                booking_id = result[0]
            
            await db.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
            await db.commit()
        
        # Удаляем напоминания
        try:
            self.scheduler.remove_job(f"reminder_{booking_id}")
            self.scheduler.remove_job(f"feedback_{booking_id}")
        except:
            pass
        
        await Database.log_event(user_id, "booking_cancelled", f"{date_str} {time_str}")
        return True, booking_id
    
    async def restore_reminders(self):
        """Восстановить напоминания после рестарта"""
        now = now_local()
        async with aiosqlite.connect(DATABASE_PATH) as db:
            async with db.execute(
                "SELECT id, date, time, user_id FROM bookings"
            ) as cursor:
                all_bookings = await cursor.fetchall()
        
        restored_count = 0
        for booking_id, date_str, time_str, user_id in all_bookings:
            booking_datetime = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            booking_datetime = booking_datetime.replace(tzinfo=TIMEZONE)
            
            # Восстановить напоминание
            reminder_time = booking_datetime - timedelta(hours=24)
            if reminder_time > now:
                try:
                    self.scheduler.add_job(
                        self._send_reminder,
                        'date',
                        run_date=reminder_time,
                        args=[user_id, date_str, time_str],
                        id=f"reminder_{booking_id}",
                        replace_existing=True
                    )
                    restored_count += 1
                except:
                    pass
            
            # Восстановить запрос обратной связи
            feedback_time = booking_datetime + timedelta(hours=2)
            if feedback_time > now:
                try:
                    self.scheduler.add_job(
                        self._send_feedback_request,
                        'date',
                        run_date=feedback_time,
                        args=[user_id, booking_id, date_str, time_str],
                        id=f"feedback_{booking_id}",
                        replace_existing=True
                    )
                except:
                    pass
        
        logging.info(f"Restored {restored_count} reminders")
    
    async def _send_reminder(self, user_id: int, date_str: str, time_str: str):
        """Отправка напоминания"""
        try:
            from config import DAY_NAMES, SERVICE_LOCATION
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            
            await self.bot.send_message(
                user_id,
                f"⏰ НАПОМИНАНИЕ!\n\n"
                f"У вас запись ЗАВТРА:\n"
                f"📅 {date_obj.strftime('%d.%m.%Y')} ({DAY_NAMES[date_obj.weekday()]})\n"
                f"🕒 {time_str}\n"
                f"📍 {SERVICE_LOCATION}\n\n"
                f"Если нужно отменить → '📋 Мои записи'"
            )
            await Database.log_event(user_id, "reminder_sent", f"{date_str} {time_str}")
        except Exception as e:
            logging.error(f"Error sending reminder: {e}")
    
    async def _send_feedback_request(
        self, 
        user_id: int, 
        booking_id: int, 
        date_str: str, 
        time_str: str
    ):
        """Запрос обратной связи"""
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        
        feedback_kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="⭐⭐⭐⭐⭐", callback_data=f"feedback:{booking_id}:5"),
                InlineKeyboardButton(text="⭐⭐⭐⭐", callback_data=f"feedback:{booking_id}:4"),
            ],
            [
                InlineKeyboardButton(text="⭐⭐⭐", callback_data=f"feedback:{booking_id}:3"),
                InlineKeyboardButton(text="⭐⭐", callback_data=f"feedback:{booking_id}:2"),
                InlineKeyboardButton(text="⭐", callback_data=f"feedback:{booking_id}:1"),
            ]
        ])
        
        try:
            await self.bot.send_message(
                user_id,
                "💬 Как прошла встреча?\n\nОцените качество услуги:",
                reply_markup=feedback_kb
            )
            await Database.log_event(user_id, "feedback_request_sent", f"{date_str} {time_str}")
        except Exception as e:
            logging.error(f"Error sending feedback request: {e}")

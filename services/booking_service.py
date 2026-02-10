"""Сервис управления бронированием"""

import logging
import sqlite3
from datetime import timedelta
from typing import Tuple

import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import DATABASE_PATH, MAX_BOOKINGS_PER_USER
from database.queries import Database
from utils.datetime_utils import now_local, parse_datetime


class BookingService:
    """Сервис для работы с бронированием"""

    def __init__(self, scheduler: AsyncIOScheduler, bot):
        self.scheduler = scheduler
        self.bot = bot

    async def create_booking(
        self, date_str: str, time_str: str, user_id: int, username: str
    ) -> Tuple[bool, str]:
        """Создание записи с атомарной проверкой

        Returns:
            Tuple[bool, str]: (success, error_code)
        """
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Начинаем транзакцию
            await db.execute("BEGIN IMMEDIATE")

            try:
                # Проверяем и лимит, и слот одним запросом
                async with db.execute(
                    """SELECT 
                        (SELECT COUNT(*) FROM bookings WHERE user_id=? AND date >= date('now')) as user_count,
                        (SELECT COUNT(*) FROM bookings WHERE date=? AND time=?) as slot_taken,
                        (SELECT COUNT(*) FROM blocked_slots WHERE date=? AND time=?) as is_blocked
                    """,
                    (user_id, date_str, time_str, date_str, time_str),
                ) as cursor:
                    result = await cursor.fetchone()
                    user_count, slot_taken, is_blocked = result

                if user_count >= MAX_BOOKINGS_PER_USER:
                    await db.rollback()
                    logging.warning(f"User {user_id} exceeded booking limit")
                    return False, "limit_exceeded"

                if slot_taken > 0:
                    await db.rollback()
                    logging.info(f"Slot {date_str} {time_str} already taken")
                    return False, "slot_taken"
                    
                if is_blocked > 0:
                    await db.rollback()
                    logging.info(f"Slot {date_str} {time_str} is blocked")
                    return False, "slot_blocked"

                # Создаем запись
                cursor = await db.execute(
                    """INSERT INTO bookings (date, time, user_id, username, created_at)
                    VALUES (?, ?, ?, ?, ?)""",
                    (date_str, time_str, user_id, username, now_local().isoformat()),
                )
                booking_id = cursor.lastrowid

                await db.commit()

                # Планируем напоминание (вне транзакции)
                await self._schedule_reminder(booking_id, date_str, time_str, user_id)
                await Database.log_event(
                    user_id, "booking_created", f"{date_str} {time_str}"
                )

                logging.info(f"Booking created: {booking_id} for user {user_id}")
                return True, "success"

            except sqlite3.IntegrityError as e:
                await db.rollback()
                logging.warning(f"Integrity error creating booking: {e}")
                return False, "slot_taken"
            except Exception as e:
                await db.rollback()
                logging.error(f"Error in create_booking: {e}")
                return False, "unknown_error"

    async def reschedule_booking(
        self,
        booking_id: int,
        old_date_str: str,
        old_time_str: str,
        new_date_str: str,
        new_time_str: str,
        user_id: int,
        username: str,
    ) -> Tuple[bool, str]:
        """Перенос записи в одной транзакции (ИСПРАВЛЕНО: race condition)
        
        Returns:
            Tuple[bool, str]: (success, error_code)
        """
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("BEGIN IMMEDIATE")

            try:
                # 1. Проверяем что старая запись существует
                async with db.execute(
                    "SELECT id FROM bookings WHERE id=? AND user_id=?",
                    (booking_id, user_id),
                ) as cursor:
                    if not await cursor.fetchone():
                        await db.rollback()
                        logging.warning(f"Booking {booking_id} not found for user {user_id}")
                        return False, "booking_not_found"

                # 2. Проверяем что новый слот свободен И не заблокирован
                async with db.execute(
                    """SELECT 
                        (SELECT COUNT(*) FROM bookings WHERE date=? AND time=?) as booking_exists,
                        (SELECT COUNT(*) FROM blocked_slots WHERE date=? AND time=?) as is_blocked
                    """,
                    (new_date_str, new_time_str, new_date_str, new_time_str),
                ) as cursor:
                    result = await cursor.fetchone()
                    booking_exists, is_blocked = result

                    if booking_exists > 0:
                        await db.rollback()
                        logging.info(f"Slot {new_date_str} {new_time_str} already taken")
                        return False, "slot_taken"
                        
                    if is_blocked > 0:
                        await db.rollback()
                        logging.info(f"Slot {new_date_str} {new_time_str} is blocked")
                        return False, "slot_blocked"

                # 3. Атомарное обновление с проверкой UNIQUE constraint
                try:
                    cursor = await db.execute(
                        """UPDATE bookings
                        SET date=?, time=?, created_at=?
                        WHERE id=? AND user_id=?""",
                        (new_date_str, new_time_str, now_local().isoformat(), booking_id, user_id),
                    )

                    # Проверяем что запись действительно обновилась
                    if cursor.rowcount == 0:
                        await db.rollback()
                        return False, "booking_not_found"

                    await db.commit()

                except sqlite3.IntegrityError:
                    # Кто-то успел занять слот между проверкой и UPDATE
                    await db.rollback()
                    logging.warning(f"Race condition detected: slot {new_date_str} {new_time_str} taken")
                    return False, "slot_taken"

                # 4. Перепланируем напоминания (вне транзакции)
                self._remove_job_safe(f"reminder_{booking_id}")
                self._remove_job_safe(f"feedback_{booking_id}")
                await self._schedule_reminder(booking_id, new_date_str, new_time_str, user_id)

                await Database.log_event(
                    user_id,
                    "booking_rescheduled",
                    f"{old_date_str} {old_time_str} -> {new_date_str} {new_time_str}",
                )

                logging.info(f"Booking {booking_id} rescheduled successfully")
                return True, "success"

            except Exception as e:
                await db.rollback()
                logging.error(f"Error in reschedule_booking: {e}")
                return False, "unknown_error"

    def _remove_job_safe(self, job_id: str):
        """Безопасное удаление задачи из scheduler"""
        try:
            self.scheduler.remove_job(job_id)
        except Exception:
            pass

    async def _schedule_reminder(
        self, booking_id: int, date_str: str, time_str: str, user_id: int
    ):
        """Планирование напоминаний (ИСПРАВЛЕНО: timezone)"""
        try:
            # Используем новую функцию парсинга
            booking_datetime = parse_datetime(date_str, time_str)
            now = now_local()
            time_until_booking = booking_datetime - now

            # Напоминание
            if time_until_booking > timedelta(hours=24):
                reminder_time = booking_datetime - timedelta(hours=24)
                self.scheduler.add_job(
                    self._send_reminder,
                    "date",
                    run_date=reminder_time,
                    args=[user_id, date_str, time_str],
                    id=f"reminder_{booking_id}",
                    replace_existing=True,
                )
            elif time_until_booking > timedelta(hours=2):
                reminder_time = booking_datetime - timedelta(hours=2)
                self.scheduler.add_job(
                    self._send_reminder,
                    "date",
                    run_date=reminder_time,
                    args=[user_id, date_str, time_str],
                    id=f"reminder_{booking_id}",
                    replace_existing=True,
                )
            elif time_until_booking > timedelta(hours=1):
                reminder_time = booking_datetime - timedelta(hours=1)
                self.scheduler.add_job(
                    self._send_reminder,
                    "date",
                    run_date=reminder_time,
                    args=[user_id, date_str, time_str],
                    id=f"reminder_{booking_id}",
                    replace_existing=True,
                )

            # Запрос обратной связи через 2 часа после встречи
            feedback_time = booking_datetime + timedelta(hours=2)
            self.scheduler.add_job(
                self._send_feedback_request,
                "date",
                run_date=feedback_time,
                args=[user_id, booking_id, date_str, time_str],
                id=f"feedback_{booking_id}",
                replace_existing=True,
            )
        except Exception as e:
            logging.error(f"Error scheduling reminder: {e}")

    async def cancel_booking(
        self, date_str: str, time_str: str, user_id: int
    ) -> Tuple[bool, int]:
        """Отмена записи"""
        try:
            async with aiosqlite.connect(DATABASE_PATH) as db:
                async with db.execute(
                    "SELECT id FROM bookings WHERE date=? AND time=? AND user_id=?",
                    (date_str, time_str, user_id),
                ) as cursor:
                    result = await cursor.fetchone()
                    if not result:
                        return False, 0

                    booking_id = result[0]

                await db.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
                await db.commit()

            # Удаляем напоминания
            self._remove_job_safe(f"reminder_{booking_id}")
            self._remove_job_safe(f"feedback_{booking_id}")

            await Database.log_event(
                user_id, "booking_cancelled", f"{date_str} {time_str}"
            )
            logging.info(f"Booking {booking_id} cancelled by user {user_id}")
            return True, booking_id
        except Exception as e:
            logging.error(f"Error cancelling booking: {e}")
            return False, 0

    async def restore_reminders(self):
        """Восстановить напоминания после рестарта (ИСПРАВЛЕНО: timezone)"""
        try:
            now = now_local()
            async with aiosqlite.connect(DATABASE_PATH) as db:
                async with db.execute(
                    "SELECT id, date, time, user_id FROM bookings"
                ) as cursor:
                    all_bookings = await cursor.fetchall()

            restored_count = 0
            for booking_id, date_str, time_str, user_id in all_bookings:
                booking_datetime = parse_datetime(date_str, time_str)

                # Восстановить напоминание
                reminder_time = booking_datetime - timedelta(hours=24)
                if reminder_time > now:
                    try:
                        self.scheduler.add_job(
                            self._send_reminder,
                            "date",
                            run_date=reminder_time,
                            args=[user_id, date_str, time_str],
                            id=f"reminder_{booking_id}",
                            replace_existing=True,
                        )
                        restored_count += 1
                    except Exception as e:
                        logging.warning(
                            f"Failed to restore reminder for booking {booking_id}: {e}"
                        )

                # Восстановить запрос обратной связи
                feedback_time = booking_datetime + timedelta(hours=2)
                if feedback_time > now:
                    try:
                        self.scheduler.add_job(
                            self._send_feedback_request,
                            "date",
                            run_date=feedback_time,
                            args=[user_id, booking_id, date_str, time_str],
                            id=f"feedback_{booking_id}",
                            replace_existing=True,
                        )
                    except Exception as e:
                        logging.warning(
                            f"Failed to restore feedback request for booking {booking_id}: {e}"
                        )

            logging.info(f"Restored {restored_count} reminders")
        except Exception as e:
            logging.error(f"Error restoring reminders: {e}")

    async def _send_reminder(self, user_id: int, date_str: str, time_str: str):
        """Отправка напоминания"""
        try:
            from datetime import datetime
            from config import DAY_NAMES, SERVICE_LOCATION

            date_obj = datetime.strptime(date_str, "%Y-%m-%d")

            await self.bot.send_message(
                user_id,
                "⏰ НАПОМИНАНИЕ!\n\n"
                "У вас запись ЗАВТРА:\n"
                f"📅 {date_obj.strftime('%d.%m.%Y')} ({DAY_NAMES[date_obj.weekday()]})\n"
                f"🕒 {time_str}\n"
                f"📍 {SERVICE_LOCATION}\n\n"
                "Если нужно отменить → '📋 Мои записи'",
            )
            await Database.log_event(user_id, "reminder_sent", f"{date_str} {time_str}")
        except Exception as e:
            logging.error(f"Error sending reminder: {e}")

    async def _send_feedback_request(
        self, user_id: int, booking_id: int, date_str: str, time_str: str
    ):
        """Запрос обратной связи"""
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        feedback_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⭐⭐⭐⭐⭐", callback_data=f"feedback:{booking_id}:5"
                    ),
                    InlineKeyboardButton(
                        text="⭐⭐⭐⭐", callback_data=f"feedback:{booking_id}:4"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="⭐⭐⭐", callback_data=f"feedback:{booking_id}:3"
                    ),
                    InlineKeyboardButton(
                        text="⭐⭐", callback_data=f"feedback:{booking_id}:2"
                    ),
                    InlineKeyboardButton(
                        text="⭐", callback_data=f"feedback:{booking_id}:1"
                    ),
                ],
            ]
        )

        try:
            await self.bot.send_message(
                user_id,
                "💬 Как прошла встреча?\n\nОцените качество услуги:",
                reply_markup=feedback_kb,
            )
            await Database.log_event(
                user_id, "feedback_request_sent", f"{date_str} {time_str}"
            )
        except Exception as e:
            logging.error(f"Error sending feedback request: {e}")

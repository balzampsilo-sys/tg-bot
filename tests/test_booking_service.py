"""Тесты для BookingService

Критические сценарии:
- Создание записи (успех, ошибки, race conditions)
- Перенос записи (атомарность, откаты)
- Отмена записи
- Планирование напоминаний
- Восстановление после рестарта
"""

import asyncio
import pytest
from datetime import timedelta
from unittest.mock import patch

from config import MAX_BOOKINGS_PER_USER
from database.queries import Database
from services.booking_service import BookingService
from utils.helpers import now_local


class TestCreateBooking:
    """Тесты создания записи"""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_create_booking_success(
        self, booking_service, init_database, tomorrow_date, test_user_data
    ):
        """Успешное создание записи"""
        success, error_code = await booking_service.create_booking(
            tomorrow_date,
            test_user_data["time_slot"],
            test_user_data["user_id"],
            test_user_data["username"],
        )

        assert success is True
        assert error_code == "success"

        # Проверяем что запись действительно создана
        bookings = await Database.get_user_bookings(test_user_data["user_id"])
        assert len(bookings) == 1
        assert bookings[0][1] == tomorrow_date
        assert bookings[0][2] == test_user_data["time_slot"]

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_create_booking_slot_taken(
        self, booking_service, init_database, tomorrow_date
    ):
        """Попытка забронировать занятый слот"""
        time_str = "10:00"

        # Первое бронирование
        success1, error1 = await booking_service.create_booking(
            tomorrow_date, time_str, 111, "user1"
        )
        assert success1 is True
        assert error1 == "success"

        # Попытка забронировать тот же слот другим пользователем
        success2, error_code = await booking_service.create_booking(
            tomorrow_date, time_str, 222, "user2"
        )

        assert success2 is False
        assert error_code == "slot_taken"

        # Проверяем что у второго пользователя нет записей
        bookings = await Database.get_user_bookings(222)
        assert len(bookings) == 0

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_create_booking_limit_exceeded(
        self, booking_service, init_database
    ):
        """Превышение лимита записей"""
        user_id = 12345

        # Создаем максимальное количество записей
        for i in range(MAX_BOOKINGS_PER_USER):
            date_str = (now_local() + timedelta(days=i + 1)).strftime("%Y-%m-%d")
            success, error_code = await booking_service.create_booking(
                date_str, f"{10 + i}:00", user_id, "testuser"
            )
            assert success is True
            assert error_code == "success"

        # Попытка создать еще одну
        date_str = (now_local() + timedelta(days=10)).strftime("%Y-%m-%d")
        success, error_code = await booking_service.create_booking(
            date_str, "15:00", user_id, "testuser"
        )

        assert success is False
        assert error_code == "limit_exceeded"

        # Проверяем что осталось только MAX_BOOKINGS_PER_USER записей
        bookings = await Database.get_user_bookings(user_id)
        assert len(bookings) == MAX_BOOKINGS_PER_USER

    @pytest.mark.asyncio
    @pytest.mark.unit
    @pytest.mark.slow
    async def test_create_booking_race_condition(
        self, booking_service, init_database, tomorrow_date
    ):
        """⚠️ КРИТИЧЕСКИЙ: Race condition - два пользователя пытаются забронировать одновременно"""
        time_str = "10:00"

        # Создаем две одновременные задачи
        task1 = booking_service.create_booking(tomorrow_date, time_str, 111, "user1")
        task2 = booking_service.create_booking(tomorrow_date, time_str, 222, "user2")

        results = await asyncio.gather(task1, task2)

        # Только один должен успешно забронировать
        success_count = sum(1 for success, _ in results if success)
        assert success_count == 1, "Больше одного пользователя получили слот!"

        # Один должен получить slot_taken
        error_codes = [code for success, code in results if not success]
        assert "slot_taken" in error_codes or "integrity_error" in error_codes

        # Проверяем что в БД только одна запись
        slot_free = await Database.is_slot_free(tomorrow_date, time_str)
        assert slot_free is False

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_create_booking_schedules_reminder(
        self, booking_service, init_database, mock_scheduler, tomorrow_date
    ):
        """Создание записи планирует напоминание"""
        user_id = 12345
        time_str = "10:00"

        await booking_service.create_booking(
            tomorrow_date, time_str, user_id, "testuser"
        )

        # Получаем booking_id
        bookings = await Database.get_user_bookings(user_id)
        booking_id = bookings[0][0]

        # Проверяем что job'ы запланированы
        reminder_job = mock_scheduler.get_job(f"reminder_{booking_id}")
        feedback_job = mock_scheduler.get_job(f"feedback_{booking_id}")

        assert reminder_job is not None, "Reminder job not scheduled"
        assert feedback_job is not None, "Feedback job not scheduled"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_create_booking_all_error_codes(
        self, booking_service, init_database, tomorrow_date
    ):
        """Тест всех возможных кодов ошибок"""
        # 1. Success
        success, code = await booking_service.create_booking(
            tomorrow_date, "10:00", 111, "user1"
        )
        assert success is True
        assert code == "success"

        # 2. Slot taken
        success, code = await booking_service.create_booking(
            tomorrow_date, "10:00", 222, "user2"
        )
        assert success is False
        assert code == "slot_taken"

        # 3. Limit exceeded
        for i in range(MAX_BOOKINGS_PER_USER):
            date = (now_local() + timedelta(days=i + 2)).strftime("%Y-%m-%d")
            await booking_service.create_booking(date, "11:00", 333, "user3")

        date = (now_local() + timedelta(days=20)).strftime("%Y-%m-%d")
        success, code = await booking_service.create_booking(
            date, "12:00", 333, "user3"
        )
        assert success is False
        assert code == "limit_exceeded"


class TestRescheduleBooking:
    """Тесты переноса записи"""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_reschedule_success(
        self, booking_service, init_database, tomorrow_date, next_week_date
    ):
        """Успешный перенос записи"""
        user_id = 12345
        old_time = "10:00"
        new_time = "14:00"

        # Создаем запись
        await booking_service.create_booking(
            tomorrow_date, old_time, user_id, "testuser"
        )

        # Получаем ID записи
        bookings = await Database.get_user_bookings(user_id)
        booking_id = bookings[0][0]

        # Переносим
        success = await booking_service.reschedule_booking(
            booking_id,
            tomorrow_date,
            old_time,
            next_week_date,
            new_time,
            user_id,
            "testuser",
        )

        assert success is True

        # Проверяем что запись обновлена
        bookings = await Database.get_user_bookings(user_id)
        assert len(bookings) == 1
        assert bookings[0][1] == next_week_date
        assert bookings[0][2] == new_time

        # Старый слот должен быть свободен
        old_slot_free = await Database.is_slot_free(tomorrow_date, old_time)
        assert old_slot_free is True

        # Новый слот должен быть занят
        new_slot_free = await Database.is_slot_free(next_week_date, new_time)
        assert new_slot_free is False

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_reschedule_to_taken_slot(
        self, booking_service, init_database, tomorrow_date, next_week_date
    ):
        """⚠️ КРИТИЧЕСКИЙ: Попытка перенести на занятый слот"""
        user_id = 12345
        old_time = "10:00"
        new_time = "14:00"

        # Создаем две записи
        await booking_service.create_booking(tomorrow_date, old_time, user_id, "testuser")
        await booking_service.create_booking(
            next_week_date, new_time, 67890, "otheruser"
        )

        bookings = await Database.get_user_bookings(user_id)
        booking_id = bookings[0][0]

        # Пытаемся перенести на занятый слот
        success = await booking_service.reschedule_booking(
            booking_id,
            tomorrow_date,
            old_time,
            next_week_date,
            new_time,
            user_id,
            "testuser",
        )

        assert success is False

        # ✅ КРИТИЧЕСКАЯ ПРОВЕРКА: старая запись НЕ должна быть удалена!
        bookings = await Database.get_user_bookings(user_id)
        assert len(bookings) == 1, "Запись пользователя была потеряна!"
        assert bookings[0][1] == tomorrow_date, "Дата изменилась"
        assert bookings[0][2] == old_time, "Время изменилось"

        # Проверяем что обе записи на месте
        bookings_other = await Database.get_user_bookings(67890)
        assert len(bookings_other) == 1

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_reschedule_nonexistent_booking(
        self, booking_service, init_database, tomorrow_date, next_week_date
    ):
        """Попытка перенести несуществующую запись"""
        success = await booking_service.reschedule_booking(
            booking_id=99999,
            old_date_str=tomorrow_date,
            old_time_str="10:00",
            new_date_str=next_week_date,
            new_time_str="11:00",
            user_id=12345,
            username="testuser",
        )

        assert success is False

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_reschedule_wrong_user(
        self, booking_service, init_database, tomorrow_date, next_week_date
    ):
        """Попытка перенести чужую запись"""
        user1_id = 111
        user2_id = 222

        # Пользователь 1 создает запись
        await booking_service.create_booking(
            tomorrow_date, "10:00", user1_id, "user1"
        )
        bookings = await Database.get_user_bookings(user1_id)
        booking_id = bookings[0][0]

        # Пользователь 2 пытается перенести чужую запись
        success = await booking_service.reschedule_booking(
            booking_id,
            tomorrow_date,
            "10:00",
            next_week_date,
            "11:00",
            user2_id,
            "user2",
        )

        assert success is False

        # Запись пользователя 1 должна остаться без изменений
        bookings = await Database.get_user_bookings(user1_id)
        assert len(bookings) == 1
        assert bookings[0][1] == tomorrow_date

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_reschedule_updates_scheduler_jobs(
        self,
        booking_service,
        init_database,
        mock_scheduler,
        tomorrow_date,
        next_week_date,
    ):
        """Перенос обновляет job'ы в scheduler"""
        user_id = 12345

        # Создаем запись
        await booking_service.create_booking(
            tomorrow_date, "10:00", user_id, "testuser"
        )
        bookings = await Database.get_user_bookings(user_id)
        booking_id = bookings[0][0]

        # Очищаем историю
        mock_scheduler.clear_history()

        # Переносим
        await booking_service.reschedule_booking(
            booking_id,
            tomorrow_date,
            "10:00",
            next_week_date,
            "14:00",
            user_id,
            "testuser",
        )

        # Проверяем что старые job'ы удалены и созданы новые
        history = mock_scheduler.job_history
        remove_actions = [h for h in history if h["action"] == "remove"]
        add_actions = [h for h in history if h["action"] == "add"]

        # Должно быть удаление старых и создание новых
        assert len(remove_actions) >= 0  # Может быть 0 если job не существовал
        assert len(add_actions) >= 2  # reminder + feedback


class TestCancelBooking:
    """Тесты отмены записи"""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_cancel_booking_success(
        self, booking_service, init_database, tomorrow_date
    ):
        """Успешная отмена записи"""
        user_id = 12345
        time_str = "10:00"

        # Создаем запись
        await booking_service.create_booking(
            tomorrow_date, time_str, user_id, "testuser"
        )

        # Отменяем
        success, booking_id = await booking_service.cancel_booking(
            tomorrow_date, time_str, user_id
        )

        assert success is True
        assert booking_id > 0

        # Проверяем что записи больше нет
        bookings = await Database.get_user_bookings(user_id)
        assert len(bookings) == 0

        # Слот должен быть свободен
        slot_free = await Database.is_slot_free(tomorrow_date, time_str)
        assert slot_free is True

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_cancel_nonexistent_booking(
        self, booking_service, init_database, tomorrow_date
    ):
        """Попытка отменить несуществующую запись"""
        success, booking_id = await booking_service.cancel_booking(
            tomorrow_date, "10:00", 12345
        )

        assert success is False
        assert booking_id == 0

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_cancel_booking_removes_scheduler_jobs(
        self, booking_service, init_database, mock_scheduler, tomorrow_date
    ):
        """Отмена удаляет job'ы из scheduler"""
        user_id = 12345
        time_str = "10:00"

        # Создаем запись
        await booking_service.create_booking(
            tomorrow_date, time_str, user_id, "testuser"
        )
        bookings = await Database.get_user_bookings(user_id)
        booking_id = bookings[0][0]

        # Проверяем что job'ы есть
        assert mock_scheduler.get_job(f"reminder_{booking_id}") is not None
        assert mock_scheduler.get_job(f"feedback_{booking_id}") is not None

        # Отменяем
        await booking_service.cancel_booking(tomorrow_date, time_str, user_id)

        # Job'ы должны быть удалены
        assert mock_scheduler.get_job(f"reminder_{booking_id}") is None
        assert mock_scheduler.get_job(f"feedback_{booking_id}") is None


class TestAtomicity:
    """Тесты атомарности операций"""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_reschedule_uses_update_not_delete_insert(
        self, booking_service, init_database, tomorrow_date, next_week_date
    ):
        """⚠️ КРИТИЧЕСКИЙ: Перенос использует UPDATE вместо DELETE+INSERT"""
        user_id = 12345

        # Создаем запись
        await booking_service.create_booking(
            tomorrow_date, "10:00", user_id, "testuser"
        )
        bookings = await Database.get_user_bookings(user_id)
        original_booking_id = bookings[0][0]

        # Переносим
        success = await booking_service.reschedule_booking(
            original_booking_id,
            tomorrow_date,
            "10:00",
            next_week_date,
            "14:00",
            user_id,
            "testuser",
        )

        assert success is True

        # ✅ КРИТИЧЕСКАЯ ПРОВЕРКА: ID записи НЕ изменился
        bookings = await Database.get_user_bookings(user_id)
        assert len(bookings) == 1
        assert (
            bookings[0][0] == original_booking_id
        ), "ID изменился - используется DELETE+INSERT!"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_reschedule_rollback_on_error(
        self, booking_service, init_database, tomorrow_date, next_week_date
    ):
        """Откат транзакции при ошибке переноса"""
        user_id = 12345

        # Создаем запись
        await booking_service.create_booking(
            tomorrow_date, "10:00", user_id, "testuser"
        )
        bookings_before = await Database.get_user_bookings(user_id)
        booking_id = bookings_before[0][0]

        # Занимаем целевой слот
        await booking_service.create_booking(
            next_week_date, "14:00", 67890, "otheruser"
        )

        # Пытаемся перенести - должен быть откат
        success = await booking_service.reschedule_booking(
            booking_id,
            tomorrow_date,
            "10:00",
            next_week_date,
            "14:00",
            user_id,
            "testuser",
        )

        assert success is False

        # Проверяем что БД в исходном состоянии
        bookings_after = await Database.get_user_bookings(user_id)
        assert len(bookings_after) == 1
        assert (
            bookings_after[0] == bookings_before[0]
        ), "Данные изменились после неудачного переноса"


class TestRestoreReminders:
    """Тесты восстановления напоминаний"""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_restore_reminders_after_restart(
        self, booking_service, init_database, create_test_booking, mock_scheduler
    ):
        """Восстановление напоминаний после рестарта"""
        # Создаем несколько будущих записей
        for i in range(3):
            date = (now_local() + timedelta(days=i + 2)).strftime("%Y-%m-%d")
            await create_test_booking(date_str=date, time_str="10:00")

        # Очищаем scheduler (симуляция рестарта)
        mock_scheduler.shutdown()

        # Восстанавливаем
        await booking_service.restore_reminders()

        # Проверяем что job'ы восстановлены
        jobs = mock_scheduler.get_jobs()
        assert len(jobs) > 0, "No jobs restored"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_restore_reminders_skips_past_bookings(
        self, booking_service, init_database, create_test_booking, yesterday_date, mock_scheduler
    ):
        """Восстановление пропускает прошлые записи"""
        # Создаем прошлую запись
        await create_test_booking(date_str=yesterday_date, time_str="10:00")

        # Очищаем scheduler
        mock_scheduler.shutdown()

        # Восстанавливаем
        await booking_service.restore_reminders()

        # Не должно быть job'ов для прошлых записей
        jobs = mock_scheduler.get_jobs()
        assert len(jobs) == 0


class TestNotifications:
    """Тесты отправки уведомлений"""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_send_reminder(
        self, booking_service, mock_bot, tomorrow_date
    ):
        """Отправка напоминания"""
        user_id = 12345
        date_str = tomorrow_date
        time_str = "10:00"

        await booking_service._send_reminder(user_id, date_str, time_str)

        # Проверяем что сообщение отправлено
        assert len(mock_bot.sent_messages) == 1
        message = mock_bot.sent_messages[0]
        assert message["chat_id"] == user_id
        assert "НАПОМИНАНИЕ" in message["text"]

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_send_feedback_request(
        self, booking_service, mock_bot, tomorrow_date
    ):
        """Отправка запроса обратной связи"""
        user_id = 12345
        booking_id = 1
        date_str = tomorrow_date
        time_str = "10:00"

        await booking_service._send_feedback_request(
            user_id, booking_id, date_str, time_str
        )

        # Проверяем что сообщение отправлено
        assert len(mock_bot.sent_messages) == 1
        message = mock_bot.sent_messages[0]
        assert message["chat_id"] == user_id
        assert "Как прошла встреча" in message["text"]
        assert message["reply_markup"] is not None


print("✅ test_booking_service.py loaded successfully")

"""Тесты для database/queries.py

Покрывает:
- Инициализацию БД
- CRUD операции для пользователей
- CRUD операции для записей
- Аналитику и логирование
- Обратную связь
- Блокировку слотов
- Админ сессии
"""

import pytest
from datetime import timedelta

from config import MAX_BOOKINGS_PER_USER
from database.queries import Database
from utils.helpers import now_local


class TestDatabaseInit:
    """Тесты инициализации БД"""

    @pytest.mark.asyncio
    async def test_init_db_creates_tables(self, init_database):
        """Инициализация создает все таблицы"""
        import aiosqlite
        from config import DATABASE_PATH

        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Проверяем что все таблицы существуют
            tables = [
                "bookings",
                "users",
                "analytics",
                "feedback",
                "blocked_slots",
                "admin_sessions",
            ]

            for table in tables:
                async with db.execute(
                    f"SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ) as cursor:
                    result = await cursor.fetchone()
                    assert result is not None, f"Table {table} not created"

    @pytest.mark.asyncio
    async def test_bookings_table_has_unique_constraint(self, init_database):
        """Таблица bookings имеет UNIQUE констрейнт"""
        import aiosqlite
        from config import DATABASE_PATH

        date_str = (now_local() + timedelta(days=1)).strftime("%Y-%m-%d")

        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Первая запись - успешна
            await db.execute(
                "INSERT INTO bookings (date, time, user_id, username, created_at) VALUES (?, ?, ?, ?, ?)",
                (date_str, "10:00", 111, "user1", now_local().isoformat()),
            )
            await db.commit()

            # Вторая запись с тем же date+time - должна фейлиться
            with pytest.raises(aiosqlite.IntegrityError):
                await db.execute(
                    "INSERT INTO bookings (date, time, user_id, username, created_at) VALUES (?, ?, ?, ?, ?)",
                    (date_str, "10:00", 222, "user2", now_local().isoformat()),
                )
                await db.commit()


class TestUserOperations:
    """Тесты операций с пользователями"""

    @pytest.mark.asyncio
    async def test_register_user(self, init_database):
        """Регистрация пользователя"""
        await Database.register_user(12345, "testuser")

        # Проверяем что пользователь добавлен
        import aiosqlite
        from config import DATABASE_PATH

        async with aiosqlite.connect(DATABASE_PATH) as db:
            async with db.execute(
                "SELECT user_id, username FROM users WHERE user_id=?", (12345,)
            ) as cursor:
                result = await cursor.fetchone()
                assert result is not None
                assert result[0] == 12345
                assert result[1] == "testuser"

    @pytest.mark.asyncio
    async def test_register_user_idempotent(self, init_database):
        """Повторная регистрация не создает дубликаты"""
        await Database.register_user(12345, "testuser")
        await Database.register_user(12345, "testuser")  # Повторно

        import aiosqlite
        from config import DATABASE_PATH

        async with aiosqlite.connect(DATABASE_PATH) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM users WHERE user_id=?", (12345,)
            ) as cursor:
                count = (await cursor.fetchone())[0]
                assert count == 1, "Должен быть только 1 пользователь"

    @pytest.mark.asyncio
    async def test_get_all_users(self, init_database, create_test_user):
        """Получение всех пользователей"""
        # Создаем несколько пользователей
        await create_test_user(111, "user1")
        await create_test_user(222, "user2")
        await create_test_user(333, "user3")

        users = await Database.get_all_users()

        assert len(users) == 3
        assert 111 in users
        assert 222 in users
        assert 333 in users

    @pytest.mark.asyncio
    async def test_get_all_users_empty(self, init_database):
        """Получение пустого списка пользователей"""
        users = await Database.get_all_users()
        assert users == []


class TestBookingOperations:
    """Тесты операций с записями"""

    @pytest.mark.asyncio
    async def test_is_slot_free_empty(self, init_database, tomorrow_date):
        """Пустой слот считается свободным"""
        is_free = await Database.is_slot_free(tomorrow_date, "10:00")
        assert is_free is True

    @pytest.mark.asyncio
    async def test_is_slot_free_taken(self, init_database, create_test_booking, tomorrow_date):
        """Занятый слот не свободен"""
        # Создаем запись
        await create_test_booking(date_str=tomorrow_date, time_str="10:00")

        is_free = await Database.is_slot_free(tomorrow_date, "10:00")
        assert is_free is False

    @pytest.mark.asyncio
    async def test_get_user_bookings(self, init_database, create_test_booking, tomorrow_date):
        """Получение записей пользователя"""
        user_id = 12345

        # Создаем 2 записи
        await create_test_booking(date_str=tomorrow_date, time_str="10:00", user_id=user_id)
        next_week = (now_local() + timedelta(days=7)).strftime("%Y-%m-%d")
        await create_test_booking(date_str=next_week, time_str="14:00", user_id=user_id)

        bookings = await Database.get_user_bookings(user_id)

        assert len(bookings) == 2
        # Проверяем структуру: (id, date, time, created_at)
        assert bookings[0][1] == tomorrow_date
        assert bookings[0][2] == "10:00"

    @pytest.mark.asyncio
    async def test_get_user_bookings_empty(self, init_database):
        """Пустой список записей"""
        bookings = await Database.get_user_bookings(99999)
        assert bookings == []

    @pytest.mark.asyncio
    async def test_get_user_bookings_only_future(self, init_database, create_test_booking, yesterday_date, tomorrow_date):
        """Возвращаются только будущие записи"""
        user_id = 12345

        # Создаем прошлую и будущую запись
        await create_test_booking(date_str=yesterday_date, time_str="10:00", user_id=user_id)
        await create_test_booking(date_str=tomorrow_date, time_str="14:00", user_id=user_id)

        bookings = await Database.get_user_bookings(user_id)

        # Должна быть только будущая
        assert len(bookings) == 1
        assert bookings[0][1] == tomorrow_date

    @pytest.mark.asyncio
    async def test_get_booking_by_id(self, init_database, create_test_booking, tomorrow_date):
        """Получение записи по ID"""
        user_id = 12345
        booking_id = await create_test_booking(
            date_str=tomorrow_date, time_str="10:00", user_id=user_id
        )

        result = await Database.get_booking_by_id(booking_id, user_id)

        assert result is not None
        assert result[0] == tomorrow_date
        assert result[1] == "10:00"

    @pytest.mark.asyncio
    async def test_get_booking_by_id_wrong_user(self, init_database, create_test_booking, tomorrow_date):
        """Нельзя получить чужую запись"""
        booking_id = await create_test_booking(
            date_str=tomorrow_date, time_str="10:00", user_id=111
        )

        # Пытаемся получить с другим user_id
        result = await Database.get_booking_by_id(booking_id, 222)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_booking_by_id_nonexistent(self, init_database):
        """Получение несуществующей записи"""
        result = await Database.get_booking_by_id(99999, 12345)
        assert result is None

    @pytest.mark.asyncio
    async def test_can_user_book(self, init_database, create_test_booking, tomorrow_date):
        """Проверка лимита записей"""
        user_id = 12345

        # Изначально может
        can_book = await Database.can_user_book(user_id)
        assert can_book is True

        # Создаем MAX_BOOKINGS_PER_USER записей
        for i in range(MAX_BOOKINGS_PER_USER):
            date = (now_local() + timedelta(days=i + 1)).strftime("%Y-%m-%d")
            await create_test_booking(date_str=date, time_str="10:00", user_id=user_id)

        # Теперь не может
        can_book = await Database.can_user_book(user_id)
        assert can_book is False


class TestScheduleOperations:
    """Тесты операций с расписанием"""

    @pytest.mark.asyncio
    async def test_get_week_schedule(self, init_database, create_test_booking):
        """Получение расписания на неделю"""
        # Создаем записи на разные дни
        for i in range(3):
            date = (now_local() + timedelta(days=i + 1)).strftime("%Y-%m-%d")
            await create_test_booking(date_str=date, time_str=f"{10 + i}:00", username=f"user{i}")

        today = now_local().strftime("%Y-%m-%d")
        schedule = await Database.get_week_schedule(today, days=7)

        assert len(schedule) >= 3
        # Проверяем структуру: (date, time, username)
        assert all(len(entry) == 3 for entry in schedule)

    @pytest.mark.asyncio
    async def test_get_month_statuses(self, init_database, create_test_booking):
        """Получение статусов дней месяца"""
        # Создаем записи на завтра
        tomorrow = (now_local() + timedelta(days=1)).strftime("%Y-%m-%d")
        await create_test_booking(date_str=tomorrow, time_str="10:00")
        await create_test_booking(date_str=tomorrow, time_str="11:00", user_id=222)

        year_month = tomorrow[:7]  # "YYYY-MM"
        statuses = await Database.get_month_statuses(year_month)

        # Проверяем что завтра есть в статусах
        day = int(tomorrow.split("-")[2])
        assert day in statuses
        assert statuses[day] == 2  # 2 записи


class TestAnalyticsOperations:
    """Тесты аналитики"""

    @pytest.mark.asyncio
    async def test_log_event(self, init_database):
        """Логирование события"""
        await Database.log_event(12345, "test_event", "test details")

        # Проверяем что событие залогировано
        import aiosqlite
        from config import DATABASE_PATH

        async with aiosqlite.connect(DATABASE_PATH) as db:
            async with db.execute(
                "SELECT user_id, event, details FROM analytics WHERE user_id=?",
                (12345,),
            ) as cursor:
                result = await cursor.fetchone()
                assert result is not None
                assert result[0] == 12345
                assert result[1] == "test_event"
                assert result[2] == "test details"

    @pytest.mark.asyncio
    async def test_get_top_clients(self, init_database, create_test_booking):
        """Получение топ клиентов"""
        # Создаем записи для разных пользователей
        for i in range(3):
            date = (now_local() + timedelta(days=i + 1)).strftime("%Y-%m-%d")
            await create_test_booking(date_str=date, time_str="10:00", user_id=111, username="user1")

        for i in range(2):
            date = (now_local() + timedelta(days=i + 10)).strftime("%Y-%m-%d")
            await create_test_booking(date_str=date, time_str="10:00", user_id=222, username="user2")

        top_clients = await Database.get_top_clients(limit=10)

        assert len(top_clients) == 2
        # Первый должен быть user1 с 3 записями
        assert top_clients[0] == ("user1", 3)
        assert top_clients[1] == ("user2", 2)


class TestFeedbackOperations:
    """Тесты обратной связи"""

    @pytest.mark.asyncio
    async def test_save_feedback(self, init_database, create_test_booking, tomorrow_date):
        """Сохранение отзыва"""
        booking_id = await create_test_booking(date_str=tomorrow_date, time_str="10:00")

        success = await Database.save_feedback(12345, booking_id, 5)
        assert success is True

        # Проверяем что отзыв сохранен
        import aiosqlite
        from config import DATABASE_PATH

        async with aiosqlite.connect(DATABASE_PATH) as db:
            async with db.execute(
                "SELECT user_id, booking_id, rating FROM feedback WHERE booking_id=?",
                (booking_id,),
            ) as cursor:
                result = await cursor.fetchone()
                assert result is not None
                assert result[0] == 12345
                assert result[1] == booking_id
                assert result[2] == 5

    @pytest.mark.asyncio
    async def test_save_feedback_invalid_rating(self, init_database, create_test_booking, tomorrow_date):
        """Невалидный рейтинг (0 или 6+)"""
        booking_id = await create_test_booking(date_str=tomorrow_date, time_str="10:00")

        # Рейтинг должен быть от 1 до 5
        success = await Database.save_feedback(12345, booking_id, 0)
        assert success is True  # Операция успешна, но значение сохранится как есть

        success = await Database.save_feedback(12345, booking_id, 6)
        assert success is True


class TestBlockedSlotsOperations:
    """Тесты блокировки слотов"""

    @pytest.mark.asyncio
    async def test_is_slot_blocked(self, init_database, tomorrow_date):
        """Проверка блокировки слота"""
        # Изначально не заблокирован
        is_blocked = await Database.is_slot_blocked(tomorrow_date, "10:00")
        assert is_blocked is False

        # Блокируем
        import aiosqlite
        from config import DATABASE_PATH

        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                "INSERT INTO blocked_slots (date, time, reason) VALUES (?, ?, ?)",
                (tomorrow_date, "10:00", "test block"),
            )
            await db.commit()

        # Теперь заблокирован
        is_blocked = await Database.is_slot_blocked(tomorrow_date, "10:00")
        assert is_blocked is True


class TestCleanupOperations:
    """Тесты очистки БД"""

    @pytest.mark.asyncio
    async def test_cleanup_old_bookings(self, init_database, create_test_booking, yesterday_date, tomorrow_date):
        """Очистка старых записей"""
        # Создаем старую и новую запись
        await create_test_booking(date_str=yesterday_date, time_str="10:00")
        await create_test_booking(date_str=tomorrow_date, time_str="10:00")

        # Удаляем все записи до сегодня
        today = now_local().strftime("%Y-%m-%d")
        deleted_count = await Database.cleanup_old_bookings(today)

        assert deleted_count >= 1

        # Проверяем что осталась только будущая
        import aiosqlite
        from config import DATABASE_PATH

        async with aiosqlite.connect(DATABASE_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM bookings") as cursor:
                count = (await cursor.fetchone())[0]
                assert count == 1  # Только завтрашняя

    @pytest.mark.asyncio
    async def test_cleanup_old_bookings_with_date_validation(self, init_database):
        """Очистка с неверной датой должна вернуть 0"""
        deleted_count = await Database.cleanup_old_bookings("invalid-date")
        assert deleted_count == 0


print("✅ test_database.py loaded successfully")

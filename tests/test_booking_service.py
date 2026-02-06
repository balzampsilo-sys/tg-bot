"""Тесты для BookingService"""
import pytest
import asyncio
from datetime import datetime, timedelta
from services.booking_service import BookingService
from database.queries import Database
from utils.helpers import now_local
from config import MAX_BOOKINGS_PER_USER


@pytest.fixture
async def booking_service(mock_scheduler, mock_bot):
    """Фикстура для BookingService"""
    service = BookingService(mock_scheduler, mock_bot)
    return service


@pytest.fixture
async def setup_database():
    """Инициализация тестовой БД перед каждым тестом"""
    await Database.init_db()
    yield
    # Очистка после теста выполняется в conftest.py


class TestCreateBooking:
    """Тесты создания записи"""
    
    @pytest.mark.asyncio
    async def test_create_booking_success(self, booking_service, setup_database):
        """Успешное создание записи"""
        tomorrow = (now_local() + timedelta(days=1)).strftime("%Y-%m-%d")
        time_str = "10:00"
        
        success, error_code = await booking_service.create_booking(
            tomorrow, time_str, 12345, "testuser"
        )
        
        assert success is True
        assert error_code == "success"
        
        # Проверяем что запись действительно создана
        bookings = await Database.get_user_bookings(12345)
        assert len(bookings) == 1
        assert bookings[0][1] == tomorrow
        assert bookings[0][2] == time_str
    
    @pytest.mark.asyncio
    async def test_create_booking_slot_taken(self, booking_service, setup_database):
        """Попытка забронировать занятый слот"""
        tomorrow = (now_local() + timedelta(days=1)).strftime("%Y-%m-%d")
        time_str = "10:00"
        
        # Первое бронирование
        success1, error1 = await booking_service.create_booking(tomorrow, time_str, 12345, "user1")
        assert success1 is True
        assert error1 == "success"
        
        # Попытка забронировать тот же слот другим пользователем
        success2, error_code = await booking_service.create_booking(
            tomorrow, time_str, 67890, "user2"
        )
        
        assert success2 is False
        assert error_code == "slot_taken"
        
        # Проверяем что у второго пользователя нет записей
        bookings = await Database.get_user_bookings(67890)
        assert len(bookings) == 0
    
    @pytest.mark.asyncio
    async def test_create_booking_limit_exceeded(self, booking_service, setup_database):
        """Превышение лимита записей"""
        user_id = 12345
        
        # Создаем максимальное количество записей
        for i in range(MAX_BOOKINGS_PER_USER):
            date_str = (now_local() + timedelta(days=i+1)).strftime("%Y-%m-%d")
            success, error_code = await booking_service.create_booking(
                date_str, f"{10+i}:00", user_id, "testuser"
            )
            assert success is True
            assert error_code == "success"
        
        # Попытка создать ещё одну
        date_str = (now_local() + timedelta(days=10)).strftime("%Y-%m-%d")
        success, error_code = await booking_service.create_booking(
            date_str, "15:00", user_id, "testuser"
        )
        
        assert success is False
        assert error_code == "limit_exceeded"
    
    @pytest.mark.asyncio
    async def test_create_booking_race_condition(self, booking_service, setup_database):
        """Тест race condition - два пользователя пытаются забронировать одновременно"""
        tomorrow = (now_local() + timedelta(days=1)).strftime("%Y-%m-%d")
        time_str = "10:00"
        
        # Создаем две одновременные задачи
        task1 = booking_service.create_booking(tomorrow, time_str, 111, "user1")
        task2 = booking_service.create_booking(tomorrow, time_str, 222, "user2")
        
        results = await asyncio.gather(task1, task2)
        
        # Только один должен успешно забронировать
        success_count = sum(1 for success, _ in results if success)
        assert success_count == 1
        
        # Один должен получить slot_taken
        error_codes = [code for success, code in results if not success]
        assert "slot_taken" in error_codes
        
        # Проверяем что в БД только одна запись
        slot_free = await Database.is_slot_free(tomorrow, time_str)
        assert slot_free is False
    
    @pytest.mark.asyncio
    async def test_create_booking_all_error_codes(self, booking_service, setup_database):
        """Тест всех возможных кодов ошибок"""
        tomorrow = (now_local() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        # 1. Success
        success, code = await booking_service.create_booking(tomorrow, "10:00", 111, "user1")
        assert success is True
        assert code == "success"
        
        # 2. Slot taken
        success, code = await booking_service.create_booking(tomorrow, "10:00", 222, "user2")
        assert success is False
        assert code == "slot_taken"
        
        # 3. Limit exceeded
        for i in range(MAX_BOOKINGS_PER_USER):
            date = (now_local() + timedelta(days=i+2)).strftime("%Y-%m-%d")
            await booking_service.create_booking(date, "11:00", 333, "user3")
        
        date = (now_local() + timedelta(days=20)).strftime("%Y-%m-%d")
        success, code = await booking_service.create_booking(date, "12:00", 333, "user3")
        assert success is False
        assert code == "limit_exceeded"


class TestRescheduleBooking:
    """Тесты переноса записи"""
    
    @pytest.mark.asyncio
    async def test_reschedule_success(self, booking_service, setup_database):
        """Успешный перенос записи"""
        user_id = 12345
        old_date = (now_local() + timedelta(days=1)).strftime("%Y-%m-%d")
        old_time = "10:00"
        new_date = (now_local() + timedelta(days=2)).strftime("%Y-%m-%d")
        new_time = "14:00"
        
        # Создаем запись
        success, error_code = await booking_service.create_booking(
            old_date, old_time, user_id, "testuser"
        )
        assert success is True
        assert error_code == "success"
        
        # Получаем ID записи
        bookings = await Database.get_user_bookings(user_id)
        booking_id = bookings[0][0]
        
        # Переносим
        success = await booking_service.reschedule_booking(
            booking_id, old_date, old_time, new_date, new_time, user_id, "testuser"
        )
        
        assert success is True
        
        # Проверяем что запись обновлена
        bookings = await Database.get_user_bookings(user_id)
        assert len(bookings) == 1
        assert bookings[0][1] == new_date
        assert bookings[0][2] == new_time
        
        # Старый слот должен быть свободен
        old_slot_free = await Database.is_slot_free(old_date, old_time)
        assert old_slot_free is True
        
        # Новый слот должен быть занят
        new_slot_free = await Database.is_slot_free(new_date, new_time)
        assert new_slot_free is False
    
    @pytest.mark.asyncio
    async def test_reschedule_to_taken_slot(self, booking_service, setup_database):
        """❗ КРИТИЧЕСКИЙ ТЕСТ: Попытка перенести на занятый слот"""
        user_id = 12345
        old_date = (now_local() + timedelta(days=1)).strftime("%Y-%m-%d")
        old_time = "10:00"
        new_date = (now_local() + timedelta(days=2)).strftime("%Y-%m-%d")
        new_time = "14:00"
        
        # Создаем две записи
        await booking_service.create_booking(old_date, old_time, user_id, "testuser")
        await booking_service.create_booking(new_date, new_time, 67890, "otheruser")
        
        bookings = await Database.get_user_bookings(user_id)
        booking_id = bookings[0][0]
        
        # Пытаемся перенести на занятый слот
        success = await booking_service.reschedule_booking(
            booking_id, old_date, old_time, new_date, new_time, user_id, "testuser"
        )
        
        assert success is False
        
        # ✅ КРИТИЧЕСКАЯ ПРОВЕРКА: старая запись НЕ должна быть удалена!
        bookings = await Database.get_user_bookings(user_id)
        assert len(bookings) == 1, "Запись пользователя была потеряна!"
        assert bookings[0][1] == old_date, "Дата изменилась при неудачном переносе"
        assert bookings[0][2] == old_time, "Время изменилось при неудачном переносе"
        
        # Проверяем что обе записи на месте
        bookings_other = await Database.get_user_bookings(67890)
        assert len(bookings_other) == 1, "Запись другого пользователя была удалена"
    
    @pytest.mark.asyncio
    async def test_reschedule_nonexistent_booking(self, booking_service, setup_database):
        """Попытка перенести несуществующую запись"""
        success = await booking_service.reschedule_booking(
            booking_id=99999,
            old_date_str="2026-12-31",
            old_time_str="10:00",
            new_date_str="2027-01-01",
            new_time_str="11:00",
            user_id=12345,
            username="testuser"
        )
        
        assert success is False
    
    @pytest.mark.asyncio
    async def test_reschedule_wrong_user(self, booking_service, setup_database):
        """Попытка перенести чужую запись"""
        user1_id = 111
        user2_id = 222
        date_str = (now_local() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        # Пользователь 1 создает запись
        await booking_service.create_booking(date_str, "10:00", user1_id, "user1")
        bookings = await Database.get_user_bookings(user1_id)
        booking_id = bookings[0][0]
        
        # Пользователь 2 пытается перенести чужую запись
        new_date = (now_local() + timedelta(days=2)).strftime("%Y-%m-%d")
        success = await booking_service.reschedule_booking(
            booking_id, date_str, "10:00", new_date, "11:00", user2_id, "user2"
        )
        
        assert success is False
        
        # Запись пользователя 1 должна остаться без изменений
        bookings = await Database.get_user_bookings(user1_id)
        assert len(bookings) == 1
        assert bookings[0][1] == date_str


class TestCancelBooking:
    """Тесты отмены записи"""
    
    @pytest.mark.asyncio
    async def test_cancel_booking_success(self, booking_service, setup_database):
        """Успешная отмена записи"""
        user_id = 12345
        date_str = (now_local() + timedelta(days=1)).strftime("%Y-%m-%d")
        time_str = "10:00"
        
        # Создаем запись
        await booking_service.create_booking(date_str, time_str, user_id, "testuser")
        
        # Отменяем
        success, booking_id = await booking_service.cancel_booking(
            date_str, time_str, user_id
        )
        
        assert success is True
        assert booking_id > 0
        
        # Проверяем что записи больше нет
        bookings = await Database.get_user_bookings(user_id)
        assert len(bookings) == 0
        
        # Слот должен быть свободен
        slot_free = await Database.is_slot_free(date_str, time_str)
        assert slot_free is True
    
    @pytest.mark.asyncio
    async def test_cancel_nonexistent_booking(self, booking_service, setup_database):
        """Попытка отменить несуществующую запись"""
        success, booking_id = await booking_service.cancel_booking(
            "2026-12-31", "10:00", 12345
        )
        
        assert success is False
        assert booking_id == 0


class TestAtomicity:
    """Тесты атомарности операций"""
    
    @pytest.mark.asyncio
    async def test_reschedule_atomicity_uses_update(self, booking_service, setup_database):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: Перенос использует UPDATE вместо DELETE+INSERT"""
        user_id = 12345
        old_date = (now_local() + timedelta(days=1)).strftime("%Y-%m-%d")
        old_time = "10:00"
        new_date = (now_local() + timedelta(days=2)).strftime("%Y-%m-%d")
        new_time = "14:00"
        
        # Создаем запись
        await booking_service.create_booking(old_date, old_time, user_id, "testuser")
        bookings = await Database.get_user_bookings(user_id)
        original_booking_id = bookings[0][0]
        
        # Переносим
        success = await booking_service.reschedule_booking(
            original_booking_id, old_date, old_time, new_date, new_time, user_id, "testuser"
        )
        
        assert success is True
        
        # ✅ КРИТИЧЕСКАЯ ПРОВЕРКА: ID записи НЕ изменился (используется UPDATE)
        bookings = await Database.get_user_bookings(user_id)
        assert len(bookings) == 1
        assert bookings[0][0] == original_booking_id, "ID изменился - используется DELETE+INSERT вместо UPDATE!"
    
    @pytest.mark.asyncio
    async def test_reschedule_rollback_on_error(self, booking_service, setup_database):
        """Тест отката транзакции при ошибке переноса"""
        user_id = 12345
        old_date = (now_local() + timedelta(days=1)).strftime("%Y-%m-%d")
        old_time = "10:00"
        new_date = (now_local() + timedelta(days=2)).strftime("%Y-%m-%d")
        new_time = "14:00"
        
        # Создаем запись
        await booking_service.create_booking(old_date, old_time, user_id, "testuser")
        bookings_before = await Database.get_user_bookings(user_id)
        booking_id = bookings_before[0][0]
        
        # Занимаем целевой слот
        await booking_service.create_booking(new_date, new_time, 67890, "otheruser")
        
        # Пытаемся перенести - должен быть откат
        success = await booking_service.reschedule_booking(
            booking_id, old_date, old_time, new_date, new_time, user_id, "testuser"
        )
        
        assert success is False
        
        # Проверяем что БД в исходном состоянии
        bookings_after = await Database.get_user_bookings(user_id)
        assert len(bookings_after) == 1
        assert bookings_after[0] == bookings_before[0], "Данные изменились после неудачного переноса"


class TestDatabaseMethods:
    """Тесты новых методов Database"""
    
    @pytest.mark.asyncio
    async def test_get_booking_by_id(self, setup_database):
        """Тест получения записи по ID"""
        user_id = 12345
        date_str = (now_local() + timedelta(days=1)).strftime("%Y-%m-%d")
        time_str = "10:00"
        
        # Создаем запись напрямую через БД
        import aiosqlite
        from config import DATABASE_PATH
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                "INSERT INTO bookings (date, time, user_id, username, created_at) VALUES (?, ?, ?, ?, ?)",
                (date_str, time_str, user_id, "testuser", now_local().isoformat())
            )
            booking_id = cursor.lastrowid
            await db.commit()
        
        # Получаем через новый метод
        result = await Database.get_booking_by_id(booking_id, user_id)
        
        assert result is not None
        assert result[0] == date_str
        assert result[1] == time_str
    
    @pytest.mark.asyncio
    async def test_get_booking_by_id_wrong_user(self, setup_database):
        """Тест получения чужой записи по ID"""
        import aiosqlite
        from config import DATABASE_PATH
        
        date_str = (now_local() + timedelta(days=1)).strftime("%Y-%m-%d")
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                "INSERT INTO bookings (date, time, user_id, username, created_at) VALUES (?, ?, ?, ?, ?)",
                (date_str, "10:00", 111, "user1", now_local().isoformat())
            )
            booking_id = cursor.lastrowid
            await db.commit()
        
        # Попытка получить с другим user_id
        result = await Database.get_booking_by_id(booking_id, 222)
        assert result is None
    
    @pytest.mark.asyncio
    async def test_cleanup_old_bookings(self, setup_database):
        """Тест очистки старых записей"""
        # Создаем старую запись
        old_date = (now_local() - timedelta(days=5)).strftime("%Y-%m-%d")
        
        import aiosqlite
        from config import DATABASE_PATH
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                "INSERT INTO bookings (date, time, user_id, username, created_at) VALUES (?, ?, ?, ?, ?)",
                (old_date, "10:00", 12345, "testuser", now_local().isoformat())
            )
            await db.commit()
        
        today = now_local().strftime("%Y-%m-%d")
        deleted_count = await Database.cleanup_old_bookings(today)
        
        assert deleted_count >= 1
    
    @pytest.mark.asyncio
    async def test_get_all_users(self, setup_database):
        """Тест получения всех пользователей"""
        # Добавляем пользователей
        import aiosqlite
        from config import DATABASE_PATH
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("INSERT INTO users (user_id, first_seen) VALUES (?, ?)", (111, now_local().isoformat()))
            await db.execute("INSERT INTO users (user_id, first_seen) VALUES (?, ?)", (222, now_local().isoformat()))
            await db.commit()
        
        users = await Database.get_all_users()
        
        assert len(users) >= 2
        assert 111 in users
        assert 222 in users
    
    @pytest.mark.asyncio
    async def test_get_week_schedule(self, setup_database):
        """Тест получения расписания на неделю"""
        # Создаем несколько записей
        import aiosqlite
        from config import DATABASE_PATH
        
        today = now_local()
        async with aiosqlite.connect(DATABASE_PATH) as db:
            for i in range(3):
                date = (today + timedelta(days=i)).strftime("%Y-%m-%d")
                await db.execute(
                    "INSERT INTO bookings (date, time, user_id, username, created_at) VALUES (?, ?, ?, ?, ?)",
                    (date, f"{10+i}:00", 111, "testuser", today.isoformat())
                )
            await db.commit()
        
        start_date = today.strftime("%Y-%m-%d")
        schedule = await Database.get_week_schedule(start_date, days=7)
        
        assert len(schedule) >= 3
        assert all(len(entry) == 3 for entry in schedule)  # (date, time, username)

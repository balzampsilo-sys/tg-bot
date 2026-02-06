"""Обработчики для администратора"""
import aiosqlite
import csv
import io
from datetime import timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext

from keyboards.admin_keyboards import ADMIN_MENU
from keyboards.user_keyboards import MAIN_MENU
from services.analytics_service import AnalyticsService
from utils.helpers import is_admin, now_local
from utils.states import AdminStates
from config import ADMIN_ID, DATABASE_PATH

router = Router()


@router.message(F.text == "/admin")
async def admin_panel(message: Message):
    """Вход в админ-панель"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        return
    
    await message.answer(
        "🔐 АДМИН-ПАНЕЛЬ\n\nВыберите действие:",
        reply_markup=ADMIN_MENU
    )


@router.message(F.text == "🔙 Выход из админки")
async def exit_admin(message: Message):
    """Выход из админ-панели"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        return
    
    await message.answer(
        "👋 Вы вышли из админ-панели",
        reply_markup=MAIN_MENU
    )


@router.message(F.text == "📊 Dashboard")
async def dashboard(message: Message):
    """Дашборд"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        return
    
    stats = await AnalyticsService.get_dashboard_stats()
    
    await message.answer(
        f"📊 ДАШБОРД\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"📅 Активных записей: {stats['active_bookings']}\n"
        f"❌ Всего отмен: {stats['total_cancelled']}\n"
        f"⭐ Средний рейтинг: {stats['avg_rating']:.1f}/5",
        reply_markup=ADMIN_MENU
    )


@router.message(F.text == "💡 Рекомендации")
async def recommendations(message: Message):
    """AI-рекомендации"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        return
    
    recs = await AnalyticsService.get_recommendations()
    
    if not recs:
        await message.answer(
            "✅ Всё отлично! Рекомендаций нет.",
            reply_markup=ADMIN_MENU
        )
        return
    
    text = "💡 РЕКОМЕНДАЦИИ:\n\n"
    for rec in recs:
        text += f"{rec['icon']} {rec['title']}\n{rec['text']}\n\n"
    
    await message.answer(text, reply_markup=ADMIN_MENU)


@router.message(F.text == "📅 Расписание")
async def schedule_view(message: Message):
    """Просмотр расписания на неделю"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        return
    
    today = now_local()
    
    # Получаем записи на 7 дней вперед
    text = "📅 РАСПИСАНИЕ НА НЕДЕЛЮ\n\n"
    
    async with aiosqlite.connect(DATABASE_PATH) as db:
        for day_offset in range(7):
            current_date = today + timedelta(days=day_offset)
            date_str = current_date.strftime("%Y-%m-%d")
            
            async with db.execute(
                "SELECT time, username FROM bookings WHERE date=? ORDER BY time",
                (date_str,)
            ) as cursor:
                bookings = await cursor.fetchall()
            
            if bookings:
                day_name = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'][current_date.weekday()]
                text += f"📆 {current_date.strftime('%d.%m')} ({day_name})\n"
                for time_str, username in bookings:
                    text += f"  🕒 {time_str} - @{username}\n"
                text += "\n"
    
    if len(text.split("\n")) == 3:  # только заголовок
        text += "📭 Нет записей на ближайшую неделю"
    
    await message.answer(text, reply_markup=ADMIN_MENU)


@router.message(F.text == "👥 Клиенты")
async def clients_list(message: Message):
    """Список активных клиентов"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        return
    
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Топ-10 клиентов по количеству записей
        async with db.execute("""
            SELECT user_id, COUNT(*) as total
            FROM analytics 
            WHERE event='booking_created'
            GROUP BY user_id
            ORDER BY total DESC
            LIMIT 10
        """) as cursor:
            top_clients = await cursor.fetchall()
        
        # Общее количество
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            total_users = (await cursor.fetchone())[0]
    
    text = f"👥 КЛИЕНТЫ\n\n"
    text += f"Всего пользователей: {total_users}\n\n"
    
    if top_clients:
        text += "🏆 ТОП-10 по записям:\n\n"
        for i, (user_id, total) in enumerate(top_clients, 1):
            text += f"{i}. ID {user_id}: {total} записей\n"
    else:
        text += "Пока нет записей"
    
    await message.answer(text, reply_markup=ADMIN_MENU)


@router.message(F.text == "⚡ Массовые операции")
async def mass_operations(message: Message):
    """Меню массовых операций"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Рассылка всем", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🗑 Очистить старые записи", callback_data="admin_cleanup")],
        [InlineKeyboardButton(text="🔒 Заблокировать слоты", callback_data="admin_block_slots")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
    ])
    
    await message.answer(
        "⚡ МАССОВЫЕ ОПЕРАЦИИ\n\n"
        "⚠️ Будьте осторожны!\n"
        "Выберите действие:",
        reply_markup=kb
    )


@router.message(F.text == "📊 Экспорт данных")
async def export_data(message: Message):
    """Экспорт данных в CSV"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа")
        return
    
    # Экспорт всех записей
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("""
            SELECT id, date, time, user_id, username, created_at 
            FROM bookings 
            ORDER BY date, time
        """) as cursor:
            bookings = await cursor.fetchall()
    
    # Создаем CSV в памяти
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Дата', 'Время', 'User ID', 'Username', 'Создано'])
    
    for booking in bookings:
        writer.writerow(booking)
    
    # Отправляем файл
    csv_data = output.getvalue().encode('utf-8-sig')  # BOM для Excel
    file = BufferedInputFile(csv_data, filename="bookings_export.csv")
    
    await message.answer_document(
        file,
        caption=f"📊 Экспорт записей\n\nВсего записей: {len(bookings)}",
        reply_markup=ADMIN_MENU
    )


# === ОБРАБОТЧИКИ МАССОВЫХ ОПЕРАЦИЙ ===

@router.callback_query(F.data == "admin_broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext):
    """Начало рассылки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.set_state(AdminStates.awaiting_broadcast_message)
    
    await callback.message.edit_text(
        "📢 РАССЫЛКА\n\n"
        "Отправьте текст сообщения для рассылки всем пользователям.\n\n"
        "Для отмены отправьте /cancel"
    )
    await callback.answer()


@router.message(AdminStates.awaiting_broadcast_message)
async def broadcast_execute(message: Message, state: FSMContext):
    """Выполнение рассылки"""
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Рассылка отменена", reply_markup=ADMIN_MENU)
        return
    
    broadcast_text = message.text
    
    # Получаем всех пользователей
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            users = await cursor.fetchall()
    
    await message.answer(f"📤 Начинаю рассылку {len(users)} пользователям...")
    
    success_count = 0
    fail_count = 0
    
    for (user_id,) in users:
        try:
            await message.bot.send_message(user_id, broadcast_text)
            success_count += 1
        except Exception:
            fail_count += 1
    
    await state.clear()
    await message.answer(
        f"✅ Рассылка завершена!\n\n"
        f"Успешно: {success_count}\n"
        f"Ошибок: {fail_count}",
        reply_markup=ADMIN_MENU
    )


@router.callback_query(F.data == "admin_cleanup")
async def cleanup_old_bookings(callback: CallbackQuery):
    """Очистка старых записей"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    today_str = now_local().strftime("%Y-%m-%d")
    
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Удаляем записи старше сегодняшнего дня
        cursor = await db.execute(
            "DELETE FROM bookings WHERE date < ?",
            (today_str,)
        )
        deleted_count = cursor.rowcount
        await db.commit()
    
    await callback.message.edit_text(
        f"✅ Очистка завершена\n\n"
        f"Удалено старых записей: {deleted_count}"
    )
    await callback.answer(f"Удалено: {deleted_count}")


@router.callback_query(F.data == "admin_block_slots")
async def block_slots_info(callback: CallbackQuery):
    """Информация о блокировке слотов"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🔒 БЛОКИРОВКА СЛОТОВ\n\n"
        "Эта функция позволяет заблокировать определенные\n"
        "даты и время для записи.\n\n"
        "💡 В разработке: будет доступна в следующей версии"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_cancel")
async def admin_cancel_operation(callback: CallbackQuery):
    """Отмена админской операции"""
    await callback.message.delete()
    await callback.answer("Отменено")

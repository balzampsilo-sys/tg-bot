"""Обработчики для администратора"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta
import aiosqlite
import csv
import io
import asyncio

from keyboards.admin_keyboards import ADMIN_MENU
from keyboards.user_keyboards import MAIN_MENU
from services.analytics_service import AnalyticsService
from utils.helpers import is_admin, now_local
from config import ADMIN_ID, DATABASE_PATH, DAY_NAMES, BROADCAST_DELAY
from utils.states import BroadcastState

router = Router()


@router.message(F.text == "/admin")
async def admin_panel(message: Message):
    """Вход в админ-панель"""
    if not is_admin(message.from_user.id):
        return
    
    await message.answer(
        "🔐 АДМИН-ПАНЕЛЬ\n\nВыберите действие:",
        reply_markup=ADMIN_MENU
    )


@router.message(F.text == "🔙 Выход из админки")
async def exit_admin(message: Message):
    """Выход из админ-панели"""
    if not is_admin(message.from_user.id):
        return
    
    await message.answer(
        "👋 Вы вышли из админ-панели",
        reply_markup=MAIN_MENU
    )


@router.message(F.text == "📊 Dashboard")
async def dashboard(message: Message):
    """Дашборд"""
    if not is_admin(message.from_user.id):
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


@router.message(F.text == "📅 Расписание")
async def schedule(message: Message):
    """Расписание на неделю"""
    if not is_admin(message.from_user.id):
        return
    
    now = now_local()
    text = "📅 РАСПИСАНИЕ НА 7 ДНЕЙ:\n\n"
    
    async with aiosqlite.connect(DATABASE_PATH) as db:
        for day_offset in range(7):
            check_date = now + timedelta(days=day_offset)
            date_str = check_date.strftime("%Y-%m-%d")
            day_name = DAY_NAMES[check_date.weekday()]
            
            async with db.execute(
                """SELECT time, username FROM bookings 
                WHERE date=? ORDER BY time""",
                (date_str,)
            ) as cursor:
                bookings = await cursor.fetchall()
            
            if bookings:
                text += f"📆 {check_date.strftime('%d.%m')} ({day_name}):\n"
                for time_slot, username in bookings:
                    text += f"  🕒 {time_slot} - @{username}\n"
                text += "\n"
    
    if text == "📅 РАСПИСАНИЕ НА 7 ДНЕЙ:\n\n":
        text += "Записей нет"
    
    await message.answer(text, reply_markup=ADMIN_MENU)


@router.message(F.text == "👥 Клиенты")
async def clients(message: Message):
    """Статистика по клиентам"""
    if not is_admin(message.from_user.id):
        return
    
    text = "👥 ТОП-10 КЛИЕНТОВ:\n\n"
    
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            """SELECT u.username, COUNT(b.id) as booking_count, 
            AVG(CASE WHEN f.rating IS NOT NULL THEN f.rating ELSE 0 END) as avg_rating
            FROM users u
            LEFT JOIN bookings b ON u.user_id = b.user_id
            LEFT JOIN feedback f ON b.id = f.booking_id
            GROUP BY u.user_id
            HAVING booking_count > 0
            ORDER BY booking_count DESC
            LIMIT 10"""
        ) as cursor:
            clients_data = await cursor.fetchall()
    
    if not clients_data:
        text += "Нет данных"
    else:
        for idx, (username, count, rating) in enumerate(clients_data, 1):
            rating_str = f"{rating:.1f}⭐" if rating > 0 else "нет отзывов"
            text += f"{idx}. @{username} - {count} записей ({rating_str})\n"
    
    await message.answer(text, reply_markup=ADMIN_MENU)


@router.message(F.text == "⚡ Массовые операции")
async def mass_operations(message: Message):
    """Массовые операции"""
    if not is_admin(message.from_user.id):
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Рассылка всем", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="🗑️ Очистить старые записи", callback_data="admin:cleanup")],
    ])
    
    await message.answer(
        "⚡ МАССОВЫЕ ОПЕРАЦИИ\n\nВыберите действие:",
        reply_markup=kb
    )


@router.callback_query(F.data == "admin:broadcast")
async def start_broadcast(callback: CallbackQuery, state: FSMContext):
    """Начало рассылки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    await callback.message.edit_text(
        "📢 РАССЫЛКА\n\n"
        "Отправьте текст сообщения для рассылки всем пользователям.\n"
        "Используйте /cancel для отмены."
    )
    await state.set_state(BroadcastState.waiting_message)
    await callback.answer()


@router.message(BroadcastState.waiting_message)
async def process_broadcast(message: Message, state: FSMContext):
    """Обработка рассылки"""
    if not is_admin(message.from_user.id):
        return
    
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Рассылка отменена", reply_markup=ADMIN_MENU)
        return
    
    broadcast_text = message.text
    
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            users = await cursor.fetchall()
    
    success = 0
    failed = 0
    
    for (user_id,) in users:
        try:
            await message.bot.send_message(user_id, broadcast_text)
            success += 1
            await asyncio.sleep(BROADCAST_DELAY)
        except Exception:
            failed += 1
    
    await state.clear()
    await message.answer(
        f"✅ Рассылка завершена!\n\n"
        f"✅ Успешно: {success}\n"
        f"❌ Ошибок: {failed}",
        reply_markup=ADMIN_MENU
    )


@router.callback_query(F.data == "admin:cleanup")
async def cleanup_old_bookings(callback: CallbackQuery):
    """Очистка старых записей"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа")
        return
    
    yesterday = (now_local() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM bookings WHERE date < ?", (yesterday,)
        ) as cursor:
            count = (await cursor.fetchone())[0]
        
        await db.execute("DELETE FROM bookings WHERE date < ?", (yesterday,))
        await db.commit()
    
    await callback.message.edit_text(
        f"✅ Удалено старых записей: {count}"
    )
    await callback.answer()


@router.message(F.text == "📊 Экспорт данных")
async def export_data(message: Message):
    """Экспорт данных в CSV"""
    if not is_admin(message.from_user.id):
        return
    
    # Экспорт записей
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            """SELECT b.id, b.date, b.time, b.user_id, b.username, 
            b.created_at, f.rating, f.comment
            FROM bookings b
            LEFT JOIN feedback f ON b.id = f.booking_id
            ORDER BY b.date DESC, b.time DESC"""
        ) as cursor:
            bookings = await cursor.fetchall()
    
    # Создание CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Дата', 'Время', 'User ID', 'Username', 'Создано', 'Рейтинг', 'Комментарий'])
    
    for booking in bookings:
        writer.writerow(booking)
    
    csv_data = output.getvalue().encode('utf-8-sig')
    output.close()
    
    file = BufferedInputFile(csv_data, filename=f"bookings_{now_local().strftime('%Y%m%d')}.csv")
    
    await message.answer_document(
        file,
        caption="📊 Экспорт данных о записях"
    )


@router.message(F.text == "💡 Рекомендации")
async def recommendations(message: Message):
    """AI-рекомендации"""
    if not is_admin(message.from_user.id):
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

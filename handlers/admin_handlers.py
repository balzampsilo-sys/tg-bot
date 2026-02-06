"""Обработчики для администратора (базовый функционал)"""
from aiogram import Router, F
from aiogram.types import Message

from keyboards.admin_keyboards import ADMIN_MENU
from keyboards.user_keyboards import MAIN_MENU
from services.analytics_service import AnalyticsService
from utils.helpers import is_admin
from config import ADMIN_ID

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

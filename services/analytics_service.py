"""Сервис аналитики"""
from datetime import datetime, timedelta
import aiosqlite
from typing import List, Dict

from config import DATABASE_PATH
from utils.helpers import now_local


class AnalyticsService:
    """Сервис для работы с аналитикой"""
    
    @staticmethod
    async def get_dashboard_stats() -> Dict:
        """Статистика для дашборда (ИСПРАВЛЕНО)"""
        today_str = now_local().strftime("%Y-%m-%d")
        
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Общая статистика
            async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                total_users = (await cursor.fetchone())[0]
            
            # ИСПРАВЛЕНИЕ: считаем только будущие записи
            async with db.execute(
                "SELECT COUNT(*) FROM bookings WHERE date >= ?",
                (today_str,)
            ) as cursor:
                active_bookings = (await cursor.fetchone())[0]
            
            async with db.execute(
                "SELECT COUNT(*) FROM analytics WHERE event='booking_cancelled'"
            ) as cursor:
                total_cancelled = (await cursor.fetchone())[0]
            
            async with db.execute("SELECT AVG(rating) FROM feedback") as cursor:
                result = await cursor.fetchone()
                avg_rating = result[0] if result and result[0] else 0.0
        
        return {
            'total_users': total_users,
            'active_bookings': active_bookings,
            'total_cancelled': total_cancelled,
            'avg_rating': avg_rating
        }
    
    @staticmethod
    async def get_recommendations() -> List[Dict]:
        """AI-рекомендации для админа"""
        recommendations = []
        now = now_local()
        today_str = now.strftime("%Y-%m-%d")
        
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Проверка загрузки на сегодня
            async with db.execute(
                "SELECT COUNT(*) FROM bookings WHERE date=?", (today_str,)
            ) as cursor:
                today_count = (await cursor.fetchone())[0]
            
            if today_count < 5:
                recommendations.append({
                    'icon': '⚠️',
                    'title': 'Низкая загрузка сегодня',
                    'text': f'Только {today_count} записей. Рассмотрите промо-акцию.'
                })
            
            # Проверка отмен
            week_ago = (now - timedelta(days=7)).isoformat()
            async with db.execute(
                "SELECT COUNT(*) FROM analytics WHERE event='booking_cancelled' AND timestamp > ?",
                (week_ago,)
            ) as cursor:
                weekly_cancels = (await cursor.fetchone())[0]
            
            if weekly_cancels > 10:
                recommendations.append({
                    'icon': '📉',
                    'title': 'Много отмен за неделю',
                    'text': f'{weekly_cancels} отмен. Проверьте качество обслуживания.'
                })
        
        return recommendations

"""Клавиатуры для пользователей"""
import calendar
from datetime import datetime, timedelta
from aiogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton,
    InlineKeyboardMarkup, 
    InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext

from config import MONTH_NAMES, DAY_NAMES_SHORT, WORK_HOURS_START, WORK_HOURS_END
from database.queries import Database
from utils.helpers import now_local


# Главное меню
MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📅 Записаться")],
        [KeyboardButton(text="📋 Мои записи"), KeyboardButton(text="ℹ️ О сервисе")]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)


async def create_month_calendar(year: int, month: int) -> InlineKeyboardMarkup:
    """Календарь с навигацией по месяцам"""
    keyboard = []
    
    # Навигация
    prev_month = month - 1
    prev_year = year
    if prev_month < 1:
        prev_month = 12
        prev_year -= 1
    
    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1
    
    keyboard.append([
        InlineKeyboardButton(text="◀️", callback_data=f"cal:{prev_year}-{prev_month:02d}"),
        InlineKeyboardButton(text=f"{MONTH_NAMES[month-1]} {year}", callback_data="ignore"),
        InlineKeyboardButton(text="▶️", callback_data=f"cal:{next_year}-{next_month:02d}")
    ])
    
    # Дни недели
    keyboard.append([
        InlineKeyboardButton(text=day, callback_data="ignore")
        for day in DAY_NAMES_SHORT
    ])
    
    # Дни месяца
    cal = calendar.monthcalendar(year, month)
    today = now_local().date()
    
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
            else:
                date = datetime(year, month, day).date()
                date_str = date.strftime("%Y-%m-%d")
                
                if date < today:
                    row.append(InlineKeyboardButton(text="⚫", callback_data="ignore"))
                else:
                    status = await Database.get_day_status(date_str)
                    row.append(InlineKeyboardButton(
                        text=f"{day}{status}",
                        callback_data=f"day:{date_str}"
                    ))
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="back_calendar")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def create_time_slots(
    date_str: str, 
    state: FSMContext = None
) -> tuple[str, InlineKeyboardMarkup]:
    """Слоты времени"""
    keyboard = []
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    now = now_local()
    
    # Оптимизация: получаем все занятые слоты одним запросом
    occupied_slots = await Database.get_occupied_slots_for_day(date_str)
    
    free_count = 0
    total_slots = 0
    
    for hour in range(WORK_HOURS_START, WORK_HOURS_END):
        time_str = f"{hour:02d}:00"
        slot_datetime = datetime.combine(
            date_obj.date(), 
            datetime.strptime(time_str, "%H:%M").time()
        )
        slot_datetime = slot_datetime.replace(tzinfo=now.tzinfo)
        
        if slot_datetime < now:
            continue
        
        total_slots += 1
        is_free = time_str not in occupied_slots
        
        if is_free:
            free_count += 1
        
        button_text = time_str if is_free else f"❌ {time_str}"
        
        if not keyboard or len(keyboard[-1]) == 3:
            keyboard.append([])
        
        # Проверяем контекст переноса
        data = await state.get_data() if state else {}
        is_rescheduling = data.get('reschedule_booking_id') is not None
        
        if is_free:
            callback_data = f"reschedule_time:{date_str}:{time_str}" if is_rescheduling else f"time:{date_str}:{time_str}"
        else:
            callback_data = "ignore"
        
        keyboard[-1].append(InlineKeyboardButton(text=button_text, callback_data=callback_data))
    
    if free_count == 0 and keyboard:
        keyboard = [[InlineKeyboardButton(
            text="😞 Все слоты на эту дату заняты",
            callback_data="ignore"
        )]]
    
    keyboard.append([InlineKeyboardButton(text="🔙 К календарю", callback_data="back_calendar")])
    
    # Формируем текст
    from config import DAY_NAMES
    day_name = DAY_NAMES[date_obj.weekday()]
    
    text = (
        f"📍 ШАГ 2 из 3: Выберите время\n\n"
        f"📅 {date_obj.strftime('%d.%m.%Y')} ({day_name})\n"
        f"🟢 Свободно: {free_count}/{total_slots} слотов\n"
    )
    
    if free_count <= 3 and free_count > 0:
        text += "⚠️ Мало мест — записывайтесь скорее!\n"
    
    text += "\n✅ = свободно | ❌ = занято"
    
    return text, InlineKeyboardMarkup(inline_keyboard=keyboard)


def create_onboarding_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для онбординга"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎓 Как это работает?", callback_data="onboarding_tour")],
        [InlineKeyboardButton(text="🚀 Записаться сразу", callback_data="skip_onboarding")]
    ])


def create_confirmation_keyboard(date_str: str, time_str: str) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения записи"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить запись", callback_data=f"confirm:{date_str}:{time_str}")],
        [InlineKeyboardButton(text="📅 Изменить дату", callback_data="back_calendar")],
        [InlineKeyboardButton(text="◀️ Другое время", callback_data=f"day:{date_str}")],
        [InlineKeyboardButton(text="❌ Отменить запись", callback_data="cancel_booking_flow")]
    ])


def create_cancel_confirmation_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения отмены"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отменить", callback_data=f"cancel_confirm:{booking_id}")],
        [InlineKeyboardButton(text="❌ Нет, оставить", callback_data="cancel_decline")]
    ])

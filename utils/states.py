"""FSM состояния"""
from aiogram.fsm.state import State, StatesGroup


class RescheduleStates(StatesGroup):
    """Состояния для переноса записи"""
    selecting_date = State()
    selecting_time = State()
    confirming = State()


class AdminStates(StatesGroup):
    """Состояния для админ-панели"""
    awaiting_message = State()
    awaiting_booking_data = State()
    awaiting_broadcast_message = State()

import asyncio
import sqlite3
import calendar
import logging
import os
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import Optional, Dict, List, Any

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ---------- НАСТРОЙКИ ----------
# ТОКЕН загружается из переменных окружения для безопасности
TOKEN = os.getenv("BOT_TOKEN", "8630017788:AAFvwsh7g_x-mm8we18izvEsYXxwwwrXBCI")
ADMIN_IDS = [995387118, 1455416795]

# Проверка токена
if TOKEN == "8630017788:AAFvwsh7g_x-mm8we18izvEsYXxwwwrXBCI":
    logger.warning("⚠️ ВНИМАНИЕ: Используется токен по умолчанию! Установите переменную окружения BOT_TOKEN")

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ---------- БАЗА ДАННЫХ ----------
DB_PATH = "lash_bookings.db"

@contextmanager
def get_db_connection():
    """Контекстный менеджер для безопасной работы с БД"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Ошибка БД: {e}")
        raise
    finally:
        conn.close()

def init_database():
    """Инициализация таблиц БД"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            username TEXT,
            phone TEXT,
            service TEXT,
            service_ids TEXT,
            date TEXT,
            time TEXT,
            duration INTEGER DEFAULT 180,
            total_price INTEGER DEFAULT 0
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS blocked_slots(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            time TEXT,
            reason TEXT
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS services(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            price INTEGER,
            duration INTEGER DEFAULT 180,
            description TEXT DEFAULT ''
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS blocked_users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            name TEXT,
            username TEXT,
            phone TEXT,
            reason TEXT,
            blocked_at TEXT
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS prepayments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER,
            user_id INTEGER,
            photo_file_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            FOREIGN KEY (booking_id) REFERENCES bookings(id)
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS payment_details(
            id INTEGER PRIMARY KEY,
            phone TEXT DEFAULT '',
            recipient TEXT DEFAULT '',
            bank TEXT DEFAULT ''
        )
        """)
        cursor.execute(
            "INSERT OR IGNORE INTO payment_details(id, phone, recipient, bank) VALUES (1, '+7 XXX XXX XX XX', 'ФИО получателя', 'Название банка')"
        )
        logger.info("База данных инициализирована")

# Запуск инициализации при старте
init_database()
# ---------- СОСТОЯНИЯ ----------
class Booking(StatesGroup):
    service = State()
    date = State()
    time = State()
    username = State()
    phone = State()
    prepayment = State()
    confirm = State()

class AdminEdit(StatesGroup):
    edit_name = State()
    edit_phone = State()

class AdminBlock(StatesGroup):
    enter_reason = State()

class AdminService(StatesGroup):
    add_name = State()
    add_price = State()
    add_duration = State()
    add_desc = State()
    edit_name = State()
    edit_price = State()
    edit_duration = State()
    edit_desc = State()

class AdminBlockUser(StatesGroup):
    enter_reason = State()

class AdminPaymentDetails(StatesGroup):
    edit_phone = State()
    edit_recipient = State()
    edit_bank = State()

# ---------- УСЛУГИ ----------
def get_services() -> Dict[str, Dict[str, Any]]:
    """Получение списка услуг из БД"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, price, duration, description FROM services ORDER BY id")
        rows = cursor.fetchall()
        return {
            str(r["id"]): {
                "name": r["name"],
                "price": r["price"],
                "duration": r["duration"] if r["duration"] else 180,
                "description": r["description"] if r["description"] else ""
            }
            for r in rows
        }

def format_duration(minutes: int) -> str:
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0 and mins > 0:
        return f"{hours}ч {mins}мин"
    elif hours > 0:
        return f"{hours}ч"
    else:
        return f"{mins}мин"

TIME_SLOTS = ["10:00", "13:00", "16:00", "18:00"]

# ---------- КЛАВИАТУРЫ ----------
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📅 Записаться"),
                KeyboardButton(text="📋 Мои записи")
            ],
            [
                KeyboardButton(text="💰 Прайс"),
                KeyboardButton(text="❓ Помощь")
            ]
        ],
        resize_keyboard=True
    )

def phone_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Поделиться номером", request_contact=True)],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def services_keyboard(selected=None):
    SERVICES = get_services()
    buttons = []
    selected = selected or []
    for k, v in SERVICES.items():
        duration = f" ({format_duration(v['duration'])})" if v.get('duration') else ""
        check = "✅ " if k in selected else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"{check}{v['name']} — {v['price']}₽{duration}",
                callback_data=f"toggle_service_{k}"
            )
        ])
    if selected:
        total_price = sum(SERVICES[k]['price'] for k in selected)
        total_duration = sum(SERVICES[k]['duration'] for k in selected)
        buttons.append([
            InlineKeyboardButton(
                text=f"✅ Выбрано ({len(selected)}) | {total_price}₽ | {format_duration(total_duration)}",
                callback_data="services_confirm"
            )
        ])
    else:
        buttons.append([InlineKeyboardButton(text="Выберите услуги", callback_data="ignore")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def prepayment_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Реквизиты для оплаты", callback_data="show_payment_details")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_booking")],
        ]
    )

def admin_prepayment_keyboard(prepayment_id, booking_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить оплату", callback_data=f"approve_prepayment_{prepayment_id}_{booking_id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_prepayment_{prepayment_id}_{booking_id}")],
            [InlineKeyboardButton(text="🗑 Удалить запись", callback_data=f"admin_delete_{booking_id}")]
        ]
    )

def dates_keyboard(half="first"):
    """Генерация клавиатуры с датами (исправлено: корректная работа с календарем и второй половиной месяца)"""
    buttons = []
    today = datetime.now()
    
    # Получаем количество дней в текущем месяце через calendar.monthrange
    _, days_in_month = calendar.monthrange(today.year, today.month)
    
    if half == "first":
        # Первая половина: от current_day+2 до 15 числа (или до конца месяца если меньше 15)
        start_offset = 2
        end_day_num = min(15, days_in_month)
    else:
        # Вторая половина: от 16 числа до конца месяца
        start_offset = max(0, 16 - today.day)
        end_day_num = days_in_month
    
    row = []
    for i in range(start_offset, 14 + start_offset):  # Показываем до 14 дней
        date = today + timedelta(days=i)
        
        # Проверка: не вышли ли за пределы месяца
        if date.month != today.month or date.day > days_in_month:
            break
            
        # Фильтрация по половинам месяца
        if half == "first" and date.day > 15:
            break  # Конец первой половины
        if half == "second" and date.day < 16:
            continue  # Пропускаем дни до 16
        
        day_number = date.strftime("%d")
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        day_name = day_names[date.weekday()]
        date_str = date.strftime("%d.%m.%Y")
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM bookings WHERE date=?", (date_str,))
            bookings_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM blocked_slots WHERE date=?", (date_str,))
            blocked_count = cursor.fetchone()[0]
        
        available = len(TIME_SLOTS) - bookings_count - blocked_count
        if available > 0:
            row.append(InlineKeyboardButton(text=f"{day_number} ({day_name})", callback_data=f"date_{date_str}"))
        
        if len(row) == 4:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    # Навигация между половинами месяца
    nav_row = []
    if half == "first" and days_in_month > 15:
        nav_row.append(InlineKeyboardButton(text="📅 16-31 >>", callback_data="dates_second_half"))
    elif half == "second":
        nav_row.append(InlineKeyboardButton(text="<< 1-15", callback_data="dates_first_half"))
    
    if nav_row:
        buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_service")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def time_keyboard(date):
    """Генерация клавиатуры времени с использованием безопасного подключения к БД"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT time FROM bookings WHERE date=?", (date,))
        busy = [x[0] for x in cursor.fetchall()]
        cursor.execute("SELECT time FROM blocked_slots WHERE date=?", (date,))
        blocked = [x[0] for x in cursor.fetchall()]
    
    is_day_blocked = len(blocked) >= len(TIME_SLOTS)
    buttons = []
    row = []
    for t in TIME_SLOTS:
        if is_day_blocked or t in blocked:
            text, callback = f"🚫 {t}", "blocked_slot"
        elif t in busy:
            text, callback = f"❌ {t}", "busy"
        else:
            text, callback = f"⏰ {t}", f"time_{t}"
        row.append(InlineKeyboardButton(text=text, callback_data=callback))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_date")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def my_booking_keyboard(booking_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 Изменить дату/время", callback_data=f"reschedule_{booking_id}")],
            [InlineKeyboardButton(text="❌ Удалить", callback_data=f"delete_{booking_id}")]
        ]
    )

# ---------- АДМИН-КЛАВИАТУРЫ ----------
def admin_main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 Записи по дням", callback_data="admin_by_date")],
            [InlineKeyboardButton(text="📋 Все записи", callback_data="admin_all")],
            [InlineKeyboardButton(text="👥 Клиенты", callback_data="admin_users")],
            [InlineKeyboardButton(text="💅 Управление услугами", callback_data="admin_services")],
            [InlineKeyboardButton(text="💳 Реквизиты оплаты", callback_data="admin_payment_details")],
            [InlineKeyboardButton(text="🚫 Заблокировать слот", callback_data="admin_block")],
            [InlineKeyboardButton(text="✅ Разблокировать слоты", callback_data="admin_unblock")]
        ]
    )

def admin_services_keyboard():
    SERVICES = get_services()
    buttons = []
    for k, v in SERVICES.items():
        duration = format_duration(v.get('duration', 180))
        buttons.append([
            InlineKeyboardButton(
                text=f"{v['name']} — {v['price']}₽ ({duration})",
                callback_data=f"service_manage_{k}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="➕ Добавить услугу", callback_data="service_add")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_service_manage_keyboard(service_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить название", callback_data=f"service_edit_name_{service_id}")],
            [InlineKeyboardButton(text="💰 Изменить цену", callback_data=f"service_edit_price_{service_id}")],
            [InlineKeyboardButton(text="⏱ Изменить время", callback_data=f"service_edit_duration_{service_id}")],
            [InlineKeyboardButton(text="📝 Изменить описание", callback_data=f"service_edit_desc_{service_id}")],
            [InlineKeyboardButton(text="🗑 Удалить услугу", callback_data=f"service_delete_{service_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_services")]
        ]
    )

def admin_service_delete_keyboard(service_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"service_delete_confirm_{service_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_services")]
        ]
    )

def admin_dates_keyboard():
    buttons = []
    row = []
    for i in range(2, 9):
        date = datetime.now() + timedelta(days=i)
        date_str = date.strftime("%d.%m.%Y")
        cursor.execute("SELECT COUNT(*) FROM bookings WHERE date=?", (date_str,))
        bookings_count = cursor.fetchone()[0]
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        day_name = day_names[date.weekday()]
        count_text = f" ({bookings_count})" if bookings_count > 0 else ""
        row.append(
            InlineKeyboardButton(
                text=f"{date.day} ({day_name}){count_text}",
                callback_data=f"admin_date_{date_str}"
            )
        )
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_booking_keyboard(booking_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Имя", callback_data=f"edit_name_{booking_id}")],
            [InlineKeyboardButton(text="📱 Телефон", callback_data=f"edit_phone_{booking_id}")],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin_delete_{booking_id}")],
            [InlineKeyboardButton(text="⬅️ К дням", callback_data="admin_by_date")]
        ]
    )

def admin_payment_keyboard():
    cursor.execute("SELECT phone, recipient, bank FROM payment_details WHERE id=1")
    row = cursor.fetchone()
    phone = row[0] if row else "Не указан"
    recipient = row[1] if row else "Не указан"
    bank = row[2] if row else "Не указан"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📱 Телефон", callback_data="edit_payment_phone")],
            [InlineKeyboardButton(text="👤 Получатель", callback_data="edit_payment_recipient")],
            [InlineKeyboardButton(text="🏦 Банк", callback_data="edit_payment_bank")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]
        ]
    )

def admin_users_keyboard():
    cursor.execute("SELECT DISTINCT user_id, name, username, phone FROM bookings ORDER BY id DESC")
    rows = cursor.fetchall()
    if not rows:
        return None
    buttons = []
    for user_id, name, username, phone in rows:
        cursor.execute("SELECT id FROM blocked_users WHERE user_id=?", (user_id,))
        is_blocked = cursor.fetchone()
        prefix = "🚫 " if is_blocked else ""
        display_name = name or username or f"ID:{user_id}"
        buttons.append([
            InlineKeyboardButton(
                text=f"{prefix}{display_name}",
                callback_data=f"admin_user_{user_id}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="📋 Заблокированные", callback_data="admin_blocked_users")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_user_keyboard(user_id):
    cursor.execute("SELECT id FROM blocked_users WHERE user_id=?", (user_id,))
    is_blocked = cursor.fetchone()
    buttons = []
    if is_blocked:
        buttons.append([InlineKeyboardButton(text="✅ Разблокировать", callback_data=f"unblock_user_{user_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"block_user_{user_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_users")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_blocked_users_keyboard():
    cursor.execute("SELECT user_id, name, reason FROM blocked_users ORDER BY id DESC")
    rows = cursor.fetchall()
    if not rows:
        return None
    buttons = []
    for user_id, name, reason in rows:
        display_reason = f" ({reason[:15]}...)" if reason and len(reason) > 15 else f" ({reason})" if reason else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"🚫 {name}{display_reason}",
                callback_data=f"unblock_user_{user_id}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_users")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_block_dates_keyboard(half="first"):
    """Генерация клавиатуры для блокировки дат (исправлено: корректная работа с календарем)"""
    buttons = []
    today = datetime.now()
    
    # Получаем количество дней в текущем месяце через calendar.monthrange
    _, days_in_month = calendar.monthrange(today.year, today.month)
    
    if half == "first":
        start_offset = 2
    else:
        start_offset = max(0, 16 - today.day)
    
    row = []
    for i in range(start_offset, 14 + start_offset):
        date = today + timedelta(days=i)
        
        # Проверка: не вышли ли за пределы месяца
        if date.month != today.month or date.day > days_in_month:
            break
        
        # Фильтрация по половинам месяца
        if half == "first" and date.day > 15:
            break
        if half == "second" and date.day < 16:
            continue
        
        date_str = date.strftime("%d.%m.%Y")
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM blocked_slots WHERE date=?", (date_str,))
            blocked_count = cursor.fetchone()[0]
        
        is_blocked = blocked_count >= len(TIME_SLOTS)
        prefix = "🚫 " if is_blocked else ""
        row.append(
            InlineKeyboardButton(
                text=f"{prefix}{date.day}",
                callback_data=f"block_date_{date_str}"
            )
        )
        if len(row) == 4:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    nav_row = []
    if half == "first" and days_in_month > 15:
        nav_row.append(InlineKeyboardButton(text="📅 16-31 >>", callback_data="block_second_half"))
    elif half == "second":
        nav_row.append(InlineKeyboardButton(text="<< 1-15", callback_data="block_first_half"))
    
    if nav_row:
        buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_block_times_keyboard(date):
    cursor.execute("SELECT time FROM bookings WHERE date=?", (date,))
    busy = [x[0] for x in cursor.fetchall()]
    cursor.execute("SELECT time FROM blocked_slots WHERE date=?", (date,))
    blocked = [x[0] for x in cursor.fetchall()]
    is_day_blocked = len(blocked) >= len(TIME_SLOTS)
    buttons = []
    row = []
    for t in TIME_SLOTS:
        if is_day_blocked or t in blocked:
            text, callback = f"🚫 {t}", "ignore"
        elif t in busy:
            text, callback = f"👤 {t}", "ignore"
        else:
            text, callback = f"⏰ {t}", f"block_time_{t}_{date}"
        row.append(InlineKeyboardButton(text=text, callback_data=callback))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    if is_day_blocked:
        buttons.append([InlineKeyboardButton(text="✅ Разблокировать весь день", callback_data=f"unblock_day_{date}")])
    else:
        buttons.append([InlineKeyboardButton(text="🚫 Заблокировать весь день", callback_data=f"block_all_{date}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_block")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_unblock_keyboard():
    cursor.execute("SELECT DISTINCT date FROM blocked_slots ORDER BY date")
    rows = cursor.fetchall()
    if not rows:
        return None
    buttons = []
    for (date,) in rows:
        cursor.execute("SELECT COUNT(*) FROM blocked_slots WHERE date=?", (date,))
        count = cursor.fetchone()[0]
        if count >= len(TIME_SLOTS):
            buttons.append([
                InlineKeyboardButton(
                    text=f"🚫 {date} (весь день)",
                    callback_data=f"unblock_day_{date}"
                )
            ])
        else:
            cursor.execute("SELECT time, reason FROM blocked_slots WHERE date=?", (date,))
            for time, reason in cursor.fetchall():
                display_reason = reason[:15] + "..." if len(reason) > 15 else reason
                buttons.append([
                    InlineKeyboardButton(
                        text=f"🔓 {date} {time} ({display_reason})",
                        callback_data=f"unblock_{date}_{time}"
                    )
                ])
    buttons.append([InlineKeyboardButton(text="🔓 Разблокировать всё", callback_data="unblock_all")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ---------- START ----------
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "✨ Добро пожаловать в Wenty.Lash ✨\n\n"
        "Профессиональное наращивание ресниц\n"
        "🕐 Рабочее время: 10:00 - 21:00\n"
        "⏱ Длительность сеанса: 3 часа",
        reply_markup=main_menu()
    )

# ---------- ПРАЙС ----------
@dp.message(F.text == "💰 Прайс")
async def price(message: types.Message):
    SERVICES = get_services()
    if not SERVICES:
        await message.answer("Услуг пока нет. Обратитесь к администратору.")
        return
    text = "💰 Прайс:\n\n"
    for v in SERVICES.values():
        duration = f"\n⏱ Время: {format_duration(v['duration'])}" if v.get('duration') else ""
        text += f"{v['name']} — {v['price']}₽{duration}\n\n"
    await message.answer(text)

# ---------- ПОДМЩЬ ----------
@dp.message(F.text == "❓ Помощь")
async def help_menu(message: types.Message):
    text = (
        "🆘 <b>Центр поддержки Wenty.Lash</b>\n\n"
        "Если у вас возник вопрос, выберите подходящий вариант ниже:\n\n"
        "🔧 <b>Технические проблемы с ботом</b>\n"
        "— ошибки, зависания, некорректная работа\n"
        "— вопросы по функционалу\n"
        "Пишите сюда: https://t.me/n_zakirov\n\n"
        "👑 <b>Организационные вопросы</b>\n"
        "— запись на услуги\n"
        "— предоплата и реквизиты\n"
        "— перенос или отмена записи\n"
        "— консультации по процедурам\n"
        "Связаться с администратором: @lolitet\n\n"
        "🤍 Спасибо, что выбираете <b>Wenty.Lash</b>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚨 Поддержка бота", url="https://t.me/n_zakirov")],
            [InlineKeyboardButton(text="👑 Главный администратор", url="https://t.me/lolitet")],
            [InlineKeyboardButton(text="🤖 Хочу такого же бота", url="https://t.me/RequestForABot")]
        ]
    )
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

# ---------- ЗАПИСЬ ----------
@dp.message(F.text == "📅 Записаться")
async def booking_start(message: types.Message, state: FSMContext):
    cursor.execute("SELECT id FROM blocked_users WHERE user_id=?", (message.from_user.id,))
    if cursor.fetchone():
        await message.answer("❌ К сожалению, вы не можете записаться. Свяжитесь с администратором.")
        return

    SERVICES = get_services()
    if not SERVICES:
        await message.answer("❌ Услуг пока нет. Обратитесь к администратору.")
        return
    await state.update_data(selected_services=[])
    await message.answer("Выберите услуги (можно несколько):", reply_markup=services_keyboard())
    await state.set_state(Booking.service)

# ---------- КНОПКИ НАЗАД ----------
@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.answer("Выберите действие:", reply_markup=main_menu())

@dp.callback_query(F.data == "back_to_service")
async def back_to_service(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    selected = data.get("selected_services", [])
    await callback.message.edit_text("Выберите услуги (можно несколько):", reply_markup=services_keyboard(selected))
    await state.set_state(Booking.service)

@dp.callback_query(F.data == "back_to_date")
async def back_to_date(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    today = datetime.now()
    half = "second" if today.day > 15 else "first"
    await callback.message.edit_text("Выберите дату:", reply_markup=dates_keyboard(half))
    await state.set_state(Booking.date)

# ---------- ПЕРЕКЛЮЧЕНИЕ ПОЛОВИН МЕСЯЦА ----------
@dp.callback_query(F.data == "dates_first_half")
async def dates_first_half(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Выберите дату:", reply_markup=dates_keyboard("first"))

@dp.callback_query(F.data == "dates_second_half")
async def dates_second_half(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Выберите дату:", reply_markup=dates_keyboard("second"))

@dp.callback_query(F.data == "block_first_half")
async def block_first_half(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    await callback.message.edit_text("🚫 Выберите день:", reply_markup=admin_block_dates_keyboard("first"))

@dp.callback_query(F.data == "block_second_half")
async def block_second_half(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    await callback.message.edit_text("🚫 Выберите день:", reply_markup=admin_block_dates_keyboard("second"))

# ---------- ВЫБОР УСЛУГ ----------
@dp.callback_query(F.data.startswith("toggle_service_"))
async def toggle_service(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    service_id = callback.data.replace("toggle_service_", "")
    data = await state.get_data()
    selected = data.get("selected_services", [])
    if service_id in selected:
        selected.remove(service_id)
    else:
        selected.append(service_id)
    await state.update_data(selected_services=selected)
    await callback.message.edit_text("Выберите услуги (можно несколько):", reply_markup=services_keyboard(selected))

@dp.callback_query(F.data == "services_confirm")
async def services_confirm(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    selected = data.get("selected_services", [])
    if not selected:
        await callback.answer("Выберите хотя бы одну услугу", show_alert=True)
        return
    SERVICES = get_services()
    service_names = [SERVICES[k]['name'] for k in selected]
    service_text = ", ".join(service_names)
    await state.update_data(service=service_text, service_ids=",".join(selected))
    today = datetime.now()
    half = "second" if today.day > 15 else "first"
    await callback.message.edit_text("Выберите дату:", reply_markup=dates_keyboard(half))
    await state.set_state(Booking.date)

# ---------- ВЫБОР ДАТЫ/ВРЕМЕНИ ----------
@dp.callback_query(F.data.startswith("date_"))
async def select_date(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    date = callback.data.split("_")[1]
    await state.update_data(date=date)
    date_obj = datetime.strptime(date, "%d.%m.%Y")
    day_number = date_obj.strftime("%d")
    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    day_name = day_names[date_obj.weekday()]
    await callback.message.edit_text(
        f"📅 {day_number} ({day_name})\nВыберите время:",
        reply_markup=time_keyboard(date)
    )
    await state.set_state(Booking.time)

@dp.callback_query(F.data.startswith("time_"))
async def select_time(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    time = callback.data.split("_")[1]
    name = callback.from_user.first_name
    username = callback.from_user.username
    await state.update_data(time=time, name=name)
    if username:
        await state.update_data(username=f"@{username}")

    cursor.execute(
        "SELECT phone FROM bookings WHERE user_id=? AND phone != 'Не указан' ORDER BY id DESC LIMIT 1",
        (callback.from_user.id,)
    )
    row = cursor.fetchone()
    if row:
        await state.update_data(phone=row[0])

    data = await state.get_data()
    if data.get("phone"):
        await continue_booking(callback, state)
    else:
        await callback.message.answer(
            f"Имя: {name}\n\nПоделитесь номером телефона:",
            reply_markup=phone_keyboard()
        )
        await state.set_state(Booking.phone)

@dp.callback_query(F.data == "busy")
async def busy(callback: types.CallbackQuery):
    await callback.answer("Это время уже занято", show_alert=True)

@dp.callback_query(F.data == "blocked_slot")
async def blocked_slot(callback: types.CallbackQuery):
    await callback.answer("Этот слот заблокирован", show_alert=True)

@dp.callback_query(F.data == "ignore")
async def ignore_callback(callback: types.CallbackQuery):
    await callback.answer()

# ---------- ТЕЛЕФОН ----------
@dp.message(F.contact)
async def phone(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "Booking:phone":
        return
    phone_number = message.contact.phone_number
    await state.update_data(phone=phone_number)
    await continue_booking(message, state)

async def continue_booking(event, state: FSMContext):
    data = await state.get_data()
    if isinstance(event, types.CallbackQuery):
        msg = event.message
    else:
        msg = event
    try:
        await msg.answer("✅ Номер получен!", reply_markup=ReplyKeyboardRemove())
    except:
        pass

    date_obj = datetime.strptime(data['date'], "%d.%m.%Y")
    day_number = date_obj.strftime("%d")
    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    day_name = day_names[date_obj.weekday()]

    service_ids = data.get("service_ids", "").split(",")
    SERVICES = get_services()
    total_price = sum(SERVICES.get(k, {}).get('price', 0) for k in service_ids if k)
    total_duration = sum(SERVICES.get(k, {}).get('duration', 180) for k in service_ids if k)

    prepayment_amount = 500
    await state.update_data(total_price=total_price, prepayment_amount=prepayment_amount)

    text = (
        f"📋 Предоплата\n\n"
        f"💰 Сумма предоплаты: {prepayment_amount}₽\n\n"
        f"📅 Дата: {day_number} ({day_name})\n"
        f"⏰ Время: {data['time']}\n\n"
        "Для подтверждения записи отправь скриншот о переводе.\n\n"
        "Для просмотра реквизит нажми на кнопку ниже,"
    )
    await msg.answer(text, reply_markup=prepayment_keyboard())
    await state.set_state(Booking.prepayment)

# ---------- ПРЕДОПЛАТА ----------
@dp.callback_query(F.data == "show_payment_details")
async def show_payment_details(callback: types.CallbackQuery):
    await callback.answer()
    cursor.execute("SELECT phone, recipient, bank FROM payment_details WHERE id=1")
    row = cursor.fetchone()
    phone = row[0] if row else "Не указан"
    recipient = row[1] if row else "Не указан"
    bank = row[2] if row else "Не указан"

    text = (
        "💳 Реквизиты для предоплаты:\n\n"
        f"📱 Телефон: {phone}\n"
        f"👤 Получатель: {recipient}\n"
        f"🏦 Банк: {bank}\n\n"
        "После оплаты отправьте скриншот чека."
    )
    await callback.message.answer(text)

@dp.message(Booking.prepayment, F.photo)
async def process_prepayment_screenshot(message: types.Message, state: FSMContext):
    photo_file_id = message.photo[-1].file_id
    data = await state.get_data()

    service_ids = data.get("service_ids", "").split(",")
    SERVICES = get_services()
    total_price = data.get("total_price", 0)
    total_duration = sum(SERVICES.get(k, {}).get('duration', 180) for k in service_ids if k)

    reschedule_id = data.get("reschedule_booking_id")

    if reschedule_id:
        booking_id = reschedule_id
        cursor.execute(
            "UPDATE bookings SET date=?, time=?, duration=?, total_price=? WHERE id=?",
            (data["date"], data["time"], total_duration, total_price, booking_id)
        )
        conn.commit()
    else:
        cursor.execute(
            "INSERT INTO bookings(user_id, name, username, phone, service, service_ids, date, time, duration, total_price) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                message.from_user.id,
                data["name"],
                data.get("username", "Нет"),
                data.get("phone", "Не указан"),
                data["service"],
                data.get("service_ids", ""),
                data["date"],
                data["time"],
                total_duration,
                total_price
            )
        )
        conn.commit()
        booking_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO prepayments(booking_id, user_id, photo_file_id, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (
            booking_id,
            message.from_user.id,
            photo_file_id,
            "pending",
            datetime.now().strftime("%d.%m.%Y %H:%M")
        )
    )
    conn.commit()
    prepayment_id = cursor.lastrowid

    await message.answer(
        "✅ Скриншот получен!\n\n"
        "⏳ Ожидайте подтверждения от администратора.\n"
        "После проверки оплаты запись будет подтверждена."
    )

    date_obj = datetime.strptime(data['date'], "%d.%m.%Y")
    day_number = date_obj.strftime("%d")
    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    day_name = day_names[date_obj.weekday()]

    admin_text = (
        "🔔 Новая запись!\n\n"
        f"👤 Имя: {data['name']}\n"
        f"🔗 {data.get('username', 'Нет')}\n"
        f"📱 Телефон: {data.get('phone', 'Не указан')}\n"
        f"💅 Услуги: {data['service']}\n"
        f"💰 Итого: {total_price}₽\n"
        f"📅 Дата: {day_number} ({day_name})\n"
        f"⏰ Время: {data['time']}"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(
                admin_id,
                photo_file_id,
                caption=admin_text,
                reply_markup=admin_prepayment_keyboard(prepayment_id, booking_id)
            )
        except:
            pass

    await state.clear()

@dp.message(Booking.prepayment)
async def prepayment_no_photo(message: types.Message):
    await message.answer("❌ Пожалуйста, отправьте фото (скриншот чека)")

# ---------- ПОДТВЕРЖДЕНИЕ ПРЕДОПЛАТЫ (АДМИН) ----------
@dp.callback_query(F.data.startswith("approve_prepayment_"))
async def approve_prepayment(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    parts = callback.data.replace("approve_prepayment_", "").split("_")
    prepayment_id, booking_id = parts[0], parts[1]

    cursor.execute("UPDATE prepayments SET status='approved' WHERE id=?", (prepayment_id,))
    conn.commit()

    cursor.execute(
        """
        SELECT user_id, name, username, phone, service, date, time, total_price
        FROM bookings
        WHERE id=?
    """, (booking_id,))
    row = cursor.fetchone()

    if not row:
        await callback.message.edit_caption("❌ Запись не найдена")
        return

    user_id, name, username, phone, service, date, time, total_price = row
    date_obj = datetime.strptime(date, "%d.%m.%Y")
    day_number = date_obj.strftime("%d")
    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    day_name = day_names[date_obj.weekday()]

    try:
        await bot.send_message(
            user_id,
            f"✅ Оплата подтверждена!\n\n"
            f"📅 Дата: {day_number} ({day_name})\n"
            f"⏰ Время: {time}\n"
            f"💅 Услуги: {service}\n"
            f"💰 Итого: {total_price}₽\n\n"
            "Ждем вас в студии Wenty.Lash! ✨\n"
            "📍 По адресу ул. Бориса Галушкина 15"
        )
    except Exception as e:
        print(f"[approve_prepayment] Не удалось уведомить клиента {user_id}: {e}")

    approved_text = (
        "✅ Запись подтверждена!\n\n"
        f"🧾 ID записи: {booking_id}\n"
        f"👤 Имя: {name}\n"
        f"🔗 {username or 'Нет'}\n"
        f"📱 Телефон: {phone}\n"
        f"💅 Услуги: {service}\n"
        f"💰 Итого: {total_price}₽\n"
        f"📅 Дата: {day_number} ({day_name})\n"
        f"⏰ Время: {time}\n"
        f"✅ Подтвердил: @{callback.from_user.username or callback.from_user.id}"
    )

    cursor.execute("SELECT photo_file_id FROM prepayments WHERE id=?", (prepayment_id,))
    prepay_row = cursor.fetchone()
    photo_file_id = prepay_row[0] if prepay_row else None

    for admin_id in ADMIN_IDS:
        try:
            if photo_file_id:
                await bot.send_photo(admin_id, photo_file_id, caption=approved_text)
            else:
                await bot.send_message(admin_id, approved_text)
        except Exception as e:
            print(f"[approve_prepayment] Не удалось отправить админу {admin_id}: {e}")

    await callback.message.edit_caption("✅ Оплата подтверждена. Подробности отправлены администраторам.")

@dp.callback_query(F.data.startswith("reject_prepayment_"))
async def reject_prepayment(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()

    parts = callback.data.replace("reject_prepayment_", "").split("_")
    prepayment_id, booking_id = parts[0], parts[1]

    cursor.execute("UPDATE prepayments SET status='rejected' WHERE id=?", (prepayment_id,))
    conn.commit()

    cursor.execute("SELECT user_id, service, date, time FROM bookings WHERE id=?", (booking_id,))
    row = cursor.fetchone()
    if row:
        user_id, service, date, time = row
        try:
            await bot.send_message(
                user_id,
                "❌ Оплата не подтверждена\n\n"
                "Пожалуйста, отправьте корректный скриншот оплаты или свяжитесь с администратором."
            )
        except:
            pass

    await callback.message.edit_caption("❌ Оплата отклонена. Клиент уведомлён.")

# ---------- ПЕРЕЗАПИСЬ КЛИЕНТОМ ----------
@dp.callback_query(F.data.startswith("reschedule_"))
async def reschedule_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    booking_id = callback.data.replace("reschedule_", "")

    cursor.execute(
        "SELECT id, service, service_ids FROM bookings WHERE id=? AND user_id=?",
        (booking_id, callback.from_user.id)
    )
    row = cursor.fetchone()
    if not row:
        await callback.answer("Это не ваша запись", show_alert=True)
        return

    await state.update_data(reschedule_booking_id=booking_id, service=row[1], service_ids=row[2])
    today = datetime.now()
    half = "second" if today.day > 15 else "first"
    await callback.message.edit_text("📅 Выберите новую дату:", reply_markup=dates_keyboard(half))
    await state.set_state(Booking.date)

# ---------- ПОДТВЕРЖДЕНИЕ ЗАПИСИ (БЕЗ ПРЕДОПЛАТЫ, ЕСЛИ НУЖНО) ----------
@dp.callback_query(F.data == "confirm_booking")
async def confirm(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    service_ids = data.get("service_ids", "").split(",")
    SERVICES = get_services()
    total_price = sum(SERVICES.get(k, {}).get('price', 0) for k in service_ids if k)
    total_duration = sum(SERVICES.get(k, {}).get('duration', 180) for k in service_ids if k)

    reschedule_id = data.get("reschedule_booking_id")

    if reschedule_id:
        cursor.execute(
            "UPDATE bookings SET date=?, time=?, duration=?, total_price=? WHERE id=?",
            (data["date"], data["time"], total_duration, total_price, reschedule_id)
        )
        conn.commit()

        date_obj = datetime.strptime(data['date'], "%d.%m.%Y")
        day_number = date_obj.strftime("%d")
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        day_name = day_names[date_obj.weekday()]

        await callback.message.edit_text(
            "✅ Запись изменена!\n\n"
            f"📅 Дата: {day_number} ({day_name})\n"
            f"⏰ Время: {data['time']}\n"
            f"💅 Услуги: {data['service']}\n"
            f"💰 Итого: {total_price}₽\n\n"
            "Ждем вас в студии Wenty.Lash! ✨\n"
            "📍 По адресу ул. Бориса Галушкина 15"
        )

        cursor.execute("SELECT name, phone FROM bookings WHERE id=?", (reschedule_id,))
        booking_info = cursor.fetchone()
        client_name = booking_info[0] if booking_info else data.get('name', 'Неизвестно')
        client_phone = booking_info[1] if booking_info else 'Не указан'

        admin_text = (
            "🔄 Клиент изменил запись!\n\n"
            f"👤 Имя: {client_name}\n"
            f"📱 Телефон: {client_phone}\n"
            f"💅 Услуги: {data['service']}\n"
            f"📅 Новая дата: {data['date']}\n"
            f"⏰ Новое время: {data['time']}"
        )
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, admin_text)
            except:
                pass
    else:
        cursor.execute(
            "INSERT INTO bookings(user_id, name, username, phone, service, service_ids, date, time, duration, total_price) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                callback.from_user.id,
                data["name"],
                data.get("username", "Нет"),
                data.get("phone", "Не указан"),
                data["service"],
                data.get("service_ids", ""),
                data["date"],
                data["time"],
                total_duration,
                total_price
            )
        )
        conn.commit()

        date_obj = datetime.strptime(data['date'], "%d.%m.%Y")
        day_number = date_obj.strftime("%d")
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        day_name = day_names[date_obj.weekday()]

        await callback.message.edit_text(
            "✅ Запись подтверждена!\n\n"
            f"📅 Дата: {day_number} ({day_name})\n"
            f"⏰ Время: {data['time']}\n"
            f"💅 Услуги: {data['service']}\n"
            f"💰 Итого: {total_price}₽\n\n"
            "Ждем вас в студии Wenty.Lash! ✨\n"
            "📍 По адресу ул. Бориса Галушкина 15\n\n"
            "Для новой записи напишите /start"
        )

        admin_text = (
            "🔔 Новая запись!\n\n"
            f"👤 Имя: {data['name']}\n"
            f"🔗 {data.get('username', 'Нет')}\n"
            f"📱 Телефон: {data.get('phone', 'Не указан')}\n"
            f"💅 Услуги: {data['service']}\n"
            f"💰 Итого: {total_price}₽\n"
            f"📅 Дата: {data['date']}\n"
            f"⏰ Время: {data['time']}"
        )
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, admin_text)
            except:
                pass

    await state.clear()

@dp.callback_query(F.data == "cancel_booking")
async def cancel(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text("❌ Запись отменена. Напишите /start")
    await state.clear()

# ---------- МОИ ЗАПИСИ ----------
@dp.message(F.text == "📋 Мои записи")
async def my_bookings(message: types.Message):
    cursor.execute(
        "SELECT id, service, date, time, total_price FROM bookings WHERE user_id=? ORDER BY date, time",
        (message.from_user.id,)
    )
    rows = cursor.fetchall()
    if not rows:
        await message.answer("У вас пока нет записей")
        return
    for r in rows:
        date_obj = datetime.strptime(r[2], "%d.%m.%Y")
        day_number = date_obj.strftime("%d")
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        day_name = day_names[date_obj.weekday()]
        text = f"📅 {day_number} ({day_name})\n⏰ {r[3]}\n💅 {r[1]}\n💰 {r[4]}₽"
        await message.answer(text, reply_markup=my_booking_keyboard(r[0]))

# ---------- УДАЛЕНИЕ (КЛИЕНТ) ----------
@dp.callback_query(F.data.startswith("delete_"))
async def delete_booking(callback: types.CallbackQuery):
    await callback.answer()
    booking_id = callback.data.replace("delete_", "")
    cursor.execute(
        "SELECT user_id, name, username, phone, service, date, time FROM bookings WHERE id=?",
        (booking_id,)
    )
    row = cursor.fetchone()
    if row and row[0] == callback.from_user.id:
        name, username, phone, service, date, time = row[1], row[2], row[3], row[4], row[5], row[6]
        cursor.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
        conn.commit()
        await callback.message.edit_text("❌ Запись удалена")
        cancel_text = (
            "🚫 Клиент отменил запись!\n\n"
            f"👤 Имя: {name}\n"
            f"📱 Телефон: {phone}\n"
            f"💅 Услуги: {service}\n"
            f"📅 Дата: {date}\n"
            f"⏰ Время: {time}"
        )
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, cancel_text)
            except:
                pass
    else:
        await callback.answer("Это не ваша запись", show_alert=True)

# ---------- АДМИН-ПАНЕЛЬ ----------
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("🔧 Админ-панель:", reply_markup=admin_main_keyboard())

@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    await callback.message.edit_text("🔧 Админ-панель:", reply_markup=admin_main_keyboard())

@dp.callback_query(F.data == "admin_by_date")
async def admin_by_date(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    await callback.message.edit_text("📅 Выберите день:", reply_markup=admin_dates_keyboard())

@dp.callback_query(F.data == "admin_all")
async def admin_all(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    cursor.execute(
        "SELECT id, name, username, phone, service, date, time, total_price, duration FROM bookings ORDER BY date, time"
    )
    rows = cursor.fetchall()
    if not rows:
        await callback.message.answer("Записей пока нет")
        return
    for r in rows:
        text = f"👤 {r[1]}\n📱 {r[3]}\n💅 {r[4]}\n💰 {r[7]}₽\n📅 {r[5]} {r[6]}"
        await callback.message.answer(text, reply_markup=admin_booking_keyboard(r[0]))

@dp.callback_query(F.data.startswith("admin_date_"))
async def admin_view_date(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    date = callback.data.replace("admin_date_", "")
    cursor.execute(
        "SELECT id, name, username, phone, service, time, total_price FROM bookings WHERE date=? ORDER BY time",
        (date,)
    )
    rows = cursor.fetchall()
    count_text = f" ({len(rows)})" if rows else ""
    text = f"📅 {date}{count_text}\n\n"
    if rows:
        text += "📝 Записи:\n"
        for r in rows:
            text += f"  ⏰ {r[5]} — {r[1]} ({r[4]}) | {r[6]}₽\n"
    else:
        text += "📝 Записей нет\n"
    await callback.message.answer(text)
    if rows:
        for r in rows:
            booking_text = f"👤 {r[1]}\n📱 {r[3]}\n💅 {r[4]}\n💰 {r[6]}₽\n⏰ {r[5]}"
            await callback.message.answer(booking_text, reply_markup=admin_booking_keyboard(r[0]))

@dp.callback_query(F.data.startswith("admin_delete_"))
async def admin_delete_booking(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    booking_id = callback.data.replace("admin_delete_", "")
    cursor.execute(
        "SELECT user_id, name, phone, service, date, time FROM bookings WHERE id=?",
        (booking_id,)
    )
    row = cursor.fetchone()
    if row:
        user_id, name, phone, service, date, time = row[0], row[1], row[2], row[3], row[4], row[5]
        cursor.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
        conn.commit()
        try:
            await bot.send_message(
                user_id,
                "❌ Ваша запись была отменена администратором!\n\n"
                f"📅 Дата: {date}\n"
                f"⏰ Время: {time}\n"
                f"💅 Услуги: {service}\n"
                "📍 По адресу ул. Бориса Галушкина 15"
            )
            await callback.message.edit_text("✅ Запись удалена\n\nКлиент уведомлён об отмене.")
        except:
            await callback.message.edit_text("✅ Запись удалена")
    else:
        await callback.message.edit_text("❌ Запись не найдена")

# ---------- АДМИН-ПАНЕЛЬ УСЛУГ ----------
@dp.callback_query(F.data == "admin_services")
async def admin_services_menu(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    SERVICES = get_services()
    text = f"💅 Управление услугами\n\nВсего услуг: {len(SERVICES)}"
    await callback.message.edit_text(text, reply_markup=admin_services_keyboard())

@dp.callback_query(F.data.startswith("service_manage_"))
async def service_manage(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    service_id = callback.data.replace("service_manage_", "")
    SERVICES = get_services()
    if service_id not in SERVICES:
        await callback.message.edit_text("❌ Услуга не найдена")
        return
    service = SERVICES[service_id]
    text = (
        f"💅 {service['name']}\n"
        f"💰 Цена: {service['price']}₽\n"
        f"⏱ Время: {format_duration(service.get('duration', 180))}\n"
        f"📝 Описание: {service.get('description') or 'Нет'}"
    )
    await callback.message.edit_text(text, reply_markup=admin_service_manage_keyboard(service_id))

# ---------- ДОБАВЛЕНИЕ УСЛУГИ ----------
@dp.callback_query(F.data == "service_add")
async def service_add_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    await callback.message.answer("➕ Введите название услуги:")
    await state.set_state(AdminService.add_name)

@dp.message(AdminService.add_name)
async def service_add_name(message: types.Message, state: FSMContext):
    await state.update_data(new_service_name=message.text)
    await message.answer("Введите цену услуги (только число):")
    await state.set_state(AdminService.add_price)

@dp.message(AdminService.add_price)
async def service_add_price(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите число")
        return
    await state.update_data(new_service_price=int(message.text))
    await message.answer("Введите длительность в минутах (например: 180):")
    await state.set_state(AdminService.add_duration)

@dp.message(AdminService.add_duration)
async def service_add_duration(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите число минут")
        return
    await state.update_data(new_service_duration=int(message.text))
    await message.answer("Введите описание (или /skip чтобы пропустить):")
    await state.set_state(AdminService.add_desc)

@dp.message(AdminService.add_desc)
async def service_add_desc(message: types.Message, state: FSMContext):
    data = await state.get_data()
    name = data["new_service_name"]
    price = data["new_service_price"]
    duration = data["new_service_duration"]
    description = message.text if message.text != "/skip" else ""
    try:
        cursor.execute(
            "INSERT INTO services(name, price, duration, description) VALUES (?, ?, ?, ?)",
            (name, price, duration, description)
        )
        conn.commit()
        await message.answer(
            f"✅ Услуга добавлена!\n\n💅 {name}\n💰 {price}₽\n⏱ {format_duration(duration)}"
        )
    except sqlite3.IntegrityError:
        await message.answer("❌ Услуга с таким названием уже существует")
    await state.clear()

# ---------- РЕДАКТИРОВАНИЕ УСЛУГ ----------
@dp.callback_query(F.data.startswith("service_edit_name_"))
async def service_edit_name_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    service_id = callback.data.replace("service_edit_name_", "")
    await state.update_data(edit_service_id=service_id)
    await callback.message.answer("Введите новое название:")
    await state.set_state(AdminService.edit_name)

@dp.message(AdminService.edit_name)
async def service_edit_name_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cursor.execute("UPDATE services SET name=? WHERE id=?", (message.text, data["edit_service_id"]))
    conn.commit()
    await message.answer(f"✅ Название изменено на: {message.text}")
    await state.clear()

@dp.callback_query(F.data.startswith("service_edit_price_"))
async def service_edit_price_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    service_id = callback.data.replace("service_edit_price_", "")
    await state.update_data(edit_service_id=service_id)
    await callback.message.answer("Введите новую цену:")
    await state.set_state(AdminService.edit_price)

@dp.message(AdminService.edit_price)
async def service_edit_price_save(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите число")
        return
    data = await state.get_data()
    cursor.execute(
        "UPDATE services SET price=? WHERE id?",
        (int(message.text), data["edit_service_id"])
    )
    conn.commit()
    await message.answer(f"✅ Цена изменена на: {message.text}₽")
    await state.clear()

@dp.callback_query(F.data.startswith("service_edit_duration_"))
async def service_edit_duration_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    service_id = callback.data.replace("service_edit_duration_", "")
    await state.update_data(edit_service_id=service_id)
    await callback.message.answer("Введите новую длительность в минутах:")
    await state.set_state(AdminService.edit_duration)

@dp.message(AdminService.edit_duration)
async def service_edit_duration_save(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите число минут")
        return
    data = await state.get_data()
    cursor.execute(
        "UPDATE services SET duration=? WHERE id=?",
        (int(message.text), data["edit_service_id"])
    )
    conn.commit()
    await message.answer(f"✅ Длительность изменена на: {format_duration(int(message.text))}")
    await state.clear()

@dp.callback_query(F.data.startswith("service_edit_desc_"))
async def service_edit_desc_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    service_id = callback.data.replace("service_edit_desc_", "")
    await state.update_data(edit_service_id=service_id)
    await callback.message.answer("Введите новое описание (или /skip чтобы удалить):")
    await state.set_state(AdminService.edit_desc)

@dp.message(AdminService.edit_desc)
async def service_edit_desc_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    desc = "" if message.text == "/skip" else message.text
    cursor.execute("UPDATE services SET description=? WHERE id=?", (desc, data["edit_service_id"]))
    conn.commit()
    await message.answer("✅ Описание изменено")
    await state.clear()

# ---------- УДАЛЕНИЕ УСЛУГИ ----------
@dp.callback_query(F.data.startswith("service_delete_"))
async def service_delete_ask(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    service_id = callback.data.replace("service_delete_", "")
    is_confirm = service_id.startswith("confirm_")
    if is_confirm:
        service_id = service_id.replace("confirm_", "")
        SERVICES = get_services()
        if service_id not in SERVICES:
            await callback.message.edit_text("❌ Услуга не найдена")
            return
        name = SERVICES[service_id]["name"]
        cursor.execute("DELETE FROM services WHERE id=?", (service_id,))
        conn.commit()
        await callback.message.edit_text(f"✅ Услуга \"{name}\" удалена")
    else:
        SERVICES = get_services()
        if service_id not in SERVICES:
            await callback.message.edit_text("❌ Услуга не найдена")
            return
        service = SERVICES[service_id]
        text = (
            "⚠️ Удалить услугу?\n\n"
            f"💅 {service['name']}\n"
            f"💰 Цена: {service['price']}₽"
        )
        await callback.message.edit_text(text, reply_markup=admin_service_delete_keyboard(service_id))

# ---------- БЛОКИРОВКА СЛОТОВ ----------
@dp.callback_query(F.data == "admin_block")
async def admin_block_start(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    today = datetime.now()
    half = "second" if today.day > 15 else "first"
    await callback.message.edit_text("🚫 Выберите день:", reply_markup=admin_block_dates_keyboard(half))

@dp.callback_query(F.data.startswith("block_date_"))
async def admin_block_date(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    date = callback.data.replace("block_date_", "")
    await callback.message.edit_text(f"🚫 {date}\nВыберите время:", reply_markup=admin_block_times_keyboard(date))

@dp.callback_query(F.data.startswith("block_time_"))
async def admin_block_time(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    parts = callback.data.replace("block_time_", "").split("_")
    time, date = parts[0], parts[1]
    await state.update_data(block_date=date, block_time=time, block_single=True)
    await callback.message.answer(f"Введите причину блокировки для {date} {time}:")
    await state.set_state(AdminBlock.enter_reason)

@dp.callback_query(F.data.startswith("block_all_"))
async def block_all(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    date = callback.data.replace("block_all_", "")
    await state.update_data(block_date=date, block_single=False)
    await callback.message.answer(f"Введите причину блокировки дня {date}:")
    await state.set_state(AdminBlock.enter_reason)

# ---------- РАЗБЛОКИРОВКИ ----------
@dp.callback_query(F.data == "admin_unblock")
async def admin_unblock_list(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    keyboard = admin_unblock_keyboard()
    if keyboard:
        await callback.message.edit_text("🔓 Выберите слот:", reply_markup=keyboard)
    else:
        await callback.message.edit_text("Нет заблокированных слотов", reply_markup=admin_main_keyboard())

@dp.callback_query(F.data.startswith("unblock_"))
async def admin_unblock_slot(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.answer()
    callback_data = callback.data.replace("unblock_", "")

    if callback_data == "all":
        cursor.execute("DELETE FROM blocked_slots")
        conn.commit()
        await callback.message.edit_text("✅ Все слоты разблокированы", reply_markup=admin_main_keyboard())
        return

    if "_" in callback_data:
        date, time = callback_data.split("_")
        cursor.execute("DELETE FROM blocked_slots WHERE date=? AND time=?", (date, time))
        conn.commit()
        await callback.message.edit_text(f"✅ Слот {date} {time} разблокирован", reply_markup=admin_unblock_keyboard())
    else:
        date = callback_data.replace("day_", "")
        cursor.execute("DELETE FROM blocked_slots WHERE date=?", (date,))
        conn.commit()
        await callback.message.edit_text(f"✅ День {date} разблокирован", reply_markup=admin_unblock_keyboard())

# ---------- ЗАПУСК ----------
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

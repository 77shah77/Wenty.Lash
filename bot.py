import asyncio
import sqlite3
import os
from datetime import datetime, timedelta
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

TOKEN = "8630017788:AAFvwsh7g_x-mm8we18izvEsYXxwwwrXBCI"
ADMIN_ID = 995387118

bot = Bot(TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ---------- БАЗА ДАННЫХ ----------
conn = sqlite3.connect("lash_bookings.db")
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
duration INTEGER,
total_price INTEGER
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

conn.commit()

# Добавляем колонки, если их нет
try:
    cursor.execute("ALTER TABLE services ADD COLUMN duration INTEGER DEFAULT 180")
except:
    pass
try:
    cursor.execute("ALTER TABLE services ADD COLUMN description TEXT DEFAULT ''")
except:
    pass
try:
    cursor.execute("ALTER TABLE bookings ADD COLUMN service_ids TEXT DEFAULT ''")
except:
    pass
try:
    cursor.execute("ALTER TABLE bookings ADD COLUMN duration INTEGER DEFAULT 180")
except:
    pass
try:
    cursor.execute("ALTER TABLE bookings ADD COLUMN total_price INTEGER DEFAULT 0")
except:
    pass

conn.commit()

# ---------- СОСТОЯНИЯ ----------
class Booking(StatesGroup):
    service = State()
    date = State()
    time = State()
    username = State()
    phone = State()
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

# ---------- УСЛУГИ ----------
def get_services():
    cursor.execute("SELECT id, name, price, duration, description FROM services ORDER BY id")
    rows = cursor.fetchall()
    return {str(r[0]): {"name": r[1], "price": r[2], "duration": r[3] if r[3] else 180, "description": r[4] if r[4] else ""} for r in rows}

def format_duration(minutes):
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
            [KeyboardButton(text="📅 Записаться")],
            [KeyboardButton(text="📋 Мои записи")],
            [KeyboardButton(text="💰 Прайс")]
        ],
        resize_keyboard=True
    )

def phone_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Поделиться номером", request_contact=True)],
            [KeyboardButton(text="Пропустить")],
            [KeyboardButton(text="⬅️ Назад")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def back_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Назад")]],
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
        buttons.append([InlineKeyboardButton(text=f"{check}{v['name']} — {v['price']}₽{duration}", callback_data=f"toggle_service_{k}")])
    if selected:
        total_price = sum(SERVICES[k]['price'] for k in selected)
        total_duration = sum(SERVICES[k]['duration'] for k in selected)
        buttons.append([InlineKeyboardButton(text=f"✅ Выбрано ({len(selected)}) | {total_price}₽ | {format_duration(total_duration)}", callback_data="services_confirm")])
    else:
        buttons.append([InlineKeyboardButton(text="Выберите услуги", callback_data="ignore")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def confirm_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_booking")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_booking")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_phone")]
        ]
    )
    
# ---------- АДМИН-КЛАВИАТУРЫ ----------
def admin_main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 Записи по дням", callback_data="admin_by_date")],
            [InlineKeyboardButton(text="📋 Все записи", callback_data="admin_all")],
            [InlineKeyboardButton(text="💅 Управление услугами", callback_data="admin_services")],
            [InlineKeyboardButton(text="🚫 Заблокировать слот", callback_data="admin_block")],
            [InlineKeyboardButton(text="✅ Разблокировать слоты", callback_data="admin_unblock")]
        ]
    )

def admin_services_keyboard():
    SERVICES = get_services()
    buttons = []
    for k, v in SERVICES.items():
        desc = v.get('description', '')
        duration = format_duration(v.get('duration', 180))
        desc_text = " 📝" if desc else ""
        buttons.append([InlineKeyboardButton(text=f"{v['name']} — {v['price']}₽ ({duration}){desc_text}", callback_data=f"service_manage_{k}")])
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
    for i in range(1, 8):
        date = datetime.now() + timedelta(days=i)
        date_str = date.strftime("%d.%m.%Y")
        cursor.execute("SELECT COUNT(*) FROM bookings WHERE date=?", (date_str,))
        bookings_count = cursor.fetchone()[0]
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        day_name = day_names[date.weekday()]
        row.append(InlineKeyboardButton(text=f"{date.day} ({day_name})", callback_data=f"admin_date_{date_str}"))
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

def admin_block_dates_keyboard(half="first"):
    buttons = []
    today = datetime.now()
    current_day = today.day
    if half == "first":
        start_day = current_day + 1
        end_day = min(15, 28)
    else:
        start_day = max(16, current_day + 1)
        end_day = 28
    days_to_show = end_day - start_day + 1
    row = []
    for i in range(min(days_to_show, 14)):
        date = today + timedelta(days=i + 1)
        if half == "first" and date.day > 15:
            continue
        if half == "second" and date.day <= 15:
            continue
        date_str = date.strftime("%d.%m.%Y")
        cursor.execute("SELECT COUNT(*) FROM blocked_slots WHERE date=?", (date_str,))
        blocked_count = cursor.fetchone()[0]
        is_blocked = blocked_count >= len(TIME_SLOTS)
        prefix = "🚫 " if is_blocked else ""
        row.append(InlineKeyboardButton(text=f"{prefix}{date.day}", callback_data=f"block_date_{date_str}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    nav_row = []
    if half == "first":
        nav_row.append(InlineKeyboardButton(text="📅 16-31 >>", callback_data="block_second_half"))
    else:
        nav_row.append(InlineKeyboardButton(text="<< 1-15", callback_data="block_first_half"))
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
            buttons.append([InlineKeyboardButton(text=f"🚫 {date} (весь день)", callback_data=f"unblock_day_{date}")])
        else:
            cursor.execute("SELECT time, reason FROM blocked_slots WHERE date=?", (date,))
            for time, reason in cursor.fetchall():
                display_reason = reason[:15] + "..." if len(reason) > 15 else reason
                buttons.append([InlineKeyboardButton(text=f"🔓 {date} {time} ({display_reason})", callback_data=f"unblock_{date}_{time}")])
    buttons.append([InlineKeyboardButton(text="🔓 Разблокировать всё", callback_data="unblock_all")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def dates_keyboard(half="first"):
    buttons = []
    today = datetime.now()
    current_day = today.day
    if half == "first":
        start_day = current_day + 1
        end_day = min(15, 28)
    else:
        start_day = max(16, current_day + 1)
        end_day = 28
    days_to_show = end_day - start_day + 1
    row = []
    for i in range(min(days_to_show, 14)):
        date = today + timedelta(days=i + 1)
        if half == "first" and date.day > 15:
            continue
        if half == "second" and date.day <= 15:
            continue
        day_number = date.strftime("%d")
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        day_name = day_names[date.weekday()]
        date_str = date.strftime("%d.%m.%Y")
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
    nav_row = []
    if half == "first":
        nav_row.append(InlineKeyboardButton(text="📅 16-31 >>", callback_data="dates_second_half"))
    else:
        nav_row.append(InlineKeyboardButton(text="<< 1-15", callback_data="dates_first_half"))
    buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_service")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def time_keyboard(date):
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
    text = "💰 Прайс:\n\n"
    for v in SERVICES.values():
        duration = f"\n⏱ Время: {format_duration(v['duration'])}" if v.get('duration') else ""
        text += f"{v['name']} — {v['price']}₽{duration}\n\n"
    await message.answer(text)

# ---------- ЗАПИСЬ ----------
@dp.message(F.text == "📅 Записаться")
async def booking_start(message: types.Message, state: FSMContext):
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

@dp.callback_query(F.data == "back_to_phone")
async def back_to_phone(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Поделитесь номером телефона:", reply_markup=phone_keyboard())
    await state.set_state(Booking.phone)

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
    await callback.answer()
    await callback.message.edit_text("🚫 Выберите день:", reply_markup=admin_block_dates_keyboard("first"))

@dp.callback_query(F.data == "block_second_half")
async def block_second_half(callback: types.CallbackQuery):
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
    await callback.message.edit_text(f"📅 {day_number} ({day_name})\nВыберите время:", reply_markup=time_keyboard(date))
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
    data = await state.get_data()
    if data.get("phone"):
        await continue_booking(callback, state)
    else:
        await callback.message.answer(f"Имя: {name}\n\nПоделитесь номером телефона:", reply_markup=phone_keyboard())
        await state.set_state(Booking.phone)

# ---------- USERNAME ----------
@dp.message(Booking.username)
async def get_username(message: types.Message, state: FSMContext):
    username = message.text.strip()
    if username != "⬅️ Назад":
        if not username.startswith("@"):
            username = "@" + username
        await state.update_data(username=username)
        data = await state.get_data()
        if data.get("phone"):
            await continue_booking(message, state)
        else:
            await message.answer("Поделитесь номером телефона:", reply_markup=phone_keyboard())
            await state.set_state(Booking.phone)

# ---------- ТЕЛЕФОН ----------
@dp.message(F.contact)
async def phone(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "Booking:phone":
        return
    phone_number = message.contact.phone_number
    await state.update_data(phone=phone_number)
    await continue_booking(message, state)

@dp.message(F.text == "Пропустить")
async def skip_phone(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "Booking:phone":
        return
    await state.update_data(phone="Не указан")
    await continue_booking(message, state)

async def continue_booking(event, state: FSMContext):
    """Продолжаем после получения телефона"""
    data = await state.get_data()
    
    # Отправляем сообщение с подтверждением
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
    
    service_descs = []
    for k in service_ids:
        if k and k in SERVICES:
            v = SERVICES[k]
            desc = v.get('description', '')
            if desc:
                service_descs.append(f"• {v['name']}: {desc}")
            else:
                service_descs.append(f"• {v['name']}")
    
    services_text = "\n".join(service_descs) if service_descs else data['service']
    
    text = (
        "📋 Подтвердите запись\n\n"
        f"👤 Имя: {data['name']}\n"
        f"🔗 {data.get('username', 'Нет')}\n"
        f"📱 Телефон: {data.get('phone', 'Не указан')}\n"
        f"💅 Услуги:\n{services_text}\n\n"
        f"💰 Итого: {total_price}₽\n"
        f"⏱ Время: {format_duration(total_duration)}\n"
        f"📅 Дата: {day_number} ({day_name})\n"
        f"⏰ Время: {data['time']}"
    )
    
    await msg.answer(text, reply_markup=confirm_keyboard())
    await state.set_state(Booking.confirm)

# ---------- ПОДТВЕРЖДЕНИЕ ЗАПИСИ ----------
@dp.callback_query(F.data == "confirm_booking")
async def confirm(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    
    current_state = await state.get_state()
    if current_state != "Booking:confirm":
        await callback.message.answer("Что-то пошло не так. Начните запись заново: /start")
        await state.clear()
        return
    
    data = await state.get_data()
    
    service_ids = data.get("service_ids", "").split(",")
    SERVICES = get_services()
    total_price = sum(SERVICES.get(k, {}).get('price', 0) for k in service_ids if k)
    total_duration = sum(SERVICES.get(k, {}).get('duration', 180) for k in service_ids if k)
    
    cursor.execute(
        "INSERT INTO bookings(user_id, name, username, phone, service, service_ids, date, time, duration, total_price) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (callback.from_user.id, data["name"], data.get("username", "Нет"), data.get("phone", "Не указан"), data["service"], data.get("service_ids", ""), data["date"], data["time"], total_duration, total_price)
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
        f"💰 Итого: {total_price}₽\n"
        f"⏱ Длительность: {format_duration(total_duration)}\n\n"
        "Ждем вас в студии Wenty.Lash! ✨\n"
        "Чтобы посмотреть записи — /start"
    )
    
    admin_text = (
        "🔔 Новая запись!\n\n"
        f"👤 Имя: {data['name']}\n"
        f"🔗 {data.get('username', 'Нет')}\n"
        f"📱 Телефон: {data.get('phone', 'Не указан')}\n"
        f"💅 Услуги: {data['service']}\n"
        f"💰 Итого: {total_price}₽\n"
        f"⏱ Время: {format_duration(total_duration)}\n"
        f"📅 Дата: {data['date']}\n"
        f"⏰ Время: {data['time']}"
    )
    await bot.send_message(ADMIN_ID, admin_text)
    await state.clear()

@dp.callback_query(F.data == "cancel_booking")
async def cancel(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text("❌ Запись отменена. Напишите /start")
    await state.clear()

# ---------- МОИ ЗАПИСИ ----------
@dp.message(F.text == "📋 Мои записи")
async def my_bookings(message: types.Message):
    cursor.execute("SELECT id, service, date, time, duration, total_price FROM bookings WHERE user_id=? ORDER BY date, time", (message.from_user.id,))
    rows = cursor.fetchall()
    if not rows:
        await message.answer("У вас пока нет записей")
        return
    for r in rows:
        date_obj = datetime.strptime(r[2], "%d.%m.%Y")
        day_number = date_obj.strftime("%d")
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        day_name = day_names[date_obj.weekday()]
        text = f"📅 {day_number} ({day_name})\n⏰ {r[3]}\n💅 {r[1]}\n💰 {r[5]}₽\n⏱ {format_duration(r[4])}"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔁 Перенести", callback_data=f"move_{r[0]}"), InlineKeyboardButton(text="❌ Удалить", callback_data=f"delete_{r[0]}")]
            ]
        )
        await message.answer(text, reply_markup=keyboard)

# ---------- ПОДТВЕРЖДЕНИЕ И УДАЛЕНИЕ ----------
@dp.callback_query(F.data.startswith("delete_"))
async def delete_booking(callback: types.CallbackQuery):
    await callback.answer()
    booking_id = callback.data.replace("delete_", "")
    cursor.execute("SELECT user_id, name, username, phone, service, date, time FROM bookings WHERE id=?", (booking_id,))
    row = cursor.fetchone()
    if row and row[0] == callback.from_user.id:
        name, username, phone, service, date, time = row[1], row[2], row[3], row[4], row[5], row[6]
        cursor.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
        conn.commit()
        await callback.message.edit_text("❌ Запись удалена")
        cancel_text = (
            "🚫 Клиент отменил запись!\n\n"
            f"👤 Имя: {name}\n"
            f"🔗 {username or 'Нет'}\n"
            f"📱 Телефон: {phone}\n"
            f"💅 Услуги: {service}\n"
            f"📅 Дата: {date}\n"
            f"⏰ Время: {time}\n"
            "Для новой записи напишите /start"
        )
        await bot.send_message(ADMIN_ID, cancel_text)
    else:
        await callback.answer("Это не ваша запись", show_alert=True)

@dp.callback_query(F.data.startswith("move_"))
async def move_booking(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    booking_id = callback.data.split("_")[1]
    cursor.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
    conn.commit()
    await state.update_data(selected_services=[])
    await callback.message.answer("Выберите новую услугу:", reply_markup=services_keyboard())
    await state.set_state(Booking.service)

# ---------- АДМИН-ПАНЕЛЬ ----------
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("🔧 Админ-панель:", reply_markup=admin_main_keyboard())

@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    await callback.message.edit_text("🔧 Админ-панель:", reply_markup=admin_main_keyboard())

@dp.callback_query(F.data == "admin_by_date")
async def admin_by_date(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    await callback.message.edit_text("📅 Выберите день:", reply_markup=admin_dates_keyboard())

@dp.callback_query(F.data == "admin_all")
async def admin_all(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    cursor.execute("SELECT id, name, username, phone, service, date, time, total_price, duration FROM bookings ORDER BY date, time")
    rows = cursor.fetchall()
    if not rows:
        await callback.message.answer("Записей пока нет")
        return
    for r in rows:
        text = f"👤 {r[1]}\n🔗 {r[2]}\n📱 {r[3]}\n💅 {r[4]}\n💰 {r[7]}₽\n⏱ {format_duration(r[8])}\n📅 {r[5]} {r[6]}"
        await callback.message.answer(text, reply_markup=admin_booking_keyboard(r[0]))

@dp.callback_query(F.data.startswith("admin_date_"))
async def admin_view_date(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    date = callback.data.replace("admin_date_", "")
    cursor.execute("SELECT id, name, username, phone, service, time, total_price, duration FROM bookings WHERE date=? ORDER BY time", (date,))
    rows = cursor.fetchall()
    cursor.execute("SELECT time, reason FROM blocked_slots WHERE date=?", (date,))
    blocked = cursor.fetchall()
    text = f"📅 {date}\n\n"
    if rows:
        text += "📝 Записи:\n"
        for r in rows:
            text += f"  ⏰ {r[5]} — {r[1]} ({r[4]}) | {r[6]}₽\n"
    else:
        text += "📝 Записей нет\n"
    if blocked:
        text += "\n🚫 Заблокировано:\n"
        for b in blocked:
            text += f"  ⏰ {b[0]} — {b[1]}\n"
    await callback.message.answer(text)
    if rows:
        for r in rows:
            booking_text = f"👤 {r[1]}\n🔗 {r[2]}\n📱 {r[3]}\n💅 {r[4]}\n💰 {r[6]}₽\n⏱ {format_duration(r[7])}\n⏰ {r[5]}"
            await callback.message.answer(booking_text, reply_markup=admin_booking_keyboard(r[0]))

@dp.callback_query(F.data.startswith("admin_delete_"))
async def admin_delete_booking(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    booking_id = callback.data.replace("admin_delete_", "")
    cursor.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
    conn.commit()
    await callback.message.edit_text("✅ Запись удалена")

@dp.callback_query(F.data.startswith("edit_name_"))
async def admin_edit_name(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    booking_id = callback.data.replace("edit_name_", "")
    await state.update_data(edit_booking_id=booking_id)
    await callback.message.answer("Введите новое имя клиента:")
    await state.set_state(AdminEdit.edit_name)

@dp.message(AdminEdit.edit_name)
async def admin_edit_name_save(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "AdminEdit:edit_name":
        return
    data = await state.get_data()
    booking_id = data["edit_booking_id"]
    new_name = message.text
    cursor.execute("UPDATE bookings SET name=? WHERE id=?", (new_name, booking_id))
    conn.commit()
    await message.answer(f"✅ Имя изменено на: {new_name}")
    await state.clear()

@dp.callback_query(F.data.startswith("edit_phone_"))
async def admin_edit_phone(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    booking_id = callback.data.replace("edit_phone_", "")
    await state.update_data(edit_booking_id=booking_id)
    await callback.message.answer("Введите новый телефон клиента:")
    await state.set_state(AdminEdit.edit_phone)

@dp.message(AdminEdit.edit_phone)
async def admin_edit_phone_save(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "AdminEdit:edit_phone":
        return
    data = await state.get_data()
    booking_id = data["edit_booking_id"]
    new_phone = message.text
    cursor.execute("UPDATE bookings SET phone=? WHERE id=?", (new_phone, booking_id))
    conn.commit()
    await message.answer(f"✅ Телефон изменён на: {new_phone}")
    await state.clear()

@dp.callback_query(F.data == "admin_services")
async def admin_services_menu(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    SERVICES = get_services()
    text = f"💅 Управление услугами\n\nВсего услуг: {len(SERVICES)}"
    await callback.message.edit_text(text, reply_markup=admin_services_keyboard())

@dp.callback_query(F.data.startswith("service_manage_"))
async def service_manage(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    service_id = callback.data.replace("service_manage_", "")
    SERVICES = get_services()
    if service_id not in SERVICES:
        await callback.message.edit_text("❌ Услуга не найдена")
        return
    service = SERVICES[service_id]
    desc = service.get('description', '')
    duration = service.get('duration', 180)
    text = f"💅 {service['name']}\n💰 Цена: {service['price']}₽\n⏱ Время: {format_duration(duration)}\n📝 Описание: {desc or 'Нет'}"
    await callback.message.edit_text(text, reply_markup=admin_service_manage_keyboard(service_id))

@dp.callback_query(F.data == "service_add")
async def service_add_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    await callback.message.answer("➕ Добавление новой услуги\n\nВведите название услуги:")
    await state.set_state(AdminService.add_name)

@dp.message(AdminService.add_name)
async def service_add_name(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "AdminService:add_name":
        return
    await state.update_data(new_service_name=message.text)
    await message.answer(f"Название: {message.text}\n\nВведите цену услуги (только число):")
    await state.set_state(AdminService.add_price)

@dp.message(AdminService.add_price)
async def service_add_price(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "AdminService:add_price":
        return
    if not message.text.isdigit():
        await message.answer("❌ Введите число (например: 2500)")
        return
    data = await state.get_data()
    price = int(message.text)
    await state.update_data(new_service_price=price)
    await message.answer(f"Цена: {price}₽\n\nВведите длительность в минутах (например: 180):")
    await state.set_state(AdminService.add_duration)

@dp.message(AdminService.add_duration)
async def service_add_duration(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "AdminService:add_duration":
        return
    if not message.text.isdigit():
        await message.answer("❌ Введите число минут")
        return
    duration = int(message.text)
    data = await state.get_data()
    name = data["new_service_name"]
    price = data["new_service_price"]
    await state.update_data(new_service_duration=duration)
    await message.answer(f"Длительность: {format_duration(duration)}\n\nВведите описание (или /skip чтобы пропустить):")
    await state.set_state(AdminService.add_desc)

@dp.message(AdminService.add_desc)
async def service_add_desc(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "AdminService:add_desc":
        return
    data = await state.get_data()
    name = data["new_service_name"]
    price = data["new_service_price"]
    duration = data["new_service_duration"]
    description = message.text if message.text != "/skip" else ""
    try:
        cursor.execute("INSERT INTO services(name, price, duration, description) VALUES (?, ?, ?, ?)", (name, price, duration, description))
        conn.commit()
        await message.answer(f"✅ Услуга добавлена!\n\n💅 {name}\n💰 {price}₽\n⏱ {format_duration(duration)}")
    except sqlite3.IntegrityError:
        await message.answer("❌ Услуга с таким названием уже существует")
    await state.clear()

@dp.callback_query(F.data.startswith("service_edit_name_"))
async def service_edit_name_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    service_id = callback.data.replace("service_edit_name_", "")
    await state.update_data(edit_service_id=service_id)
    await callback.message.answer("Введите новое название услуги:")
    await state.set_state(AdminService.edit_name)

@dp.message(AdminService.edit_name)
async def service_edit_name_save(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "AdminService:edit_name":
        return
    data = await state.get_data()
    service_id = data["edit_service_id"]
    cursor.execute("UPDATE services SET name=? WHERE id=?", (message.text, service_id))
    conn.commit()
    await message.answer(f"✅ Название изменено на: {message.text}")
    await state.clear()

@dp.callback_query(F.data.startswith("service_edit_price_"))
async def service_edit_price_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    service_id = callback.data.replace("service_edit_price_", "")
    await state.update_data(edit_service_id=service_id)
    await callback.message.answer("Введите новую цену:")
    await state.set_state(AdminService.edit_price)

@dp.message(AdminService.edit_price)
async def service_edit_price_save(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "AdminService:edit_price":
        return
    if not message.text.isdigit():
        await message.answer("❌ Введите число")
        return
    data = await state.get_data()
    cursor.execute("UPDATE services SET price=? WHERE id=?", (int(message.text), data["edit_service_id"]))
    conn.commit()
    await message.answer(f"✅ Цена изменена на: {message.text}₽")
    await state.clear()

@dp.callback_query(F.data.startswith("service_edit_duration_"))
async def service_edit_duration_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    service_id = callback.data.replace("service_edit_duration_", "")
    SERVICES = get_services()
    current = SERVICES.get(service_id, {}).get('duration', 180)
    await state.update_data(edit_service_id=service_id)
    await callback.message.answer(f"Текущая длительность: {format_duration(current)}\n\nВведите новую длительность в минутах:")
    await state.set_state(AdminService.edit_duration)

@dp.message(AdminService.edit_duration)
async def service_edit_duration_save(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "AdminService:edit_duration":
        return
    if not message.text.isdigit():
        await message.answer("❌ Введите число минут")
        return
    data = await state.get_data()
    cursor.execute("UPDATE services SET duration=? WHERE id=?", (int(message.text), data["edit_service_id"]))
    conn.commit()
    await message.answer(f"✅ Длительность изменена на: {format_duration(int(message.text))}")
    await state.clear()

@dp.callback_query(F.data.startswith("service_edit_desc_"))
async def service_edit_desc_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    service_id = callback.data.replace("service_edit_desc_", "")
    SERVICES = get_services()
    current = SERVICES.get(service_id, {}).get('description', '')
    await state.update_data(edit_service_id=service_id, current_desc=current)
    await callback.message.answer(f"Текущее описание: {current or 'Нет'}\n\nВведите новое описание (или /skip чтобы удалить):")
    await state.set_state(AdminService.edit_desc)

@dp.message(AdminService.edit_desc)
async def service_edit_desc_save(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "AdminService:edit_desc":
        return
    data = await state.get_data()
    desc = "" if message.text == "/skip" else message.text
    cursor.execute("UPDATE services SET description=? WHERE id=?", (desc, data["edit_service_id"]))
    conn.commit()
    await message.answer(f"✅ Описание изменено")
    await state.clear()

@dp.callback_query(F.data.startswith("service_delete_"))
async def service_delete_ask(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
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
    if is_confirm:
        name = SERVICES[service_id]["name"]
        cursor.execute("DELETE FROM services WHERE id=?", (service_id,))
        conn.commit()
        await callback.message.edit_text(f"✅ Услуга \"{name}\" удалена")
    else:
        service = SERVICES[service_id]
        text = f"⚠️ Удалить услугу?\n\n💅 {service['name']}\n💰 {service['price']}₽"
        await callback.message.edit_text(text, reply_markup=admin_service_delete_keyboard(service_id))

# ---------- БЛОКИРОВКА ----------
@dp.callback_query(F.data == "admin_block")
async def admin_block_start(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    today = datetime.now()
    half = "second" if today.day > 15 else "first"
    await callback.message.edit_text("🚫 Выберите день:", reply_markup=admin_block_dates_keyboard(half))

@dp.callback_query(F.data.startswith("block_date_"))
async def admin_block_date(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    date = callback.data.replace("block_date_", "")
    await callback.message.edit_text(f"🚫 {date}\nВыберите время:", reply_markup=admin_block_times_keyboard(date))

@dp.callback_query(F.data.startswith("block_time_"))
async def admin_block_time(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    parts = callback.data.replace("block_time_", "").split("_")
    time, date = parts[0], parts[1]
    await state.update_data(block_date=date, block_time=time)
    await callback.message.answer(f"Введите причину блокировки для {date} {time}:")
    await state.set_state(AdminBlock.enter_reason)

@dp.message(AdminBlock.enter_reason)
async def admin_block_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    date = data["block_date"]
    reason = message.text
    for t in TIME_SLOTS:
        cursor.execute("INSERT OR IGNORE INTO blocked_slots(date, time, reason) VALUES (?, ?, ?)", (date, t, reason))
    conn.commit()
    await message.answer(f"✅ Заблокирован весь день:\n📅 {date}\n📝 {reason}")
    today = datetime.now()
    half = "second" if today.day > 15 else "first"
    await message.answer("🚫 Выберите день:", reply_markup=admin_block_dates_keyboard(half))
    await state.clear()

@dp.callback_query(F.data.startswith("block_all_"))
async def block_all(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    date = callback.data.replace("block_all_", "")
    await state.update_data(block_date=date)
    await callback.message.answer(f"Введите причину блокировки дня {date}:")
    await state.set_state(AdminBlock.enter_reason)

# ---------- РАЗБЛОКИРОВКА ----------
@dp.callback_query(F.data == "admin_unblock")
async def admin_unblock_list(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    keyboard = admin_unblock_keyboard()
    if keyboard:
        await callback.message.edit_text("🔓 Выберите слот:", reply_markup=keyboard)
    else:
        await callback.message.edit_text("Нет заблокированных слотов", reply_markup=admin_main_keyboard())

@dp.callback_query(F.data.startswith("unblock_"))
async def admin_unblock_slot(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    callback_data = callback.data.replace("unblock_", "")
    if callback_data.startswith("day_"):
        date = callback_data.replace("day_", "")
        cursor.execute("DELETE FROM blocked_slots WHERE date=?", (date,))
        conn.commit()
        await callback.message.edit_text(f"✅ Весь день разблокирован: {date}")
    else:
        parts = callback_data.split("_")
        if len(parts) >= 2:
            cursor.execute("DELETE FROM blocked_slots WHERE date=? AND time=?", (parts[0], parts[1]))
            conn.commit()
            await callback.message.edit_text(f"✅ Слот разблокирован")

@dp.callback_query(F.data == "unblock_all")
async def admin_unblock_all(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    cursor.execute("DELETE FROM blocked_slots")
    conn.commit()
    await callback.message.edit_text("✅ Все слоты разблокированы", reply_markup=admin_main_keyboard())

# ---------- ЗАПУСК ----------
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

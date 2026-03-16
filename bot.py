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

TOKEN = ""
ADMIN_ID = 995387118

bot = Bot(TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Remove existing database file if it exists
if os.path.exists("lash_bookings.db"):
    os.remove("lash_bookings.db")

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
    date TEXT,
    time TEXT
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

# ---------- УСЛУГИ ----------
SERVICES = {
    "1": {"name": "Классическое наращивание", "price": 2500},
    "2": {"name": "Объём 2D", "price": 3000},
    "3": {"name": "Объём 3D", "price": 3500},
    "4": {"name": "Hollywood", "price": 4000}
}

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

def services_keyboard():
    buttons = []
    for k, v in SERVICES.items():
        buttons.append([InlineKeyboardButton(text=f"{v['name']} — {v['price']}₽", callback_data=f"service_{k}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def confirm_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_phone")]
        ]
    )

# ---------- АДМИН КЛАВИАТУРЫ ----------
def admin_main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 Записи по дням", callback_data="admin_by_date")],
            [InlineKeyboardButton(text="📋 Все записи", callback_data="admin_all")],
            [InlineKeyboardButton(text="🚫 Заблокировать слот", callback_data="admin_block")],
            [InlineKeyboardButton(text="✅ Разблокировать слоты", callback_data="admin_unblock")]
        ]
    )

def admin_dates_keyboard():
    buttons = []
    for i in range(7):
        date = datetime.now() + timedelta(days=i)
        date_str = date.strftime("%d.%m.%Y")
        cursor.execute("SELECT COUNT(*) FROM bookings WHERE date=?", (date_str,))
        bookings_count = cursor.fetchone()[0]
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        day_name = day_names[date.weekday()]
        buttons.append([InlineKeyboardButton(text=f"{date_str} ({day_name}) — {bookings_count} записей", callback_data=f"admin_date_{date_str}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_booking_keyboard(booking_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Имя", callback_data=f"edit_name_{booking_id}"),
                InlineKeyboardButton(text="📱 Телефон", callback_data=f"edit_phone_{booking_id}")
            ],
            [
                InlineKeyboardButton(text="💅 Услуга", callback_data=f"edit_service_{booking_id}"),
                InlineKeyboardButton(text="⏰ Время", callback_data=f"edit_time_{booking_id}")
            ],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin_delete_{booking_id}")],
            [InlineKeyboardButton(text="⬅️ К дням", callback_data="admin_by_date")]
        ]
    )

def admin_services_keyboard(booking_id):
    buttons = []
    for k, v in SERVICES.items():
        buttons.append([InlineKeyboardButton(text=f"{v['name']} — {v['price']}₽", callback_data=f"set_service_{k}_{booking_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_booking_{booking_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_time_keyboard(booking_id, date):
    cursor.execute("SELECT time FROM bookings WHERE date=? AND id!=?", (date, booking_id))
    busy = [x[0] for x in cursor.fetchall()]
    cursor.execute("SELECT time FROM blocked_slots WHERE date=?", (date,))
    blocked = [x[0] for x in cursor.fetchall()]
    buttons = []
    row = []
    for t in TIME_SLOTS:
        if t in blocked:
            text, callback = f"🚫 {t}", "ignore"
        elif t in busy:
            text, callback = f"❌ {t}", "ignore"
        else:
            text, callback = f"⏰ {t}", f"set_time_{t}_{booking_id}"
        row.append(InlineKeyboardButton(text=text, callback_data=callback))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_booking_{booking_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_block_dates_keyboard():
    buttons = []
    for i in range(14):
        date = datetime.now() + timedelta(days=i)
        date_str = date.strftime("%d.%m.%Y")
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        day_name = day_names[date.weekday()]
        buttons.append([InlineKeyboardButton(text=f"{date_str} ({day_name})", callback_data=f"block_date_{date_str}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_block_times_keyboard(date):
    cursor.execute("SELECT time FROM bookings WHERE date=?", (date,))
    busy = [x[0] for x in cursor.fetchall()]
    cursor.execute("SELECT time FROM blocked_slots WHERE date=?", (date,))
    blocked = [x[0] for x in cursor.fetchall()]
    buttons = []
    row = []
    for t in TIME_SLOTS:
        if t in blocked:
            text, callback = f"🚫 {t} (заблокирован)", "ignore"
        elif t in busy:
            text, callback = f"👤 {t} (занят)", "ignore"
        else:
            text, callback = f"⏰ {t}", f"block_time_{t}_{date}"
        row.append(InlineKeyboardButton(text=text, callback_data=callback))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="🚫 Заблокировать весь день", callback_data=f"block_all_{date}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_block")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_unblock_keyboard():
    cursor.execute("SELECT date, time, reason FROM blocked_slots ORDER BY date, time")
    rows = cursor.fetchall()
    if not rows:
        return None
    buttons = []
    for date, time, reason in rows:
        display_reason = reason[:15] + "..." if len(reason) > 15 else reason
        buttons.append([InlineKeyboardButton(text=f"🔓 {date} {time} ({display_reason})", callback_data=f"unblock_{date}_{time}")])
    buttons.append([InlineKeyboardButton(text="🔓 Разблокировать всё", callback_data="unblock_all")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ---------- ДАТЫ (КЛИЕНТ) ----------
def dates_keyboard():
    buttons = []
    for i in range(7):
        date = datetime.now() + timedelta(days=i)
        date_str = date.strftime("%d.%m.%Y")
        cursor.execute("SELECT COUNT(*) FROM bookings WHERE date=?", (date_str,))
        bookings_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM blocked_slots WHERE date=?", (date_str,))
        blocked_count = cursor.fetchone()[0]
        available = len(TIME_SLOTS) - bookings_count - blocked_count
        if available > 0:
            day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
            day_name = day_names[date.weekday()]
            buttons.append([InlineKeyboardButton(text=f"{date_str} ({day_name})", callback_data=f"date_{date_str}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_service")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ---------- ВРЕМЯ (КЛИЕНТ) ----------
def time_keyboard(date):
    cursor.execute("SELECT time FROM bookings WHERE date=?", (date,))
    busy = [x[0] for x in cursor.fetchall()]
    cursor.execute("SELECT time FROM blocked_slots WHERE date=?", (date,))
    blocked = [x[0] for x in cursor.fetchall()]
    buttons = []
    row = []
    for t in TIME_SLOTS:
        if t in blocked:
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
    text = "💰 Прайс:\n\n"
    for v in SERVICES.values():
        text += f"{v['name']} — {v['price']}₽\n"
    await message.answer(text)

# ---------- ЗАПИСЬ ----------
@dp.message(F.text == "📅 Записаться")
async def booking_start(message: types.Message, state: FSMContext):
    await message.answer("Выберите услугу:", reply_markup=services_keyboard())
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
    await callback.message.edit_text("Выберите услугу:", reply_markup=services_keyboard())
    await state.set_state(Booking.service)

@dp.callback_query(F.data == "back_to_date")
async def back_to_date(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text("Выберите дату:", reply_markup=dates_keyboard())
    await state.set_state(Booking.date)

@dp.callback_query(F.data == "back_to_phone")
async def back_to_phone(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Поделитесь номером телефона:", reply_markup=phone_keyboard())
    await state.set_state(Booking.phone)

@dp.message(Booking.username, F.text == "⬅️ Назад")
async def back_from_username(message: types.Message, state: FSMContext):
    data = await state.get_data()
    date = data.get("date", "")
    await message.answer(f"📅 {date}\nВыберите время:", reply_markup=time_keyboard(date))
    await state.set_state(Booking.time)

@dp.message(Booking.phone, F.text == "⬅️ Назад")
async def back_from_phone(message: types.Message, state: FSMContext):
    data = await state.get_data()
    username = data.get("username", "")
    if username:
        await message.answer("Поделитесь номером телефона:", reply_markup=phone_keyboard())
        await state.set_state(Booking.phone)
    else:
        await message.answer("Введите ваш Telegram username (@username):", reply_markup=back_keyboard())
        await state.set_state(Booking.username)

# ---------- ВЫБОР УСЛУГИ/ДАТЫ/ВРЕМЕНИ ----------
@dp.callback_query(F.data.startswith("service_"))
async def select_service(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    service_id = callback.data.split("_")[1]
    service = SERVICES[service_id]
    await state.update_data(service=service["name"])
    await callback.message.edit_text("Выберите дату:", reply_markup=dates_keyboard())
    await state.set_state(Booking.date)

@dp.callback_query(F.data.startswith("date_"))
async def select_date(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    date = callback.data.split("_")[1]
    await state.update_data(date=date)
    await callback.message.edit_text(f"📅 {date}\nВыберите время:", reply_markup=time_keyboard(date))
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
        await callback.message.answer(f"Имя: {name}\n\nПоделитесь номером телефона:", reply_markup=phone_keyboard())
        await state.set_state(Booking.phone)
    else:
        await callback.message.answer("Введите ваш Telegram username (@username):", reply_markup=back_keyboard())
        await state.set_state(Booking.username)

@dp.callback_query(F.data == "busy")
async def busy(callback: types.CallbackQuery):
    await callback.answer("Это время уже занято", show_alert=True)

@dp.callback_query(F.data == "blocked_slot")
async def blocked_slot(callback: types.CallbackQuery):
    await callback.answer("Этот слот заблокирован", show_alert=True)

@dp.callback_query(F.data == "ignore")
async def ignore_callback(callback: types.CallbackQuery):
    await callback.answer()

# ---------- USERNAME ----------
@dp.message(Booking.username)
async def get_username(message: types.Message, state: FSMContext):
    username = message.text.strip()
    if username != "⬅️ Назад":
        if not username.startswith("@"):
            username = "@" + username
        await state.update_data(username=username)
        await message.answer("Поделитесь номером телефона:", reply_markup=phone_keyboard())
        await state.set_state(Booking.phone)

# ---------- ТЕЛЕФОН ----------
@dp.message(Booking.phone, F.contact)
async def phone(message: types.Message, state: FSMContext):
    phone = message.contact.phone_number
    await state.update_data(phone=phone)
    data = await state.get_data()
    await message.answer("✅ Номер получен!", reply_markup=types.ReplyKeyboardRemove())
    text = (
        "📋 Подтвердите запись\n\n"
        f"👤 Имя: {data['name']}\n"
        f"🔗 {data.get('username', 'Нет')}\n"
        f"📱 Телефон: {phone}\n"
        f"💅 Услуга: {data['service']}\n"
        f"📅 Дата: {data['date']}\n"
        f"⏰ Время: {data['time']}"
    )
    await message.answer(text, reply_markup=confirm_keyboard())
    await state.set_state(Booking.confirm)

# ---------- ПОДТВЕРЖДЕНИЕ ----------
@dp.callback_query(Booking.confirm, F.data == "confirm")
async def confirm(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    cursor.execute(
        "INSERT INTO bookings(user_id, name, username, phone, service, date, time) VALUES (?,?,?,?,?,?,?)",
        (callback.from_user.id, data["name"], data.get("username", "Нет"), data["phone"], data["service"], data["date"], data["time"])
    )
    conn.commit()
    await callback.message.edit_text(
        "✅ Запись подтверждена!\n\n"
        f"📅 Дата: {data['date']}\n"
        f"⏰ Время: {data['time']}\n"
        f"💅 Услуга: {data['service']}\n\n"
        "Ждём вас в студии Wenty.Lash! ✨\n"
        "Чтобы посмотреть записи — /start"
    )
    admin_text = (
        "🔔 Новая запись!\n\n"
        f"👤 Имя: {data['name']}\n"
        f"🔗 {data.get('username', 'Нет')}\n"
        f"📱 Телефон: {data['phone']}\n"
        f"💅 Услуга: {data['service']}\n"
        f"📅 Дата: {data['date']}\n"
        f"⏰ Время: {data['time']}"
    )
    await bot.send_message(ADMIN_ID, admin_text)
    await state.clear()

@dp.callback_query(Booking.confirm, F.data == "cancel")
async def cancel(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text("❌ Запись отменена. Напишите /start")
    await state.clear()

# ---------- МОИ ЗАПИСИ ----------
@dp.message(F.text == "📋 Мои записи")
async def my_bookings(message: types.Message):
    cursor.execute("SELECT id, service, date, time FROM bookings WHERE user_id=? ORDER BY date, time", (message.from_user.id,))
    rows = cursor.fetchall()
    if not rows:
        await message.answer("У вас пока нет записей")
        return
    for r in rows:
        text = f"📅 {r[2]}\n⏰ {r[3]}\n💅 {r[1]}"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🔁 Перенести", callback_data=f"move_{r[0]}"),
                    InlineKeyboardButton(text="❌ Удалить", callback_data=f"delete_{r[0]}")
                ]
            ]
        )
        await message.answer(text, reply_markup=keyboard)

# ---------- УДАЛЕНИЕ (КЛИЕНТ) ----------
@dp.callback_query(F.data.startswith("delete_"))
async def delete_booking(callback: types.CallbackQuery):
    await callback.answer()
    booking_id = callback.data.split("_")[1]
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
            f"💅 Услуга: {service}\n"
            f"📅 Дата: {date}\n"
            f"⏰ Время: {time}"
        )
        await bot.send_message(ADMIN_ID, cancel_text)
    else:
        await callback.answer("Это не ваша запись", show_alert=True)

# ---------- ПЕРЕНОС ЗАПИСИ ----------
@dp.callback_query(F.data.startswith("move_"))
async def move_booking(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    booking_id = callback.data.split("_")[1]
    cursor.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
    conn.commit()
    await callback.message.answer("Выберите новую услугу:", reply_markup=services_keyboard())
    await state.set_state(Booking.service)

# ==========================================
# АДМИН ПАНЕЛЬ
# ==========================================

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
    cursor.execute("SELECT id, name, username, phone, service, date, time FROM bookings ORDER BY date, time")
    rows = cursor.fetchall()
    if not rows:
        await callback.message.answer("Записей пока нет", reply_markup=admin_main_keyboard())
        return
    for r in rows:
        text = f"👤 {r[1]}\n🔗 {r[2]}\n📱 {r[3]}\n💅 {r[4]}\n📅 {r[5]} {r[6]}"
        await callback.message.answer(text, reply_markup=admin_booking_keyboard(r[0]))

@dp.callback_query(F.data.startswith("admin_date_"))
async def admin_view_date(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    date = callback.data.split("_")[2]
    cursor.execute("SELECT id, name, username, phone, service, time FROM bookings WHERE date=? ORDER BY time", (date,))
    rows = cursor.fetchall()
    cursor.execute("SELECT time, reason FROM blocked_slots WHERE date=?", (date,))
    blocked = cursor.fetchall()
    
    text = f"📅 {date}\n\n"
    if rows:
        text += "📝 Записи:\n"
        for r in rows:
            text += f"  ⏰ {r[5]} — {r[1]} ({r[4]})\n"
    else:
        text += "📝 Записей нет\n"
    if blocked:
        text += "\n🚫 Заблокировано:\n"
        for b in blocked:
            text += f"  ⏰ {b[0]} — {b[1]}\n"
    
    await callback.message.answer(text)
    if rows:
        for r in rows:
            booking_text = f"👤 {r[1]}\n🔗 {r[2]}\n📱 {r[3]}\n💅 {r[4]}\n⏰ {r[5]}"
            await callback.message.answer(booking_text, reply_markup=admin_booking_keyboard(r[0]))

# ---------- РЕДАКТИРОВАНИЕ ----------
@dp.callback_query(F.data.startswith("view_booking_"))
async def view_booking(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    booking_id = callback.data.split("_")[2]
    cursor.execute("SELECT id, name, username, phone, service, date, time FROM bookings WHERE id=?", (booking_id,))
    r = cursor.fetchone()
    if r:
        text = f"👤 {r[1]}\n🔗 {r[2]}\n📱 {r[3]}\n💅 {r[4]}\n📅 {r[5]} {r[6]}"
        await callback.message.edit_text(text, reply_markup=admin_booking_keyboard(r[0]))

@dp.callback_query(F.data.startswith("edit_name_"))
async def edit_name(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    booking_id = callback.data.split("_")[2]
    await state.update_data(edit_booking_id=booking_id)
    await callback.message.answer("Введите новое имя:")
    await state.set_state(AdminEdit.edit_name)

@dp.message(AdminEdit.edit_name)
async def save_name(message: types.Message, state: FSMContext):
    data = await state.get_data()
    booking_id = data["edit_booking_id"]
    cursor.execute("UPDATE bookings SET name=? WHERE id=?", (message.text, booking_id))
    conn.commit()
    await message.answer("✅ Имя обновлено")
    await state.clear()

@dp.callback_query(F.data.startswith("edit_phone_"))
async def edit_phone(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    booking_id = callback.data.split("_")[2]
    await state.update_data(edit_booking_id=booking_id)
    await callback.message.answer("Введите новый телефон:")
    await state.set_state(AdminEdit.edit_phone)

@dp.message(AdminEdit.edit_phone)
async def save_phone(message: types.Message, state: FSMContext):
    data = await state.get_data()
    booking_id = data["edit_booking_id"]
    cursor.execute("UPDATE bookings SET phone=? WHERE id=?", (message.text, booking_id))
    conn.commit()
    await message.answer("✅ Телефон обновлён")
    await state.clear()

@dp.callback_query(F.data.startswith("edit_service_"))
async def edit_service(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    booking_id = callback.data.split("_")[2]
    await callback.message.edit_text("Выберите новую услугу:", reply_markup=admin_services_keyboard(booking_id))

@dp.callback_query(F.data.startswith("set_service_"))
async def save_service(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    parts = callback.data.split("_")
    service_id = parts[2]
    booking_id = parts[3]
    new_service = SERVICES[service_id]["name"]
    
    cursor.execute("SELECT user_id, name, service, date, time FROM bookings WHERE id=?", (booking_id,))
    row = cursor.fetchone()
    
    if row:
        user_id, name, old_service, date, time = row[0], row[1], row[2], row[3], row[4]
        
        cursor.execute("UPDATE bookings SET service=? WHERE id=?", (new_service, booking_id))
        conn.commit()
        await callback.message.edit_text("✅ Услуга обновлена")
        
        try:
            await bot.send_message(
                user_id,
                f"💅 Услуга вашей записи изменена\n\n"
                f"💅 Было: {old_service}\n"
                f"💅 Стало: {new_service}\n"
                f"📅 Дата: {date}\n"
                f"⏰ Время: {time}\n\n"
                f"Для новой записи напишите /start"
            )
        except:
            pass

@dp.callback_query(F.data.startswith("edit_time_"))
async def edit_time(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    booking_id = callback.data.split("_")[2]
    cursor.execute("SELECT date FROM bookings WHERE id=?", (booking_id,))
    row = cursor.fetchone()
    if row:
        await callback.message.edit_text("Выберите новое время:", reply_markup=admin_time_keyboard(booking_id, row[0]))

@dp.callback_query(F.data.startswith("set_time_"))
async def save_time(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    parts = callback.data.split("_")
    time = parts[2]
    booking_id = parts[3]
    
    cursor.execute("SELECT user_id, name, service, date, time FROM bookings WHERE id=?", (booking_id,))
    row = cursor.fetchone()
    
    if row:
        user_id, name, service, date, old_time = row[0], row[1], row[2], row[3], row[4]
        
        cursor.execute("UPDATE bookings SET time=? WHERE id=?", (time, booking_id))
        conn.commit()
        await callback.message.edit_text("✅ Время обновлено")
        
        try:
            await bot.send_message(
                user_id,
                f"⏰ Время вашей записи изменено\n\n"
                f"💅 Услуга: {service}\n"
                f"📅 Дата: {date}\n"
                f"⏰ Было: {old_time}\n"
                f"⏰ Стало: {time}"
            )
        except:
            pass

# ---------- УДАЛЕНИЕ (АДМИН) ----------
@dp.callback_query(F.data.startswith("admin_delete_"))
async def admin_delete(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    await callback.answer()
    booking_id = callback.data.split("_")[2]
    
    cursor.execute("SELECT user_id, name, service, date, time FROM bookings WHERE id=?", (booking_id,))
    row = cursor.fetchone()
    
    if row:
        user_id, name, service, date, time = row[0], row[1], row[2], row[3], row[4]
        
        cursor.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
        conn.commit()
        await callback.message.edit_text("🗑 Запись удалена")
        
        try:
            await bot.send_message(
                user_id,
                f"❌ Ваша запись была отменена\n\n"
                f"💅 Услуга: {service}\n"
                f"📅 Дата: {date}\n"
                f"⏰ Время: {time}\n\n"
                f"Для новой записи /start"
            )
            await callback.message.answer("✅ Клиент уведомлён об отмене")
        except Exception as e:
            await callback.message.answer(f"⚠️ Не удалось уведомить клиента: {e}")
    else:
        await callback.message.edit_text("Запись не найдена")

# ---------- БЛОКИРОВКА СЛОТОВ ----------
@dp.callback_query(F.data == "admin_block")
async def admin_block_start(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    await callback.message.edit_text("🚫 Выберите день:", reply_markup=admin_block_dates_keyboard())

@dp.callback_query(F.data.startswith("block_date_"))
async def admin_block_date(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    date = callback.data.split("_")[2]
    await callback.message.edit_text(f"🚫 {date}\nВыберите время:", reply_markup=admin_block_times_keyboard(date))

@dp.callback_query(F.data.startswith("block_time_"))
async def admin_block_time(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    parts = callback.data.split("_")
    time = parts[2]
    date = parts[3]
    await state.update_data(block_date=date, block_time=time)
    await callback.message.answer(f"Введите причину блокировки для {date} {time}:")
    await state.set_state(AdminBlock.enter_reason)

@dp.message(AdminBlock.enter_reason)
async def admin_block_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    date = data["block_date"]
    time = data.get("block_time")
    reason = message.text
    
    if time:
        cursor.execute("INSERT INTO blocked_slots(date, time, reason) VALUES (?, ?, ?)", (date, time, reason))
    else:
        for t in TIME_SLOTS:
            cursor.execute("INSERT OR IGNORE INTO blocked_slots(date, time, reason) VALUES (?, ?, ?)", (date, t, reason))
    conn.commit()
    await message.answer(f"✅ Заблокировано:\n📅 {date}\n⏰ {time or 'весь день'}\n📝 {reason}")
    await state.clear()

@dp.callback_query(F.data.startswith("block_all_"))
async def admin_block_all(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    date = callback.data.split("_")[2]
    await state.update_data(block_date=date)
    await callback.message.answer(f"Введите причину блокировки дня {date}:")
    await state.set_state(AdminBlock.enter_reason)

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
    parts = callback.data.split("_")
    date = parts[1]
    time = parts[2]
    cursor.execute("DELETE FROM blocked_slots WHERE date=? AND time=?", (date, time))
    conn.commit()
    await callback.message.edit_text(f"✅ Слот разблокирован: {date} {time}")

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

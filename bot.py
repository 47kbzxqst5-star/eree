#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram-бот для аутсорсинг-биржи Coded
Полноценная бизнес-версия с анкетами, модерацией и сделками
"""

import re
import sqlite3
import logging
from datetime import datetime
from typing import Optional, Dict, List, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    CallbackQueryHandler, ConversationHandler
)

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = "8673602188:AAESrTPIYuHvnYFNaJtPh_TT-M9ZCNou-Vo"
SUPER_ADMIN_ID = 8350371908
CHANNEL_ID = -1003998507793

# Состояния для диалогов
NAME, CONTACT, ROLE, TECH_STACK, BUDGET, DESCRIPTION = range(6)  # для заявки
REG_NAME, REG_CONTACT, REG_STACK, REG_EXP, REG_PORTFOLIO, REG_SALARY = range(6, 12)  # для регистрации исполнителя

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

DB_PATH = "outsourcing.db"

# ========== РАБОТА С БАЗОЙ ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Таблица проектов (заявок)
    c.execute('''CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER,
        name TEXT,
        contact TEXT,
        role TEXT,
        tech_stack TEXT,
        budget TEXT,
        description TEXT,
        created_at TIMESTAMP,
        status TEXT DEFAULT 'open'
    )''')
    # Таблица откликов (связь: проект -> исполнитель)
    c.execute('''CREATE TABLE IF NOT EXISTS responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        user_id INTEGER,
        username TEXT,
        contact TEXT,
        responded_at TIMESTAMP,
        status TEXT DEFAULT 'pending'  -- pending, approved, rejected
    )''')
    # Таблица исполнителей (анкеты)
    c.execute('''CREATE TABLE IF NOT EXISTS contractors (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        contact TEXT,
        stack TEXT,
        experience TEXT,
        portfolio TEXT,
        salary_expectation TEXT,
        registered_at TIMESTAMP,
        rating REAL DEFAULT 0
    )''')
    # Таблица сделок (успешные наймы)
    c.execute('''CREATE TABLE IF NOT EXISTS deals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        contractor_id INTEGER,
        client_id INTEGER,
        amount INTEGER,
        commission INTEGER,
        status TEXT DEFAULT 'closed',
        created_at TIMESTAMP
    )''')
    # Подписчики на новые проекты
    c.execute('''CREATE TABLE IF NOT EXISTS subscribers (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        role TEXT,
        subscribed_at TIMESTAMP
    )''')
    # Администраторы
    c.execute('''CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        added_by INTEGER,
        added_at TIMESTAMP
    )''')
    # Добавляем суперадмина
    c.execute("SELECT user_id FROM admins WHERE user_id=?", (SUPER_ADMIN_ID,))
    if not c.fetchone():
        c.execute("INSERT INTO admins (user_id, added_by, added_at) VALUES (?, ?, ?)",
                  (SUPER_ADMIN_ID, SUPER_ADMIN_ID, datetime.now()))
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

# ---- Вспомогательные функции ----
def is_admin(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
    r = c.fetchone()
    conn.close()
    return r is not None

def add_admin(admin_id: int, added_by: int) -> bool:
    if added_by != SUPER_ADMIN_ID:
        return False
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO admins (user_id, added_by, added_at) VALUES (?,?,?)",
                  (admin_id, added_by, datetime.now()))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def remove_admin(admin_id: int, removed_by: int) -> bool:
    if removed_by != SUPER_ADMIN_ID or admin_id == SUPER_ADMIN_ID:
        return False
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM admins WHERE user_id=?", (admin_id,))
    ok = c.rowcount > 0
    conn.commit()
    conn.close()
    return ok

def get_all_admins() -> List[int]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM admins")
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

def save_project(client_id: int, data: dict) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO projects 
        (client_id, name, contact, role, tech_stack, budget, description, created_at, status)
        VALUES (?,?,?,?,?,?,?,?,?)''',
        (client_id, data['name'], data['contact'], data['role'], data['tech_stack'],
         data['budget'], data['description'], datetime.now(), 'open'))
    pid = c.lastrowid
    conn.commit()
    conn.close()
    return pid

def get_project(project_id: int) -> Optional[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM projects WHERE id=?", (project_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            'id': row[0],
            'client_id': row[1],
            'name': row[2],
            'contact': row[3],
            'role': row[4],
            'tech_stack': row[5],
            'budget': row[6],
            'description': row[7],
            'created_at': row[8],
            'status': row[9]
        }
    return None

def get_projects_by_client(client_id: int) -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, role, budget, status, created_at FROM projects WHERE client_id=? ORDER BY created_at DESC", (client_id,))
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'role': r[1], 'budget': r[2], 'status': r[3], 'created_at': r[4]} for r in rows]

def close_project(project_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE projects SET status='closed' WHERE id=?", (project_id,))
    conn.commit()
    conn.close()

def get_open_projects() -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, role, budget, created_at FROM projects WHERE status='open' ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'role': r[1], 'budget': r[2], 'created_at': r[3]} for r in rows]

def save_response(project_id: int, user_id: int, username: str, contact: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO responses (project_id, user_id, username, contact, responded_at, status)
                 VALUES (?,?,?,?,?,?)''', (project_id, user_id, username, contact, datetime.now(), 'pending'))
    conn.commit()
    conn.close()

def get_responses_for_project(project_id: int) -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, user_id, username, contact, status, responded_at FROM responses WHERE project_id=? ORDER BY responded_at", (project_id,))
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'user_id': r[1], 'username': r[2], 'contact': r[3], 'status': r[4], 'responded_at': r[5]} for r in rows]

def update_response_status(response_id: int, status: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE responses SET status=? WHERE id=?", (status, response_id))
    conn.commit()
    conn.close()

def save_contractor(user_id: int, username: str, data: dict):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO contractors 
        (user_id, username, full_name, contact, stack, experience, portfolio, salary_expectation, registered_at)
        VALUES (?,?,?,?,?,?,?,?,?)''',
        (user_id, username, data['full_name'], data['contact'], data['stack'],
         data['experience'], data['portfolio'], data['salary'], datetime.now()))
    conn.commit()
    conn.close()

def get_contractor(user_id: int) -> Optional[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM contractors WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            'user_id': row[0],
            'username': row[1],
            'full_name': row[2],
            'contact': row[3],
            'stack': row[4],
            'experience': row[5],
            'portfolio': row[6],
            'salary_expectation': row[7],
            'registered_at': row[8],
            'rating': row[9]
        }
    return None

def is_registered_contractor(user_id: int) -> bool:
    return get_contractor(user_id) is not None

def add_deal(project_id: int, contractor_id: int, client_id: int, amount: int, commission: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO deals (project_id, contractor_id, client_id, amount, commission, created_at)
                 VALUES (?,?,?,?,?,?)''', (project_id, contractor_id, client_id, amount, commission, datetime.now()))
    conn.commit()
    conn.close()

def add_subscriber(user_id: int, username: str, role: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO subscribers (user_id, username, role, subscribed_at) VALUES (?,?,?,?)",
              (user_id, username, role.lower(), datetime.now()))
    conn.commit()
    conn.close()

def remove_subscriber(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM subscribers WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def get_subscribers_by_role(role: str) -> List[Tuple[int, str]]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username FROM subscribers WHERE role=? OR role='all'", (role.lower(),))
    rows = c.fetchall()
    conn.close()
    return rows

# ========== ОБРАБОТЧИКИ ДЛЯ ЗАКАЗЧИКА ==========
async def start(update: Update, context):
    await update.message.reply_text(
        "👋 Добро пожаловать в аутсорсинг-биржу Coded!\n\n"
        "📌 **Заказчики**:\n/new_project – создать заявку на исполнителя\n"
        "/my_projects – мои проекты\n\n"
        "💼 **Исполнители**:\n/register – заполнить анкету\n/subscribe <роль> – подписка на новые проекты\n"
        "/unsubscribe – отписаться\n\n"
        "💰 Комиссия платформы: 15% от бюджета при успешной сделке.\n"
        "Вопросы: @coded_support"
    )

# ---- Создание заявки ----
async def new_project(update: Update, context):
    context.user_data['client_id'] = update.effective_user.id
    await update.message.reply_text("Введите название вашей компании или ваше имя:")
    return NAME

async def get_name(update, context):
    context.user_data['name'] = update.message.text
    await update.message.reply_text("Ваши контакты (Telegram username или email):")
    return CONTACT

async def get_contact(update, context):
    context.user_data['contact'] = update.message.text
    await update.message.reply_text("Какую роль нужно найти? (Frontend, Backend, Fullstack, Mobile, DevOps, AI/ML, Дизайнер, Другое):")
    return ROLE

async def get_role(update, context):
    context.user_data['role'] = update.message.text
    await update.message.reply_text("Какой стек технологий предпочтителен?")
    return TECH_STACK

async def get_tech_stack(update, context):
    context.user_data['tech_stack'] = update.message.text
    await update.message.reply_text("Какой бюджет проекта (в ₽)?")
    return BUDGET

async def get_budget(update, context):
    budget = update.message.text.strip()
    if not re.match(r"^\d{4,8}$", budget.replace(" ", "")):
        await update.message.reply_text("Введите бюджет числом (от 1000 до 100 млн). Попробуйте ещё раз:")
        return BUDGET
    context.user_data['budget'] = budget
    await update.message.reply_text("Опишите проект кратко (задачи, сроки, требования):")
    return DESCRIPTION

async def get_description(update, context):
    context.user_data['description'] = update.message.text
    client_id = context.user_data['client_id']
    pid = save_project(client_id, context.user_data)
    
    # Публикация в канал
    text = (
        f"🔧 **Новый проект Coded**\n\n"
        f"🆔 №{pid}\n"
        f"📌 Роль: {context.user_data['role']}\n"
        f"⚙️ Стек: {context.user_data['tech_stack']}\n"
        f"💰 Бюджет: {context.user_data['budget']} ₽\n"
        f"📝 Описание: {context.user_data['description']}\n\n"
        f"⏳ Создан: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 Откликнуться", callback_data=f"bid_{pid}")]
    ])
    await context.bot.send_message(CHANNEL_ID, text, parse_mode="Markdown", reply_markup=keyboard)
    
    await update.message.reply_text(
        f"✅ Заявка №{pid} опубликована. Исполнители могут откликаться.\n"
        f"Комиссия 15% от бюджета при успешной сделке.\n"
        f"Управлять проектом можно через /my_projects."
    )
    # Уведомление админов
    for admin_id in get_all_admins():
        await context.bot.send_message(admin_id, f"🆕 Новая заявка #{pid} от {context.user_data['name']} ({context.user_data['contact']})")
    
    # Уведомление подписанных исполнителей
    role_low = context.user_data['role'].lower()
    for uid, uname in get_subscribers_by_role(role_low):
        try:
            await context.bot.send_message(uid, f"🔔 Новый проект: {role_low}, бюджет {context.user_data['budget']} ₽. Подробности в канале.")
        except:
            pass
    return ConversationHandler.END

async def cancel_project(update, context):
    await update.message.reply_text("Создание заявки отменено.")
    return ConversationHandler.END

# ---- Личный кабинет заказчика ----
async def my_projects(update, context):
    user_id = update.effective_user.id
    projects = get_projects_by_client(user_id)
    if not projects:
        await update.message.reply_text("У вас пока нет заявок. Создайте: /new_project")
        return
    text = "📋 **Ваши проекты:**\n\n"
    for p in projects:
        status_emoji = "🟢" if p['status'] == 'open' else "🔴"
        text += f"{status_emoji} #{p['id']} – {p['role']} | {p['budget']} ₽ | {p['status']}\n"
    text += "\nДля управления проектом используйте /project_<id> (например, /project_123)"
    # Временно: просто показать список. Команда /project_<id> не реализована в этом примере, но можно добавить.
    await update.message.reply_text(text, parse_mode="Markdown")

# ========== РЕГИСТРАЦИЯ ИСПОЛНИТЕЛЯ ==========
async def register_start(update, context):
    await update.message.reply_text("Давайте заполним вашу анкету исполнителя.\n\nВведите ваше полное имя (или название студии):")
    return REG_NAME

async def reg_get_name(update, context):
    context.user_data['full_name'] = update.message.text
    await update.message.reply_text("Контактные данные (Telegram username, email, телефон):")
    return REG_CONTACT

async def reg_get_contact(update, context):
    context.user_data['contact'] = update.message.text
    await update.message.reply_text("Ваш основной стек технологий (например: Python, Django, PostgreSQL):")
    return REG_STACK

async def reg_get_stack(update, context):
    context.user_data['stack'] = update.message.text
    await update.message.reply_text("Опыт работы (лет):")
    return REG_EXP

async def reg_get_exp(update, context):
    context.user_data['experience'] = update.message.text
    await update.message.reply_text("Портфолио (ссылка на GitHub, Behance, резюме):")
    return REG_PORTFOLIO

async def reg_get_portfolio(update, context):
    context.user_data['portfolio'] = update.message.text
    await update.message.reply_text("Желаемый доход (в ₽):")
    return REG_SALARY

async def reg_get_salary(update, context):
    context.user_data['salary'] = update.message.text
    user = update.effective_user
    save_contractor(user.id, user.username or str(user.id), {
        'full_name': context.user_data['full_name'],
        'contact': context.user_data['contact'],
        'stack': context.user_data['stack'],
        'experience': context.user_data['experience'],
        'portfolio': context.user_data['portfolio'],
        'salary': context.user_data['salary']
    })
    await update.message.reply_text(
        "✅ Анкета сохранена! Теперь вы можете:\n"
        "– Подписаться на проекты: /subscribe <роль>\n"
        "– Откликаться на проекты кнопкой в канале\n\n"
        "Ваша анкета будет передана заказчику при отклике."
    )
    return ConversationHandler.END

async def cancel_register(update, context):
    await update.message.reply_text("Регистрация отменена.")
    return ConversationHandler.END

# ========== ОБРАБОТКА ОТКЛИКОВ (КНОПКА В КАНАЛЕ) ==========
async def handle_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("bid_"):
        pid = int(data.split("_")[1])
        user = update.effective_user
        if not is_registered_contractor(user.id):
            await query.edit_message_text(
                "❌ Вы не зарегистрированы как исполнитель. Используйте /register, чтобы заполнить анкету, затем нажмите 'Откликнуться' снова.",
                reply_markup=None
            )
            return
        contact = f"@{user.username}" if user.username else str(user.id)
        save_response(pid, user.id, user.username or str(user.id), contact)
        await query.edit_message_text(f"✅ Ваш отклик на проект №{pid} принят! Администратор рассмотрит вашу анкету и свяжется с вами при выборе.")
        # Уведомление всех админов
        contractor_info = get_contractor(user.id)
        for admin_id in get_all_admins():
            text = (
                f"📢 **Новый отклик** на проект #{pid}\n"
                f"Исполнитель: @{user.username or user.id}\n"
                f"Имя: {contractor_info['full_name']}\n"
                f"Стек: {contractor_info['stack']}\n"
                f"Опыт: {contractor_info['experience']} лет\n"
                f"Портфолио: {contractor_info['portfolio']}\n"
                f"Зарплатные ожидания: {contractor_info['salary_expectation']} ₽\n"
                f"Контакт: {contractor_info['contact']}\n\n"
                f"Для просмотра всех откликов используйте /review_responses {pid}"
            )
            await context.bot.send_message(admin_id, text, parse_mode="Markdown")
    else:
        await query.edit_message_text("Неизвестная команда", reply_markup=None)

# ========== АДМИНСКИЕ ФУНКЦИИ ДЛЯ РАССМОТРЕНИЯ ОТКЛИКОВ ==========
async def review_responses(update: Update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Недостаточно прав.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /review_responses <project_id>")
        return
    try:
        pid = int(context.args[0])
    except:
        await update.message.reply_text("ID должен быть числом.")
        return
    responses = get_responses_for_project(pid)
    if not responses:
        await update.message.reply_text(f"На проект #{pid} пока нет откликов.")
        return
    text = f"📋 **Отклики на проект #{pid}**\n\n"
    for r in responses:
        contractor = get_contractor(r['user_id'])
        if contractor:
            text += f"👤 @{r['username']} | {contractor['stack']} | опыт {contractor['experience']} лет\n"
        else:
            text += f"👤 @{r['username']} (анкета не заполнена?)\n"
        text += f"Статус: {r['status']}\n"
        text += f"Команды для администратора:\n/approve_{pid}_{r['user_id']} – предложить заказчику\n/reject_{pid}_{r['user_id']} – отклонить\n\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def approve_response(update: Update, context):
    # Ожидается команда /approve_<project_id>_<user_id>
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Недостаточно прав.")
        return
    # Парсим команду (в реальном боте нужно использовать аргументы, но для простоты сделаем через args)
    if not context.args:
        await update.message.reply_text("Использование: /approve <project_id> <user_id>")
        return
    try:
        pid = int(context.args[0])
        uid = int(context.args[1])
    except:
        await update.message.reply_text("Неверные аргументы. /approve <project_id> <user_id>")
        return
    # Находим отклик
    responses = get_responses_for_project(pid)
    resp_id = None
    for r in responses:
        if r['user_id'] == uid:
            resp_id = r['id']
            break
    if not resp_id:
        await update.message.reply_text("Отклик не найден.")
        return
    update_response_status(resp_id, 'approved')
    # Получаем данные проекта и заказчика
    project = get_project(pid)
    if not project:
        await update.message.reply_text("Проект не найден.")
        return
    client_id = project['client_id']
    contractor = get_contractor(uid)
    # Отправляем предложение заказчику
    text = (
        f"✅ **По вашему проекту #{pid}** найден кандидат!\n\n"
        f"Исполнитель: @{contractor['username'] if contractor else str(uid)}\n"
        f"Стек: {contractor['stack']}\n"
        f"Опыт: {contractor['experience']} лет\n"
        f"Портфолио: {contractor['portfolio']}\n"
        f"Зарплатные ожидания: {contractor['salary_expectation']} ₽\n\n"
        f"Если хотите нанять этого специалиста, нажмите /accept_{pid}_{uid}\n"
        f"Если нет – просто проигнорируйте или напишите администратору @coded_support.\n\n"
        f"Комиссия платформы: 15% от бюджета."
    )
    await context.bot.send_message(client_id, text, parse_mode="Markdown")
    await update.message.reply_text(f"Кандидат @{contractor['username'] if contractor else str(uid)} предложен заказчику проекта #{pid}.")

async def accept_deal(update: Update, context):
    # Команда /accept_<project_id>_<user_id>
    if not context.args:
        await update.message.reply_text("Использование: /accept <project_id> <user_id>")
        return
    try:
        pid = int(context.args[0])
        uid = int(context.args[1])
    except:
        await update.message.reply_text("Неверные аргументы.")
        return
    project = get_project(pid)
    if not project:
        await update.message.reply_text("Проект не найден.")
        return
    # Фиксируем сделку
    budget_text = project['budget'].replace(' ', '')
    try:
        amount = int(budget_text)
    except:
        amount = 0
    commission = int(amount * 0.15)
    add_deal(pid, uid, project['client_id'], amount, commission)
    # Обновляем статус проекта и заявки
    close_project(pid)
    # Уведомление администратора
    for admin_id in get_all_admins():
        await context.bot.send_message(admin_id, f"🎉 Сделка по проекту #{pid} заключена! Исполнитель {uid}, сумма {amount}, комиссия {commission}.")
    await update.message.reply_text(
        f"✅ Сделка по проекту #{pid} подтверждена!\n"
        f"Благодарим за использование Coded.\n"
        f"Комиссия (15%) = {commission} ₽ будет удержана с заказчика.\n"
        f"Свяжитесь с исполнителем напрямую для деталей."
    )
    # Уведомление исполнителя
    await context.bot.send_message(uid, f"🎉 Поздравляем! Заказчик принял вашу кандидатуру по проекту #{pid}. Свяжитесь с заказчиком для старта работы.")

# ========== ПОДПИСКА ==========
async def subscribe(update, context):
    if not context.args:
        await update.message.reply_text("Укажите роль: /subscribe backend, /subscribe frontend, /subscribe all")
        return
    role = context.args[0].lower()
    user = update.effective_user
    add_subscriber(user.id, user.username or str(user.id), role)
    await update.message.reply_text(f"✅ Вы подписались на новые проекты по роли: {role}")

async def unsubscribe(update, context):
    user = update.effective_user
    remove_subscriber(user.id)
    await update.message.reply_text("✅ Вы отписаны от уведомлений.")

# ========== АДМИН-КОМАНДЫ (статистика и управление) ==========
async def stats(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Недостаточно прав.")
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM projects WHERE status='open'")
    open_pr = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM contractors")
    contractors = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM deals")
    deals = c.fetchone()[0]
    conn.close()
    await update.message.reply_text(
        f"📊 **Статистика Coded**\n"
        f"Открытых проектов: {open_pr}\n"
        f"Исполнителей: {contractors}\n"
        f"Завершённых сделок: {deals}"
    )

async def list_open(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Недостаточно прав.")
        return
    projects = get_open_projects()
    if not projects:
        await update.message.reply_text("Нет открытых проектов.")
        return
    text = "🔓 Открытые проекты:\n"
    for p in projects:
        text += f"#{p['id']} – {p['role']}, {p['budget']} ₽\n"
    await update.message.reply_text(text)

async def close_project_cmd(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Недостаточно прав.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /close_project <id>")
        return
    try:
        pid = int(context.args[0])
        close_project(pid)
        await update.message.reply_text(f"Проект #{pid} закрыт.")
    except:
        await update.message.reply_text("ID должен быть числом.")

async def add_admin_cmd(update, context):
    if update.effective_user.id != SUPER_ADMIN_ID:
        await update.message.reply_text("Только суперадмин.")
        return
    if not context.args:
        await update.message.reply_text("/add_admin <user_id>")
        return
    try:
        uid = int(context.args[0])
        if add_admin(uid, SUPER_ADMIN_ID):
            await update.message.reply_text(f"Админ {uid} добавлен.")
        else:
            await update.message.reply_text("Не удалось добавить.")
    except:
        await update.message.reply_text("ID должен быть числом.")

async def del_admin_cmd(update, context):
    if update.effective_user.id != SUPER_ADMIN_ID:
        await update.message.reply_text("Только суперадмин.")
        return
    if not context.args:
        await update.message.reply_text("/del_admin <user_id>")
        return
    try:
        uid = int(context.args[0])
        if remove_admin(uid, SUPER_ADMIN_ID):
            await update.message.reply_text(f"Админ {uid} удалён.")
        else:
            await update.message.reply_text("Не удалось удалить.")
    except:
        await update.message.reply_text("ID должен быть числом.")

# ========== ЗАПУСК ==========
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    # Диалог создания заявки
    conv_new = ConversationHandler(
        entry_points=[CommandHandler('new_project', new_project)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_contact)],
            ROLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_role)],
            TECH_STACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_tech_stack)],
            BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_budget)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_description)],
        },
        fallbacks=[CommandHandler('cancel', cancel_project)],
    )
    # Диалог регистрации исполнителя
    conv_reg = ConversationHandler(
        entry_points=[CommandHandler('register', register_start)],
        states={
            REG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_get_name)],
            REG_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_get_contact)],
            REG_STACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_get_stack)],
            REG_EXP: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_get_exp)],
            REG_PORTFOLIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_get_portfolio)],
            REG_SALARY: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_get_salary)],
        },
        fallbacks=[CommandHandler('cancel', cancel_register)],
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('my_projects', my_projects))
    app.add_handler(CommandHandler('subscribe', subscribe))
    app.add_handler(CommandHandler('unsubscribe', unsubscribe))
    app.add_handler(conv_new)
    app.add_handler(conv_reg)
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Админские команды
    app.add_handler(CommandHandler('stats', stats))
    app.add_handler(CommandHandler('list_open', list_open))
    app.add_handler(CommandHandler('close_project', close_project_cmd))
    app.add_handler(CommandHandler('add_admin', add_admin_cmd))
    app.add_handler(CommandHandler('del_admin', del_admin_cmd))
    app.add_handler(CommandHandler('review_responses', review_responses))
    app.add_handler(CommandHandler('approve', approve_response))  # /approve <project_id> <user_id>
    app.add_handler(CommandHandler('accept', accept_deal))        # /accept <project_id> <user_id>

    logger.info("Бот запущен в полноценном бизнес-режиме")
    app.run_polling()

if __name__ == '__main__':
    main()

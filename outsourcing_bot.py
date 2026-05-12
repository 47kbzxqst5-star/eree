#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram-бот для аутсорсинг-биржи Coded
Версия: финальная для Python 3.12, python-telegram-bot 20.7
Исправлены таймауты и совместимость
"""

import re
import sqlite3
import logging
import os
from flask import Flask, request
import threading

app_flask = Flask(__name__)

@app_flask.route('/')
def health():
    return "Bot is running", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    CallbackQueryHandler, ConversationHandler
)
from telegram.request import HTTPXRequest

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = "8673602188:AAESrTPIYuHvnYFNaJtPh_TT-M9ZCNou-Vo"
SUPER_ADMIN_ID = 8350371908
CHANNEL_ID = -1003998507793  # ID приватного канала

# Состояния диалога
NAME, CONTACT, ROLE, TECH_STACK, BUDGET, DESCRIPTION = range(6)

# Настройка логирования
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
    c.execute('''CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, contact TEXT, role TEXT, tech_stack TEXT,
        budget TEXT, description TEXT, created_at TIMESTAMP, status TEXT DEFAULT 'open')''')
    c.execute('''CREATE TABLE IF NOT EXISTS responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER, user_id INTEGER, username TEXT, contact TEXT, responded_at TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS subscribers (
        user_id INTEGER PRIMARY KEY, username TEXT, role TEXT, subscribed_at TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY, added_by INTEGER, added_at TIMESTAMP)''')
    c.execute("SELECT user_id FROM admins WHERE user_id=?", (SUPER_ADMIN_ID,))
    if not c.fetchone():
        c.execute("INSERT INTO admins (user_id, added_by, added_at) VALUES (?, ?, ?)",
                  (SUPER_ADMIN_ID, SUPER_ADMIN_ID, datetime.now()))
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

def is_admin(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row is not None

def add_admin(user_id, added_by):
    if added_by != SUPER_ADMIN_ID:
        return False
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO admins (user_id, added_by, added_at) VALUES (?, ?, ?)",
                  (user_id, added_by, datetime.now()))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def remove_admin(user_id, removed_by):
    if removed_by != SUPER_ADMIN_ID or user_id == SUPER_ADMIN_ID:
        return False
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def save_project(data):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO projects 
        (name, contact, role, tech_stack, budget, description, created_at, status)
        VALUES (?,?,?,?,?,?,?,?)''',
        (data['name'], data['contact'], data['role'], data['tech_stack'],
         data['budget'], data['description'], datetime.now(), 'open'))
    pid = c.lastrowid
    conn.commit()
    conn.close()
    return pid

def save_response(project_id, user_id, username, contact):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO responses (project_id, user_id, username, contact, responded_at)
                 VALUES (?,?,?,?,?)''', (project_id, user_id, username, contact, datetime.now()))
    conn.commit()
    conn.close()

def get_project(project_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM projects WHERE id=?", (project_id,))
    row = c.fetchone()
    conn.close()
    return row

def close_project(project_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE projects SET status='closed' WHERE id=?", (project_id,))
    conn.commit()
    conn.close()

def get_open_projects():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, role, budget, created_at FROM projects WHERE status='open' ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_subscribers_by_role(role):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username FROM subscribers WHERE role=? OR role='all'", (role.lower(),))
    rows = c.fetchall()
    conn.close()
    return rows

def add_subscriber(user_id, username, role):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO subscribers (user_id, username, role, subscribed_at) VALUES (?,?,?,?)",
              (user_id, username, role.lower(), datetime.now()))
    conn.commit()
    conn.close()

def remove_subscriber(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM subscribers WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

# ========== ОБРАБОТЧИКИ ==========
async def start(update, context):
    await update.message.reply_text(
        "👋 Добро пожаловать в аутсорсинг-биржу Coded!\n\n"
        "📌 Заказчики: /new_project — создайте заявку на исполнителя\n"
        "💼 Исполнители: /subscribe backend — подписка на проекты по роли\n"
        "💰 Комиссия: 15% с заказчика при успешной сделке\n"
        "📢 Приватный канал с заявками: ссылка выдаётся после подписки\n\n"
        "Вопросы: @coded_support"
    )

async def new_project(update, context):
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
        await update.message.reply_text("Пожалуйста, введите бюджет числом (от 1000 до 100 млн). Попробуйте ещё раз:")
        return BUDGET
    context.user_data['budget'] = budget
    await update.message.reply_text("Опишите проект кратко (задачи, сроки, требования):")
    return DESCRIPTION

async def get_description(update, context):
    context.user_data['description'] = update.message.text
    pid = save_project(context.user_data)
    
    # Публикация в канал
    text = (f"🔧 **Новый проект Coded**\n\n"
            f"🆔 №{pid}\n"
            f"📌 Роль: {context.user_data['role']}\n"
            f"⚙️ Стек: {context.user_data['tech_stack']}\n"
            f"💰 Бюджет: {context.user_data['budget']} ₽\n"
            f"📝 Описание: {context.user_data['description']}\n\n"
            f"⏳ Создан: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 Откликнуться", callback_data=f"bid_{pid}")]
    ])
    
    await context.bot.send_message(CHANNEL_ID, text, parse_mode="Markdown", reply_markup=keyboard)
    
    await update.message.reply_text(
        f"✅ Заявка №{pid} опубликована! Исполнители могут откликнуться.\n"
        f"Комиссия платформы: 15% от бюджета при успешной сделке."
    )
    
    # Уведомление админов
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM admins")
    admin_ids = [row[0] for row in c.fetchall()]
    conn.close()
    for admin_id in admin_ids:
        await context.bot.send_message(
            admin_id,
            f"🆕 Новая заявка #{pid} от {context.user_data['name']} ({context.user_data['contact']})"
        )
    
    # Уведомление подписанных исполнителей
    subscribers = get_subscribers_by_role(context.user_data['role'])
    for uid, username in subscribers:
        try:
            await context.bot.send_message(
                uid,
                f"🔔 Новый проект по роли *{context.user_data['role']}*! Бюджет {context.user_data['budget']} ₽.\n"
                f"Подробности в приватном канале.",
                parse_mode="Markdown"
            )
        except:
            pass
    
    return ConversationHandler.END

async def cancel(update, context):
    await update.message.reply_text("Создание заявки отменено.")
    return ConversationHandler.END

async def handle_callback(update, context):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("bid_"):
        pid = int(query.data.split("_")[1])
        user = query.from_user
        contact = f"@{user.username}" if user.username else str(user.id)
        save_response(pid, user.id, user.username or str(user.id), contact)
        await query.edit_message_text(f"✅ Ваш отклик на проект №{pid} принят! Администратор свяжется с вами.")
        
        # Уведомление админов
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id FROM admins")
        admin_ids = [row[0] for row in c.fetchall()]
        conn.close()
        for admin_id in admin_ids:
            await context.bot.send_message(
                admin_id,
                f"📢 Отклик на проект #{pid} от @{user.username or user.id} (контакт {contact})"
            )
        
        # Уведомление заказчика (через админа, можно потом расширить)
        project = get_project(pid)
        if project:
            for admin_id in admin_ids:
                await context.bot.send_message(
                    admin_id,
                    f"🎯 Заказчик проекта #{pid}: {project[1]}, контакты: {project[2]}"
                )
    else:
        await query.edit_message_text("Неизвестная команда")

# ========== АДМИН-КОМАНДЫ ==========
async def stats(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Недостаточно прав.")
        return
    open_projects = get_open_projects()
    await update.message.reply_text(f"📊 Открытых проектов: {len(open_projects)}")

async def list_open(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Недостаточно прав.")
        return
    projects = get_open_projects()
    if not projects:
        await update.message.reply_text("Нет открытых проектов.")
        return
    text = "🔓 Открытые проекты:\n\n"
    for pid, role, budget, created in projects:
        text += f"#{pid} — {role}, бюджет {budget} ₽ (создан {created[:10]})\n"
    await update.message.reply_text(text)

async def close_project_cmd(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Недостаточно прав.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /close_project <id>")
        return
    try:
        pid = int(context.args[0])
        close_project(pid)
        await update.message.reply_text(f"✅ Проект #{pid} закрыт.")
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")

async def notify(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Недостаточно прав.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /notify <текст>")
        return
    msg = " ".join(context.args)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM subscribers")
    users = c.fetchall()
    conn.close()
    sent = 0
    for (uid,) in users:
        try:
            await context.bot.send_message(uid, f"📢 Рассылка Coded:\n{msg}")
            sent += 1
        except:
            pass
    await update.message.reply_text(f"Рассылка отправлена {sent} подписчикам.")

async def add_admin_cmd(update, context):
    if update.effective_user.id != SUPER_ADMIN_ID:
        await update.message.reply_text("❌ Только суперадмин может добавлять админов.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /add_admin <user_id>")
        return
    try:
        uid = int(context.args[0])
        if add_admin(uid, SUPER_ADMIN_ID):
            await update.message.reply_text(f"✅ Администратор {uid} добавлен.")
        else:
            await update.message.reply_text("❌ Не удалось добавить.")
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")

async def del_admin_cmd(update, context):
    if update.effective_user.id != SUPER_ADMIN_ID:
        await update.message.reply_text("❌ Только суперадмин может удалять админов.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /del_admin <user_id>")
        return
    try:
        uid = int(context.args[0])
        if remove_admin(uid, SUPER_ADMIN_ID):
            await update.message.reply_text(f"✅ Администратор {uid} удалён.")
        else:
            await update.message.reply_text("❌ Не удалось удалить.")
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")

async def list_admins(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Недостаточно прав.")
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, added_by, added_at FROM admins")
    rows = c.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Список администраторов пуст.")
        return
    text = "👥 **Администраторы:**\n"
    for uid, added_by, added_at in rows:
        text += f"• `{uid}` (добавлен {added_at[:10]})\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# ========== ПОДПИСКА ==========
async def subscribe(update, context):
    if not context.args:
        await update.message.reply_text("Укажите роль: /subscribe backend, /subscribe frontend, /subscribe all")
        return
    role = context.args[0].lower()
    user = update.effective_user
    add_subscriber(user.id, user.username or str(user.id), role)
    await update.message.reply_text(f"✅ Вы подписались на проекты по роли: {role}")

async def unsubscribe(update, context):
    user = update.effective_user
    remove_subscriber(user.id)
    await update.message.reply_text("✅ Вы отписаны от уведомлений.")

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    init_db()
    
    # Запускаем Flask в отдельном потоке (для health check на Render)
    threading.Thread(target=run_flask, daemon=True).start()
    
    request = HTTPXRequest(
        connect_timeout=60.0,
        read_timeout=60.0,
        write_timeout=60.0,
        http_version="1.1"
    )
    
    app = Application.builder().token(TOKEN).request(request).build()
    
    # Все обработчики команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("list_open", list_open))
    app.add_handler(CommandHandler("close_project", close_project_cmd))
    app.add_handler(CommandHandler("notify", notify))
    app.add_handler(CommandHandler("add_admin", add_admin_cmd))
    app.add_handler(CommandHandler("del_admin", del_admin_cmd))
    app.add_handler(CommandHandler("list_admins", list_admins))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("new_project", new_project)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_contact)],
            ROLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_role)],
            TECH_STACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_tech_stack)],
            BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_budget)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_description)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    logger.info("Бот запущен. Ожидание обновлений...")
    app.run_polling(timeout=60)
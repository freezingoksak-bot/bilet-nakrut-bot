import logging
import sqlite3
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import random

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
    CallbackQuery, Message, LabeledPrice, PreCheckoutQuery,
    FSInputFile, ChatMemberUpdated, ChatMember
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# Конфигурация
BOT_TOKEN = "8231242202:AAGK7lOG3cGOso4Io1Na7BtjdpjfwkzgXxA"  # Новый токен
ADMIN_ID = 8451120262  # ID администратора

# Список спонсоров (каналы для подписки)
SPONSORS = [
    {"name": "Основной канал", "url": "symskooypython", "bonus": 2},
    {"name": "Chat Cod Mastera", "url": "chatcodmastera", "bonus": 2},
    {"name": "Biletik Cod", "url": "BiletikCod", "bonus": 2}
]

# Цены в билетах
PRICES = {
    "subs_10": 10,  # 10 подписчиков = 10 билетов
    "subs_30": 25,  # 30 подписчиков = 25 билетов
    "subs_50": 40,  # 50 подписчиков = 40 билетов
    "subs_100": 70,  # 100 подписчиков = 70 билетов

    "views_100": 2,  # 100 просмотров = 2 билета
    "views_200": 4,  # 200 просмотров = 4 билета
    "views_500": 8,  # 500 просмотров = 8 билетов
    "views_1000": 15,  # 1000 просмотров = 15 билетов

    "reactions_50": 3,  # 50 реакций = 3 билета

    "boost": 150,  # Буст канала на неделю = 150 билетов
}

# Цены в звёздах Telegram для покупки билетов
STAR_PRICES = {
    "tickets_10": 15,  # 10 билетов = 15 звёзд
    "tickets_30": 30,  # 30 билетов = 30 звёзд
}

# Доступные реакции (emoji)
REACTIONS = ["👍", "❤️", "🔥", "😁", "😱", "👀"]

# Стикеры для капчи (emoji)
CAPTCHA_STICKERS = ["🐶", "🐱", "🐼", "🦊"]

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


# Состояния FSM
class OrderStates(StatesGroup):
    waiting_for_subs_link = State()  # Ожидание ссылки для подписчиков
    waiting_for_post = State()  # Ожидание поста для просмотров/реакций
    waiting_for_reaction_choice = State()  # Выбор реакции
    waiting_for_boost_link = State()  # Ожидание ссылки для буста
    waiting_for_captcha = State()  # Ожидание выбора капчи
    waiting_for_sponsor = State()  # Ожидание проверки спонсора


class AdminStates(StatesGroup):
    admin_action = State()  # Действия админа
    waiting_for_user_id = State()  # Ожидание ID пользователя для управления
    waiting_for_amount = State()  # Ожидание количества билетов
    waiting_for_message = State()  # Ожидание сообщения для рассылки
    waiting_for_ban_reason = State()  # Ожидание причины бана


# Функция для обновления структуры БД
def migrate_database():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    # Проверяем, есть ли колонка boost_used в users
    cursor.execute("PRAGMA table_info(users)")
    user_columns = [column[1] for column in cursor.fetchall()]

    if 'boost_used' not in user_columns:
        print("Добавляем колонку boost_used в users...")
        cursor.execute('ALTER TABLE users ADD COLUMN boost_used INTEGER DEFAULT 0')

    if 'boost_until' not in user_columns:
        print("Добавляем колонку boost_until в users...")
        cursor.execute('ALTER TABLE users ADD COLUMN boost_until TEXT')

    if 'captcha_passed' not in user_columns:
        print("Добавляем колонку captcha_passed в users...")
        cursor.execute('ALTER TABLE users ADD COLUMN captcha_passed INTEGER DEFAULT 0')

    if 'is_banned' not in user_columns:
        print("Добавляем колонку is_banned в users...")
        cursor.execute('ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0')

    if 'ban_reason' not in user_columns:
        print("Добавляем колонку ban_reason в users...")
        cursor.execute('ALTER TABLE users ADD COLUMN ban_reason TEXT')

    # Создаем таблицу для спонсорских бонусов
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS sponsor_bonuses
                   (
                       bonus_id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       user_id
                       INTEGER,
                       sponsor_url
                       TEXT,
                       claimed_date
                       TIMESTAMP
                       DEFAULT
                       CURRENT_TIMESTAMP,
                       UNIQUE
                   (
                       user_id,
                       sponsor_url
                   )
                       )
                   ''')

    # Проверяем таблицу referrals
    cursor.execute("PRAGMA table_info(referrals)")
    ref_columns = [column[1] for column in cursor.fetchall()]

    if 'notified' not in ref_columns:
        print("Добавляем колонку notified в referrals...")
        cursor.execute('ALTER TABLE referrals ADD COLUMN notified INTEGER DEFAULT 0')

    conn.commit()
    conn.close()
    print("Миграция базы данных выполнена успешно!")


# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    # Таблица пользователей (создаем если нет)
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS users
                   (
                       user_id
                       INTEGER
                       PRIMARY
                       KEY,
                       username
                       TEXT,
                       first_name
                       TEXT,
                       balance
                       INTEGER
                       DEFAULT
                       0,
                       referred_by
                       INTEGER,
                       referral_count
                       INTEGER
                       DEFAULT
                       0,
                       joined_date
                       TIMESTAMP
                       DEFAULT
                       CURRENT_TIMESTAMP
                   )
                   ''')

    # Таблица заказов
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS orders
                   (
                       order_id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       user_id
                       INTEGER,
                       order_type
                       TEXT,
                       amount
                       INTEGER,
                       price
                       INTEGER,
                       target_link
                       TEXT,
                       reaction
                       TEXT,
                       status
                       TEXT
                       DEFAULT
                       'pending',
                       created_at
                       TIMESTAMP
                       DEFAULT
                       CURRENT_TIMESTAMP,
                       FOREIGN
                       KEY
                   (
                       user_id
                   ) REFERENCES users
                   (
                       user_id
                   )
                       )
                   ''')

    # Таблица для рефералов
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS referrals
                   (
                       referral_id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       user_id
                       INTEGER,
                       referred_user_id
                       INTEGER,
                       date
                       TIMESTAMP
                       DEFAULT
                       CURRENT_TIMESTAMP,
                       FOREIGN
                       KEY
                   (
                       user_id
                   ) REFERENCES users
                   (
                       user_id
                   ),
                       FOREIGN KEY
                   (
                       referred_user_id
                   ) REFERENCES users
                   (
                       user_id
                   )
                       )
                   ''')

    conn.commit()
    conn.close()

    # Выполняем миграцию для добавления новых полей
    migrate_database()


# Запускаем инициализацию БД
init_db()


# Вспомогательные функции для работы с БД
def get_user(user_id: int) -> Optional[Dict]:
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        # Получаем список колонок
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in cursor.fetchall()]
        conn.close()

        # Создаем словарь с данными
        user_dict = {}
        for i, col in enumerate(columns):
            user_dict[col] = row[i]

        # Добавляем значения по умолчанию для новых полей, если их нет
        if 'boost_used' not in user_dict:
            user_dict['boost_used'] = 0
        if 'boost_until' not in user_dict:
            user_dict['boost_until'] = None
        if 'captcha_passed' not in user_dict:
            user_dict['captcha_passed'] = 0
        if 'is_banned' not in user_dict:
            user_dict['is_banned'] = 0
        if 'ban_reason' not in user_dict:
            user_dict['ban_reason'] = None

        return user_dict
    return None


def create_user(user_id: int, username: str = None, first_name: str = None, referred_by: int = None):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    # Проверяем, какие колонки есть в таблице
    cursor.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in cursor.fetchall()]

    # Базовый запрос
    base_query = '''
                 INSERT \
                 OR IGNORE INTO users (user_id, username, first_name, referred_by)
    VALUES (?, ?, ?, ?) \
                 '''
    cursor.execute(base_query, (user_id, username, first_name, referred_by))

    conn.commit()
    conn.close()


def update_user_captcha(user_id: int):
    """Отмечает, что пользователь прошел капчу"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET captcha_passed = 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()


def user_passed_captcha(user_id: int) -> bool:
    """Проверяет, прошел ли пользователь капчу"""
    user = get_user(user_id)
    return user and user.get('captcha_passed', 0) == 1


def check_user_banned(user_id: int) -> bool:
    """Проверяет, забанен ли пользователь"""
    user = get_user(user_id)
    return user and user.get('is_banned', 0) == 1


def ban_user(user_id: int, reason: str = None) -> bool:
    """Банит пользователя"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_banned = 1, ban_reason = ? WHERE user_id = ?', (reason, user_id))
    conn.commit()
    conn.close()
    return True


def unban_user(user_id: int) -> bool:
    """Разбанивает пользователя"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_banned = 0, ban_reason = NULL WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    return True


def claim_sponsor_bonus(user_id: int, sponsor_url: str) -> bool:
    """Начисляет бонус за подписку на спонсора, если еще не получал"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    # Проверяем, получал ли уже бонус за этого спонсора
    cursor.execute('SELECT bonus_id FROM sponsor_bonuses WHERE user_id = ? AND sponsor_url = ?',
                   (user_id, sponsor_url))
    if cursor.fetchone():
        conn.close()
        return False

    # Находим бонус для этого спонсора
    bonus = 2  # По умолчанию 2 билета
    for sponsor in SPONSORS:
        if sponsor['url'] == sponsor_url:
            bonus = sponsor['bonus']
            break

    # Начисляем бонус
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (bonus, user_id))
    cursor.execute('INSERT INTO sponsor_bonuses (user_id, sponsor_url) VALUES (?, ?)',
                   (user_id, sponsor_url))

    conn.commit()
    conn.close()
    return True


def get_user_sponsor_bonuses(user_id: int) -> List[str]:
    """Получает список спонсоров, за которых пользователь уже получил бонус"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT sponsor_url FROM sponsor_bonuses WHERE user_id = ?', (user_id,))
    rows = cursor.fetchall()
    conn.close()

    return [row[0] for row in rows]


def add_referral(referrer_id: int, referred_id: int):
    """Добавляет реферала и начисляет бонус"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    # Добавляем запись о реферале
    cursor.execute('''
                   INSERT INTO referrals (user_id, referred_user_id, notified)
                   VALUES (?, ?, 0)
                   ''', (referrer_id, referred_id))

    # Увеличиваем счетчик рефералов
    cursor.execute('UPDATE users SET referral_count = referral_count + 1 WHERE user_id = ?', (referrer_id,))

    conn.commit()
    conn.close()


def get_unnotified_referrals() -> List[Dict]:
    """Получает рефералов, о которых еще не уведомлен реферер"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    try:
        cursor.execute('''
                       SELECT r.*, u.username, u.first_name
                       FROM referrals r
                                JOIN users u ON r.referred_user_id = u.user_id
                       WHERE r.notified = 0
                       ''')
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        # Если колонки нет, возвращаем пустой список
        conn.close()
        return []

    conn.close()

    referrals = []
    for row in rows:
        referrals.append({
            'referral_id': row[0],
            'user_id': row[1],
            'referred_user_id': row[2],
            'date': row[3],
            'notified': row[4],
            'username': row[5],
            'first_name': row[6]
        })
    return referrals


def mark_referral_notified(referral_id: int):
    """Отмечает реферала как уведомленного"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    try:
        cursor.execute('UPDATE referrals SET notified = 1 WHERE referral_id = ?', (referral_id,))
        conn.commit()
    except sqlite3.OperationalError:
        pass
    conn.close()


def update_balance(user_id: int, amount: int) -> bool:
    """Обновляет баланс пользователя. amount может быть отрицательным (списание)"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    # Проверяем, что баланс не уйдет в минус при списании
    if amount < 0:
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        current = cursor.fetchone()
        if not current or current[0] + amount < 0:
            conn.close()
            return False

    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()
    return True


def reset_all_balances():
    """Сбрасывает балансы всех пользователей (для админа)"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = 0')
    conn.commit()
    conn.close()


def reset_all_referrals():
    """Сбрасывает рефералов всех пользователей"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM referrals')
    cursor.execute('UPDATE users SET referral_count = 0')
    conn.commit()
    conn.close()


def activate_boost(user_id: int) -> bool:
    """Активирует буст для канала (на 7 дней)"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    # Проверяем, не использовал ли пользователь буст
    cursor.execute('SELECT boost_used FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()

    if not row or row[0] == 1:
        conn.close()
        return False

    # Активируем буст на 7 дней
    boost_until = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('UPDATE users SET boost_used = 1, boost_until = ? WHERE user_id = ?', (boost_until, user_id))

    conn.commit()
    conn.close()
    return True


def check_boost_active(user_id: int) -> bool:
    """Проверяет, активен ли буст у пользователя"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    cursor.execute('SELECT boost_until FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()

    if not row or not row[0]:
        return False

    try:
        boost_until = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
        return datetime.now() < boost_until
    except:
        return False


def create_order(user_id: int, order_type: str, amount: int, price: int, target_link: str = None,
                 reaction: str = None) -> int:
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
                   INSERT INTO orders (user_id, order_type, amount, price, target_link, reaction)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ''', (user_id, order_type, amount, price, target_link, reaction))
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return order_id


def get_user_orders(user_id: int, status: str = None) -> List[Dict]:
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    if status:
        cursor.execute('SELECT * FROM orders WHERE user_id = ? AND status = ? ORDER BY created_at DESC',
                       (user_id, status))
    else:
        cursor.execute('SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC', (user_id,))

    rows = cursor.fetchall()
    conn.close()

    orders = []
    for row in rows:
        orders.append({
            'order_id': row[0],
            'user_id': row[1],
            'order_type': row[2],
            'amount': row[3],
            'price': row[4],
            'target_link': row[5],
            'reaction': row[6],
            'status': row[7],
            'created_at': row[8]
        })
    return orders


def get_all_orders(status: str = None) -> List[Dict]:
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    if status:
        cursor.execute('SELECT * FROM orders WHERE status = ? ORDER BY created_at DESC', (status,))
    else:
        cursor.execute('SELECT * FROM orders ORDER BY created_at DESC')

    rows = cursor.fetchall()
    conn.close()

    orders = []
    for row in rows:
        orders.append({
            'order_id': row[0],
            'user_id': row[1],
            'order_type': row[2],
            'amount': row[3],
            'price': row[4],
            'target_link': row[5],
            'reaction': row[6],
            'status': row[7],
            'created_at': row[8]
        })
    return orders


def update_order_status(order_id: int, status: str):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE orders SET status = ? WHERE order_id = ?', (status, order_id))
    conn.commit()
    conn.close()


def get_top_users_by_balance(limit: int = 10) -> List[Dict]:
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute(
        'SELECT user_id, username, first_name, balance, referral_count FROM users WHERE is_banned = 0 ORDER BY balance DESC LIMIT ?',
        (limit,))
    rows = cursor.fetchall()
    conn.close()

    users = []
    for row in rows:
        users.append({
            'user_id': row[0],
            'username': row[1],
            'first_name': row[2],
            'balance': row[3],
            'referral_count': row[4]
        })
    return users


def get_top_users_by_referrals(limit: int = 10) -> List[Dict]:
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute(
        'SELECT user_id, username, first_name, balance, referral_count FROM users WHERE is_banned = 0 ORDER BY referral_count DESC LIMIT ?',
        (limit,))
    rows = cursor.fetchall()
    conn.close()

    users = []
    for row in rows:
        users.append({
            'user_id': row[0],
            'username': row[1],
            'first_name': row[2],
            'balance': row[3],
            'referral_count': row[4]
        })
    return users


def get_all_users(include_banned: bool = False) -> List[Dict]:
    """Получает всех пользователей для админ-панели"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    if include_banned:
        cursor.execute(
            'SELECT user_id, username, first_name, balance, referral_count, captcha_passed, is_banned, ban_reason, boost_used, boost_until FROM users ORDER BY joined_date DESC')
    else:
        cursor.execute(
            'SELECT user_id, username, first_name, balance, referral_count, captcha_passed, is_banned, ban_reason, boost_used, boost_until FROM users WHERE is_banned = 0 ORDER BY joined_date DESC')

    rows = cursor.fetchall()
    conn.close()

    users = []
    for row in rows:
        users.append({
            'user_id': row[0],
            'username': row[1],
            'first_name': row[2],
            'balance': row[3],
            'referral_count': row[4],
            'captcha_passed': row[5],
            'is_banned': row[6],
            'ban_reason': row[7],
            'boost_used': row[8],
            'boost_until': row[9]
        })
    return users


def get_banned_users() -> List[Dict]:
    """Получает список забаненных пользователей"""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute(
        'SELECT user_id, username, first_name, ban_reason FROM users WHERE is_banned = 1 ORDER BY joined_date DESC')
    rows = cursor.fetchall()
    conn.close()

    users = []
    for row in rows:
        users.append({
            'user_id': row[0],
            'username': row[1],
            'first_name': row[2],
            'ban_reason': row[3]
        })
    return users


# Проверка подписки на канал (упрощенная версия - всегда True если ошибка)
async def check_subscription(user_id: int, channel: str) -> bool:
    try:
        # Пытаемся получить информацию о пользователе в канале
        member = await bot.get_chat_member(chat_id=f"@{channel}", user_id=user_id)
        return member.status not in ['left', 'kicked']
    except Exception as e:
        logger.error(f"Error checking subscription to {channel}: {e}")
        # Если не можем проверить (бот не админ), пропускаем проверку
        return True  # Всегда пропускаем, чтобы бот работал


# Клавиатуры
def get_main_keyboard(user_id: int = None):
    """Главное меню"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Профиль"), KeyboardButton(text="🛒 Заказать")],
            [KeyboardButton(text="👥 Рефералы"), KeyboardButton(text="🏆 Топ")],
            [KeyboardButton(text="🤝 Спонсоры")]
        ],
        resize_keyboard=True
    )
    return keyboard


def get_main_inline_keyboard(user_id: int = None):
    """Главное меню в инлайн варианте (для edit_text)"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📊 Профиль", callback_data="profile"),
        InlineKeyboardButton(text="🛒 Заказать", callback_data="order_type")
    )
    builder.row(
        InlineKeyboardButton(text="👥 Рефералы", callback_data="referrals"),
        InlineKeyboardButton(text="🏆 Топ", callback_data="top")
    )
    builder.row(
        InlineKeyboardButton(text="🤝 Спонсоры", callback_data="sponsors")
    )
    return builder.as_markup()


def get_admin_button_keyboard():
    """Клавиатура с кнопкой админ-панели (только для админа)"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel"))
    return builder.as_markup()


def get_order_type_keyboard():
    """Выбор типа заказа"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👁 Просмотры", callback_data="order_views"),
        InlineKeyboardButton(text="❤️ Реакции", callback_data="order_reactions")
    )
    builder.row(
        InlineKeyboardButton(text="👥 Подписчики", callback_data="order_subs"),
        InlineKeyboardButton(text="🚀 Буст канала", callback_data="order_boost")
    )
    builder.row(
        InlineKeyboardButton(text="🎫 Купить билеты", callback_data="buy_tickets")
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    return builder.as_markup()


def get_sponsors_keyboard(user_id: int):
    """Клавиатура для спонсоров"""
    builder = InlineKeyboardBuilder()

    # Получаем список уже полученных бонусов
    claimed_sponsors = get_user_sponsor_bonuses(user_id)

    for sponsor in SPONSORS:
        status = "✅" if sponsor['url'] in claimed_sponsors else "❌"
        builder.row(InlineKeyboardButton(
            text=f"{status} {sponsor['name']} (+{sponsor['bonus']} билетов)",
            url=f"https://t.me/{sponsor['url']}"
        ))

    builder.row(InlineKeyboardButton(
        text="✅ Проверить подписки и получить бонусы",
        callback_data="check_all_sponsors"
    ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    return builder.as_markup()


def get_subs_amount_keyboard():
    """Выбор количества подписчиков"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=f"10 подписчиков ({PRICES['subs_10']} билетов)", callback_data="subs_10"),
        InlineKeyboardButton(text=f"30 подписчиков ({PRICES['subs_30']} билетов)", callback_data="subs_30")
    )
    builder.row(
        InlineKeyboardButton(text=f"50 подписчиков ({PRICES['subs_50']} билетов)", callback_data="subs_50"),
        InlineKeyboardButton(text=f"100 подписчиков ({PRICES['subs_100']} билетов)", callback_data="subs_100")
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="order_type"))
    return builder.as_markup()


def get_views_amount_keyboard():
    """Выбор количества просмотров"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=f"100 просмотров ({PRICES['views_100']} билетов)", callback_data="views_100"),
        InlineKeyboardButton(text=f"200 просмотров ({PRICES['views_200']} билетов)", callback_data="views_200")
    )
    builder.row(
        InlineKeyboardButton(text=f"500 просмотров ({PRICES['views_500']} билетов)", callback_data="views_500"),
        InlineKeyboardButton(text=f"1000 просмотров ({PRICES['views_1000']} билетов)", callback_data="views_1000")
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="order_type"))
    return builder.as_markup()


def get_reactions_amount_keyboard():
    """Выбор количества реакций"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=f"50 реакций ({PRICES['reactions_50']} билетов)", callback_data="reactions_50")
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="order_type"))
    return builder.as_markup()


def get_reaction_choice_keyboard():
    """Выбор типа реакции"""
    builder = InlineKeyboardBuilder()
    buttons = []
    for reaction in REACTIONS:
        buttons.append(InlineKeyboardButton(text=reaction, callback_data=f"reaction_{reaction}"))

    # Разбиваем на ряды по 3 кнопки
    for i in range(0, len(buttons), 3):
        builder.row(*buttons[i:i + 3])

    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="order_reactions"))
    return builder.as_markup()


def get_boost_keyboard():
    """Кнопка для заказа буста"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=f"🚀 Буст на 7 дней ({PRICES['boost']} билетов)", callback_data="order_boost_confirm")
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="order_type"))
    return builder.as_markup()


def get_buy_tickets_keyboard():
    """Кнопки для покупки билетов за звёзды"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=f"10 билетов ({STAR_PRICES['tickets_10']} ⭐)", callback_data="buy_tickets_10"),
        InlineKeyboardButton(text=f"30 билетов ({STAR_PRICES['tickets_30']} ⭐)", callback_data="buy_tickets_30")
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="order_type"))
    return builder.as_markup()


def get_profile_keyboard(is_admin: bool = False):
    """Кнопки в профиле"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📊 Мои заказы", callback_data="my_orders"),
        InlineKeyboardButton(text="🎫 Купить билеты", callback_data="buy_tickets")
    )

    # Если это админ, добавляем кнопку админ-панели
    if is_admin:
        builder.row(InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel"))

    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    return builder.as_markup()


def get_my_orders_keyboard(orders):
    """Клавиатура со списком заказов пользователя"""
    builder = InlineKeyboardBuilder()
    for order in orders[:5]:  # Показываем последние 5 заказов
        status_emoji = "✅" if order['status'] == 'completed' else "⏳" if order['status'] == 'pending' else "❌"
        builder.row(InlineKeyboardButton(
            text=f"{status_emoji} Заказ #{order['order_id']} - {order['order_type']} ({order['amount']})",
            callback_data=f"order_info_{order['order_id']}"
        ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="profile"))
    return builder.as_markup()


def get_admin_keyboard():
    """Админ-панель"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Все заказы", callback_data="admin_orders"),
        InlineKeyboardButton(text="⏳ Ожидают", callback_data="admin_pending")
    )
    builder.row(
        InlineKeyboardButton(text="💰 Управление балансом", callback_data="admin_balance"),
        InlineKeyboardButton(text="👥 Управление рефералами", callback_data="admin_referrals")
    )
    builder.row(
        InlineKeyboardButton(text="🔨 Управление банами", callback_data="admin_bans"),
        InlineKeyboardButton(text="📨 Рассылка", callback_data="admin_mailing")
    )
    builder.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
        InlineKeyboardButton(text="👤 Все пользователи", callback_data="admin_users")
    )
    builder.row(
        InlineKeyboardButton(text="🗑 Очистить топ", callback_data="admin_reset_top")
    )
    builder.row(InlineKeyboardButton(text="🔙 Выход", callback_data="back_to_main"))
    return builder.as_markup()


def get_admin_balance_keyboard():
    """Кнопки для управления балансом"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Выдать билеты", callback_data="admin_add_tickets"),
        InlineKeyboardButton(text="➖ Забрать билеты", callback_data="admin_remove_tickets")
    )
    builder.row(
        InlineKeyboardButton(text="🎫 Выдать реферальные", callback_data="admin_add_referral_tickets"),
        InlineKeyboardButton(text="🎁 Сбросить бонусы спонсоров", callback_data="admin_reset_sponsor")
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Сбросить все балансы", callback_data="admin_reset_all_balances")
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    return builder.as_markup()


def get_admin_referrals_keyboard():
    """Кнопки для управления рефералами"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📊 Статистика рефералов", callback_data="admin_referral_stats"),
        InlineKeyboardButton(text="🔄 Сбросить рефералов", callback_data="admin_reset_referrals")
    )
    builder.row(
        InlineKeyboardButton(text="🗑 Сбросить всех", callback_data="admin_reset_all_referrals")
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    return builder.as_markup()


def get_admin_bans_keyboard():
    """Кнопки для управления банами"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔨 Забанить пользователя", callback_data="admin_ban_user"),
        InlineKeyboardButton(text="🔓 Разбанить пользователя", callback_data="admin_unban_user")
    )
    builder.row(
        InlineKeyboardButton(text="📋 Список забаненных", callback_data="admin_banned_list")
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    return builder.as_markup()


def get_admin_orders_keyboard(orders):
    """Клавиатура со списком заказов для админа"""
    builder = InlineKeyboardBuilder()
    for order in orders[:10]:  # Показываем последние 10 заказов
        status_emoji = "✅" if order['status'] == 'completed' else "⏳" if order['status'] == 'pending' else "❌"
        builder.row(InlineKeyboardButton(
            text=f"{status_emoji} #{order['order_id']} - {order['order_type']} ({order['amount']})",
            callback_data=f"admin_order_{order['order_id']}"
        ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    return builder.as_markup()


def get_admin_order_action_keyboard(order_id: int):
    """Кнопки действий для конкретного заказа"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_order_{order_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_order_{order_id}")
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_pending"))
    return builder.as_markup()


def get_admin_users_keyboard(users):
    """Клавиатура со списком пользователей"""
    builder = InlineKeyboardBuilder()
    for user in users[:10]:  # Показываем последних 10 пользователей
        name = user['first_name'] or user['username'] or f"User{user['user_id']}"
        banned_emoji = "🔨" if user.get('is_banned') else ""
        builder.row(InlineKeyboardButton(
            text=f"{banned_emoji} {name} - {user['balance']} билетов ({user['referral_count']} реф)",
            callback_data=f"admin_user_{user['user_id']}"
        ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    return builder.as_markup()


def get_admin_banned_users_keyboard(users):
    """Клавиатура со списком забаненных пользователей"""
    builder = InlineKeyboardBuilder()
    for user in users[:10]:
        name = user['first_name'] or user['username'] or f"User{user['user_id']}"
        builder.row(InlineKeyboardButton(
            text=f"🔨 {name} - {user['ban_reason'] or 'Без причины'}",
            callback_data=f"admin_unban_user_{user['user_id']}"
        ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_bans"))
    return builder.as_markup()


def get_back_keyboard(callback_data: str = "back_to_main"):
    """Кнопка назад"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=callback_data))
    return builder.as_markup()


def get_subscribe_keyboard():
    """Клавиатура для подписки на основной канал (только для первого входа)"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"📢 Подписаться на канал",
        url=f"https://t.me/{SPONSORS[0]['url']}"
    ))
    builder.row(InlineKeyboardButton(
        text="✅ Я подписался",
        callback_data="check_sub_after_subscribe"
    ))
    return builder.as_markup()


def get_captcha_keyboard():
    """Клавиатура для капчи со стикерами"""
    builder = InlineKeyboardBuilder()
    # Создаем перемешанный список стикеров
    stickers = CAPTCHA_STICKERS.copy()
    random.shuffle(stickers)

    # Добавляем кнопки со стикерами
    buttons = []
    for sticker in stickers:
        buttons.append(InlineKeyboardButton(text=sticker, callback_data=f"captcha_{sticker}"))

    # Разбиваем на ряды по 2 кнопки
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            builder.row(buttons[i], buttons[i + 1])
        else:
            builder.row(buttons[i])

    return builder.as_markup()


# Обработчики команд
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    # Проверяем, не забанен ли пользователь
    if check_user_banned(user_id):
        await message.answer("⛔ <b>Вы забанены в боте</b>\n\nОбратитесь к администратору.")
        return

    # Проверяем реферальный параметр
    args = message.text.split()
    referred_by = None
    if len(args) > 1 and args[1].isdigit():
        referred_by = int(args[1])
        if referred_by == user_id:  # Нельзя реферить самого себя
            referred_by = None

    # Создаем пользователя в БД
    create_user(user_id, username, first_name, referred_by)

    # Проверяем, прошел ли пользователь капчу
    if not user_passed_captcha(user_id):
        # Выбираем случайный стикер для проверки
        correct_sticker = random.choice(CAPTCHA_STICKERS)
        await state.update_data(correct_captcha=correct_sticker, referred_by=referred_by)

        # Создаем клавиатуру с перемешанными стикерами
        await message.answer(
            f"🎯 <b>Проверка на бота</b>\n\n"
            f"Выберите стикер: <b>{correct_sticker}</b>\n\n"
            f"Нажмите на правильный стикер чтобы продолжить:",
            reply_markup=get_captcha_keyboard()
        )
        await state.set_state(OrderStates.waiting_for_captcha)
    else:
        # Если уже прошел капчу, проверяем подписку на первый канал
        await check_and_handle_subscription(message, state, user_id, first_name)


async def check_and_handle_subscription(message: Message, state: FSMContext, user_id: int, first_name: str):
    """Проверяет подписку на первый канал и отправляет соответствующее сообщение"""
    if await check_subscription(user_id, SPONSORS[0]['url']):
        await message.answer(
            f"✅ <b>Подписка подтверждена!</b>\n\n"
            f"🌟 <b>Добро пожаловать в главное меню, {first_name}!</b>\n"
            f"Используйте кнопки ниже для навигации.\n\n"
            f"💡 Не забудьте зайти в раздел 🤝 Спонсоры, чтобы получить бонусы за подписку на каналы!",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer(
            f"🌟 <b>Добро пожаловать, {first_name}!</b>\n\n"
            f"📢 <b>Для использования бота необходимо подписаться на канал:</b>\n"
            f"@{SPONSORS[0]['url']}\n\n"
            f"👇 <b>Нажмите кнопку ниже чтобы подписаться</b>",
            reply_markup=get_subscribe_keyboard()
        )

    await state.clear()


@dp.callback_query(OrderStates.waiting_for_captcha, F.data.startswith("captcha_"))
async def process_captcha(callback: CallbackQuery, state: FSMContext):
    # Проверяем, не забанен ли пользователь
    if check_user_banned(callback.from_user.id):
        await callback.answer("⛔ Вы забанены в боте", show_alert=True)
        return

    selected = callback.data.replace("captcha_", "")
    data = await state.get_data()
    correct = data.get('correct_captcha')
    referred_by = data.get('referred_by')

    if selected == correct:
        # Пользователь прошел капчу
        update_user_captcha(callback.from_user.id)

        # Если есть реферер, добавляем реферала
        if referred_by:
            try:
                add_referral(referred_by, callback.from_user.id)
            except Exception as e:
                logger.error(f"Error adding referral: {e}")

        await callback.message.edit_text(
            "✅ <b>Проверка пройдена!</b>\n\n"
            "Сейчас проверим подписку на канал..."
        )

        # Проверяем подписку на первый канал
        if await check_subscription(callback.from_user.id, SPONSORS[0]['url']):
            await callback.message.answer(
                f"✅ <b>Подписка подтверждена!</b>\n\n"
                f"🌟 <b>Добро пожаловать в главное меню!</b>\n"
                f"Используйте кнопки ниже для навигации.\n\n"
                f"💡 Не забудьте зайти в раздел 🤝 Спонсоры, чтобы получить бонусы за подписку на каналы!",
                reply_markup=get_main_keyboard(callback.from_user.id)
            )
            await callback.message.delete()
        else:
            await callback.message.answer(
                f"📢 <b>Для использования бота необходимо подписаться на канал:</b>\n"
                f"@{SPONSORS[0]['url']}\n\n"
                f"👇 <b>Нажмите кнопку ниже чтобы подписаться</b>",
                reply_markup=get_subscribe_keyboard()
            )
            await callback.message.delete()
    else:
        # Неправильный выбор - новый стикер
        new_sticker = random.choice(CAPTCHA_STICKERS)
        await state.update_data(correct_captcha=new_sticker)

        await callback.message.edit_text(
            f"❌ <b>Неправильно!</b>\n\n"
            f"Попробуйте еще раз.\n"
            f"Выберите стикер: <b>{new_sticker}</b>",
            reply_markup=get_captcha_keyboard()
        )

    await callback.answer()


# Функция для проверки и отправки уведомлений о новых рефералах
async def check_and_notify_referrals():
    """Периодическая проверка новых рефералов"""
    while True:
        try:
            referrals = get_unnotified_referrals()
            for ref in referrals:
                # Проверяем, не забанен ли реферер
                if check_user_banned(ref['user_id']):
                    mark_referral_notified(ref['referral_id'])
                    continue

                # Получаем информацию о реферере
                referrer = get_user(ref['user_id'])
                if referrer:
                    # Начисляем билет
                    update_balance(ref['user_id'], 1)

                    # Отправляем уведомление
                    try:
                        await bot.send_message(
                            ref['user_id'],
                            f"🎉 <b>Новый реферал!</b>\n\n"
                            f"👤 Пользователь: @{ref['username'] or ref['first_name'] or 'Неизвестно'}\n"
                            f"✅ Прошел капчу и подписался на канал\n\n"
                            f"💰 Вам начислен <b>1 билет</b>!\n"
                            f"💳 Текущий баланс: {referrer['balance'] + 1} билетов"
                        )
                    except:
                        pass

                # Отмечаем как уведомленного
                mark_referral_notified(ref['referral_id'])

            await asyncio.sleep(5)  # Проверяем каждые 5 секунд
        except Exception as e:
            logger.error(f"Error in referral notifier: {e}")
            await asyncio.sleep(5)


@dp.callback_query(F.data == "check_sub_after_subscribe")
async def check_sub_after_subscribe(callback: CallbackQuery, state: FSMContext):
    # Проверяем, не забанен ли пользователь
    if check_user_banned(callback.from_user.id):
        await callback.answer("⛔ Вы забанены в боте", show_alert=True)
        return

    await callback.message.edit_text(
        "🔄 <b>Проверяем подписку...</b>"
    )

    # Проверяем подписку на первый канал
    is_subscribed = await check_subscription(callback.from_user.id, SPONSORS[0]['url'])

    if is_subscribed:
        # Отправляем НОВОЕ сообщение с главным меню
        await callback.message.answer(
            f"✅ <b>Подписка подтверждена!</b>\n\n"
            f"🌟 <b>Добро пожаловать в главное меню!</b>\n"
            f"Используйте кнопки ниже для навигации.\n\n"
            f"💡 Не забудьте зайти в раздел 🤝 Спонсоры, чтобы получить бонусы за подписку на каналы!",
            reply_markup=get_main_keyboard(callback.from_user.id)
        )
        # Удаляем старое сообщение с проверкой
        await callback.message.delete()
    else:
        await callback.message.edit_text(
            "❌ <b>Подписка не найдена!</b>\n\n"
            f"📢 Пожалуйста, подпишитесь на канал @{SPONSORS[0]['url']}\n"
            f"и нажмите кнопку '✅ Я подписался' снова.\n\n"
            f"💡 Если вы уже подписались, попробуйте:\n"
            f"• Отписаться и подписаться заново\n"
            f"• Написать любое сообщение в канал\n"
            f"• Подождать 1-2 минуты",
            reply_markup=get_subscribe_keyboard()
        )

    await callback.answer()


# Обработчик для спонсоров
@dp.message(F.text == "🤝 Спонсоры")
async def sponsors_handler(message: Message):
    user_id = message.from_user.id

    # Проверяем, не забанен ли пользователь
    if check_user_banned(user_id):
        await message.answer("⛔ <b>Вы забанены в боте</b>\n\nОбратитесь к администратору.")
        return

    user = get_user(user_id)
    claimed_sponsors = get_user_sponsor_bonuses(user_id)

    text = (
        f"🤝 <b>Наши спонсоры</b>\n\n"
        f"Подпишитесь на каналы и получите бонусы:\n\n"
    )

    total_bonus = 0
    for sponsor in SPONSORS:
        status = "✅" if sponsor['url'] in claimed_sponsors else "❌"
        text += f"{status} {sponsor['name']}: +{sponsor['bonus']} билетов\n"
        if sponsor['url'] not in claimed_sponsors:
            total_bonus += sponsor['bonus']

    if total_bonus > 0:
        text += f"\n🎁 Доступно бонусов: <b>{total_bonus} билетов</b>"
    else:
        text += f"\n✅ Вы уже получили все бонусы!"

    await message.answer(text, reply_markup=get_sponsors_keyboard(user_id))


@dp.callback_query(F.data == "check_all_sponsors")
async def check_all_sponsors(callback: CallbackQuery):
    user_id = callback.from_user.id

    # Проверяем, не забанен ли пользователь
    if check_user_banned(user_id):
        await callback.answer("⛔ Вы забанены в боте", show_alert=True)
        return

    await callback.message.edit_text(
        "🔄 <b>Проверяем подписки на каналы...</b>"
    )

    claimed_sponsors = get_user_sponsor_bonuses(user_id)
    new_bonuses = 0

    for sponsor in SPONSORS:
        if sponsor['url'] not in claimed_sponsors:
            if await check_subscription(user_id, sponsor['url']):
                if claim_sponsor_bonus(user_id, sponsor['url']):
                    new_bonuses += sponsor['bonus']

    if new_bonuses > 0:
        user = get_user(user_id)
        await callback.message.edit_text(
            f"✅ <b>Бонусы получены!</b>\n\n"
            f"🎁 Вам начислено <b>{new_bonuses} билетов</b> за подписку на каналы!\n"
            f"💰 Текущий баланс: {user['balance']} билетов\n\n"
            f"Спасибо за поддержку! 🤝"
        )
    else:
        await callback.message.edit_text(
            "❌ <b>Новых бонусов не найдено</b>\n\n"
            f"Возможно, вы уже получили все бонусы или не подписались на каналы.",
            reply_markup=get_sponsors_keyboard(user_id)
        )

    # Добавляем кнопку возврата
    await callback.message.answer(
        "Вернуться в главное меню:",
        reply_markup=get_main_keyboard(user_id)
    )
    await callback.answer()


# Обработчики главного меню
@dp.message(F.text == "📊 Профиль")
async def profile_handler(message: Message):
    user_id = message.from_user.id

    # Проверяем, не забанен ли пользователь
    if check_user_banned(user_id):
        await message.answer("⛔ <b>Вы забанены в боте</b>\n\nОбратитесь к администратору.")
        return

    user = get_user(user_id)
    if not user:
        await message.answer("❌ Ошибка загрузки профиля")
        return

    # Проверяем статус буста
    boost_status = "❌ Не активен"
    if check_boost_active(user_id):
        boost_status = "✅ Активен"
    elif user.get('boost_used') == 1:
        boost_status = "⏳ Истек"

    # Получаем информацию о бонусах спонсоров
    claimed_sponsors = get_user_sponsor_bonuses(user_id)
    sponsor_count = len(claimed_sponsors)

    text = (
        f"📊 <b>Ваш профиль</b>\n\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"👤 Имя: {user['first_name']}\n"
        f"💰 Баланс: <b>{user['balance']} билетов</b>\n"
        f"👥 Рефералов: {user['referral_count']}\n"
        f"🚀 Буст канала: {boost_status}\n"
        f"🤝 Бонусов спонсоров: {sponsor_count}/{len(SPONSORS)}\n"
    )

    # Для админа добавляем информацию о том, что это админ
    is_admin = (user_id == ADMIN_ID)
    await message.answer(text, reply_markup=get_profile_keyboard(is_admin))


@dp.message(F.text == "🛒 Заказать")
async def order_handler(message: Message, state: FSMContext):
    user_id = message.from_user.id

    # Проверяем, не забанен ли пользователь
    if check_user_banned(user_id):
        await message.answer("⛔ <b>Вы забанены в боте</b>\n\nОбратитесь к администратору.")
        return

    await state.clear()
    await message.answer(
        "🛒 <b>Что хотите заказать?</b>\n\n"
        "Выберите тип услуги:",
        reply_markup=get_order_type_keyboard()
    )


@dp.message(F.text == "👥 Рефералы")
async def referrals_handler(message: Message):
    user_id = message.from_user.id

    # Проверяем, не забанен ли пользователь
    if check_user_banned(user_id):
        await message.answer("⛔ <b>Вы забанены в боте</b>\n\nОбратитесь к администратору.")
        return

    user = get_user(user_id)
    if not user:
        return

    bot_username = (await bot.me()).username
    referral_link = f"https://t.me/{bot_username}?start={user['user_id']}"

    text = (
        f"👥 <b>Реферальная программа</b>\n\n"
        f"🔗 <b>Ваша реферальная ссылка:</b>\n"
        f"<code>{referral_link}</code>\n\n"
        f"📊 <b>Приглашено пользователей:</b> {user['referral_count']}\n\n"
        f"💰 <b>Бонус:</b> За каждого приглашенного друга вы получаете <b>1 билет</b>!\n"
        f"🎁 Бонус начисляется сразу после прохождения капчи и подписки друга."
    )

    await message.answer(text, reply_markup=get_back_keyboard())


@dp.message(F.text == "🏆 Топ")
async def top_handler(message: Message):
    user_id = message.from_user.id

    # Проверяем, не забанен ли пользователь
    if check_user_banned(user_id):
        await message.answer("⛔ <b>Вы забанены в боте</b>\n\nОбратитесь к администратору.")
        return

    top_balance = get_top_users_by_balance(10)
    top_referrals = get_top_users_by_referrals(10)

    text = "🏆 <b>Топ пользователей</b>\n\n"

    text += "💰 <b>По балансу:</b>\n"
    for i, user in enumerate(top_balance, 1):
        name = user['first_name'] or user['username'] or f"User{user['user_id']}"
        text += f"{i}. {name} — {user['balance']} билетов\n"

    text += "\n👥 <b>По рефералам:</b>\n"
    for i, user in enumerate(top_referrals, 1):
        name = user['first_name'] or user['username'] or f"User{user['user_id']}"
        text += f"{i}. {name} — {user['referral_count']} рефералов\n"

    await message.answer(text, reply_markup=get_back_keyboard())


# Обработчики заказов
@dp.callback_query(F.data == "order_subs")
async def order_subs(callback: CallbackQuery):
    # Проверяем, не забанен ли пользователь
    if check_user_banned(callback.from_user.id):
        await callback.answer("⛔ Вы забанены в боте", show_alert=True)
        return

    await callback.message.edit_text(
        "👥 <b>Заказ подписчиков</b>\n\n"
        "Выберите количество подписчиков:",
        reply_markup=get_subs_amount_keyboard()
    )


@dp.callback_query(F.data == "order_views")
async def order_views(callback: CallbackQuery):
    # Проверяем, не забанен ли пользователь
    if check_user_banned(callback.from_user.id):
        await callback.answer("⛔ Вы забанены в боте", show_alert=True)
        return

    await callback.message.edit_text(
        "👁 <b>Заказ просмотров</b>\n\n"
        "Выберите количество просмотров:",
        reply_markup=get_views_amount_keyboard()
    )


@dp.callback_query(F.data == "order_reactions")
async def order_reactions(callback: CallbackQuery):
    # Проверяем, не забанен ли пользователь
    if check_user_banned(callback.from_user.id):
        await callback.answer("⛔ Вы забанены в боте", show_alert=True)
        return

    await callback.message.edit_text(
        "❤️ <b>Заказ реакций</b>\n\n"
        "Выберите количество реакций:",
        reply_markup=get_reactions_amount_keyboard()
    )


@dp.callback_query(F.data == "order_boost")
async def order_boost(callback: CallbackQuery):
    # Проверяем, не забанен ли пользователь
    if check_user_banned(callback.from_user.id):
        await callback.answer("⛔ Вы забанены в боте", show_alert=True)
        return

    user = get_user(callback.from_user.id)

    if user.get('boost_used') == 1:
        if check_boost_active(callback.from_user.id):
            await callback.message.edit_text(
                "🚫 <b>Буст уже активирован!</b>\n\n"
                f"У вас уже есть активный буст канала.\n"
                f"Буст можно заказать только 1 раз.",
                reply_markup=get_back_keyboard("order_type")
            )
        else:
            await callback.message.edit_text(
                "🚫 <b>Буст уже был использован</b>\n\n"
                f"Вы уже использовали буст канала ранее.\n"
                f"Буст можно заказать только 1 раз.",
                reply_markup=get_back_keyboard("order_type")
            )
    else:
        await callback.message.edit_text(
            "🚀 <b>Буст Telegram канала</b>\n\n"
            "🔥 <b>Что дает буст:</b>\n"
            "• Повышение активности на канале\n"
            "• Увеличение охвата публикаций\n"
            "• Привлечение новой аудитории\n"
            "• Длительность: 7 дней\n\n"
            f"💰 <b>Стоимость: {PRICES['boost']} билетов</b>\n"
            f"⚠️ <b>Важно:</b> Буст можно заказать только 1 раз!\n\n"
            "Хотите заказать буст?",
            reply_markup=get_boost_keyboard()
        )


@dp.callback_query(F.data == "order_boost_confirm")
async def process_boost_order(callback: CallbackQuery, state: FSMContext):
    # Проверяем, не забанен ли пользователь
    if check_user_banned(callback.from_user.id):
        await callback.answer("⛔ Вы забанены в боте", show_alert=True)
        return

    price = PRICES['boost']

    user = get_user(callback.from_user.id)
    if user['balance'] < price:
        await callback.answer(f"❌ Недостаточно билетов! Нужно {price}, у вас {user['balance']}", show_alert=True)
        return

    if user.get('boost_used') == 1:
        await callback.answer("❌ Вы уже использовали буст!", show_alert=True)
        return

    await state.update_data(order_type="boost", amount=1, price=price)
    await callback.message.edit_text(
        f"🚀 <b>Заказ буста канала</b>\n\n"
        f"💰 Стоимость: {price} билетов\n\n"
        f"📎 Отправьте ссылку на ваш Telegram канал\n"
        f"(например: https://t.me/your_channel или @channel_username):",
        reply_markup=get_back_keyboard("order_boost")
    )
    await state.set_state(OrderStates.waiting_for_boost_link)


@dp.message(StateFilter(OrderStates.waiting_for_boost_link))
async def process_boost_link(message: Message, state: FSMContext):
    user_id = message.from_user.id

    # Проверяем, не забанен ли пользователь
    if check_user_banned(user_id):
        await message.answer("⛔ <b>Вы забанены в боте</b>\n\nОбратитесь к администратору.")
        await state.clear()
        return

    link = message.text.strip()

    # Простая валидация ссылки
    if not (link.startswith("https://t.me/") or link.startswith("t.me/") or link.startswith("@")):
        await message.answer(
            "❌ Неверный формат ссылки. Отправьте ссылку вида:\nhttps://t.me/your_channel\nили @channel_username")
        return

    data = await state.get_data()

    # Списываем билеты
    if not update_balance(user_id, -data['price']):
        await message.answer("❌ Ошибка при списании билетов. Недостаточно средств.")
        await state.clear()
        return

    # Активируем буст
    activate_boost(user_id)

    # Создаем заказ
    order_id = create_order(
        user_id=user_id,
        order_type="boost",
        amount=1,
        price=data['price'],
        target_link=link
    )

    # Уведомляем админа
    admin_text = (
        f"🆕 <b>Новый заказ #{order_id}</b>\n\n"
        f"👤 Пользователь: {message.from_user.full_name} (@{message.from_user.username})\n"
        f"🆔 ID: {user_id}\n"
        f"📦 Тип: Буст канала (7 дней)\n"
        f"💰 Стоимость: {data['price']} билетов\n"
        f"🔗 Ссылка: {link}\n"
        f"💳 Баланс после списания: {get_user(user_id)['balance']} билетов"
    )

    await bot.send_message(ADMIN_ID, admin_text)

    # Ответ пользователю
    boost_until = (datetime.now() + timedelta(days=7)).strftime('%d.%m.%Y %H:%M')

    await message.answer(
        f"✅ <b>Заказ #{order_id} создан!</b>\n\n"
        f"📦 Тип: 🚀 Буст канала (7 дней)\n"
        f"💰 Списано билетов: {data['price']}\n"
        f"🔗 Ссылка: {link}\n\n"
        f"🎉 <b>Буст активирован до: {boost_until}</b>\n\n"
        f"⏳ Ожидайте подтверждения администратором.",
        reply_markup=get_main_keyboard(user_id)
    )

    await state.clear()


@dp.callback_query(F.data.startswith("subs_"))
async def process_subs_order(callback: CallbackQuery, state: FSMContext):
    # Проверяем, не забанен ли пользователь
    if check_user_banned(callback.from_user.id):
        await callback.answer("⛔ Вы забанены в боте", show_alert=True)
        return

    amount_key = callback.data
    amount = int(amount_key.split('_')[1])
    price = PRICES[amount_key]

    user = get_user(callback.from_user.id)
    if user['balance'] < price:
        await callback.answer(f"❌ Недостаточно билетов! Нужно {price}, у вас {user['balance']}", show_alert=True)
        return

    await state.update_data(order_type="subs", amount=amount, price=price)
    await callback.message.edit_text(
        f"👥 <b>Заказ подписчиков: {amount}</b>\n"
        f"💰 Стоимость: {price} билетов\n\n"
        f"📎 Отправьте ссылку на ваш Telegram канал\n"
        f"(например: https://t.me/your_channel или @channel_username):",
        reply_markup=get_back_keyboard("order_subs")
    )
    await state.set_state(OrderStates.waiting_for_subs_link)


@dp.callback_query(F.data.startswith("views_"))
async def process_views_order(callback: CallbackQuery, state: FSMContext):
    # Проверяем, не забанен ли пользователь
    if check_user_banned(callback.from_user.id):
        await callback.answer("⛔ Вы забанены в боте", show_alert=True)
        return

    amount_key = callback.data
    amount = int(amount_key.split('_')[1])
    price = PRICES[amount_key]

    user = get_user(callback.from_user.id)
    if user['balance'] < price:
        await callback.answer(f"❌ Недостаточно билетов! Нужно {price}, у вас {user['balance']}", show_alert=True)
        return

    await state.update_data(order_type="views", amount=amount, price=price)
    await callback.message.edit_text(
        f"👁 <b>Заказ просмотров: {amount}</b>\n"
        f"💰 Стоимость: {price} билетов\n\n"
        f"📎 Перешлите пост из канала, на котором нужно накрутить просмотры:",
        reply_markup=get_back_keyboard("order_views")
    )
    await state.set_state(OrderStates.waiting_for_post)


@dp.callback_query(F.data == "reactions_50")
async def process_reactions_amount(callback: CallbackQuery, state: FSMContext):
    # Проверяем, не забанен ли пользователь
    if check_user_banned(callback.from_user.id):
        await callback.answer("⛔ Вы забанены в боте", show_alert=True)
        return

    amount_key = callback.data
    amount = 50
    price = PRICES[amount_key]

    user = get_user(callback.from_user.id)
    if user['balance'] < price:
        await callback.answer(f"❌ Недостаточно билетов! Нужно {price}, у вас {user['balance']}", show_alert=True)
        return

    await state.update_data(order_type="reactions", amount=amount, price=price)
    await callback.message.edit_text(
        f"❤️ <b>Заказ реакций: {amount}</b>\n"
        f"💰 Стоимость: {price} билетов\n\n"
        f"Выберите тип реакции:",
        reply_markup=get_reaction_choice_keyboard()
    )
    await state.set_state(OrderStates.waiting_for_reaction_choice)


@dp.callback_query(F.data.startswith("reaction_"), StateFilter(OrderStates.waiting_for_reaction_choice))
async def process_reaction_choice(callback: CallbackQuery, state: FSMContext):
    # Проверяем, не забанен ли пользователь
    if check_user_banned(callback.from_user.id):
        await callback.answer("⛔ Вы забанены в боте", show_alert=True)
        return

    reaction = callback.data.replace("reaction_", "")

    await state.update_data(reaction=reaction)
    await callback.message.edit_text(
        f"❤️ <b>Заказ реакций: {reaction}</b>\n\n"
        f"📎 Перешлите пост из канала, на котором нужно накрутить реакции:",
        reply_markup=get_back_keyboard("order_reactions")
    )
    await state.set_state(OrderStates.waiting_for_post)


@dp.message(StateFilter(OrderStates.waiting_for_subs_link))
async def process_subs_link(message: Message, state: FSMContext):
    user_id = message.from_user.id

    # Проверяем, не забанен ли пользователь
    if check_user_banned(user_id):
        await message.answer("⛔ <b>Вы забанены в боте</b>\n\nОбратитесь к администратору.")
        await state.clear()
        return

    link = message.text.strip()

    # Простая валидация ссылки
    if not (link.startswith("https://t.me/") or link.startswith("t.me/") or link.startswith("@")):
        await message.answer(
            "❌ Неверный формат ссылки. Отправьте ссылку вида:\nhttps://t.me/your_channel\nили @channel_username")
        return

    data = await state.get_data()

    # Списываем билеты
    if not update_balance(user_id, -data['price']):
        await message.answer("❌ Ошибка при списании билетов. Недостаточно средств.")
        await state.clear()
        return

    # Создаем заказ
    order_id = create_order(
        user_id=user_id,
        order_type="subs",
        amount=data['amount'],
        price=data['price'],
        target_link=link
    )

    # Уведомляем админа
    admin_text = (
        f"🆕 <b>Новый заказ #{order_id}</b>\n\n"
        f"👤 Пользователь: {message.from_user.full_name} (@{message.from_user.username})\n"
        f"🆔 ID: {user_id}\n"
        f"📦 Тип: Подписчики\n"
        f"🔢 Количество: {data['amount']}\n"
        f"💰 Стоимость: {data['price']} билетов\n"
        f"🔗 Ссылка: {link}\n"
        f"💳 Баланс после списания: {get_user(user_id)['balance']} билетов"
    )

    await bot.send_message(ADMIN_ID, admin_text, reply_markup=get_admin_order_action_keyboard(order_id))

    # Ответ пользователю
    await message.answer(
        f"✅ <b>Заказ #{order_id} создан!</b>\n\n"
        f"📦 Тип: Подписчики\n"
        f"🔢 Количество: {data['amount']}\n"
        f"💰 Списано билетов: {data['price']}\n"
        f"🔗 Ссылка: {link}\n\n"
        f"⏳ Ожидайте подтверждения администратором.\n"
        f"После одобрения заказ будет выполнен.",
        reply_markup=get_main_keyboard(user_id)
    )

    await state.clear()


@dp.message(StateFilter(OrderStates.waiting_for_post))
async def process_post(message: Message, state: FSMContext):
    user_id = message.from_user.id

    # Проверяем, не забанен ли пользователь
    if check_user_banned(user_id):
        await message.answer("⛔ <b>Вы забанены в боте</b>\n\nОбратитесь к администратору.")
        await state.clear()
        return

    # Проверяем, что сообщение - пересланный пост
    if not message.forward_from_chat:
        await message.answer("❌ Пожалуйста, перешлите пост из канала (не ссылку)")
        return

    data = await state.get_data()

    # Списываем билеты
    if not update_balance(user_id, -data['price']):
        await message.answer("❌ Ошибка при списании билетов. Недостаточно средств.")
        await state.clear()
        return

    chat_info = message.forward_from_chat
    target_link = f"https://t.me/{chat_info.username}/{message.forward_from_message_id}" if chat_info.username else f"Чат {chat_info.id}, сообщение {message.forward_from_message_id}"

    # Создаем заказ
    order_id = create_order(
        user_id=user_id,
        order_type=data['order_type'],
        amount=data['amount'],
        price=data['price'],
        target_link=target_link,
        reaction=data.get('reaction')
    )

    # Формируем текст для админа
    order_type_text = {
        'views': 'Просмотры',
        'reactions': f'Реакции ({data.get("reaction", "любые")})'
    }.get(data['order_type'], data['order_type'])

    admin_text = (
        f"🆕 <b>Новый заказ #{order_id}</b>\n\n"
        f"👤 Пользователь: {message.from_user.full_name} (@{message.from_user.username})\n"
        f"🆔 ID: {user_id}\n"
        f"📦 Тип: {order_type_text}\n"
        f"🔢 Количество: {data['amount']}\n"
        f"💰 Стоимость: {data['price']} билетов\n"
        f"🔗 Пост: {target_link}\n"
        f"💳 Баланс после списания: {get_user(user_id)['balance']} билетов"
    )

    await bot.send_message(ADMIN_ID, admin_text, reply_markup=get_admin_order_action_keyboard(order_id))

    # Ответ пользователю
    await message.answer(
        f"✅ <b>Заказ #{order_id} создан!</b>\n\n"
        f"📦 Тип: {order_type_text}\n"
        f"🔢 Количество: {data['amount']}\n"
        f"💰 Списано билетов: {data['price']}\n"
        f"🔗 Пост принят\n\n"
        f"⏳ Ожидайте подтверждения администратором.\n"
        f"После одобрения заказ будет выполнен.",
        reply_markup=get_main_keyboard(user_id)
    )

    await state.clear()


# Покупка билетов за звёзды
@dp.callback_query(F.data == "buy_tickets")
async def buy_tickets(callback: CallbackQuery):
    # Проверяем, не забанен ли пользователь
    if check_user_banned(callback.from_user.id):
        await callback.answer("⛔ Вы забанены в боте", show_alert=True)
        return

    await callback.message.edit_text(
        "🎫 <b>Покупка билетов</b>\n\n"
        "Вы можете купить билеты за звёзды Telegram:\n\n"
        f"• 10 билетов — {STAR_PRICES['tickets_10']} ⭐\n"
        f"• 30 билетов — {STAR_PRICES['tickets_30']} ⭐\n\n"
        "Выберите количество:",
        reply_markup=get_buy_tickets_keyboard()
    )


@dp.callback_query(F.data.startswith("buy_tickets_"))
async def process_buy_tickets(callback: CallbackQuery):
    # Проверяем, не забанен ли пользователь
    if check_user_banned(callback.from_user.id):
        await callback.answer("⛔ Вы забанены в боте", show_alert=True)
        return

    ticket_key = callback.data
    amount = int(ticket_key.split('_')[2])
    stars = STAR_PRICES[ticket_key]

    prices = [LabeledPrice(label=f"{amount} билетов", amount=stars)]

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"Покупка {amount} билетов",
        description=f"Приобретите {amount} билетов для заказов в боте",
        payload=f"buy_tickets_{amount}",
        provider_token="",  # Пусто для звёзд Telegram
        currency="XTR",  # Специальная валюта для звёзд
        prices=prices,
        start_parameter="create_order"
    )

    await callback.answer()


@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    user_id = message.from_user.id

    # Проверяем, не забанен ли пользователь
    if check_user_banned(user_id):
        await message.answer("⛔ <b>Вы забанены в боте</b>\n\nОбратитесь к администратору.")
        return

    payload = message.successful_payment.invoice_payload

    if payload.startswith("buy_tickets_"):
        amount = int(payload.split('_')[2])

        # Начисляем билеты
        update_balance(user_id, amount)

        await message.answer(
            f"✅ <b>Оплата прошла успешно!</b>\n\n"
            f"💰 Вам начислено <b>{amount} билетов</b>\n"
            f"💳 Текущий баланс: {get_user(user_id)['balance']} билетов",
            reply_markup=get_main_keyboard(user_id)
        )

        # Уведомляем админа
        await bot.send_message(
            ADMIN_ID,
            f"💰 <b>Покупка билетов</b>\n\n"
            f"👤 Пользователь: {message.from_user.full_name} (@{message.from_user.username})\n"
            f"🆔 ID: {user_id}\n"
            f"🎫 Куплено: {amount} билетов\n"
            f"💳 Новый баланс: {get_user(user_id)['balance']} билетов"
        )


# Профиль и заказы
@dp.callback_query(F.data == "profile")
async def profile_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    # Проверяем, не забанен ли пользователь
    if check_user_banned(user_id):
        await callback.answer("⛔ Вы забанены в боте", show_alert=True)
        return

    user = get_user(user_id)

    # Проверяем статус буста
    boost_status = "❌ Не активен"
    if check_boost_active(user_id):
        boost_status = "✅ Активен"
    elif user.get('boost_used') == 1:
        boost_status = "⏳ Истек"

    # Получаем информацию о бонусах спонсоров
    claimed_sponsors = get_user_sponsor_bonuses(user_id)
    sponsor_count = len(claimed_sponsors)

    text = (
        f"📊 <b>Ваш профиль</b>\n\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"👤 Имя: {user['first_name']}\n"
        f"💰 Баланс: <b>{user['balance']} билетов</b>\n"
        f"👥 Рефералов: {user['referral_count']}\n"
        f"🚀 Буст канала: {boost_status}\n"
        f"🤝 Бонусов спонсоров: {sponsor_count}/{len(SPONSORS)}\n"
    )

    is_admin = (user_id == ADMIN_ID)
    await callback.message.edit_text(text, reply_markup=get_profile_keyboard(is_admin))


@dp.callback_query(F.data == "my_orders")
async def my_orders_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    # Проверяем, не забанен ли пользователь
    if check_user_banned(user_id):
        await callback.answer("⛔ Вы забанены в боте", show_alert=True)
        return

    orders = get_user_orders(user_id)

    if not orders:
        await callback.message.edit_text(
            "📭 У вас пока нет заказов",
            reply_markup=get_back_keyboard("profile")
        )
        return

    await callback.message.edit_text(
        "📋 <b>Ваши заказы</b>\n\n"
        "Последние заказы:",
        reply_markup=get_my_orders_keyboard(orders)
    )


@dp.callback_query(F.data.startswith("order_info_"))
async def order_info_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    # Проверяем, не забанен ли пользователь
    if check_user_banned(user_id):
        await callback.answer("⛔ Вы забанены в боте", show_alert=True)
        return

    order_id = int(callback.data.replace("order_info_", ""))

    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM orders WHERE order_id = ?', (order_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    order = {
        'order_id': row[0],
        'order_type': row[2],
        'amount': row[3],
        'price': row[4],
        'target_link': row[5],
        'reaction': row[6],
        'status': row[7],
        'created_at': row[8]
    }

    status_text = {
        'pending': '⏳ Ожидает подтверждения',
        'completed': '✅ Выполнен',
        'rejected': '❌ Отклонен'
    }.get(order['status'], order['status'])

    type_text = {
        'subs': 'Подписчики',
        'views': 'Просмотры',
        'reactions': f'Реакции ({order["reaction"]})' if order['reaction'] else 'Реакции',
        'boost': '🚀 Буст канала (7 дней)'
    }.get(order['order_type'], order['order_type'])

    text = (
        f"📋 <b>Заказ #{order['order_id']}</b>\n\n"
        f"📦 Тип: {type_text}\n"
        f"🔢 Количество: {order['amount']}\n"
        f"💰 Стоимость: {order['price']} билетов\n"
        f"📎 Цель: {order['target_link']}\n"
        f"📊 Статус: {status_text}\n"
        f"📅 Создан: {order['created_at']}"
    )

    await callback.message.edit_text(text, reply_markup=get_back_keyboard("my_orders"))


# Админ-панель
@dp.message(F.text == "/admin")
async def admin_panel_command(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Доступ запрещен")
        return

    await message.answer(
        "🔐 <b>Админ-панель</b>\n\n"
        "Выберите действие:",
        reply_markup=get_admin_keyboard()
    )


@dp.callback_query(F.data == "admin_panel")
async def admin_panel_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    await callback.message.edit_text(
        "🔐 <b>Админ-панель</b>\n\n"
        "Выберите действие:",
        reply_markup=get_admin_keyboard()
    )


@dp.callback_query(F.data == "admin_balance")
async def admin_balance_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    await callback.message.edit_text(
        "💰 <b>Управление балансом</b>\n\n"
        "Выберите действие:",
        reply_markup=get_admin_balance_keyboard()
    )


@dp.callback_query(F.data == "admin_referrals")
async def admin_referrals_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    await callback.message.edit_text(
        "👥 <b>Управление рефералами</b>\n\n"
        "Выберите действие:",
        reply_markup=get_admin_referrals_keyboard()
    )


@dp.callback_query(F.data == "admin_bans")
async def admin_bans_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    await callback.message.edit_text(
        "🔨 <b>Управление банами</b>\n\n"
        "Выберите действие:",
        reply_markup=get_admin_bans_keyboard()
    )


@dp.callback_query(F.data == "admin_mailing")
async def admin_mailing_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    await callback.message.edit_text(
        "📨 <b>Рассылка сообщения</b>\n\n"
        "Отправьте сообщение для рассылки всем пользователям:",
        reply_markup=get_back_keyboard("admin_panel")
    )
    await state.set_state(AdminStates.waiting_for_message)


@dp.message(StateFilter(AdminStates.waiting_for_message))
async def process_admin_mailing(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Доступ запрещен")
        await state.clear()
        return

    users = get_all_users(include_banned=True)
    sent_count = 0
    failed_count = 0

    await message.answer(f"📨 Начинаю рассылку {len(users)} пользователям...")

    for user in users:
        try:
            await bot.send_message(
                user['user_id'],
                f"📢 <b>Сообщение от администратора</b>\n\n{message.text}"
            )
            sent_count += 1
            await asyncio.sleep(0.05)  # Небольшая задержка чтобы не спамить
        except:
            failed_count += 1

    await message.answer(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📨 Отправлено: {sent_count}\n"
        f"❌ Не доставлено: {failed_count}"
    )
    await state.clear()


@dp.callback_query(F.data == "admin_users")
async def admin_users_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    users = get_all_users(include_banned=True)

    if not users:
        await callback.message.edit_text(
            "👥 Пользователей нет",
            reply_markup=get_back_keyboard("admin_panel")
        )
        return

    await callback.message.edit_text(
        "👥 <b>Все пользователи</b>\n\n"
        "Последние пользователи:",
        reply_markup=get_admin_users_keyboard(users)
    )


@dp.callback_query(F.data == "admin_banned_list")
async def admin_banned_list_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    users = get_banned_users()

    if not users:
        await callback.message.edit_text(
            "✅ Нет забаненных пользователей",
            reply_markup=get_back_keyboard("admin_bans")
        )
        return

    await callback.message.edit_text(
        "🔨 <b>Забаненные пользователи</b>\n\n"
        "Нажмите на пользователя чтобы разбанить:",
        reply_markup=get_admin_banned_users_keyboard(users)
    )


@dp.callback_query(F.data == "admin_orders")
async def admin_orders_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    orders = get_all_orders()

    if not orders:
        await callback.message.edit_text(
            "📭 Заказов нет",
            reply_markup=get_back_keyboard("admin_panel")
        )
        return

    await callback.message.edit_text(
        "📋 <b>Все заказы</b>\n\n"
        "Последние заказы:",
        reply_markup=get_admin_orders_keyboard(orders)
    )


@dp.callback_query(F.data == "admin_pending")
async def admin_pending_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    orders = get_all_orders(status="pending")

    if not orders:
        await callback.message.edit_text(
            "✅ Нет заказов, ожидающих подтверждения",
            reply_markup=get_back_keyboard("admin_panel")
        )
        return

    await callback.message.edit_text(
        "⏳ <b>Заказы, ожидающие подтверждения</b>",
        reply_markup=get_admin_orders_keyboard(orders)
    )


@dp.callback_query(F.data == "admin_add_tickets")
async def admin_add_tickets(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    await callback.message.edit_text(
        "➕ <b>Выдача билетов</b>\n\n"
        "Отправьте ID пользователя:",
        reply_markup=get_back_keyboard("admin_balance")
    )
    await state.set_state(AdminStates.waiting_for_user_id)
    await state.update_data(action="add_tickets")


@dp.callback_query(F.data == "admin_remove_tickets")
async def admin_remove_tickets(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    await callback.message.edit_text(
        "➖ <b>Списание билетов</b>\n\n"
        "Отправьте ID пользователя:",
        reply_markup=get_back_keyboard("admin_balance")
    )
    await state.set_state(AdminStates.waiting_for_user_id)
    await state.update_data(action="remove_tickets")


@dp.callback_query(F.data == "admin_add_referral_tickets")
async def admin_add_referral_tickets(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    await callback.message.edit_text(
        "🎫 <b>Выдача реферальных билетов</b>\n\n"
        "Отправьте ID пользователя:",
        reply_markup=get_back_keyboard("admin_balance")
    )
    await state.set_state(AdminStates.waiting_for_user_id)
    await state.update_data(action="add_referral_tickets")


@dp.callback_query(F.data == "admin_reset_sponsor")
async def admin_reset_sponsor(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    await callback.message.edit_text(
        "🎁 <b>Сброс бонусов спонсоров</b>\n\n"
        "Отправьте ID пользователя для сброса бонусов\n"
        "(или 'all' для сброса у всех):",
        reply_markup=get_back_keyboard("admin_balance")
    )
    await state.set_state(AdminStates.waiting_for_user_id)
    await state.update_data(action="reset_sponsor")


@dp.callback_query(F.data == "admin_reset_all_balances")
async def admin_reset_all_balances(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    reset_all_balances()
    await callback.answer("✅ Все балансы сброшены", show_alert=True)
    await callback.message.edit_text(
        "💰 <b>Управление балансом</b>\n\n"
        "Выберите действие:",
        reply_markup=get_admin_balance_keyboard()
    )


@dp.callback_query(F.data == "admin_ban_user")
async def admin_ban_user(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    await callback.message.edit_text(
        "🔨 <b>Бан пользователя</b>\n\n"
        "Отправьте ID пользователя и причину через пробел\n"
        "Например: <code>123456789 Спам</code>",
        reply_markup=get_back_keyboard("admin_bans")
    )
    await state.set_state(AdminStates.waiting_for_ban_reason)


@dp.callback_query(F.data == "admin_unban_user")
async def admin_unban_user(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    await callback.message.edit_text(
        "🔓 <b>Разбан пользователя</b>\n\n"
        "Отправьте ID пользователя:",
        reply_markup=get_back_keyboard("admin_bans")
    )
    await state.set_state(AdminStates.waiting_for_user_id)
    await state.update_data(action="unban_user")


@dp.message(StateFilter(AdminStates.waiting_for_ban_reason))
async def process_admin_ban(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Доступ запрещен")
        await state.clear()
        return

    try:
        parts = message.text.strip().split(maxsplit=1)
        if len(parts) < 1:
            await message.answer("❌ Неверный формат. Отправьте ID и причину")
            return

        user_id = int(parts[0])
        reason = parts[1] if len(parts) > 1 else "Без причины"

        user = get_user(user_id)
        if not user:
            await message.answer("❌ Пользователь не найден")
            await state.clear()
            return

        if user_id == ADMIN_ID:
            await message.answer("❌ Нельзя забанить администратора")
            await state.clear()
            return

        ban_user(user_id, reason)

        await message.answer(f"✅ Пользователь {user_id} забанен. Причина: {reason}")

        # Уведомляем пользователя о бане
        try:
            await bot.send_message(
                user_id,
                f"⛔ <b>Вы забанены в боте</b>\n\nПричина: {reason}\n\nОбратитесь к администратору для разблокировки."
            )
        except:
            pass

    except ValueError:
        await message.answer("❌ Неверный формат ID")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

    await state.clear()


@dp.callback_query(F.data.startswith("admin_unban_user_"))
async def admin_unban_user_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    user_id = int(callback.data.replace("admin_unban_user_", ""))

    unban_user(user_id)
    await callback.answer(f"✅ Пользователь {user_id} разбанен", show_alert=True)

    # Возвращаемся к списку забаненных
    users = get_banned_users()
    await callback.message.edit_text(
        "🔨 <b>Забаненные пользователи</b>\n\n"
        "Нажмите на пользователя чтобы разбанить:",
        reply_markup=get_admin_banned_users_keyboard(users)
    )


@dp.callback_query(F.data == "admin_referral_stats")
async def admin_referral_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT COUNT(*) FROM referrals')
        total_referrals = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(DISTINCT user_id) FROM referrals')
        users_with_referrals = cursor.fetchone()[0]

        cursor.execute('SELECT AVG(referral_count) FROM users WHERE referral_count > 0')
        avg_referrals = cursor.fetchone()[0] or 0

        cursor.execute('''
                       SELECT u.username, u.first_name, u.referral_count
                       FROM users u
                       WHERE u.referral_count > 0
                       ORDER BY u.referral_count DESC LIMIT 5
                       ''')
        top_referrers = cursor.fetchall()
    except:
        total_referrals = 0
        users_with_referrals = 0
        avg_referrals = 0
        top_referrers = []

    conn.close()

    text = (
        f"📊 <b>Статистика рефералов</b>\n\n"
        f"👥 Всего рефералов: {total_referrals}\n"
        f"👤 Пользователей с рефералами: {users_with_referrals}\n"
        f"📈 Среднее количество: {avg_referrals:.1f}\n\n"
    )

    if top_referrers:
        text += "🏆 <b>Топ рефереров:</b>\n"
        for i, (username, first_name, count) in enumerate(top_referrers, 1):
            name = first_name or f"@{username}" or "Неизвестно"
            text += f"{i}. {name} — {count} рефералов\n"

    await callback.message.edit_text(text, reply_markup=get_back_keyboard("admin_referrals"))


@dp.callback_query(F.data == "admin_reset_referrals")
async def admin_reset_referrals(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    await callback.message.edit_text(
        "🔄 <b>Сброс рефералов</b>\n\n"
        "Отправьте ID пользователя для сброса рефералов\n"
        "(или 'all' для сброса у всех):",
        reply_markup=get_back_keyboard("admin_referrals")
    )
    await state.set_state(AdminStates.waiting_for_user_id)
    await state.update_data(action="reset_referrals")


@dp.callback_query(F.data == "admin_reset_all_referrals")
async def admin_reset_all_referrals(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    reset_all_referrals()
    await callback.answer("✅ Все рефералы сброшены", show_alert=True)
    await callback.message.edit_text(
        "👥 <b>Управление рефералами</b>\n\n"
        "Выберите действие:",
        reply_markup=get_admin_referrals_keyboard()
    )


@dp.callback_query(F.data == "admin_reset_top")
async def admin_reset_top(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    # Создаем клавиатуру с подтверждением
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, очистить", callback_data="admin_confirm_reset_top"),
        InlineKeyboardButton(text="❌ Нет, отмена", callback_data="admin_panel")
    )

    await callback.message.edit_text(
        "🗑 <b>Очистка топа</b>\n\n"
        "Вы уверены, что хотите очистить топ по балансу и рефералам?\n"
        "Это действие нельзя отменить!",
        reply_markup=builder.as_markup()
    )


@dp.callback_query(F.data == "admin_confirm_reset_top")
async def admin_confirm_reset_top(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    # Сбрасываем балансы и рефералов
    reset_all_balances()
    reset_all_referrals()

    await callback.message.edit_text(
        "✅ <b>Топ очищен!</b>\n\n"
        "Балансы и рефералы всех пользователей сброшены.",
        reply_markup=get_back_keyboard("admin_panel")
    )


@dp.message(StateFilter(AdminStates.waiting_for_user_id))
async def process_admin_user_id(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Доступ запрещен")
        await state.clear()
        return

    data = await state.get_data()
    action = data.get("action")
    user_input = message.text.strip()

    if user_input.lower() == 'all':
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()

        if action == "reset_referrals":
            try:
                cursor.execute('DELETE FROM referrals')
                cursor.execute('UPDATE users SET referral_count = 0')
                await message.answer("✅ Рефералы всех пользователей сброшены")
            except:
                await message.answer("❌ Ошибка при сбросе рефералов")

        elif action == "reset_sponsor":
            try:
                cursor.execute('DELETE FROM sponsor_bonuses')
                await message.answer("✅ Бонусы спонсоров сброшены для всех пользователей")
            except:
                await message.answer("❌ Ошибка при сбросе бонусов")

        elif action == "unban_user":
            try:
                cursor.execute('UPDATE users SET is_banned = 0, ban_reason = NULL')
                await message.answer("✅ Все пользователи разбанены")
            except:
                await message.answer("❌ Ошибка при разбане")

        conn.commit()
        conn.close()
        await state.clear()
        return

    try:
        user_id = int(user_input)
        user = get_user(user_id)

        if not user:
            await message.answer("❌ Пользователь не найден")
            await state.clear()
            return

        if action in ["add_tickets", "remove_tickets", "add_referral_tickets"]:
            await state.update_data(target_user_id=user_id)
            action_text = {
                "add_tickets": "выдать",
                "remove_tickets": "забрать",
                "add_referral_tickets": "выдать реферальных"
            }.get(action, "")

            # Получаем информацию о бонусах спонсоров
            claimed_sponsors = get_user_sponsor_bonuses(user_id)

            await message.answer(
                f"💰 Пользователь: {user['first_name']} (ID: {user_id})\n"
                f"💳 Текущий баланс: {user['balance']} билетов\n"
                f"👥 Рефералов: {user['referral_count']}\n"
                f"🤝 Бонусов спонсоров: {len(claimed_sponsors)}/{len(SPONSORS)}\n"
                f"🚫 Бан: {'Да' if user.get('is_banned') else 'Нет'}\n\n"
                f"Введите количество билетов для {action_text}:"
            )
            await state.set_state(AdminStates.waiting_for_amount)

        elif action == "reset_referrals":
            conn = sqlite3.connect('bot_database.db')
            cursor = conn.cursor()
            try:
                cursor.execute('DELETE FROM referrals WHERE user_id = ? OR referred_user_id = ?', (user_id, user_id))
                cursor.execute('UPDATE users SET referral_count = 0 WHERE user_id = ?', (user_id,))
                conn.commit()
                await message.answer(f"✅ Рефералы пользователя {user_id} сброшены")
            except:
                await message.answer(f"❌ Ошибка при сбросе рефералов")
            conn.close()
            await state.clear()

        elif action == "reset_sponsor":
            conn = sqlite3.connect('bot_database.db')
            cursor = conn.cursor()
            try:
                cursor.execute('DELETE FROM sponsor_bonuses WHERE user_id = ?', (user_id,))
                conn.commit()
                await message.answer(f"✅ Бонусы спонсоров сброшены для пользователя {user_id}")
            except:
                await message.answer(f"❌ Ошибка при сбросе бонусов")
            conn.close()
            await state.clear()

        elif action == "unban_user":
            unban_user(user_id)
            await message.answer(f"✅ Пользователь {user_id} разбанен")

            # Уведомляем пользователя
            try:
                await bot.send_message(
                    user_id,
                    f"🔓 <b>Вы разбанены в боте!</b>\n\n"
                    f"Теперь вы снова можете пользоваться ботом."
                )
            except:
                pass
            await state.clear()

    except ValueError:
        await message.answer("❌ Неверный формат ID. Отправьте число или 'all'")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        await state.clear()


@dp.message(StateFilter(AdminStates.waiting_for_amount))
async def process_admin_amount(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Доступ запрещен")
        await state.clear()
        return

    data = await state.get_data()
    action = data.get("action")
    user_id = data.get("target_user_id")

    try:
        amount = int(message.text.strip())

        if amount <= 0:
            await message.answer("❌ Количество должно быть положительным")
            return

        user = get_user(user_id)

        if action == "add_tickets":
            update_balance(user_id, amount)
            new_balance = user['balance'] + amount
            await message.answer(
                f"✅ Пользователю {user_id} выдано {amount} билетов\n"
                f"💳 Новый баланс: {new_balance} билетов"
            )

            try:
                await bot.send_message(
                    user_id,
                    f"💰 Вам начислено <b>{amount} билетов</b> администратором!\n"
                    f"💳 Текущий баланс: {new_balance} билетов"
                )
            except:
                pass

        elif action == "remove_tickets":
            if not update_balance(user_id, -amount):
                await message.answer("❌ Недостаточно билетов у пользователя")
                await state.clear()
                return

            new_balance = user['balance'] - amount
            await message.answer(
                f"✅ У пользователя {user_id} списано {amount} билетов\n"
                f"💳 Новый баланс: {new_balance} билетов"
            )

            try:
                await bot.send_message(
                    user_id,
                    f"➖ У вас списано <b>{amount} билетов</b> администратором.\n"
                    f"💳 Текущий баланс: {new_balance} билетов"
                )
            except:
                pass

        elif action == "add_referral_tickets":
            # Добавляем реферальные билеты
            update_balance(user_id, amount)

            # Увеличиваем счетчик рефералов
            conn = sqlite3.connect('bot_database.db')
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET referral_count = referral_count + ? WHERE user_id = ?', (amount, user_id))
            conn.commit()
            conn.close()

            new_balance = user['balance'] + amount
            new_referrals = user['referral_count'] + amount

            await message.answer(
                f"✅ Пользователю {user_id} выдано {amount} реферальных билетов\n"
                f"💳 Новый баланс: {new_balance} билетов\n"
                f"👥 Новое количество рефералов: {new_referrals}"
            )

            try:
                await bot.send_message(
                    user_id,
                    f"🎉 Вам начислено <b>{amount} реферальных билетов</b>!\n"
                    f"💳 Текущий баланс: {new_balance} билетов\n"
                    f"👥 Всего рефералов: {new_referrals}"
                )
            except:
                pass

    except ValueError:
        await message.answer("❌ Неверный формат. Введите число")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

    await state.clear()


@dp.callback_query(F.data.startswith("admin_user_"))
async def admin_user_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    user_id = int(callback.data.replace("admin_user_", ""))
    user = get_user(user_id)

    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    boost_status = "✅ Активен" if check_boost_active(user_id) else "❌ Не активен"
    if user.get('boost_used') == 1 and not check_boost_active(user_id):
        boost_status = "⏳ Истек"

    banned_status = "✅ Да" if user.get('is_banned') else "❌ Нет"
    captcha_status = "✅ Пройдена" if user.get('captcha_passed') == 1 else "❌ Не пройдена"

    # Получаем информацию о бонусах спонсоров
    claimed_sponsors = get_user_sponsor_bonuses(user_id)
    sponsor_count = len(claimed_sponsors)

    text = (
        f"👤 <b>Информация о пользователе</b>\n\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"👤 Имя: {user['first_name']}\n"
        f"📱 Username: @{user['username'] or 'Нет'}\n"
        f"💰 Баланс: <b>{user['balance']} билетов</b>\n"
        f"👥 Рефералов: {user['referral_count']}\n"
        f"🚀 Буст: {boost_status}\n"
        f"✅ Капча: {captcha_status}\n"
        f"🔨 Забанен: {banned_status}\n"
        f"🤝 Бонусов спонсоров: {sponsor_count}/{len(SPONSORS)}\n"
        f"📅 Дата регистрации: {user['joined_date']}\n"
    )

    if user.get('is_banned') and user.get('ban_reason'):
        text += f"📝 Причина бана: {user['ban_reason']}\n"

    # Кнопки для управления
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Выдать билеты", callback_data=f"admin_add_user_tickets_{user_id}"),
        InlineKeyboardButton(text="➖ Забрать билеты", callback_data=f"admin_remove_user_tickets_{user_id}")
    )
    builder.row(
        InlineKeyboardButton(text="🎫 Выдать реферальные", callback_data=f"admin_add_user_referral_{user_id}"),
        InlineKeyboardButton(text="🔄 Сбросить рефералов", callback_data=f"admin_reset_user_referrals_{user_id}")
    )
    builder.row(
        InlineKeyboardButton(text="🎁 Сбросить бонусы", callback_data=f"admin_reset_user_sponsor_{user_id}")
    )

    if user.get('is_banned'):
        builder.row(InlineKeyboardButton(text="🔓 Разбанить", callback_data=f"admin_unban_user_{user_id}"))
    else:
        builder.row(InlineKeyboardButton(text="🔨 Забанить", callback_data=f"admin_ban_user_{user_id}"))

    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_users"))

    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@dp.callback_query(F.data.startswith("admin_add_user_tickets_"))
async def admin_add_user_tickets(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    user_id = int(callback.data.replace("admin_add_user_tickets_", ""))
    user = get_user(user_id)

    await callback.message.edit_text(
        f"💰 <b>Выдача билетов пользователю {user['first_name']}</b>\n\n"
        f"Текущий баланс: {user['balance']} билетов\n\n"
        f"Введите количество билетов для выдачи:",
        reply_markup=get_back_keyboard("admin_users")
    )
    await state.set_state(AdminStates.waiting_for_amount)
    await state.update_data(action="add_tickets", target_user_id=user_id)


@dp.callback_query(F.data.startswith("admin_remove_user_tickets_"))
async def admin_remove_user_tickets(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    user_id = int(callback.data.replace("admin_remove_user_tickets_", ""))
    user = get_user(user_id)

    await callback.message.edit_text(
        f"➖ <b>Списание билетов у пользователя {user['first_name']}</b>\n\n"
        f"Текущий баланс: {user['balance']} билетов\n\n"
        f"Введите количество билетов для списания:",
        reply_markup=get_back_keyboard("admin_users")
    )
    await state.set_state(AdminStates.waiting_for_amount)
    await state.update_data(action="remove_tickets", target_user_id=user_id)


@dp.callback_query(F.data.startswith("admin_add_user_referral_"))
async def admin_add_user_referral(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    user_id = int(callback.data.replace("admin_add_user_referral_", ""))
    user = get_user(user_id)

    await callback.message.edit_text(
        f"🎫 <b>Выдача реферальных билетов пользователю {user['first_name']}</b>\n\n"
        f"Текущий баланс: {user['balance']} билетов\n"
        f"Текущие рефералы: {user['referral_count']}\n\n"
        f"Введите количество реферальных билетов для выдачи:",
        reply_markup=get_back_keyboard("admin_users")
    )
    await state.set_state(AdminStates.waiting_for_amount)
    await state.update_data(action="add_referral_tickets", target_user_id=user_id)


@dp.callback_query(F.data.startswith("admin_reset_user_referrals_"))
async def admin_reset_user_referrals(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    user_id = int(callback.data.replace("admin_reset_user_referrals_", ""))

    try:
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM referrals WHERE user_id = ? OR referred_user_id = ?', (user_id, user_id))
        cursor.execute('UPDATE users SET referral_count = 0 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        await callback.answer("✅ Рефералы пользователя сброшены", show_alert=True)
    except:
        await callback.answer("❌ Ошибка при сбросе рефералов", show_alert=True)

    # Возвращаемся к списку пользователей
    users = get_all_users(include_banned=True)
    await callback.message.edit_text(
        "👥 <b>Все пользователи</b>\n\n"
        "Последние пользователи:",
        reply_markup=get_admin_users_keyboard(users)
    )


@dp.callback_query(F.data.startswith("admin_reset_user_sponsor_"))
async def admin_reset_user_sponsor(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    user_id = int(callback.data.replace("admin_reset_user_sponsor_", ""))

    try:
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM sponsor_bonuses WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        await callback.answer("✅ Бонусы спонсоров сброшены", show_alert=True)
    except:
        await callback.answer("❌ Ошибка при сбросе бонусов", show_alert=True)

    # Возвращаемся к списку пользователей
    users = get_all_users(include_banned=True)
    await callback.message.edit_text(
        "👥 <b>Все пользователи</b>\n\n"
        "Последние пользователи:",
        reply_markup=get_admin_users_keyboard(users)
    )


@dp.callback_query(F.data.startswith("admin_ban_user_"))
async def admin_ban_user_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    user_id = int(callback.data.replace("admin_ban_user_", ""))

    if user_id == ADMIN_ID:
        await callback.answer("❌ Нельзя забанить администратора", show_alert=True)
        return

    await callback.message.edit_text(
        f"🔨 <b>Бан пользователя {user_id}</b>\n\n"
        f"Введите причину бана:",
        reply_markup=get_back_keyboard("admin_users")
    )
    await state.set_state(AdminStates.waiting_for_ban_reason)
    await state.update_data(target_user_id=user_id)


@dp.callback_query(F.data.startswith("admin_unban_user_"))
async def admin_unban_user_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    user_id = int(callback.data.replace("admin_unban_user_", ""))

    unban_user(user_id)
    await callback.answer(f"✅ Пользователь {user_id} разбанен", show_alert=True)

    # Уведомляем пользователя
    try:
        await bot.send_message(
            user_id,
            f"🔓 <b>Вы разбанены в боте!</b>\n\n"
            f"Теперь вы снова можете пользоваться ботом."
        )
    except:
        pass

    # Возвращаемся к списку пользователей
    users = get_all_users(include_banned=True)
    await callback.message.edit_text(
        "👥 <b>Все пользователи</b>\n\n"
        "Последние пользователи:",
        reply_markup=get_admin_users_keyboard(users)
    )


@dp.callback_query(F.data.startswith("admin_order_"))
async def admin_order_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    order_id = int(callback.data.replace("admin_order_", ""))

    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM orders WHERE order_id = ?', (order_id,))
    row = cursor.fetchone()
    cursor.execute('SELECT username, first_name FROM users WHERE user_id = ?', (row[1],))
    user_row = cursor.fetchone()
    conn.close()

    if not row:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    order = {
        'order_id': row[0],
        'user_id': row[1],
        'order_type': row[2],
        'amount': row[3],
        'price': row[4],
        'target_link': row[5],
        'reaction': row[6],
        'status': row[7],
        'created_at': row[8]
    }

    status_text = {
        'pending': '⏳ Ожидает',
        'completed': '✅ Выполнен',
        'rejected': '❌ Отклонен'
    }.get(order['status'], order['status'])

    type_text = {
        'subs': 'Подписчики',
        'views': 'Просмотры',
        'reactions': f'Реакции ({order["reaction"]})' if order['reaction'] else 'Реакции',
        'boost': '🚀 Буст канала (7 дней)'
    }.get(order['order_type'], order['order_type'])

    user_info = f"@{user_row[0]}" if user_row[0] else user_row[1] or f"ID {order['user_id']}"

    text = (
        f"📋 <b>Заказ #{order['order_id']}</b>\n\n"
        f"👤 Пользователь: {user_info}\n"
        f"🆔 ID: {order['user_id']}\n"
        f"📦 Тип: {type_text}\n"
        f"🔢 Количество: {order['amount']}\n"
        f"💰 Стоимость: {order['price']} билетов\n"
        f"📎 Цель: {order['target_link']}\n"
        f"📊 Статус: {status_text}\n"
        f"📅 Создан: {order['created_at']}"
    )

    if order['status'] == 'pending':
        await callback.message.edit_text(text, reply_markup=get_admin_order_action_keyboard(order_id))
    else:
        await callback.message.edit_text(text, reply_markup=get_back_keyboard("admin_orders"))


@dp.callback_query(F.data.startswith("approve_order_"))
async def approve_order_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    order_id = int(callback.data.replace("approve_order_", ""))

    # Получаем информацию о заказе
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, order_type, amount, target_link FROM orders WHERE order_id = ?', (order_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    user_id, order_type, amount, target_link = row

    # Обновляем статус заказа
    update_order_status(order_id, "completed")

    # Уведомляем пользователя
    type_text = {
        'subs': 'подписчиков',
        'views': 'просмотров',
        'reactions': 'реакций',
        'boost': 'буста канала'
    }.get(order_type, order_type)

    try:
        await bot.send_message(
            user_id,
            f"✅ <b>Заказ #{order_id} одобрен!</b>\n\n"
            f"📦 Тип: {type_text}\n"
            f"🔢 Количество: {amount if order_type != 'boost' else '7 дней'}\n"
            f"🎉 Заказ будет выполнен в ближайшее время!"
        )
    except:
        pass

    # Уведомляем админа об успехе
    await callback.message.edit_text(
        f"✅ Заказ #{order_id} одобрен",
        reply_markup=get_back_keyboard("admin_panel")
    )

    await callback.answer("Заказ одобрен")


@dp.callback_query(F.data.startswith("reject_order_"))
async def reject_order_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    order_id = int(callback.data.replace("reject_order_", ""))

    # Получаем информацию о заказе
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, order_type, amount, price FROM orders WHERE order_id = ?', (order_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    user_id, order_type, amount, price = row

    # Возвращаем билеты
    update_balance(user_id, price)

    # Обновляем статус заказа
    update_order_status(order_id, "rejected")

    # Уведомляем пользователя
    type_text = {
        'subs': 'подписчиков',
        'views': 'просмотров',
        'reactions': 'реакций',
        'boost': 'буста канала'
    }.get(order_type, order_type)

    try:
        await bot.send_message(
            user_id,
            f"❌ <b>Заказ #{order_id} отклонен</b>\n\n"
            f"📦 Тип: {type_text}\n"
            f"🔢 Количество: {amount if order_type != 'boost' else '7 дней'}\n"
            f"💰 Билеты ({price}) возвращены на ваш баланс.\n\n"
            f"Пожалуйста, свяжитесь с администратором для уточнения причин."
        )
    except:
        pass

    # Уведомляем админа об успехе
    await callback.message.edit_text(
        f"❌ Заказ #{order_id} отклонен, билеты возвращены",
        reply_markup=get_back_keyboard("admin_panel")
    )

    await callback.answer("Заказ отклонен")


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    # Общая статистика
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM users WHERE captcha_passed = 1')
    captcha_passed = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM users WHERE is_banned = 1')
    banned_users = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(DISTINCT user_id) FROM sponsor_bonuses')
    sponsor_bonus_users = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM orders')
    total_orders = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM orders WHERE status = "pending"')
    pending_orders = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM orders WHERE status = "completed"')
    completed_orders = cursor.fetchone()[0]

    cursor.execute('SELECT SUM(price) FROM orders WHERE status = "completed"')
    total_spent = cursor.fetchone()[0] or 0

    cursor.execute('SELECT SUM(balance) FROM users')
    total_balance = cursor.fetchone()[0] or 0

    try:
        cursor.execute('SELECT COUNT(*) FROM referrals')
        total_referrals = cursor.fetchone()[0]
    except:
        total_referrals = 0

    cursor.execute('SELECT COUNT(*) FROM users WHERE boost_used = 1')
    boost_users = cursor.fetchone()[0]

    conn.close()

    text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"✅ Прошли капчу: {captcha_passed}\n"
        f"🔨 Забанено: {banned_users}\n"
        f"🎁 Получили бонус спонсоров: {sponsor_bonus_users}\n"
        f"📦 Всего заказов: {total_orders}\n"
        f"⏳ Ожидают: {pending_orders}\n"
        f"✅ Выполнено: {completed_orders}\n"
        f"💰 Потрачено билетов: {total_spent}\n"
        f"💳 Всего билетов: {total_balance}\n"
        f"👥 Рефералов: {total_referrals}\n"
        f"🚀 Купили буст: {boost_users}\n"
    )

    await callback.message.edit_text(text, reply_markup=get_back_keyboard("admin_panel"))


# Обработчики навигации
@dp.callback_query(F.data == "back_to_main")
async def back_to_main_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "🌟 <b>Главное меню</b>\n\n"
        "Используйте кнопки ниже для навигации.",
        reply_markup=get_main_inline_keyboard(callback.from_user.id)
    )


@dp.callback_query(F.data == "order_type")
async def order_type_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "🛒 <b>Что хотите заказать?</b>\n\n"
        "Выберите тип услуги:",
        reply_markup=get_order_type_keyboard()
    )


@dp.callback_query(F.data == "referrals")
async def referrals_callback(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user:
        return

    bot_username = (await bot.me()).username
    referral_link = f"https://t.me/{bot_username}?start={user['user_id']}"

    text = (
        f"👥 <b>Реферальная программа</b>\n\n"
        f"🔗 <b>Ваша реферальная ссылка:</b>\n"
        f"<code>{referral_link}</code>\n\n"
        f"📊 <b>Приглашено пользователей:</b> {user['referral_count']}\n\n"
        f"💰 <b>Бонус:</b> За каждого приглашенного друга вы получаете <b>1 билет</b>!\n"
        f"🎁 Бонус начисляется сразу после прохождения капчи и подписки друга."
    )

    await callback.message.edit_text(text, reply_markup=get_back_keyboard())


@dp.callback_query(F.data == "top")
async def top_callback(callback: CallbackQuery):
    top_balance = get_top_users_by_balance(10)
    top_referrals = get_top_users_by_referrals(10)

    text = "🏆 <b>Топ пользователей</b>\n\n"

    text += "💰 <b>По балансу:</b>\n"
    for i, user in enumerate(top_balance, 1):
        name = user['first_name'] or user['username'] or f"User{user['user_id']}"
        text += f"{i}. {name} — {user['balance']} билетов\n"

    text += "\n👥 <b>По рефералам:</b>\n"
    for i, user in enumerate(top_referrals, 1):
        name = user['first_name'] or user['username'] or f"User{user['user_id']}"
        text += f"{i}. {name} — {user['referral_count']} рефералов\n"

    await callback.message.edit_text(text, reply_markup=get_back_keyboard())


@dp.callback_query(F.data == "sponsors")
async def sponsors_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    claimed_sponsors = get_user_sponsor_bonuses(user_id)

    text = (
        f"🤝 <b>Наши спонсоры</b>\n\n"
        f"Подпишитесь на каналы и получите бонусы:\n\n"
    )

    total_bonus = 0
    for sponsor in SPONSORS:
        status = "✅" if sponsor['url'] in claimed_sponsors else "❌"
        text += f"{status} {sponsor['name']}: +{sponsor['bonus']} билетов\n"
        if sponsor['url'] not in claimed_sponsors:
            total_bonus += sponsor['bonus']

    if total_bonus > 0:
        text += f"\n🎁 Доступно бонусов: <b>{total_bonus} билетов</b>"
    else:
        text += f"\n✅ Вы уже получили все бонусы!"

    await callback.message.edit_text(text, reply_markup=get_sponsors_keyboard(user_id))


# Запуск бота
async def main():
    # Запускаем фоновую задачу для проверки рефералов
    asyncio.create_task(check_and_notify_referrals())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

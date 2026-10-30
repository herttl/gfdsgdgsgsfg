import asyncio
import html
import math
import re

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, DiceEmoji
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from config import BOT_TOKEN, OWNER_IDS, DB_NAME


bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

GAME_EMOJI = {
    "cube": "🎲",
    "slots": "🎰",
    "bowling": "🎳",
    "dart": "🎯",
    "ball": "⚽️",
    "basket": "🏀",
}
SUPPORT_PAGE_SIZE = 8


class SettingState(StatesGroup):
    waiting_multiplier = State()
    waiting_support_reply = State()


async def db_execute(query, params=(), fetchone=False, fetchall=False):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        await db.commit()
        if fetchone:
            return await cursor.fetchone()
        if fetchall:
            return await cursor.fetchall()
        return None


async def init_db():
    # Таблицы создаются, если их нет; существующая база и статистика не сбрасываются.
    await db_execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance INTEGER NOT NULL DEFAULT 500,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            games INTEGER NOT NULL DEFAULT 0,
            cube_games INTEGER NOT NULL DEFAULT 0,
            slots_games INTEGER NOT NULL DEFAULT 0,
            bowling_games INTEGER NOT NULL DEFAULT 0,
            dart_games INTEGER NOT NULL DEFAULT 0,
            ball_games INTEGER NOT NULL DEFAULT 0,
            basket_games INTEGER NOT NULL DEFAULT 0
        )
    """)
    await db_execute("""
        CREATE TABLE IF NOT EXISTS settings (
            name TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    await db_execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL DEFAULT '',
            first_name TEXT NOT NULL DEFAULT '',
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new',
            owner_id INTEGER,
            reply TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    defaults = {
        "start_enabled": "1",
        "profile_enabled": "1",
        "stats_enabled": "1",
        "support_enabled": "1",
        "cube_enabled": "1",
        "slots_enabled": "1",
        "bowling_enabled": "1",
        "dart_enabled": "1",
        "ball_enabled": "1",
        "basket_enabled": "1",
        "cube_multiplier": "1.5",
        "slots_multiplier": "1.5",
        "bowling_multiplier": "1.5",
        "dart_multiplier": "1.5",
        "ball_multiplier": "1.5",
        "basket_multiplier": "1.5",
    }
    for name, value in defaults.items():
        await db_execute(
            "INSERT OR IGNORE INTO settings(name, value) VALUES (?, ?)",
            (name, value),
        )


async def get_setting(name):
    row = await db_execute(
        "SELECT value FROM settings WHERE name = ?", (name,), fetchone=True
    )
    return row["value"] if row else "1"


async def set_setting(name, value):
    await db_execute(
        "INSERT OR REPLACE INTO settings(name, value) VALUES (?, ?)",
        (name, str(value)),
    )


async def register_user(user):
    if user is None:
        return
    # При повторном входе обновляется только имя, баланс и статистика сохраняются.
    await db_execute("""
        INSERT INTO users(user_id, username, first_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name
    """, (user.id, user.username or "", user.first_name or ""))


async def user_data(user_id):
    return await db_execute(
        "SELECT * FROM users WHERE user_id = ?", (user_id,), fetchone=True
    )


def user_link(user):
    name = html.escape(user.full_name or "Пользователь")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def integer(value):
    return bool(re.fullmatch(r"-?\d+", value or ""))


def format_number(value):
    return f"{int(value):,}".replace(",", " ")


async def change_balance(user_id, amount):
    await db_execute(
        "UPDATE users SET balance = balance + ? WHERE user_id = ?",
        (amount, user_id),
    )


async def game_result(user_id, game, win, stake):
    field = f"{game}_games"  # game задаётся только внутренними обработчиками.
    stats_enabled = await get_setting("stats_enabled") == "1"
    counted = 1 if stats_enabled else 0
    if win:
        multiplier = float(await get_setting(f"{game}_multiplier"))
        payout = int(math.floor(stake * multiplier))
        await db_execute(f"""
            UPDATE users SET balance = balance + ?, wins = wins + ?,
                games = games + ?, {field} = {field} + ?
            WHERE user_id = ?
        """, (payout, counted, counted, counted, user_id))
        return payout

    await db_execute(f"""
        UPDATE users SET balance = balance - ?, losses = losses + ?,
            games = games + ?, {field} = {field} + ?
        WHERE user_id = ?
    """, (stake, counted, counted, counted, user_id))
    return 0


@dp.message.outer_middleware()
async def update_user_middleware(handler, event, data):
    if isinstance(event, Message) and event.from_user:
        await register_user(event.from_user)
    return await handler(event, data)


@dp.message(CommandStart())
async def start(message: Message):
    if await get_setting("start_enabled") == "1":
        await message.answer(
            "<i><b>⛩ Welcome!!</b></i>\n"
            "<i>Решил сыграть депнуть? Gooo)</i>"
        )


@dp.message(Command("profile"))
async def profile(message: Message):
    if await get_setting("profile_enabled") != "1":
        await message.answer("🏛 <i>Временно не работает..</i>")
        return
    row = await user_data(message.from_user.id)
    if row is None:
        await register_user(message.from_user)
        row = await user_data(message.from_user.id)
    text = (
        "🏛 <b>Профиль:</b>\n\n"
        f"🐾 {user_link(message.from_user)}\n"
        f"🍃<code>{message.from_user.id}</code>\n"
        f"🪬 Раймов: <b><i>{format_number(row['balance'])}</i></b>\n\n"
        "╭──<b> Statistic </b>\n"
        f"🎖 побед: <b>{row['wins']}</b>\n"
        f"🎭 луз: <b>{row['losses']}</b>\n"
        f"⚖️ игр: <b>{row['games']}</b>\n\n"
        "╭──<b> Game </b>\n"
        f"🎲 — <b>{row['cube_games']}</b>\n"
        f"🎰 — <b>{row['slots_games']}</b>\n"
        f"🎳 — <b>{row['bowling_games']}</b>\n"
        f"🎯 — <b>{row['dart_games']}</b>\n"
        f"⚽️ — <b>{row['ball_games']}</b>\n"
        f"🏀 — <b>{row['basket_games']}</b>"
    )
    await message.answer(text)


async def parse_stake(message):
    args = (message.text or "").split()
    if len(args) != 2 or not integer(args[1]):
        await message.answer("❗️Формат: команда ставка\nСтавка должна быть целым числом.")
        return None
    stake = int(args[1])
    if stake <= 0:
        await message.answer("❗️Ставка должна быть положительной.")
        return None
    return stake


async def valid_game(message, game, stake):
    if await get_setting(f"{game}_enabled") != "1":
        await message.answer("❗️<i>Временно не работает..</i>")
        return False
    if stake < 10:
        await message.answer("❗️Минимальная ставка — 10.")
        return False
    row = await user_data(message.from_user.id)
    if row is None or row["balance"] < stake:
        await message.answer("❗️Недостаточно раймов.")
        return False
    return True


def result_text(win, amount, dice_total=None):
    if win:
        first_line = (
            f"🍃 <i>В точку!! Выпало: <b>{dice_total}</b></i>\n"
            if dice_total is not None else ""
        )
        return first_line + f"✅ <i>Победа:</i> <b><i>+{amount}</i></b>"
    first_line = (
        f"🏮<i>Мимо.. Выпало: <b>{dice_total}</b></i>\n"
        if dice_total is not None else ""
    )
    return first_line + f"❌<i>Поражение:</i> <b><i>-{amount}</i></b>"


@dp.message(Command("cube"))
async def cube(message: Message):
    args = (message.text or "").split()
    if len(args) != 3 or not integer(args[1]) or not integer(args[2]):
        await message.answer("❗️Формат: /cube число ставка")
        return
    target, stake = int(args[1]), int(args[2])
    if not 2 <= target <= 12:
        await message.answer("❗️Число должно быть от 2 до 12.")
        return
    if stake <= 0:
        await message.answer("❗️Ставка должна быть положительной.")
        return
    if not await valid_game(message, "cube", stake):
        return
    first = await message.answer_dice(emoji=DiceEmoji.DICE)
    second = await message.answer_dice(emoji=DiceEmoji.DICE)
    total = first.dice.value + second.dice.value
    win = total == target
    payout = await game_result(message.from_user.id, "cube", win, stake)
    await message.answer(result_text(win, payout if win else stake, total))


async def simple_game(message, game, emoji, win_function):
    stake = await parse_stake(message)
    if stake is None or not await valid_game(message, game, stake):
        return
    result = await message.answer_dice(emoji=emoji)
    win = win_function(result.dice.value)
    payout = await game_result(message.from_user.id, game, win, stake)
    # Для игр, где число не требуется, значение броска не выводим.
    await message.answer(result_text(win, payout if win else stake))


@dp.message(Command("slots"))
async def slots(message: Message):
    await simple_game(message, "slots", DiceEmoji.SLOT_MACHINE, lambda value: value % 8 == 0)


@dp.message(Command("bowling"))
async def bowling(message: Message):
    await simple_game(message, "bowling", DiceEmoji.BOWLING, lambda value: value == 6)


@dp.message(Command("dart"))
async def dart(message: Message):
    await simple_game(message, "dart", DiceEmoji.DART, lambda value: value == 6)


@dp.message(Command("ball"))
async def ball(message: Message):
    await simple_game(message, "ball", DiceEmoji.FOOTBALL, lambda value: value in (3, 4, 5))


@dp.message(Command("basket"))
async def basket(message: Message):
    await simple_game(message, "basket", DiceEmoji.BASKETBALL, lambda value: value in (4, 5))


@dp.message(Command("graim"))
async def graim(message: Message):
    if message.from_user.id not in OWNER_IDS:
        try:
            await message.delete()
        except Exception:
            pass
        return
    args = (message.text or "").split()
    if len(args) != 3 or not integer(args[1]) or not integer(args[2]):
        await message.answer("❗️Формат: /graim id количество")
        return
    target_id, amount = int(args[1]), int(args[2])
    target = await user_data(target_id)
    if not target:
        await message.answer("❗️Пользователь не найден.")
        return
    await change_balance(target_id, amount)
    name = html.escape(target["first_name"] or target["username"] or str(target_id))
    target_name = f'<a href="tg://user?id={target_id}">{name}</a>'
    await message.answer(f"ライム <i>Вы выдали</i> {target_name} — <b>{amount}🪬</b>")
    try:
        await bot.send_message(target_id, f"ライム <i>Вам выдали</i> — <b>{amount}🪬</b>")
    except Exception:
        pass


# ------------------------- Поддержка -------------------------
def support_status(status):
    return {
        "new": "🆕 Новое",
        "answering": "✍️ Ожидает ответа",
        "accepted": "✅ Принято",
        "rejected": "⛔️ Отклонено",
    }.get(status, status)


def support_user_link(user_id, first_name, username):
    label = (f"@{username}" if username else first_name) or str(user_id)
    return f'<a href="tg://user?id={user_id}">{html.escape(label)}</a>'


async def support_list_markup(page=0):
    rows = await db_execute(
        "SELECT * FROM support_tickets ORDER BY ticket_id DESC", fetchall=True
    )
    start = page * SUPPORT_PAGE_SIZE
    shown = rows[start:start + SUPPORT_PAGE_SIZE]
    buttons = []
    for ticket in shown:
        label = (f"@{ticket['username']}" if ticket['username'] else ticket['first_name']) or str(ticket['user_id'])
        label = f"{label[:24]} — {support_status(ticket['status'])}"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"help_ticket_{ticket['ticket_id']}_{page}",
        )])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Предыдущая", callback_data=f"help_page_{page - 1}"))
    if start + SUPPORT_PAGE_SIZE < len(rows):
        nav.append(InlineKeyboardButton(text="Следующая ➡️", callback_data=f"help_page_{page + 1}"))
    if nav:
        buttons.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=buttons), len(rows)


async def show_support_list(target, page=0, edit=False):
    markup, count = await support_list_markup(page)
    text = f"Список «❗️Help List»\nВсего обращений: {count}"
    if edit:
        await target.edit_text(text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


@dp.message(Command("help"))
async def create_support_ticket(message: Message):
    if await get_setting("support_enabled") != "1":
        await message.answer("⛩ <i>Ведутся тех.работы..</i>")
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer("Укажите сообщение после команды: /help ваш вопрос")
        return
    text = parts[1].strip()
    user = message.from_user
    # Получаем ticket_id из той же транзакции, чтобы параллельные запросы не перепутались.
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "INSERT INTO support_tickets(user_id, username, first_name, message) VALUES (?, ?, ?, ?)",
            (user.id, user.username or "", user.first_name or "", text),
        )
        await db.commit()
        ticket_id = cursor.lastrowid

    link = support_user_link(user.id, user.first_name or "", user.username or "")
    owner_text = (
        "❗️<b><i>Новое обращение в поддержку</i></b>\n"
        f"Номер: <code>{ticket_id}</code>\n"
        f"От: {link}\n\n<i>{html.escape(text)}</i>"
    )
    delivered = False
    for owner_id in OWNER_IDS:
        try:
            await bot.send_message(owner_id, owner_text)
            delivered = True
        except Exception:
            pass
    if delivered:
        await message.answer("✅ Обращение отправлено в поддержку.")
    else:
        await message.answer("⚠️ Не удалось доставить обращение. Попробуйте позже.")


@dp.message(Command("helplist"))
async def support_list_command(message: Message):
    if message.from_user.id not in OWNER_IDS:
        return
    await show_support_list(message, 0)


@dp.callback_query(F.data.startswith("help_page_"))
async def support_page(callback: CallbackQuery):
    if callback.from_user.id not in OWNER_IDS:
        await callback.answer()
        return
    try:
        page = int(callback.data.rsplit("_", 1)[1])
        if page < 0:
            raise ValueError
    except ValueError:
        await callback.answer("Некорректная страница.", show_alert=True)
        return
    await show_support_list(callback.message, page, edit=True)
    await callback.answer()


@dp.callback_query(F.data.startswith("help_ticket_"))
async def support_ticket_view(callback: CallbackQuery):
    if callback.from_user.id not in OWNER_IDS:
        await callback.answer()
        return
    try:
        parts = callback.data.split("_")
        ticket_id, page = int(parts[2]), int(parts[3])
    except (ValueError, IndexError):
        await callback.answer("Некорректное обращение.", show_alert=True)
        return
    ticket = await db_execute(
        "SELECT * FROM support_tickets WHERE ticket_id = ?", (ticket_id,), fetchone=True
    )
    if not ticket:
        await callback.answer("Обращение не найдено.", show_alert=True)
        return
    link = support_user_link(ticket["user_id"], ticket["first_name"], ticket["username"])
    text = (
        f"⛩ {link} обратился с:\n\n<i>{html.escape(ticket['message'])}</i>\n\n"
        f"Статус: <b>{support_status(ticket['status'])}</b>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅Ответить", callback_data=f"help_reply_{ticket_id}"),
         InlineKeyboardButton(text="⛔️Отклонить", callback_data=f"help_reject_{ticket_id}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"help_delete_{ticket_id}_{page}")],
        [InlineKeyboardButton(text="⬅️Назад", callback_data=f"help_page_{page}")],

    ])
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data.startswith("help_reply_"))
async def support_reply_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in OWNER_IDS:
        await callback.answer()
        return
    try:
        ticket_id = int(callback.data.rsplit("_", 1)[1])
    except ValueError:
        await callback.answer("Некорректное обращение.", show_alert=True)
        return
    ticket = await db_execute(
        "SELECT ticket_id FROM support_tickets WHERE ticket_id = ?", (ticket_id,), fetchone=True
    )
    if not ticket:
        await callback.answer("Обращение не найдено.", show_alert=True)
        return
    await state.update_data(support_ticket_id=ticket_id)
    await state.set_state(SettingState.waiting_support_reply)
    await db_execute(
        "UPDATE support_tickets SET status = 'answering', owner_id = ? WHERE ticket_id = ?",
        (callback.from_user.id, ticket_id),
    )
    prompt = await callback.message.answer(
        f"Ответьте реплаем на это сообщение, чтобы отправить ответ по обращению #{ticket_id}."
    )
    await state.update_data(
        support_prompt_chat_id=prompt.chat.id,
        support_prompt_message_id=prompt.message_id,
    )
    await callback.answer("Ожидаю ответ.")


@dp.callback_query(F.data.startswith("help_delete_"))
async def support_delete(callback: CallbackQuery):
    if callback.from_user.id not in OWNER_IDS:
        await callback.answer()
        return

    try:
        _, _, _, ticket_id, page = callback.data.split("_")
        ticket_id, page = int(ticket_id), int(page)
    except (ValueError, TypeError):
        await callback.answer("Некорректное обращение.", show_alert=True)
        return

    ticket = await db_execute(
        "SELECT ticket_id FROM support_tickets WHERE ticket_id = ?",
        (ticket_id,), fetchone=True,
    )
    if not ticket:
        await callback.answer("Обращение уже удалено.", show_alert=True)
        return

    await db_execute(
        "DELETE FROM support_tickets WHERE ticket_id = ?",
        (ticket_id,),
    )

    await callback.answer("Обращение удалено.")
    await show_support_list(callback.message, page, edit=True)



@dp.message(SettingState.waiting_support_reply)
async def support_reply_receive(message: Message, state: FSMContext):
    if message.from_user.id not in OWNER_IDS:
        return
    data = await state.get_data()
    reply_to = message.reply_to_message
    if (not reply_to
            or reply_to.chat.id != data.get("support_prompt_chat_id")
            or reply_to.message_id != data.get("support_prompt_message_id")):
        await message.answer("Отправьте ответ реплаем на сообщение бота с просьбой ответить.")
        return
    reply_text = (message.text or message.caption or "").strip()
    if not reply_text:
        await message.answer("Нужен текстовый ответ. Попробуйте ещё раз.")
        return
    ticket_id = data.get("support_ticket_id")
    ticket = await db_execute(
        "SELECT * FROM support_tickets WHERE ticket_id = ?", (ticket_id,), fetchone=True
    )
    if not ticket:
        await state.clear()
        await message.answer("Обращение не найдено.")
        return
    try:
        await bot.send_message(
            ticket["user_id"],
            "⛩ <b>Обращение было принято:</b>\n\n"
            f"🎖 <i><b>{html.escape(reply_text)}</b></i>",
        )
    except Exception:
        await message.answer("Не удалось написать игроку. Возможно, он заблокировал бота.")
        return
    await db_execute(
        "UPDATE support_tickets SET status = 'accepted', owner_id = ?, reply = ? WHERE ticket_id = ?",
        (message.from_user.id, reply_text, ticket_id),
    )
    await state.clear()
    await message.answer("✅ Ответ отправлен игроку.")


@dp.callback_query(F.data.startswith("help_reject_"))
async def support_reject(callback: CallbackQuery):
    if callback.from_user.id not in OWNER_IDS:
        await callback.answer()
        return
    try:
        ticket_id = int(callback.data.rsplit("_", 1)[1])
    except ValueError:
        await callback.answer("Некорректное обращение.", show_alert=True)
        return
    ticket = await db_execute(
        "SELECT * FROM support_tickets WHERE ticket_id = ?", (ticket_id,), fetchone=True
    )
    if not ticket:
        await callback.answer("Обращение не найдено.", show_alert=True)
        return
    try:
        await bot.send_message(ticket["user_id"], "⚠️ <i>Ваше обращение было отклонено!</i>")
    except Exception:
        await callback.answer("Не удалось уведомить игрока.", show_alert=True)
        return
    await db_execute(
        "UPDATE support_tickets SET status = 'rejected', owner_id = ? WHERE ticket_id = ?",
        (callback.from_user.id, ticket_id),
    )
    link = support_user_link(ticket["user_id"], ticket["first_name"], ticket["username"])
    text = (
        f"⛩ {link} обратился с:\n\n<i>{html.escape(ticket['message'])}</i>\n\n"
        f"Статус: <b>{support_status('rejected')}</b>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=callback.message.reply_markup)
    except Exception:
        pass
    await callback.answer("Обращение отклонено.")


# ------------------------- Настройки -------------------------
def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏛 Профиль", callback_data="set_profile"), InlineKeyboardButton(text="⛩ Старт", callback_data="set_start")],
        [InlineKeyboardButton(text="🎖 Статистика", callback_data="set_stats")],
        [InlineKeyboardButton(text="❗️ Поддержка", callback_data="set_support")],
        [InlineKeyboardButton(text="🎲 Кости", callback_data="set_cube"), InlineKeyboardButton(text="🎰 Рулетка", callback_data="set_slots")],
        [InlineKeyboardButton(text="🎳 Боулинг", callback_data="set_bowling"), InlineKeyboardButton(text="🎯 Дартс", callback_data="set_dart")],
        [InlineKeyboardButton(text="⚽️ Мяч", callback_data="set_ball"), InlineKeyboardButton(text="🏀 Баскетбол", callback_data="set_basket")],
        [InlineKeyboardButton(text="✅ Save", callback_data="set_save")],
    ])


@dp.message(Command("config"))
async def config(message: Message):
    if message.chat.type != "private" or message.from_user.id not in OWNER_IDS:
        return
    await message.answer("<b><i>Настройки мини-игр, профилей и бота</i></b>", reply_markup=main_keyboard())


@dp.callback_query(F.data == "set_save")
async def save_settings(callback: CallbackQuery):
    if callback.from_user.id not in OWNER_IDS:
        await callback.answer()
        return
    await callback.message.delete()
    await callback.answer("Настройки сохранены.")


@dp.callback_query(F.data == "back_settings")
async def back_settings(callback: CallbackQuery):
    if callback.from_user.id not in OWNER_IDS:
        await callback.answer()
        return
    await callback.message.edit_text("<b><i>Настройки мини-игр, профилей и бота</i></b>", reply_markup=main_keyboard())
    await callback.answer()


@dp.callback_query(F.data.startswith("set_"))
async def settings_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in OWNER_IDS:
        await callback.answer()
        return
    name = callback.data.removeprefix("set_")
    if name == "stats":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚫 Сброс", callback_data="reset_stats"), InlineKeyboardButton(text="⛔️ Стоп", callback_data="stats_off")],
            [InlineKeyboardButton(text="✅ Вкл", callback_data="stats_on")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_settings")],
        ])
        await callback.message.edit_text("Настройки «🎖 Статистика»:", reply_markup=keyboard)
        await callback.answer()
        return
    if name == "support":
        enabled = await get_setting("support_enabled") == "1"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚫 Выкл", callback_data="support_toggle_0"),
             InlineKeyboardButton(text="✅ Вкл", callback_data="support_toggle_1")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_settings")],
        ])
        state_text = "включена" if enabled else "выключена"
        await callback.message.edit_text(
            f"Настройки «❗️Поддержка» (сейчас {state_text}):", reply_markup=keyboard
        )
        await callback.answer()
        return
    if name in ("profile", "start"):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚫 Выкл", callback_data=f"toggle_{name}_0"), InlineKeyboardButton(text="✅ Вкл", callback_data=f"toggle_{name}_1")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_settings")],
        ])
        title = "🏛 Профиль" if name == "profile" else "⛩ Старт"
        await callback.message.edit_text(f"Настройки «{title}»:", reply_markup=keyboard)
        await callback.answer()
        return
    if name not in GAME_EMOJI:
        await callback.answer("Неизвестная настройка.", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍃 Множ", callback_data=f"mult_{name}")],
        [InlineKeyboardButton(text="🚫 Выкл", callback_data=f"toggle_{name}_0"), InlineKeyboardButton(text="✅ Вкл", callback_data=f"toggle_{name}_1")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_settings")],
    ])
    await callback.message.edit_text(f"Настройки «{GAME_EMOJI[name]}»:", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data.startswith("support_toggle_"))
async def support_toggle(callback: CallbackQuery):
    if callback.from_user.id not in OWNER_IDS:
        await callback.answer()
        return
    value = callback.data.rsplit("_", 1)[1]
    if value not in ("0", "1"):
        await callback.answer("Некорректное значение.", show_alert=True)
        return
    await set_setting("support_enabled", value)
    await callback.answer("Поддержка включена." if value == "1" else "Поддержка выключена.")


@dp.callback_query(F.data.startswith("toggle_"))
async def toggle_setting(callback: CallbackQuery):
    if callback.from_user.id not in OWNER_IDS:
        await callback.answer()
        return
    parts = callback.data.split("_")
    if len(parts) != 3 or parts[2] not in ("0", "1"):
        await callback.answer("Некорректная настройка.", show_alert=True)
        return
    _, name, value = parts
    if name not in ("start", "profile", *GAME_EMOJI.keys()):
        await callback.answer("Неизвестная настройка.", show_alert=True)
        return
    await set_setting(f"{name}_enabled", value)
    await callback.answer("Изменено.")


@dp.callback_query(F.data == "stats_on")
async def stats_on(callback: CallbackQuery):
    if callback.from_user.id not in OWNER_IDS:
        await callback.answer()
        return
    await set_setting("stats_enabled", "1")
    await callback.answer("Статистика включена.")


@dp.callback_query(F.data == "stats_off")
async def stats_off(callback: CallbackQuery):
    if callback.from_user.id not in OWNER_IDS:
        await callback.answer()
        return
    await set_setting("stats_enabled", "0")
    await callback.answer("Статистика остановлена.")


@dp.callback_query(F.data == "reset_stats")
async def reset_stats(callback: CallbackQuery):
    if callback.from_user.id not in OWNER_IDS:
        await callback.answer()
        return
    await db_execute("""
        UPDATE users SET wins = 0, losses = 0, games = 0,
        cube_games = 0, slots_games = 0, bowling_games = 0,
        dart_games = 0, ball_games = 0, basket_games = 0
    """)
    await callback.answer("Статистика сброшена.")


@dp.callback_query(F.data.startswith("mult_"))
async def multiplier_request(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in OWNER_IDS:
        await callback.answer()
        return
    game = callback.data.removeprefix("mult_")
    if game not in GAME_EMOJI:
        await callback.answer("Неизвестная игра.", show_alert=True)
        return
    await state.update_data(game=game)
    await state.set_state(SettingState.waiting_multiplier)
    await callback.message.answer("Введите множитель, например: <code>1.5</code>")
    await callback.answer()


@dp.message(SettingState.waiting_multiplier)
async def save_multiplier(message: Message, state: FSMContext):
    if message.from_user.id not in OWNER_IDS:
        return
    try:
        number = float((message.text or "").replace(",", "."))
        if not math.isfinite(number) or number <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❗️Введите корректное число, например 1.5")
        return
    data = await state.get_data()
    game = data.get("game")
    if game not in GAME_EMOJI:
        await state.clear()
        await message.answer("❗️Не удалось определить игру. Откройте настройки снова.")
        return
    await set_setting(f"{game}_multiplier", number)
    await state.clear()
    await message.answer("✅ Множитель сохранён.")


async def main():
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

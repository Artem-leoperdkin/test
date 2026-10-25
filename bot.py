
import os
import sqlite3
import random
import csv
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬ_ТОКЕН_ОТ_BOTFATHER")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
PARTNER = os.getenv("PARTNER_NAME", "Партнёр")
PARTNER_URL = os.getenv("PARTNER_URL", "https://t.me/")
CHANNEL_ID = os.getenv("PARTNER_CHANNEL_ID", "")
DB = "giveaway.db"
MAX_CHANCES = 10

def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            uid INTEGER PRIMARY KEY, username TEXT, name TEXT, started TEXT
        );
        CREATE TABLE IF NOT EXISTS promos(
            code TEXT PRIMARY KEY, uid INTEGER UNIQUE, assigned TEXT
        );
        CREATE TABLE IF NOT EXISTS entries(
            uid INTEGER, day TEXT, partner TEXT, created TEXT,
            PRIMARY KEY(uid,day,partner)
        );
        CREATE TABLE IF NOT EXISTS active_days(
            uid INTEGER, day TEXT, PRIMARY KEY(uid,day)
        );
        CREATE TABLE IF NOT EXISTS draws(
            id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, partner TEXT,
            prize TEXT, winners TEXT, status TEXT DEFAULT 'pending',
            UNIQUE(day,partner)
        );
        CREATE TABLE IF NOT EXISTS contacts(
            uid INTEGER PRIMARY KEY, name TEXT, consent INTEGER
        );
        """)

def today():
    return date.today().isoformat()

def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")

def save_user(u):
    with conn() as c:
        c.execute("""INSERT INTO users VALUES(?,?,?,?)
        ON CONFLICT(uid) DO UPDATE SET username=excluded.username,name=excluded.name""",
        (u.id, u.username, u.first_name or "", now()))

def menu():
    return ReplyKeyboardMarkup([
        ["🎁 Получить промокод", "🎉 Участвовать в розыгрыше"],
        ["🎟 Мои шансы", "ℹ️ Как участвовать"],
        ["📜 Правила акции"]
    ], resize_keyboard=True)

def join_buttons():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Подписаться на партнёра", url=PARTNER_URL)],
        [InlineKeyboardButton("✅ Проверить подписку", callback_data="check")]
    ])

def active(uid):
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO active_days VALUES(?,?)", (uid, today()))

def chances(uid):
    with conn() as c:
        n = c.execute("SELECT COUNT(*) n FROM active_days WHERE uid=?", (uid,)).fetchone()["n"]
    return min(n, MAX_CHANCES)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)
    await update.message.reply_text("Добро пожаловать в Бот розыгрышей 🎪", reply_markup=menu())

async def promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    save_user(u)
    with conn() as c:
        old = c.execute("SELECT code FROM promos WHERE uid=?", (u.id,)).fetchone()
        if old:
            code = old["code"]
        else:
            row = c.execute("SELECT code FROM promos WHERE uid IS NULL LIMIT 1").fetchone()
            if not row:
                await update.message.reply_text(
                    f"Промокоды от {PARTNER} закончились 🔥 Но ты всё ещё можешь участвовать в розыгрыше.",
                    reply_markup=menu())
                return
            code = row["code"]
            c.execute("UPDATE promos SET uid=?,assigned=? WHERE code=? AND uid IS NULL",
                      (u.id, now(), code))
            active(u.id)
    await update.message.reply_text(
        f"Твой фестивальный бонус от {PARTNER} готов 🎁\n\n"
        f"Промокод: {code}\nИспользуй его до 31.12.2026 на сайте партнёра.\n\n"
        "Теперь можешь участвовать в розыгрыше призов дня.",
        reply_markup=menu())

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)
    await update.message.reply_text(
        f"Чтобы участвовать в розыгрыше от {PARTNER}, подпишись на канал партнёра, затем проверь подписку.",
        reply_markup=join_buttons())

async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if not CHANNEL_ID:
        await q.message.reply_text("Администратор ещё не настроил проверку подписки.")
        return
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, uid)
        subscribed = member.status in ("member", "administrator", "creator") or (
            member.status == "restricted" and getattr(member, "is_member", False))
    except Exception:
        await q.message.reply_text("Не удалось проверить подписку. Попробуй позже.")
        return
    if not subscribed:
        await q.message.reply_text("Пока не вижу подписку 👀 Подпишись и проверь ещё раз.", reply_markup=join_buttons())
        return
    with conn() as c:
        exists = c.execute("SELECT 1 FROM entries WHERE uid=? AND day=? AND partner=?",
                           (uid, today(), PARTNER)).fetchone()
        if exists:
            await q.message.reply_text("Ты уже участвуешь в сегодняшнем розыгрыше ✅")
            return
        c.execute("INSERT INTO entries VALUES(?,?,?,?)", (uid, today(), PARTNER, now()))
        c.execute("INSERT OR IGNORE INTO active_days VALUES(?,?)", (uid, today()))
    await q.message.reply_text(
        f"Ты в лайнапе ✅\nЗаявка зарегистрирована.\nТвои шансы: {chances(uid)} из {MAX_CHANCES}.\nВозвращайся завтра!")

async def my_chances(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with conn() as c:
        days = c.execute("SELECT day FROM active_days WHERE uid=? ORDER BY day", (uid,)).fetchall()
        partners = c.execute("SELECT DISTINCT partner FROM entries WHERE uid=?", (uid,)).fetchall()
    await update.message.reply_text(
        f"🎟 Твой фестивальный пропуск\nНакоплено шансов: {chances(uid)} из 10\n"
        f"Активные дни: {len(days)}\nПартнёры: {', '.join(x['partner'] for x in partners) or 'Пока нет'}\n"
        "Главный приз: главный приз фестиваля")

async def howto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "1. Получи промокод или участвуй в ежедневном розыгрыше.\n"
        "2. Для ежедневного розыгрыша подпишись на канал партнёра и проверь подписку.\n"
        "3. Один активный день даёт один шанс, максимум 10.")

async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Правила: для ежедневного розыгрыша нужна подтверждённая подписка. "
        "Одна заявка на пользователя в день у партнёра. Один шанс за активный день, максимум 10. "
        "Победителей подтверждает администратор. Организатор должен отдельно опубликовать сроки, призы "
        "и правила обработки персональных данных.")

def admin(update):
    return update.effective_user.id in ADMIN_IDS

async def addpromo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin(update):
        await update.message.reply_text("Команда доступна только администратору.")
        return
    if not context.args:
        await update.message.reply_text("Пример: /addpromo ABC123 DEF456")
        return
    with conn() as c:
        for code in context.args:
            c.execute("INSERT OR IGNORE INTO promos(code) VALUES(?)", (code,))
    await update.message.reply_text(f"Добавлено промокодов: {len(context.args)}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin(update):
        await update.message.reply_text("Команда доступна только администратору.")
        return
    with conn() as c:
        users = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        total = c.execute("SELECT COUNT(*) n FROM promos").fetchone()["n"]
        used = c.execute("SELECT COUNT(*) n FROM promos WHERE uid IS NOT NULL").fetchone()["n"]
        entries = c.execute("SELECT COUNT(*) n FROM entries").fetchone()["n"]
        days = c.execute("SELECT day,COUNT(*) n FROM entries GROUP BY day ORDER BY day").fetchall()
    await update.message.reply_text(
        f"📊 Пользователей: {users}\nПромокодов выдано: {used}/{total}\nУчастий: {entries}\n" +
        "По дням: " + (", ".join(f"{r['day']}: {r['n']}" for r in days) or "пока нет"))

async def draw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin(update):
        await update.message.reply_text("Команда доступна только администратору.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Пример: /draw 2026-10-26 3 Название_приза")
        return
    day = context.args[0]
    try:
        count = int(context.args[1])
        if count < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Количество победителей должно быть положительным числом.")
        return
    prize = " ".join(context.args[2:]) or "Приз дня"
    with conn() as c:
        old = c.execute("SELECT id,status FROM draws WHERE day=? AND partner=?", (day, PARTNER)).fetchone()
        if old and old["status"] == "approved":
            await update.message.reply_text("Этот розыгрыш уже подтверждён.")
            return
        ids = [r["uid"] for r in c.execute(
            "SELECT uid FROM entries WHERE day=? AND partner=?", (day, PARTNER)).fetchall()]
        if not ids:
            await update.message.reply_text("В этот день нет участников.")
            return
        winners = random.SystemRandom().sample(ids, min(count, len(ids)))
        if old:
            draw_id = old["id"]
            c.execute("UPDATE draws SET prize=?,winners=?,status='pending' WHERE id=?",
                      (prize, ",".join(map(str, winners)), draw_id))
        else:
            cur = c.execute("INSERT INTO draws(day,partner,prize,winners) VALUES(?,?,?,?)",
                            (day, PARTNER, prize, ",".join(map(str, winners))))
            draw_id = cur.lastrowid
    await update.message.reply_text(
        f"Результат ожидает подтверждения администратора.\nПобедители: {', '.join(map(str, winners))}\n"
        f"Подтвердить: /approve {draw_id}")

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin(update):
        await update.message.reply_text("Команда доступна только администратору.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Пример: /approve 1")
        return
    draw_id = int(context.args[0])
    with conn() as c:
        d = c.execute("SELECT * FROM draws WHERE id=?", (draw_id,)).fetchone()
        if not d:
            await update.message.reply_text("Розыгрыш не найден.")
            return
        if d["status"] == "approved":
            await update.message.reply_text("Уже подтверждено.")
            return
        winners = [int(x) for x in d["winners"].split(",") if x]
        c.execute("UPDATE draws SET status='approved' WHERE id=?", (draw_id,))
    sent = 0
    for uid in winners:
        try:
            await context.bot.send_message(
                uid, f"Ты в числе хедлайнеров дня 🔥\nТы выиграл {d['prize']} от {PARTNER}.\n"
                     "Чтобы получить приз, отправь /contact Имя Фамилия | да")
            sent += 1
        except Exception:
            pass
    await update.message.reply_text(f"Розыгрыш подтверждён. Уведомлений отправлено: {sent}.")

async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = " ".join(context.args)
    parts = raw.split("|", 1)
    if len(parts) != 2 or parts[1].strip().lower() not in ("да", "yes", "согласен", "согласна"):
        await update.message.reply_text("Формат: /contact Имя Фамилия | да")
        return
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO contacts VALUES(?,?,1)",
                  (update.effective_user.id, parts[0].strip()))
    await update.message.reply_text("Имя сохранено, согласие зафиксировано.")

async def export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin(update):
        await update.message.reply_text("Команда доступна только администратору.")
        return
    path = "participants.csv"
    with conn() as c, open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["day", "partner", "user_id", "registered_at"])
        writer.writerows(c.execute("SELECT day,partner,uid,created FROM entries ORDER BY day,created"))
    with open(path, "rb") as f:
        await update.message.reply_document(f, filename=path)

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query.data == "check":
        await check(update, context)

async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    actions = {
        "🎁 Получить промокод": promo,
        "🎉 Участвовать в розыгрыше": join,
        "🎟 Мои шансы": my_chances,
        "ℹ️ Как участвовать": howto,
        "📜 Правила акции": rules
    }
    if text in actions:
        await actions[text](update, context)
    else:
        await update.message.reply_text("Выбери действие в меню.", reply_markup=menu())

def main():
    if not TOKEN or TOKEN == "ВСТАВЬ_ТОКЕН_ОТ_BOTFATHER":
        raise SystemExit("Вставь токен от @BotFather в TOKEN или переменную BOT_TOKEN.")
    init()
    app = Application.builder().token(TOKEN).build()
    for command, handler in [
        ("start", start), ("addpromo", addpromo), ("stats", stats),
        ("draw", draw), ("approve", approve), ("contact", contact), ("export", export)
    ]:
        app.add_handler(CommandHandler(command, handler))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messages))
    app.run_polling()

if __name__ == "__main__":
    main()

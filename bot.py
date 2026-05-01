import sqlite3
import os
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 5575627219

states = {}

# ---------- DB ----------
def db():
    return sqlite3.connect("bot.db")

def init():
    conn = db()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        name TEXT,
        balance REAL DEFAULT 0,
        refs INTEGER DEFAULT 0
    )""")

    conn.commit()
    conn.close()

# ---------- UI ----------
def menu(uid):
    kb = [
        [InlineKeyboardButton("💰 Wallet", callback_data="wallet")],
        [InlineKeyboardButton("👥 Refer", callback_data="refer")],
        [InlineKeyboardButton("📊 Stats", callback_data="stats")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")]
    ]

    if uid == ADMIN_ID:
        kb.append([InlineKeyboardButton("🛠 Admin", callback_data="admin")])

    return InlineKeyboardMarkup(kb)

def back():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]])

# ---------- START ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user

    conn = db()
    c = conn.cursor()

    c.execute("INSERT OR IGNORE INTO users(user_id,username,name) VALUES(?,?,?)",
              (u.id, u.username, u.first_name))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"👋 Welcome {u.first_name}\n\n💸 Earn with referrals!",
        reply_markup=menu(u.id)
    )

# ---------- CALLBACK ----------
async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    conn = db()
    c = conn.cursor()

    if q.data == "wallet":
        c.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
        bal = c.fetchone()[0]
        await q.edit_message_text(f"💰 Balance: ₹{bal}", reply_markup=back())

    elif q.data == "refer":
        link = f"https://t.me/{context.bot.username}?start={uid}"
        await q.edit_message_text(f"🔗 Your link:\n{link}", reply_markup=back())

    elif q.data == "stats":
        c.execute("SELECT refs FROM users WHERE user_id=?", (uid,))
        r = c.fetchone()[0]
        await q.edit_message_text(f"👥 Referrals: {r}", reply_markup=back())

    elif q.data == "withdraw":
        states[uid] = "UPI"
        await q.edit_message_text("Enter UPI:", reply_markup=back())

    # ===== ADMIN PANEL =====
    elif q.data == "admin":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Search", callback_data="search")],
            [InlineKeyboardButton("➕ Credit", callback_data="credit")],
            [InlineKeyboardButton("➖ Debit", callback_data="debit")],
            [InlineKeyboardButton("🔙 Back", callback_data="back")]
        ])
        await q.edit_message_text("🛠 Admin Panel", reply_markup=kb)

    elif q.data == "search":
        states[uid] = "SEARCH"
        await q.edit_message_text("Enter user ID:")

    elif q.data == "credit":
        states[uid] = "CREDIT_ID"
        await q.edit_message_text("Enter user ID to credit:")

    elif q.data == "debit":
        states[uid] = "DEBIT_ID"
        await q.edit_message_text("Enter user ID to debit:")

    elif q.data == "back":
        await q.edit_message_text("🏠 Menu", reply_markup=menu(uid))

    conn.close()

# ---------- MESSAGE ----------
async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    state = states.get(uid)

    conn = db()
    c = conn.cursor()

    # SEARCH
    if state == "SEARCH":
        c.execute("SELECT * FROM users WHERE user_id=?", (int(text),))
        u = c.fetchone()

        if u:
            await update.message.reply_text(f"👤 {u[2]}\n💰 ₹{u[3]}")
        else:
            await update.message.reply_text("Not found")

        states.pop(uid)

    # CREDIT
    elif state == "CREDIT_ID":
        states[uid] = ("CREDIT_AMT", int(text))
        await update.message.reply_text("Enter amount:")

    elif isinstance(state, tuple) and state[0] == "CREDIT_AMT":
        user_id = state[1]
        amt = float(text)

        c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amt, user_id))
        conn.commit()

        await context.bot.send_message(user_id, f"💰 ₹{amt} credited to your account")
        await update.message.reply_text("Done")

        states.pop(uid)

    # DEBIT
    elif state == "DEBIT_ID":
        states[uid] = ("DEBIT_AMT", int(text))
        await update.message.reply_text("Enter amount:")

    elif isinstance(state, tuple) and state[0] == "DEBIT_AMT":
        user_id = state[1]
        amt = float(text)

        c.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amt, user_id))
        conn.commit()

        await context.bot.send_message(user_id, f"➖ ₹{amt} deducted from your account")
        await update.message.reply_text("Done")

        states.pop(uid)

    # WITHDRAW
    elif state == "UPI":
        states[uid] = ("AMT", text)
        await update.message.reply_text("Enter amount:")

    elif isinstance(state, tuple) and state[0] == "AMT":
        upi = state[1]
        amt = float(text)

        await context.bot.send_message(ADMIN_ID, f"Withdraw\nUser:{uid}\n₹{amt}\nUPI:{upi}")
        await update.message.reply_text("Request sent")

        states.pop(uid)

    conn.close()

# ---------- MAIN ----------
def main():
    init()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(MessageHandler(filters.TEXT, msg))

    print("🚀 Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()

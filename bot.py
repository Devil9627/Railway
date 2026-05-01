import sqlite3
import os
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 5575627219

user_states = {}

# ================= DB =================
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
        referrals INTEGER DEFAULT 0,
        banned INTEGER DEFAULT 0
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS tx(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        amount REAL,
        date TEXT
    )""")

    conn.commit()
    conn.close()

# ================= UI =================
def menu(uid):
    kb = [
        [InlineKeyboardButton("💰 Wallet", callback_data="wallet")],
        [InlineKeyboardButton("👥 Refer", callback_data="refer")],
        [InlineKeyboardButton("📊 Stats", callback_data="stats")],
        [InlineKeyboardButton("📜 History", callback_data="history")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")]
    ]
    if uid == ADMIN_ID:
        kb.append([InlineKeyboardButton("🛠 Admin Panel", callback_data="admin")])
    return InlineKeyboardMarkup(kb)

def back():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]])

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    conn = db()
    c = conn.cursor()

    c.execute("INSERT OR IGNORE INTO users(user_id,username,name) VALUES(?,?,?)",
              (user.id, user.username, user.first_name))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"👋 Welcome {user.first_name}!\n\n"
        "💸 Earn money using referrals\n"
        "🎯 Use menu below:",
        reply_markup=menu(user.id)
    )

# ================= CALLBACK =================
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
        c.execute("SELECT referrals FROM users WHERE user_id=?", (uid,))
        r = c.fetchone()[0]
        await q.edit_message_text(f"👥 Referrals: {r}", reply_markup=back())

    elif q.data == "history":
        c.execute("SELECT type,amount FROM tx WHERE user_id=?", (uid,))
        rows = c.fetchall()
        text = "📜 History:\n\n"
        for i in rows:
            text += f"{i[0]} ₹{i[1]}\n"
        await q.edit_message_text(text, reply_markup=back())

    elif q.data == "withdraw":
        user_states[uid] = "UPI"
        await q.edit_message_text("💳 Enter UPI ID:", reply_markup=back())

    # ===== ADMIN =====
    elif q.data == "admin":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Search User", callback_data="search")],
            [InlineKeyboardButton("🔙 Back", callback_data="back")]
        ])
        await q.edit_message_text("🛠 Admin Panel", reply_markup=kb)

    elif q.data == "search":
        user_states[uid] = "SEARCH"
        await q.edit_message_text("Enter user ID or username:")

    elif q.data.startswith("add_"):
        user_states[uid] = ("ADD", int(q.data.split("_")[1]))
        await q.edit_message_text("Enter amount:")

    elif q.data.startswith("ded_"):
        user_states[uid] = ("DED", int(q.data.split("_")[1]))
        await q.edit_message_text("Enter amount:")

    elif q.data == "back":
        await q.edit_message_text("🏠 Menu", reply_markup=menu(uid))

    conn.close()

# ================= MESSAGE =================
async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    state = user_states.get(uid)

    conn = db()
    c = conn.cursor()

    # Withdraw
    if state == "UPI":
        user_states[uid] = ("AMT", text)
        await update.message.reply_text("Enter amount:")
        return

    elif isinstance(state, tuple) and state[0] == "AMT":
        upi = state[1]
        amt = float(text)

        c.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amt, uid))
        c.execute("INSERT INTO tx(user_id,type,amount,date) VALUES(?,?,?,?)",
                  (uid, "withdraw", amt, str(datetime.now())))
        conn.commit()

        await context.bot.send_message(ADMIN_ID, f"💸 Withdraw Request\nUser: {uid}\n₹{amt}\nUPI: {upi}")
        await update.message.reply_text("✅ Request sent")

        user_states.pop(uid)

    # Search user
    elif state == "SEARCH":
        if text.isdigit():
            c.execute("SELECT * FROM users WHERE user_id=?", (int(text),))
        else:
            c.execute("SELECT * FROM users WHERE username=?", (text.replace("@",""),))
        u = c.fetchone()

        if not u:
            await update.message.reply_text("❌ Not found")
            return

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add", callback_data=f"add_{u[0]}"),
             InlineKeyboardButton("➖ Deduct", callback_data=f"ded_{u[0]}")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin")]
        ])

        await update.message.reply_text(
            f"👤 {u[2]}\n🆔 {u[0]}\n💰 ₹{u[3]}\n👥 {u[4]}",
            reply_markup=kb
        )

        user_states.pop(uid)

    elif isinstance(state, tuple) and state[0] == "ADD":
        tid = state[1]
        amt = float(text)
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amt, tid))
        conn.commit()
        await update.message.reply_text(f"✅ Added ₹{amt}")
        user_states.pop(uid)

    elif isinstance(state, tuple) and state[0] == "DED":
        tid = state[1]
        amt = float(text)
        c.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amt, tid))
        conn.commit()
        await update.message.reply_text(f"➖ Deducted ₹{amt}")
        user_states.pop(uid)

    conn.close()

# ================= MAIN =================
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

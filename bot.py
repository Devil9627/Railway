import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = "8746636665:AAGG8-sKbexfpwqR1iDmtsh3hRrS2JyyWQ4"
ADMIN_ID = 5575627219

REFERRAL_REWARD = 5
MIN_WITHDRAW = 50

user_states = {}

# ================= DATABASE =================
def db():
    return sqlite3.connect("bot.db")

def init_db():
    conn = db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        referrer_id INTEGER,
        balance REAL DEFAULT 0,
        total_referrals INTEGER DEFAULT 0,
        joined_date TEXT,
        banned INTEGER DEFAULT 0
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS withdrawals(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        upi TEXT,
        status TEXT DEFAULT 'pending',
        date TEXT
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS transactions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        amount REAL,
        date TEXT
    )""")

    conn.commit()
    conn.close()

# ================= HELPERS =================
def get_user(uid):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    r = c.fetchone()
    conn.close()
    return r

def get_user_by_username(username):
    username = username.replace("@","")
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username=?", (username,))
    r = c.fetchone()
    conn.close()
    return r

def add_user(uid, username, name, ref):
    if get_user(uid):
        return False
    conn = db()
    c = conn.cursor()
    c.execute("""INSERT INTO users(user_id,username,first_name,referrer_id,joined_date)
                 VALUES(?,?,?,?,?)""",(uid,username,name,ref,datetime.now()))
    conn.commit()
    conn.close()
    return True

def update_balance(uid, amt):
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amt, uid))
    conn.commit()
    conn.close()

def add_tx(uid, t, amt):
    conn = db()
    c = conn.cursor()
    c.execute("INSERT INTO transactions(user_id,type,amount,date) VALUES(?,?,?,?)",
              (uid,t,amt,datetime.now()))
    conn.commit()
    conn.close()

# ================= UI =================
def menu(uid):
    btns = [
        [InlineKeyboardButton("💰 Wallet", callback_data="wallet")],
        [InlineKeyboardButton("👥 Invite", callback_data="refer")],
        [InlineKeyboardButton("📊 Stats", callback_data="stats")],
        [InlineKeyboardButton("📜 History", callback_data="history")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")]
    ]
    if uid == ADMIN_ID:
        btns.append([InlineKeyboardButton("🛠 Admin", callback_data="admin")])
    return InlineKeyboardMarkup(btns)

def back():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]])

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id

    u = get_user(uid)
    if u and u[7] == 1:
        await update.message.reply_text("🚫 You are banned")
        return

    ref = None
    if context.args:
        try:
            r = int(context.args[0])
            if r != uid:
                ref = r
        except:
            pass

    created = add_user(uid, user.username or "", user.first_name, ref)

    if created and ref and get_user(ref):
        update_balance(ref, REFERRAL_REWARD)
        add_tx(ref, "referral", REFERRAL_REWARD)

    await update.message.reply_text("🏠 Menu", reply_markup=menu(uid))

# ================= CALLBACK =================
async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    data = q.data
    u = get_user(uid)

    if data == "wallet":
        await q.edit_message_text(f"💰 Balance: ₹{u[4]}", reply_markup=back())

    elif data == "refer":
        link = f"https://t.me/{context.bot.username}?start={uid}"
        await q.edit_message_text(link, reply_markup=back())

    elif data == "stats":
        await q.edit_message_text(f"👥 Referrals: {u[5]}", reply_markup=back())

    elif data == "history":
        conn = db(); c = conn.cursor()
        c.execute("SELECT type,amount FROM transactions WHERE user_id=?", (uid,))
        rows = c.fetchall(); conn.close()

        text = "📜 History\n\n"
        for r in rows:
            text += f"{r[0]} ₹{r[1]}\n"

        await q.edit_message_text(text, reply_markup=back())

    elif data == "withdraw":
        user_states[uid] = "UPI"
        await q.edit_message_text("💳 Enter UPI ID:", reply_markup=back())

    # ===== ADMIN =====
    elif data == "admin":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Search User", callback_data="search")],
            [InlineKeyboardButton("📥 Withdraws", callback_data="pending")],
            [InlineKeyboardButton("🔙 Back", callback_data="back")]
        ])
        await q.edit_message_text("🛠 Admin Panel", reply_markup=kb)

    elif data == "search":
        user_states[uid] = "SEARCH"
        await q.edit_message_text("Enter ID or username:")

    elif data == "pending":
        conn = db(); c = conn.cursor()
        c.execute("SELECT id,user_id,amount FROM withdrawals WHERE status='pending'")
        rows = c.fetchall(); conn.close()

        if not rows:
            await q.edit_message_text("No pending", reply_markup=back())
            return

        text = "📥 Pending:\n\n"
        for r in rows:
            text += f"{r[0]} | {r[1]} | ₹{r[2]}\n"

        await q.edit_message_text(text, reply_markup=back())

    elif data == "back":
        await q.edit_message_text("🏠 Menu", reply_markup=menu(uid))

    # ===== ADMIN ACTIONS =====
    elif data.startswith("add_"):
        user_states[uid] = ("ADD", int(data.split("_")[1]))
        await q.edit_message_text("Enter amount to ADD:")

    elif data.startswith("ded_"):
        user_states[uid] = ("DED", int(data.split("_")[1]))
        await q.edit_message_text("Enter amount to DEDUCT:")

    elif data.startswith("ban_"):
        tid = int(data.split("_")[1])
        conn = db(); c = conn.cursor()
        c.execute("UPDATE users SET banned=1 WHERE user_id=?", (tid,))
        conn.commit(); conn.close()
        await q.edit_message_text("🚫 User banned", reply_markup=back())

    elif data.startswith("unban_"):
        tid = int(data.split("_")[1])
        conn = db(); c = conn.cursor()
        c.execute("UPDATE users SET banned=0 WHERE user_id=?", (tid,))
        conn.commit(); conn.close()
        await q.edit_message_text("✅ User unbanned", reply_markup=back())

# ================= MESSAGE =================
async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    state = user_states.get(uid)

    if state == "UPI":
        user_states[uid] = ("AMT", text)
        await update.message.reply_text("Enter amount:")
        return

    elif isinstance(state, tuple) and state[0] == "AMT":
        upi = state[1]
        try:
            amt = float(text)
        except:
            return

        u = get_user(uid)
        if not u or amt < MIN_WITHDRAW or amt > u[4]:
            return

        update_balance(uid, -amt)
        add_tx(uid, "withdraw", -amt)

        conn = db(); c = conn.cursor()
        c.execute("INSERT INTO withdrawals(user_id,amount,upi,date) VALUES(?,?,?,?)",
                  (uid, amt, upi, datetime.now()))
        conn.commit(); conn.close()

        user_states.pop(uid)

        await context.bot.send_message(ADMIN_ID, f"💸 Withdraw\nUser:{uid}\n₹{amt}")
        await update.message.reply_text("✅ Requested")

    elif state == "SEARCH":
        if text.isdigit():
            u = get_user(int(text))
        else:
            u = get_user_by_username(text)

        if not u:
            await update.message.reply_text("❌ Not found")
            return

        tid = u[0]

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add", callback_data=f"add_{tid}"),
             InlineKeyboardButton("➖ Deduct", callback_data=f"ded_{tid}")],
            [InlineKeyboardButton("🚫 Ban", callback_data=f"ban_{tid}"),
             InlineKeyboardButton("✅ Unban", callback_data=f"unban_{tid}")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin")]
        ])

        await update.message.reply_text(
            f"👤 {u[2]}\n🆔 {u[0]}\n💰 ₹{u[4]}\n👥 {u[5]}",
            reply_markup=kb
        )

        user_states.pop(uid)

    elif isinstance(state, tuple) and state[0] == "ADD":
        tid = state[1]
        amt = float(text)
        update_balance(tid, amt)
        await update.message.reply_text(f"✅ Added ₹{amt}")
        user_states.pop(uid)

    elif isinstance(state, tuple) and state[0] == "DED":
        tid = state[1]
        amt = float(text)
        update_balance(tid, -amt)
        await update.message.reply_text(f"➖ Deducted ₹{amt}")
        user_states.pop(uid)

# ================= MAIN =================
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(MessageHandler(filters.TEXT, msg))

    print("🚀 Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()

import os
import uuid
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from supabase import create_client

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 5575627219

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

states = {}

# ================= UI =================
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

# ================= DB =================
def create_user(user):
    supabase.table("users").upsert({
        "id": user.id,
        "username": user.username,
        "name": user.first_name
    }).execute()

def get_balance(uid):
    res = supabase.table("users").select("balance").eq("id", uid).execute()
    return (res.data[0]["balance"] if res.data else 0) // 100

def add_transaction(uid, amount, ttype):
    txn_id = f"TXN_{uuid.uuid4().hex[:8]}"
    supabase.table("transactions").insert({
        "txn_id": txn_id,
        "user_id": uid,
        "type": ttype,
        "amount": amount,
        "status": "success"
    }).execute()

def update_balance(uid, amt):
    supabase.rpc("increment_balance", {"uid": uid, "amt": amt}).execute()

def add_referral(new_user, inviter):
    if new_user == inviter:
        return

    exists = supabase.table("referrals").select("id").eq("invited_id", new_user).execute()
    if exists.data:
        return

    supabase.table("referrals").insert({
        "inviter_id": inviter,
        "invited_id": new_user
    }).execute()

    # reward ₹5 = 500 paise
    add_transaction(inviter, 500, "referral_bonus")
    update_balance(inviter, 500)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_user(user)

    if context.args:
        try:
            inviter = int(context.args[0])
            add_referral(user.id, inviter)
        except:
            pass

    await update.message.reply_text(
        f"👋 Welcome {user.first_name}\n\n💸 Earn with referrals!",
        reply_markup=menu(user.id)
    )

# ================= CALLBACK =================
async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data == "wallet":
        bal = get_balance(uid)
        await q.edit_message_text(f"💰 Balance: ₹{bal}", reply_markup=back())

    elif q.data == "refer":
        link = f"https://t.me/{context.bot.username}?start={uid}"
        await q.edit_message_text(f"🔗 Your link:\n{link}", reply_markup=back())

    elif q.data == "stats":
        r = supabase.table("referrals").select("id").eq("inviter_id", uid).execute()
        await q.edit_message_text(f"👥 Referrals: {len(r.data)}", reply_markup=back())

    elif q.data == "withdraw":
        states[uid] = "UPI"
        await q.edit_message_text("Enter UPI ID:", reply_markup=back())

    # ADMIN
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
        await q.edit_message_text("Enter user ID:")

    elif q.data == "debit":
        states[uid] = "DEBIT_ID"
        await q.edit_message_text("Enter user ID:")

    elif q.data == "back":
        await q.edit_message_text("🏠 Menu", reply_markup=menu(uid))

# ================= MESSAGE =================
async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    state = states.get(uid)

    # SEARCH
    if state == "SEARCH":
        res = supabase.table("users").select("*").eq("id", int(text)).execute()
        if res.data:
            u = res.data[0]
            await update.message.reply_text(f"👤 {u['name']}\n💰 ₹{u['balance']//100}")
        else:
            await update.message.reply_text("Not found")
        states.pop(uid)

    # CREDIT
    elif state == "CREDIT_ID":
        states[uid] = ("CREDIT_AMT", int(text))
        await update.message.reply_text("Enter amount:")

    elif isinstance(state, tuple) and state[0] == "CREDIT_AMT":
        user_id = state[1]
        amt = int(float(text) * 100)

        add_transaction(user_id, amt, "credit")
        update_balance(user_id, amt)

        await context.bot.send_message(user_id, f"💰 ₹{amt/100} credited")
        await update.message.reply_text("Done")
        states.pop(uid)

    # DEBIT
    elif state == "DEBIT_ID":
        states[uid] = ("DEBIT_AMT", int(text))
        await update.message.reply_text("Enter amount:")

    elif isinstance(state, tuple) and state[0] == "DEBIT_AMT":
        user_id = state[1]
        amt = int(float(text) * 100)

        add_transaction(user_id, amt, "debit")
        update_balance(user_id, -amt)

        await context.bot.send_message(user_id, f"➖ ₹{amt/100} deducted")
        await update.message.reply_text("Done")
        states.pop(uid)

    # WITHDRAW
    elif state == "UPI":
        states[uid] = ("AMT", text)
        await update.message.reply_text("Enter amount:")

    elif isinstance(state, tuple) and state[0] == "AMT":
        upi = state[1]
        amt = int(float(text) * 100)

        wid = f"WD_{uuid.uuid4().hex[:8]}"

        supabase.table("withdrawals").insert({
            "withdraw_id": wid,
            "user_id": uid,
            "upi_id": upi,
            "amount": amt,
            "status": "pending"
        }).execute()

        await context.bot.send_message(
            ADMIN_ID,
            f"💸 Withdraw Request\nUser: {uid}\nAmount: ₹{amt/100}\nUPI: {upi}\nID: {wid}"
        )

        await update.message.reply_text("✅ Request sent")
        states.pop(uid)

# ================= MAIN =================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

    print("🚀 Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()

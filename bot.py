import os
import re
import uuid
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from supabase import create_client

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not BOT_TOKEN:
    raise Exception("BOT_TOKEN missing")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise Exception("Supabase env missing")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

ADMIN_ID = 5575627219
MIN_WITHDRAW = 100
REFERRAL_REWARD = 10

user_state = {}

# ================= HELPERS =================

def get_user(user_id):
    res = supabase.table("users").select("*").eq("id", user_id).execute()
    return res.data[0] if res.data else None

def get_referral_count(user_id):
    res = supabase.table("referrals").select("*").eq("inviter_id", user_id).execute()
    return len(res.data)

def update_balance(user_id, amount):
    supabase.rpc("increment_balance", {"uid": user_id, "amt": amount}).execute()

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or ""

    ref = None
    if context.args:
        try:
            ref = int(context.args[0])
        except:
            pass

    if not get_user(user_id):
        supabase.table("users").insert({
            "id": user_id,
            "username": username,
            "balance": 0,
            "referred_by": ref
        }).execute()

        if ref and ref != user_id:
            supabase.table("referrals").insert({
                "inviter_id": ref,
                "invited_id": user_id
            }).execute()

            update_balance(ref, REFERRAL_REWARD)

    keyboard = [
        [InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")],
    ]

    if user_id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin")])

    await update.message.reply_text(
        "🏠 Welcome to the Bot",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================= BALANCE =================

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = get_user(query.from_user.id)
    refs = get_referral_count(query.from_user.id)

    text = f"""
💰 Your Balance

💵 Balance: ₹{user['balance']}
👥 Referrals: {refs}
🎁 Per Referral: ₹{REFERRAL_REWARD}

📊 Min Withdrawal: ₹{MIN_WITHDRAW}
"""

    await query.edit_message_text(text)

# ================= WITHDRAW =================

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = get_user(query.from_user.id)

    text = f"""
💸 Withdraw Funds

💵 Your Balance: ₹{user['balance']}
📊 Minimum: ₹{MIN_WITHDRAW}

✏️ Enter amount:
"""
    user_state[query.from_user.id] = {"step": "amount"}

    await query.edit_message_text(text)

# ================= MESSAGE HANDLER =================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if user_id not in user_state:
        return

    state = user_state[user_id]

    # ---------- WITHDRAW FLOW ----------
    if state["step"] == "amount":
        amount = int(text)
        user = get_user(user_id)

        if amount < MIN_WITHDRAW or amount > user["balance"]:
            await update.message.reply_text("❌ Invalid amount")
            return

        state["amount"] = amount
        state["step"] = "upi"

        await update.message.reply_text("💳 Enter UPI ID (name@bank)")

    elif state["step"] == "upi":
        if not re.match(r"^[\w.-]+@[\w.-]+$", text):
            await update.message.reply_text("❌ Invalid UPI format")
            return

        state["upi"] = text
        state["step"] = "confirm"

        await update.message.reply_text(
            f"""📦 Confirm Withdrawal

💵 Amount: ₹{state['amount']}
💳 UPI: {text}
"""
        )

    # ---------- ADMIN SEARCH ----------
    elif state["step"] == "admin_search":
        query_input = text.replace("@", "")

        if query_input.isdigit():
            res = supabase.table("users").select("*").eq("id", int(query_input)).execute()
        else:
            res = supabase.table("users").select("*").ilike("username", query_input).execute()

        if not res.data:
            await update.message.reply_text("❌ User not found")
            return

        u = res.data[0]
        refs = get_referral_count(u["id"])

        user_state[user_id] = {"target": u["id"]}

        keyboard = [
            [InlineKeyboardButton("➕ Add", callback_data="add")],
            [InlineKeyboardButton("➖ Deduct", callback_data="deduct")]
        ]

        await update.message.reply_text(
            f"""👤 User

🆔 {u['id']}
👤 @{u.get('username')}
💰 ₹{u['balance']}
👥 Referrals: {refs}
""",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

# ================= ADMIN =================

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🔍 Search User", callback_data="search")]
    ]

    await query.edit_message_text("👑 Admin Panel", reply_markup=InlineKeyboardMarkup(keyboard))

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_state[query.from_user.id] = {"step": "admin_search"}
    await query.edit_message_text("🔍 Enter User ID or Username")

# ================= CALLBACK =================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data

    if data == "balance":
        await balance(update, context)
    elif data == "withdraw":
        await withdraw(update, context)
    elif data == "admin":
        await admin(update, context)
    elif data == "search":
        await search(update, context)

# ================= MAIN =================

app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

print("🚀 Bot Running...")
app.run_polling()

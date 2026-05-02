import os
import re
import uuid
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

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

ADMIN_ID = 5575627219
MIN_WITHDRAW = 50
REFERRAL_REWARD = 5

user_state = {}

# ================= HELPERS =================

def get_user(uid):
    res = supabase.table("users").select("*").eq("id", uid).execute()
    return res.data[0] if res.data else None

def get_referrals(uid):
    res = supabase.table("referrals").select("*").eq("inviter_id", uid).execute()
    return len(res.data)

def update_balance(uid, amt):
    supabase.rpc("increment_balance", {"uid": uid, "amt": amt}).execute()

# ================= HOME =================

def home_keyboard(uid):
    keyboard = [
        [InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")],
        [InlineKeyboardButton("🎁 Refer & Earn", callback_data="refer")]
    ]
    if uid == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin")])
    return InlineKeyboardMarkup(keyboard)

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    username = user.username or None

    ref = None
    if context.args:
        try:
            ref = int(context.args[0])
        except:
            pass

    existing = get_user(uid)

    if not existing:
        supabase.table("users").insert({
            "id": uid,
            "username": username,
            "balance": 0,
            "referred_by": ref
        }).execute()

        if ref and ref != uid:
            check = supabase.table("referrals").select("*").eq("invited_id", uid).execute()
            if not check.data:
                supabase.table("referrals").insert({
                    "inviter_id": ref,
                    "invited_id": uid
                }).execute()

                update_balance(ref, REFERRAL_REWARD)

    await update.message.reply_text("🏠 Welcome to the Bot", reply_markup=home_keyboard(uid))

# ================= BALANCE =================

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user = get_user(q.from_user.id)
    refs = get_referrals(q.from_user.id)

    text = f"""💰 Your Balance

💵 Balance: ₹{user['balance']}
👥 Referrals: {refs}
🎁 Per Referral: ₹{REFERRAL_REWARD}

📊 Min Withdrawal: ₹{MIN_WITHDRAW}
"""

    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="home")]
    ]))

# ================= REFER =================

async def refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    bot_username = (await context.bot.get_me()).username

    link = f"https://t.me/{bot_username}?start={uid}"
    refs = get_referrals(uid)

    text = f"""🎁 Refer & Earn

🔗 Your Link:
{link}

👥 Referrals: {refs}
💰 Per Referral: ₹{REFERRAL_REWARD}
"""

    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="home")]
    ]))

# ================= WITHDRAW =================

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user = get_user(q.from_user.id)

    user_state[q.from_user.id] = {"step": "amount"}

    await q.edit_message_text(
        f"""💸 Withdraw Funds

💵 Balance: ₹{user['balance']}
📊 Minimum: ₹{MIN_WITHDRAW}

✏️ Enter amount:
""",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="home")]
        ])
    )

# ================= MESSAGE =================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()

    if uid not in user_state:
        return

    state = user_state[uid]

    # ===== AMOUNT =====
    if state["step"] == "amount":
        if not text.isdigit():
            await update.message.reply_text("❌ Enter valid number")
            return

        amount = int(text)
        user = get_user(uid)

        if amount < MIN_WITHDRAW or amount > user["balance"]:
            await update.message.reply_text("❌ Invalid amount")
            return

        state["amount"] = amount
        state["step"] = "upi"

        await update.message.reply_text("💳 Enter UPI (name@bank)")

    # ===== UPI =====
    elif state["step"] == "upi":
        if not re.match(r"^[\w.-]+@[\w.-]+$", text):
            await update.message.reply_text("❌ Invalid UPI format")
            return

        state["upi"] = text
        state["step"] = "confirm"

        await update.message.reply_text(
            f"""📦 Confirm Withdrawal

💵 ₹{state['amount']}
💳 {text}
""",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data="confirm_withdraw")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_withdraw")]
            ])
        )

    # ===== ADMIN SEARCH =====
    elif state["step"] == "search":
        query = text.replace("@", "")

        if query.isdigit():
            res = supabase.table("users").select("*").eq("id", int(query)).execute()
        else:
            res = supabase.table("users").select("*").ilike("username", f"%{query}%").execute()

        if not res.data:
            await update.message.reply_text("❌ User not found")
            return

        u = res.data[0]
        username = u.get("username") or "No username"

        await update.message.reply_text(
            f"""👤 User

🆔 {u['id']}
👤 @{username}
💰 ₹{u['balance']}
"""
        )

# ================= BUTTON =================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    data = q.data

    if data == "home":
        await q.edit_message_text("🏠 Welcome to the Bot", reply_markup=home_keyboard(uid))

    elif data == "balance":
        await balance(update, context)

    elif data == "withdraw":
        await withdraw(update, context)

    elif data == "refer":
        await refer(update, context)

    elif data == "confirm_withdraw":
        state = user_state.get(uid)

        wid = str(uuid.uuid4())[:8].upper()

        supabase.table("withdrawals").insert({
            "withdraw_id": wid,
            "user_id": uid,
            "upi_id": state["upi"],
            "amount": state["amount"],
            "status": "pending"
        }).execute()

        update_balance(uid, -state["amount"])
        user_state.pop(uid, None)

        await q.edit_message_text(f"✅ Withdrawal Submitted\nID: {wid}")

    elif data == "cancel_withdraw":
        user_state.pop(uid, None)
        await q.edit_message_text("❌ Cancelled")

    elif data == "admin":
        await q.edit_message_text("👑 Admin Panel", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Search User", callback_data="search")]
        ]))

    elif data == "search":
        user_state[uid] = {"step": "search"}
        await q.edit_message_text("🔍 Enter ID or Username")

# ================= RUN =================

app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

print("🚀 Bot Running...")
app.run_polling()

import os
import re
import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from supabase import create_client

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

ADMIN_ID = 5575627219
state = {}

# ================= SETTINGS =================

def get_setting(key, default=0):
    r = supabase.table("settings").select("value").eq("key", key).execute()
    return int(r.data[0]["value"]) if r.data else default

# ================= HELPERS =================

def get_user(uid):
    r = supabase.table("users").select("*").eq("id", uid).execute()
    return r.data[0] if r.data else None

def get_referrals(uid):
    r = supabase.table("referrals").select("*").eq("inviter_id", uid).execute()
    return len(r.data)

def update_balance(uid, amount):
    supabase.rpc("increment_balance", {"uid": uid, "amt": amount}).execute()

# ================= UI =================

def main_menu(uid):
    kb = [
        [InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")],
        [InlineKeyboardButton("🎁 Refer", callback_data="refer")]
    ]
    if uid == ADMIN_ID:
        kb.append([InlineKeyboardButton("👑 Admin", callback_data="admin")])
    return InlineKeyboardMarkup(kb)

def back_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back", callback_data="home")]])

# ================= START =================

async def start(update, context):
    u = update.effective_user
    uid = u.id

    ref = int(context.args[0]) if context.args else None

    if not get_user(uid):
        supabase.table("users").insert({
            "id": uid,
            "username": u.username,
            "balance": 0
        }).execute()

        if ref and ref != uid:
            exists = supabase.table("referrals").select("*").eq("invited_id", uid).execute()
            if not exists.data:
                supabase.table("referrals").insert({
                    "inviter_id": ref,
                    "invited_id": uid
                }).execute()

                reward = get_setting("referral_reward", 5)
                update_balance(ref, reward)

    await update.message.reply_text("🏠 Welcome", reply_markup=main_menu(uid))

# ================= CALLBACK =================

async def callback(update, context):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    try:
        if q.data == "home":
            state.pop(uid, None)
            await q.edit_message_text("🏠 Welcome", reply_markup=main_menu(uid))

        elif q.data == "balance":
            u = get_user(uid)
            ref_count = get_referrals(uid)
            reward = get_setting("referral_reward", 5)
            min_wd = get_setting("min_withdraw", 50)

            await q.edit_message_text(
                f"💰 Balance: ₹{u['balance']}\n"
                f"👥 Referrals: {ref_count}\n"
                f"🎁 Per Referral: ₹{reward}\n\n"
                f"📊 Min Withdraw: ₹{min_wd}",
                reply_markup=back_btn()
            )

        elif q.data == "refer":
            bot = (await context.bot.get_me()).username
            link = f"https://t.me/{bot}?start={uid}"
            reward = get_setting("referral_reward", 5)

            await q.edit_message_text(
                f"🎁 Your Referral Link:\n{link}\n\n"
                f"Earn ₹{reward} per referral",
                reply_markup=back_btn()
            )

        elif q.data == "withdraw":
            u = get_user(uid)
            min_wd = get_setting("min_withdraw", 50)

            state[uid] = {"action": "withdraw", "step": "amount"}

            await q.edit_message_text(
                f"💰 Balance: ₹{u['balance']}\n"
                f"📊 Minimum: ₹{min_wd}\n\n"
                f"✍️ Enter amount:",
                reply_markup=back_btn()
            )

        elif q.data == "admin":
            await q.edit_message_text(
                "👑 Admin Panel",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 Search User", callback_data="search")],
                    [InlineKeyboardButton("📤 Pending Withdrawals", callback_data="pending")],
                    [InlineKeyboardButton("⬅ Back", callback_data="home")]
                ])
            )

        elif q.data == "search":
            state[uid] = {"action": "search"}
            await q.edit_message_text("Enter user ID or username:")

        elif q.data == "confirm_withdraw":
            s = state[uid]

            wid = str(uuid.uuid4())[:8]

            supabase.table("withdrawals").insert({
                "withdraw_id": wid,
                "user_id": uid,
                "upi_id": s["upi"],
                "amount": s["amount"],
                "status": "pending"
            }).execute()

            update_balance(uid, -s["amount"])

            state.pop(uid)

            await q.edit_message_text(
                f"✅ Withdrawal Submitted!\nID: {wid}",
                reply_markup=back_btn()
            )

        elif q.data == "cancel":
            state.pop(uid, None)
            await q.edit_message_text("❌ Cancelled", reply_markup=main_menu(uid))

    except:
        pass

# ================= MESSAGE =================

async def message(update, context):
    uid = update.effective_user.id
    text = update.message.text.strip()

    if uid not in state:
        return

    s = state[uid]

    # ===== WITHDRAW =====
    if s["action"] == "withdraw":

        if s["step"] == "amount":
            if not text.isdigit():
                return await update.message.reply_text("❌ Enter valid number")

            amount = int(text)
            u = get_user(uid)
            min_wd = get_setting("min_withdraw", 50)

            if amount < min_wd:
                return await update.message.reply_text(f"❌ Minimum is ₹{min_wd}")

            if amount > u["balance"]:
                return await update.message.reply_text("❌ Insufficient balance")

            s["amount"] = amount
            s["step"] = "upi"

            await update.message.reply_text("🏦 Enter UPI ID (name@bank):")

        elif s["step"] == "upi":
            if not re.match(r"^[\w.-]+@[\w.-]+$", text):
                return await update.message.reply_text("❌ Invalid UPI format")

            s["upi"] = text

            await update.message.reply_text(
                f"📦 Confirm Withdrawal\n\n"
                f"💰 Amount: ₹{s['amount']}\n"
                f"🏦 UPI: {text}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Confirm", callback_data="confirm_withdraw")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
                ])
            )

    # ===== ADMIN SEARCH =====
    elif s["action"] == "search":
        query = text.replace("@", "")

        if query.isdigit():
            r = supabase.table("users").select("*").eq("id", int(query)).execute()
        else:
            r = supabase.table("users").select("*").ilike("username", f"%{query}%").execute()

        if not r.data:
            return await update.message.reply_text("❌ User not found")

        u = r.data[0]

        state.pop(uid)

        await update.message.reply_text(
            f"👤 {u.get('username')}\n"
            f"💰 Balance: ₹{u['balance']}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅ Back", callback_data="admin")]
            ])
        )

# ================= RUN =================

app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(callback))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message))

print("🚀 Bot Running...")
app.run_polling()

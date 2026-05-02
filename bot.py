# ================= IMPORTANT =================
# THIS VERSION USES ₹ DIRECTLY (NO *100 ANYWHERE)

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
REFERRAL_REWARD = 5
MIN_WITHDRAW = 50

state = {}

# ================= HELPERS =================

def user(uid):
    r = supabase.table("users").select("*").eq("id", uid).execute()
    return r.data[0] if r.data else None

def referrals(uid):
    r = supabase.table("referrals").select("*").eq("inviter_id", uid).execute()
    return len(r.data)

def add_balance(uid, amt):
    supabase.rpc("increment_balance", {"uid": uid, "amt": amt}).execute()

# ================= UI =================

def home(uid):
    kb = [
        [InlineKeyboardButton("💰 Balance", callback_data="bal")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="wd")],
        [InlineKeyboardButton("🎁 Refer", callback_data="ref")]
    ]
    if uid == ADMIN_ID:
        kb.append([InlineKeyboardButton("👑 Admin", callback_data="admin")])
    return InlineKeyboardMarkup(kb)

def back():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="home")]])

# ================= START =================

async def start(update, context):
    u = update.effective_user
    uid = u.id

    ref = int(context.args[0]) if context.args else None

    if not user(uid):
        supabase.table("users").insert({
            "id": uid,
            "username": u.username,
            "balance": 0
        }).execute()

        if ref and ref != uid:
            exist = supabase.table("referrals").select("*").eq("invited_id", uid).execute()
            if not exist.data:
                supabase.table("referrals").insert({
                    "inviter_id": ref,
                    "invited_id": uid
                }).execute()

                add_balance(ref, REFERRAL_REWARD)

    await update.message.reply_text("🏠 Welcome", reply_markup=home(uid))

# ================= CALLBACK =================

async def cb(update, context):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    try:
        if q.data == "home":
            await q.edit_message_text("🏠 Welcome", reply_markup=home(uid))

        elif q.data == "bal":
            u = user(uid)
            await q.edit_message_text(
                f"💰 Balance: ₹{u['balance']}\n👥 Referrals: {referrals(uid)}",
                reply_markup=back()
            )

        elif q.data == "ref":
            bot = (await context.bot.get_me()).username
            link = f"https://t.me/{bot}?start={uid}"

            await q.edit_message_text(
                f"🎁 Your Link:\n{link}\n\nEarn ₹{REFERRAL_REWARD} per referral",
                reply_markup=back()
            )

        elif q.data == "wd":
            state[uid] = {"step": "amt"}
            await q.edit_message_text("Enter amount:", reply_markup=back())

        elif q.data == "admin":
            await q.edit_message_text(
                "👑 Admin Panel",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 Search", callback_data="search")],
                    [InlineKeyboardButton("🔙 Back", callback_data="home")]
                ])
            )

        elif q.data == "search":
            state[uid] = {"step": "search"}
            await q.edit_message_text("Enter ID or username:")

        elif q.data == "confirm":
            s = state[uid]

            wid = str(uuid.uuid4())[:8]

            supabase.table("withdrawals").insert({
                "withdraw_id": wid,
                "user_id": uid,
                "upi_id": s["upi"],
                "amount": s["amt"],
                "status": "pending"
            }).execute()

            add_balance(uid, -s["amt"])

            await q.edit_message_text(f"✅ Withdraw placed\nID: {wid}")
            state.pop(uid)

        elif q.data == "cancel":
            state.pop(uid, None)
            await q.edit_message_text("❌ Cancelled", reply_markup=home(uid))

    except:
        pass  # prevents "message not modified crash"

# ================= MESSAGE =================

async def msg(update, context):
    uid = update.effective_user.id
    txt = update.message.text.strip()

    if uid not in state:
        return

    s = state[uid]

    if s["step"] == "amt":
        if not txt.isdigit():
            return await update.message.reply_text("Enter valid number")

        amt = int(txt)
        u = user(uid)

        if amt < MIN_WITHDRAW or amt > u["balance"]:
            return await update.message.reply_text("Invalid amount")

        s["amt"] = amt
        s["step"] = "upi"

        await update.message.reply_text("Enter UPI:")

    elif s["step"] == "upi":
        if not re.match(r"^[\w.-]+@[\w.-]+$", txt):
            return await update.message.reply_text("Invalid UPI")

        s["upi"] = txt

        await update.message.reply_text(
            f"Confirm ₹{s['amt']} to {txt}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data="confirm")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
            ])
        )

    elif s["step"] == "search":
        q = txt.replace("@", "")

        if q.isdigit():
            r = supabase.table("users").select("*").eq("id", int(q)).execute()
        else:
            r = supabase.table("users").select("*").ilike("username", f"%{q}%").execute()

        if not r.data:
            return await update.message.reply_text("Not found")

        u = r.data[0]

        await update.message.reply_text(
            f"👤 {u.get('username')}\n💰 ₹{u['balance']}"
        )

# ================= RUN =================

app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(cb))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

print("🚀 Running...")
app.run_polling()

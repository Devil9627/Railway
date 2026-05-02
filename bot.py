import os
import re
import uuid
from datetime import datetime
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

def add_transaction(uid, amount, ttype, status="success"):
    supabase.table("transactions").insert({
        "txn_id": str(uuid.uuid4())[:8],
        "user_id": uid,
        "type": ttype,
        "amount": amount,
        "status": status
    }).execute()

async def notify_user(context, uid, text):
    try:
        await context.bot.send_message(chat_id=uid, text=text)
    except Exception as e:
        print("Notify error:", e)

# ================= UI =================

def main_menu(uid):
    if uid == ADMIN_ID:
        kb = [
            [
                InlineKeyboardButton("💰 Balance", callback_data="balance"),
                InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")
            ],
            [
                InlineKeyboardButton("🎁 Refer", callback_data="refer"),
                InlineKeyboardButton("📜 History", callback_data="history")
            ],
            [
                InlineKeyboardButton("👑 Admin", callback_data="admin")
            ]
        ]
    else:
        kb = [
            [
                InlineKeyboardButton("💰 Balance", callback_data="balance"),
                InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")
            ],
            [
                InlineKeyboardButton("🎁 Refer", callback_data="refer"),
                InlineKeyboardButton("📜 History", callback_data="history")
            ]
        ]
    return InlineKeyboardMarkup(kb)

def back_home():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back", callback_data="home")]])

# ================= START =================

async def start(update, context):
    u = update.effective_user
    uid = u.id

    if not get_user(uid):
        supabase.table("users").insert({
            "id": uid,
            "username": u.username,
            "balance": 0,
            "created_at": datetime.utcnow().isoformat()
        }).execute()

    await update.message.reply_text(
        f"✨ Welcome, {u.first_name}!\n\n"
        f"Earn rewards by inviting friends.\n\n"
        f"Choose below 👇",
        reply_markup=main_menu(uid)
    )

# ================= CALLBACK =================

async def callback(update, context):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    try:
        if q.data == "home":
            state.pop(uid, None)
            await q.edit_message_text("🏠 Menu", reply_markup=main_menu(uid))

        elif q.data == "balance":
            u = get_user(uid)
            refs = get_referrals(uid)
            min_w = get_setting("min_withdraw", 50)

            await q.edit_message_text(
                f"💰 Balance: ₹{u['balance']}\n"
                f"👥 Referrals: {refs}\n"
                f"📊 Min Withdraw: ₹{min_w}",
                reply_markup=back_home()
            )

        elif q.data == "history":
            r = supabase.table("transactions") \
                .select("*") \
                .eq("user_id", uid) \
                .order("created_at", desc=True) \
                .limit(5) \
                .execute()

            if not r.data:
                return await q.edit_message_text("No transactions", reply_markup=back_home())

            text = "📜 Last 5 Transactions:\n\n"
            for t in r.data:
                text += f"#{t['txn_id']} | ₹{t['amount']} | {t['type']} | {t['status']}\n"

            await q.edit_message_text(text, reply_markup=back_home())

        elif q.data == "withdraw":
            u = get_user(uid)
            min_w = get_setting("min_withdraw", 50)

            state[uid] = {"action": "withdraw", "step": "amount"}

            await q.edit_message_text(
                f"💰 Balance: ₹{u['balance']}\n📊 Min: ₹{min_w}\n\nEnter amount:",
                reply_markup=back_home()
            )

        elif q.data == "admin":
            await q.edit_message_text(
                "👑 Admin Panel",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("🔍 Search", callback_data="search"),
                        InlineKeyboardButton("📤 Pending", callback_data="pending")
                    ],
                    [InlineKeyboardButton("⬅ Back", callback_data="home")]
                ])
            )

        elif q.data == "search":
            state[uid] = {"action": "search"}
            await q.edit_message_text("Enter user ID or username:")

        elif q.data == "pending":
            r = supabase.table("withdrawals").select("*").eq("status", "pending").execute()

            if not r.data:
                return await q.edit_message_text("No pending", reply_markup=back_home())

            w = r.data[0]

            await q.edit_message_text(
                f"ID: {w['withdraw_id']}\nUser: {w['user_id']}\n₹{w['amount']}",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{w['id']}"),
                        InlineKeyboardButton("❌ Reject", callback_data=f"reject_{w['id']}")
                    ]
                ])
            )

        elif q.data.startswith("approve_"):
            wid = int(q.data.split("_")[1])
            w = supabase.table("withdrawals").select("*").eq("id", wid).execute().data[0]

            supabase.table("withdrawals").update({"status": "approved"}).eq("id", wid).execute()

            add_transaction(w["user_id"], w["amount"], "withdraw", "approved")
            await notify_user(context, w["user_id"], f"✅ Withdraw ₹{w['amount']} approved")

            await q.edit_message_text("Approved")

        elif q.data.startswith("reject_"):
            wid = int(q.data.split("_")[1])
            w = supabase.table("withdrawals").select("*").eq("id", wid).execute().data[0]

            supabase.table("withdrawals").update({"status": "rejected"}).eq("id", wid).execute()
            update_balance(w["user_id"], w["amount"])

            add_transaction(w["user_id"], w["amount"], "withdraw", "rejected")
            await notify_user(context, w["user_id"], f"❌ Withdraw rejected")

            await q.edit_message_text("Rejected")

    except Exception as e:
        print("Error:", e)

# ================= MESSAGE =================

async def message(update, context):
    uid = update.effective_user.id
    text = update.message.text.strip()

    if uid not in state:
        return

    s = state[uid]

    if s["action"] == "withdraw":

        if s["step"] == "amount":
            if not text.isdigit():
                return await update.message.reply_text("Invalid amount")

            amt = int(text)
            u = get_user(uid)
            min_w = get_setting("min_withdraw", 50)

            if amt < min_w:
                return await update.message.reply_text(f"Minimum ₹{min_w}")
            if amt > u["balance"]:
                return await update.message.reply_text("Insufficient balance")

            s["amount"] = amt
            s["step"] = "upi"

            await update.message.reply_text("Enter UPI:")

        elif s["step"] == "upi":
            if not re.match(r"^[\w.-]+@[\w.-]+$", text):
                return await update.message.reply_text("Invalid UPI")

            wid = str(uuid.uuid4())[:8]

            supabase.table("withdrawals").insert({
                "withdraw_id": wid,
                "user_id": uid,
                "upi_id": text,
                "amount": s["amount"],
                "status": "pending"
            }).execute()

            update_balance(uid, -s["amount"])
            add_transaction(uid, s["amount"], "withdraw", "pending")

            await notify_user(context, ADMIN_ID, f"📤 New withdrawal ₹{s['amount']}")

            state.pop(uid)
            await update.message.reply_text("✅ Request submitted")

    elif s["action"] == "search":
        q = text.replace("@", "")

        if q.isdigit():
            r = supabase.table("users").select("*").eq("id", int(q)).execute()
        else:
            r = supabase.table("users").select("*").ilike("username", f"%{q}%").execute()

        if not r.data:
            return await update.message.reply_text("User not found")

        u = r.data[0]

        await update.message.reply_text(
            f"👤 {u.get('username')}\n🆔 {u['id']}\n💰 ₹{u['balance']}"
        )

        state.pop(uid)

# ================= RUN =================

app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(callback))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message))

print("🚀 Bot Running...")
app.run_polling()

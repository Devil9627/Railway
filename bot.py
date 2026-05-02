import os, re, uuid
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from supabase import create_client

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

ADMIN_ID = 5575627219

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
state = {}

# ========= HELPERS =========

def get_user(uid):
    r = supabase.table("users").select("*").eq("id", uid).execute()
    return r.data[0] if r.data else None

def update_balance(uid, amt):
    supabase.rpc("increment_balance", {"uid": uid, "amt": amt}).execute()

def add_tx(uid, amt, t):
    supabase.table("transactions").insert({
        "txn_id": str(uuid.uuid4())[:8],
        "user_id": uid,
        "type": t,
        "amount": amt,
        "status": "success",
        "created_at": datetime.utcnow().isoformat()
    }).execute()

async def notify(context, uid, text):
    try:
        await context.bot.send_message(chat_id=uid, text=text)
    except:
        pass

# ========= UI =========

def menu(uid):
    kb = [
        [InlineKeyboardButton("💰 Balance", callback_data="bal"),
         InlineKeyboardButton("💸 Withdraw", callback_data="wd")],
        [InlineKeyboardButton("📜 History", callback_data="his"),
         InlineKeyboardButton("🎁 Refer", callback_data="ref")]
    ]
    if uid == ADMIN_ID:
        kb.append([InlineKeyboardButton("👑 Admin", callback_data="admin")])
    return InlineKeyboardMarkup(kb)

def back():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back", callback_data="home")]])

# ========= START =========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user

    if not get_user(u.id):
        supabase.table("users").insert({
            "id": u.id,
            "username": u.username,
            "balance": 0,
            "is_banned": False,
            "created_at": datetime.utcnow().isoformat()
        }).execute()

    await update.message.reply_text(
        f"✨ Welcome, {u.first_name}!\n\nChoose an option 👇",
        reply_markup=menu(u.id)
    )

# ========= CALLBACK =========

async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data == "home":
        state.pop(uid, None)
        await q.edit_message_text("🏠 Menu", reply_markup=menu(uid))

    elif q.data == "bal":
        u = get_user(uid)
        await q.edit_message_text(f"💰 Balance: ₹{u['balance']}", reply_markup=back())

    elif q.data == "wd":
        state[uid] = {"a": "wd", "step": "amt"}
        await q.edit_message_text("Enter withdrawal amount:", reply_markup=back())

    elif q.data == "admin":
        await q.edit_message_text(
            "👑 Admin Panel",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Search User", callback_data="search"),
                 InlineKeyboardButton("📤 Pending", callback_data="pending")],
                [InlineKeyboardButton("⬅ Back", callback_data="home")]
            ])
        )

    elif q.data == "search":
        state[uid] = {"a": "search"}
        await q.edit_message_text("Enter user ID or username:")

    elif q.data == "pending":
        r = supabase.table("withdrawals").select("*").eq("status", "pending").execute()
        if not r.data:
            return await q.edit_message_text("No pending withdrawals", reply_markup=back())

        w = r.data[0]
        state[uid] = {"a": "pending", "wid": w["id"]}

        await q.edit_message_text(
            f"👤 {w['user_id']}\n💰 ₹{w['amount']}\n🏦 {w['upi_id']}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve", callback_data="approve"),
                 InlineKeyboardButton("❌ Reject", callback_data="reject")],
                [InlineKeyboardButton("⏭ Next", callback_data="pending")]
            ])
        )

    elif q.data == "approve":
        wid = state[uid]["wid"]
        w = supabase.table("withdrawals").select("*").eq("id", wid).execute().data[0]

        supabase.table("withdrawals").update({
            "status": "approved",
            "processed_at": datetime.utcnow().isoformat()
        }).eq("id", wid).execute()

        add_tx(w["user_id"], w["amount"], "debit")

        await notify(context, w["user_id"], f"✅ Withdrawal Approved\n₹{w['amount']}")
        await q.edit_message_text("Approved")

    elif q.data == "reject":
        state[uid]["step"] = "reason"
        await q.edit_message_text("Enter rejection reason:")

    elif q.data in ["credit", "debit", "ban", "unban"]:
        state[uid]["step"] = q.data
        await q.edit_message_text("Enter amount:" if q.data in ["credit", "debit"] else "Processing...")

# ========= MESSAGE =========

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    if uid not in state:
        return

    s = state[uid]

    if s["a"] == "search":
        if text.isdigit():
            r = supabase.table("users").select("*").eq("id", int(text)).execute()
        else:
            r = supabase.table("users").select("*").ilike("username", f"%{text}%").execute()

        if not r.data:
            return await update.message.reply_text("User not found")

        u = r.data[0]
        state[uid] = {"a": "edit", "target": u["id"], "banned": u["is_banned"]}

        ban_btn = "✅ Unban" if u["is_banned"] else "🚫 Ban"
        ban_cb = "unban" if u["is_banned"] else "ban"

        await update.message.reply_text(
            f"👤 {u['username']}\n💰 ₹{u['balance']}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Credit", callback_data="credit"),
                 InlineKeyboardButton("➖ Debit", callback_data="debit")],
                [InlineKeyboardButton(ban_btn, callback_data=ban_cb)]
            ])
        )

    elif s["a"] == "edit":
        target = s["target"]

        if s.get("step") == "credit":
            amt = int(text)
            update_balance(target, amt)
            add_tx(target, amt, "admin_credit")
            await notify(context, target, f"💰 ₹{amt} credited")

        elif s.get("step") == "debit":
            amt = int(text)
            update_balance(target, -amt)
            add_tx(target, amt, "admin_debit")
            await notify(context, target, f"💸 ₹{amt} debited")

        elif s.get("step") == "ban":
            supabase.table("users").update({"is_banned": True}).eq("id", target).execute()

        elif s.get("step") == "unban":
            supabase.table("users").update({"is_banned": False}).eq("id", target).execute()

        await update.message.reply_text("Updated")
        state.pop(uid)

    elif s["a"] == "wd":
        if s["step"] == "amt":
            if not text.isdigit():
                return await update.message.reply_text("Invalid amount")
            s["amt"] = int(text)
            s["step"] = "upi"
            await update.message.reply_text("Enter UPI ID:")

        elif s["step"] == "upi":
            if not re.match(r"^[\w.-]+@[\w.-]+$", text):
                return await update.message.reply_text("Invalid UPI format")

            supabase.table("withdrawals").insert({
                "withdraw_id": str(uuid.uuid4())[:8],
                "user_id": uid,
                "amount": s["amt"],
                "upi_id": text,
                "status": "pending"
            }).execute()

            update_balance(uid, -s["amt"])

            await notify(context, ADMIN_ID, f"📤 New Withdrawal ₹{s['amt']}")
            await update.message.reply_text("✅ Request submitted")

            state.pop(uid)

    elif s["a"] == "pending" and s.get("step") == "reason":
        wid = s["wid"]
        w = supabase.table("withdrawals").select("*").eq("id", wid).execute().data[0]

        supabase.table("withdrawals").update({
            "status": "rejected",
            "note": text,
            "processed_at": datetime.utcnow().isoformat()
        }).eq("id", wid).execute()

        update_balance(w["user_id"], w["amount"])
        add_tx(w["user_id"], w["amount"], "credit")

        await notify(context, w["user_id"], f"❌ Rejected\nReason: {text}")
        await update.message.reply_text("Rejected")

        state.pop(uid)

# ========= ERROR HANDLER =========

async def error_handler(update, context):
    print("ERROR:", context.error)

# ========= RUN =========

app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(cb))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
app.add_error_handler(error_handler)

PORT = int(os.getenv("PORT", 8080))

app.run_webhook(
    listen="0.0.0.0",
    port=PORT,
    url_path=BOT_TOKEN,
    webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
)

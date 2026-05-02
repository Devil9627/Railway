import os, re, uuid
from datetime import datetime
from aiohttp import web

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

from supabase import create_client

# ========= ENV =========
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

def is_banned(uid):
    u = get_user(uid)
    return u and u["is_banned"]

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

    if is_banned(uid):
        return await q.edit_message_text("🚫 You are banned")

    # HOME
    if q.data == "home":
        state.pop(uid, None)
        return await q.edit_message_text("🏠 Menu", reply_markup=menu(uid))

    # BALANCE
    elif q.data == "bal":
        u = get_user(uid)
        return await q.edit_message_text(f"💰 Balance: ₹{u['balance']}", reply_markup=back())

    # HISTORY
    elif q.data == "his":
        r = supabase.table("transactions")\
            .select("*")\
            .eq("user_id", uid)\
            .order("created_at", desc=True)\
            .limit(5)\
            .execute()

        if not r.data:
            return await q.edit_message_text("No transactions", reply_markup=back())

        txt = "📜 Last 5 Transactions:\n\n"
        for t in r.data:
            txt += f"{t['type']} | ₹{t['amount']}\n"

        return await q.edit_message_text(txt, reply_markup=back())

    # WITHDRAW START
    elif q.data == "wd":
        state[uid] = {"a": "wd", "step": "amt"}
        return await q.edit_message_text("Enter withdrawal amount:", reply_markup=back())

    # CONFIRM WITHDRAW
    elif q.data == "confirm_wd":
        s = state.get(uid)

        supabase.table("withdrawals").insert({
            "withdraw_id": str(uuid.uuid4())[:8],
            "user_id": uid,
            "amount": s["amt"],
            "upi_id": s["upi"],
            "status": "pending",
            "requested_at": datetime.utcnow().isoformat()
        }).execute()

        update_balance(uid, -s["amt"])

        await notify(context, ADMIN_ID, f"📤 New Withdrawal ₹{s['amt']}")
        state.pop(uid)

        return await q.edit_message_text("✅ Request submitted", reply_markup=back())

    # ADMIN PANEL
    elif q.data == "admin":
        return await q.edit_message_text(
            "👑 Admin Panel",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Search User", callback_data="search"),
                 InlineKeyboardButton("📤 Pending", callback_data="pending")],
                [InlineKeyboardButton("⬅ Back", callback_data="home")]
            ])
        )

    # SEARCH USER
    elif q.data == "search":
        state[uid] = {"a": "search"}
        return await q.edit_message_text("Enter user ID or username:")

    # PENDING WITHDRAWALS
    elif q.data == "pending":
        pending_list = supabase.table("withdrawals")\
            .select("*")\
            .eq("status", "pending")\
            .execute().data

        if not pending_list:
            return await q.edit_message_text("No pending withdrawals", reply_markup=back())

        idx = state.get(uid, {}).get("idx", 0) % len(pending_list)
        w = pending_list[idx]

        state[uid] = {"a": "pending", "wid": w["withdraw_id"], "idx": idx + 1}

        return await q.edit_message_text(
            f"👤 {w['user_id']}\n💰 ₹{w['amount']}\n🏦 {w['upi_id']}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve", callback_data="approve"),
                 InlineKeyboardButton("❌ Reject", callback_data="reject")],
                [InlineKeyboardButton("⏭ Next", callback_data="pending")]
            ])
        )

    # APPROVE
    elif q.data == "approve":
        wid = state[uid]["wid"]

        w = supabase.table("withdrawals")\
            .select("*")\
            .eq("withdraw_id", wid)\
            .execute().data[0]

        if w["status"] != "pending":
            return await q.edit_message_text("Already processed")

        supabase.table("withdrawals").update({
            "status": "approved",
            "processed_at": datetime.utcnow().isoformat()
        }).eq("withdraw_id", wid).execute()

        add_tx(w["user_id"], w["amount"], "debit")

        await notify(context, w["user_id"], f"✅ Withdrawal Approved\n₹{w['amount']}")
        return await q.edit_message_text("Approved", reply_markup=back())

    # REJECT
    elif q.data == "reject":
        state[uid]["step"] = "reason"
        return await q.edit_message_text("Enter rejection reason:")

    # ADMIN ACTIONS
    elif q.data in ["credit", "debit", "ban", "unban"]:
        state[uid]["step"] = q.data
        return await q.edit_message_text("Enter amount:" if q.data in ["credit", "debit"] else "Processing...")

# ========= MESSAGE =========

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    if is_banned(uid):
        return await update.message.reply_text("🚫 You are banned")

    if uid not in state:
        return

    s = state[uid]

    # SEARCH
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

        return await update.message.reply_text(
            f"👤 {u['username']}\n💰 ₹{u['balance']}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Credit", callback_data="credit"),
                 InlineKeyboardButton("➖ Debit", callback_data="debit")],
                [InlineKeyboardButton(ban_btn, callback_data=ban_cb)]
            ])
        )

    # ADMIN EDIT
    elif s["a"] == "edit":
        target = s["target"]

        if s.get("step") == "credit":
            amt = int(text)
            if amt <= 0:
                return await update.message.reply_text("Invalid amount")

            update_balance(target, amt)
            add_tx(target, amt, "admin_credit")
            await notify(context, target, f"💰 ₹{amt} credited")

        elif s.get("step") == "debit":
            amt = int(text)
            if amt <= 0:
                return await update.message.reply_text("Invalid amount")

            update_balance(target, -amt)
            add_tx(target, amt, "admin_debit")
            await notify(context, target, f"💸 ₹{amt} debited")

        elif s.get("step") == "ban":
            supabase.table("users").update({"is_banned": True}).eq("id", target).execute()

        elif s.get("step") == "unban":
            supabase.table("users").update({"is_banned": False}).eq("id", target).execute()

        state.pop(uid)
        return await update.message.reply_text("Updated")

    # WITHDRAW FLOW
    elif s["a"] == "wd":
        u = get_user(uid)

        if s["step"] == "amt":
            if not text.isdigit():
                return await update.message.reply_text("Invalid amount")

            amt = int(text)

            if amt <= 0:
                return await update.message.reply_text("Invalid amount")

            if u["balance"] < amt:
                return await update.message.reply_text("❌ Insufficient balance")

            s["amt"] = amt
            s["step"] = "upi"
            return await update.message.reply_text("Enter UPI ID:")

        elif s["step"] == "upi":
            if not re.match(r"^[\w.-]+@[\w.-]+$", text):
                return await update.message.reply_text("Invalid UPI format")

            s["upi"] = text
            s["step"] = "confirm"

            return await update.message.reply_text(
                f"Confirm Withdraw?\n\n₹{s['amt']}\nUPI: {text}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Confirm", callback_data="confirm_wd")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="home")]
                ])
            )

    # REJECT REASON
    elif s["a"] == "pending" and s.get("step") == "reason":
        wid = s["wid"]

        w = supabase.table("withdrawals")\
            .select("*")\
            .eq("withdraw_id", wid)\
            .execute().data[0]

        supabase.table("withdrawals").update({
            "status": "rejected",
            "note": text,
            "processed_at": datetime.utcnow().isoformat()
        }).eq("withdraw_id", wid).execute()

        update_balance(w["user_id"], w["amount"])
        add_tx(w["user_id"], w["amount"], "credit")

        await notify(context, w["user_id"], f"❌ Rejected\nReason: {text}")
        state.pop(uid)

        return await update.message.reply_text("Rejected")

# ========= ERROR =========

async def error_handler(update, context):
    print("ERROR:", context.error)

# ========= HEALTH =========

async def health(request):
    return web.Response(text="OK")

# ========= RUN =========

app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(cb))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
app.add_error_handler(error_handler)

app.web_app.router.add_get("/", health)

PORT = int(os.getenv("PORT", 8080))

app.run_webhook(
    listen="0.0.0.0",
    port=PORT,
    url_path=BOT_TOKEN,
    webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
)

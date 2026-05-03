import os, re, uuid
from datetime import datetime, UTC
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

# ---------- HELPERS ----------

def now():
    return datetime.now(UTC).isoformat()

def get_user(uid):
    r = supabase.table("users").select("*").eq("id", uid).execute()
    return r.data[0] if r.data else None

def update_balance(uid, amt):
    try:
        supabase.rpc("increment_balance", {"uid": uid, "amt": amt}).execute()
        return True
    except Exception as e:
        print("BALANCE ERROR:", e)
        return False

def add_tx(uid, amt, t):
    supabase.table("transactions").insert({
        "txn_id": str(uuid.uuid4())[:8],
        "user_id": uid,
        "type": t,
        "amount": amt,
        "status": "success",
        "created_at": now()
    }).execute()

async def notify(context, uid, text):
    try:
        await context.bot.send_message(chat_id=uid, text=text)
    except:
        pass

async def safe_edit(q, text, markup=None):
    try:
        await q.edit_message_text(text, reply_markup=markup)
    except Exception as e:
        if "Message is not modified" not in str(e):
            print("EDIT ERROR:", e)

# ---------- UI ----------

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

# ---------- START ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user

    if not get_user(u.id):
        supabase.table("users").insert({
            "id": u.id,
            "username": u.username,
            "balance": 0,
            "is_banned": False,
            "created_at": now()
        }).execute()

    await update.message.reply_text(
        f"✨ Welcome, {u.first_name}!\n\n"
        "💸 Earn money by referring friends\n"
        "📈 Track your balance & withdrawals\n\n"
        "Choose an option below 👇",
        reply_markup=menu(u.id)
    )

# ---------- CALLBACK ----------

async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data == "home":
        state.pop(uid, None)
        await safe_edit(q, "🏠 Menu", menu(uid))

    elif q.data == "bal":
        u = get_user(uid)
        await safe_edit(q, f"💰 Balance: ₹{u['balance']}", back())

    elif q.data == "ref":
        bot = await context.bot.get_me()
        link = f"https://t.me/{bot.username}?start={uid}"
        await safe_edit(q, f"🎁 Your Referral Link:\n\n{link}", back())

    elif q.data == "his":
        w = supabase.table("withdrawals").select("*").eq("user_id", uid).order("requested_at", desc=True).limit(5).execute()

        if not w.data:
            return await safe_edit(q, "📜 No withdrawal history", back())

        text = "📜 Withdrawal History:\n\n"

        for i in w.data:
            status = "✅" if i["status"]=="approved" else "❌" if i["status"]=="rejected" else "⏳"
            text += f"{status} ₹{i['amount']}\n🏦 {i['upi_id']}\n📌 {i['status']}\n"
            if i.get("note"):
                text += f"📝 {i['note']}\n"
            text += "\n"

        await safe_edit(q, text, back())

    elif q.data == "wd":
        state[uid] = {"a": "wd", "step": "amt"}
        await safe_edit(q, "Enter amount (Min ₹50):", back())

    elif q.data == "admin":
        await safe_edit(q, "👑 Admin Panel", InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Search", callback_data="search"),
             InlineKeyboardButton("📤 Pending", callback_data="pending")],
            [InlineKeyboardButton("⬅ Back", callback_data="home")]
        ]))

    elif q.data == "search":
        state[uid] = {"a": "search"}
        await safe_edit(q, "Enter ID or username:")

    elif q.data == "pending":
        r = supabase.table("withdrawals").select("*").eq("status","pending").execute()

        if not r.data:
            return await safe_edit(q, "No pending withdrawals", back())

        w = r.data[0]
        state[uid] = {"a": "pending", "wid": w["id"]}

        await safe_edit(q,
            f"👤 {w['user_id']}\n💰 ₹{w['amount']}\n🏦 {w['upi_id']}",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve", callback_data="approve"),
                 InlineKeyboardButton("❌ Reject", callback_data="reject")]
            ])
        )

    elif q.data == "approve":
        w = supabase.table("withdrawals").select("*").eq("id", state[uid]["wid"]).execute().data[0]

        supabase.table("withdrawals").update({
            "status":"approved",
            "processed_at": now()
        }).eq("id", w["id"]).execute()

        add_tx(w["user_id"], w["amount"], "debit")
        await notify(context, w["user_id"], f"✅ Withdrawal Approved ₹{w['amount']}")
        await safe_edit(q, "Approved")

    elif q.data == "reject":
        state[uid]["step"] = "reason"
        await safe_edit(q, "Enter rejection reason:")

# ---------- MESSAGE ----------

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()

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
        state[uid] = {"a":"edit","target":u["id"]}

        await update.message.reply_text(
            f"👤 @{u.get('username','N/A')}\n🆔 {u['id']}\n💰 ₹{u['balance']}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Credit", callback_data="credit"),
                 InlineKeyboardButton("➖ Debit", callback_data="debit")],
                [InlineKeyboardButton("🚫 Ban" if not u["is_banned"] else "✅ Unban",
                                      callback_data="ban" if not u["is_banned"] else "unban")]
            ])
        )

    elif s["a"] == "wd":
        user = get_user(uid)

        if s["step"] == "amt":
            if not text.isdigit():
                return await update.message.reply_text("Invalid amount")

            amt = int(text)

            if amt > user["balance"]:
                return await update.message.reply_text("Insufficient balance")

            if amt < 50:
                return await update.message.reply_text("Minimum ₹50")

            s["amt"] = amt
            s["step"] = "upi"

            await update.message.reply_text(
                f"📦 Confirm Withdrawal\n\n"
                f"💰 Amount: ₹{amt}\n\n"
                "Enter your UPI ID (name@bank)"
            )

        elif s["step"] == "upi":
            if not re.match(r"^[\w.\-]{2,}@[a-zA-Z]{2,}$", text):
                return await update.message.reply_text("Invalid UPI")

            update_balance(uid, -s["amt"])

            supabase.table("withdrawals").insert({
                "withdraw_id": str(uuid.uuid4())[:8],
                "user_id": uid,
                "amount": s["amt"],
                "upi_id": text,
                "status": "pending",
                "requested_at": now()
            }).execute()

            await notify(context, ADMIN_ID, f"📤 New Withdrawal ₹{s['amt']}")
            await update.message.reply_text("✅ Request submitted")

            state.pop(uid)

    elif s["a"] == "pending" and s.get("step") == "reason":
        w = supabase.table("withdrawals").select("*").eq("id", s["wid"]).execute().data[0]

        supabase.table("withdrawals").update({
            "status":"rejected",
            "note": text,
            "processed_at": now()
        }).eq("id", w["id"]).execute()

        update_balance(w["user_id"], w["amount"])
        add_tx(w["user_id"], w["amount"], "credit")

        await notify(context, w["user_id"], f"❌ Rejected: {text}")
        await update.message.reply_text("Rejected")

        state.pop(uid)

# ---------- ERROR ----------

async def error_handler(update, context):
    print("ERROR:", context.error)

# ---------- RUN ----------

app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(cb))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
app.add_error_handler(error_handler)

PORT = int(os.getenv("PORT", 8080))

print("🚀 Starting bot on port", PORT)

# 👇 ADD THIS
app.post_init = on_startup

app.run_webhook(
    listen="0.0.0.0",
    port=PORT,
    url_path=BOT_TOKEN,
    webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
)

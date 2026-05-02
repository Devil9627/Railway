import os, re, uuid
from datetime import datetime
from telegram import *
from telegram.ext import *
from supabase import create_client

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

ADMIN_ID = 5575627219

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
state = {}

# ================== HELPERS ==================

def get_user(uid):
    r = supabase.table("users").select("*").eq("id", uid).execute()
    return r.data[0] if r.data else None

def create_user(u, ref=None):
    supabase.table("users").insert({
        "id": u.id,
        "username": u.username,
        "balance": 0,
        "referred_by": ref,
        "created_at": datetime.utcnow().isoformat()
    }).execute()

def update_balance(uid, amt):
    supabase.rpc("increment_balance", {"uid": uid, "amt": amt}).execute()

def add_tx(uid, amt, t, status="success"):
    supabase.table("transactions").insert({
        "txn_id": str(uuid.uuid4())[:8],
        "user_id": uid,
        "type": t,
        "amount": amt,
        "status": status
    }).execute()

def get_setting(key, default):
    r = supabase.table("settings").select("value").eq("key", key).execute()
    return int(r.data[0]["value"]) if r.data else default

async def notify(context, uid, text):
    try:
        await context.bot.send_message(uid, text)
    except:
        pass

# ================== UI ==================

def main_menu(uid):
    kb = [
        [InlineKeyboardButton("💰 Balance", callback_data="bal"),
         InlineKeyboardButton("💸 Withdraw", callback_data="wd")],
        [InlineKeyboardButton("🎁 Refer", callback_data="ref"),
         InlineKeyboardButton("📜 History", callback_data="his")]
    ]
    if uid == ADMIN_ID:
        kb.append([InlineKeyboardButton("👑 Admin", callback_data="admin")])
    return InlineKeyboardMarkup(kb)

def back():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back", callback_data="home")]])

# ================== START ==================

async def start(update, context):
    user = update.effective_user
    args = context.args

    ref = int(args[0]) if args else None

    if not get_user(user.id):
        create_user(user, ref)

        # referral reward
        if ref and ref != user.id:
            reward = get_setting("referral_reward", 5)
            update_balance(ref, reward)
            add_tx(ref, reward, "referral")
            await notify(context, ref, f"🎉 You earned ₹{reward} from referral!")

    await update.message.reply_text(
        f"✨ Welcome, {user.first_name}!\nEarn rewards by inviting friends.\n\nChoose below 👇",
        reply_markup=main_menu(user.id)
    )

# ================== CALLBACK ==================

async def cb(update, context):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data == "home":
        state.pop(uid, None)
        await q.edit_message_text("🏠 Menu", reply_markup=main_menu(uid))

    elif q.data == "bal":
        u = get_user(uid)
        reward = get_setting("referral_reward", 5)
        min_wd = get_setting("min_withdraw", 50)

        await q.edit_message_text(
            f"💰 Balance: ₹{u['balance']}\n"
            f"👥 Per Referral: ₹{reward}\n"
            f"📉 Min Withdraw: ₹{min_wd}",
            reply_markup=back()
        )

    elif q.data == "his":
        r = supabase.table("transactions").select("*").eq("user_id", uid)\
            .order("created_at", desc=True).limit(5).execute()

        txt = "📜 Last 5 Transactions\n\n"
        for t in r.data:
            txt += f"{t['type']} ₹{t['amount']} ({t['status']})\n"

        await q.edit_message_text(txt, reply_markup=back())

    elif q.data == "wd":
        state[uid] = {"action": "wd", "step": "amount"}
        await q.edit_message_text("Enter withdrawal amount:", reply_markup=back())

    elif q.data == "admin":
        await q.edit_message_text(
            "👑 Admin Panel",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Search User", callback_data="search"),
                 InlineKeyboardButton("📤 Pending", callback_data="pending")],
                [InlineKeyboardButton("⚙ Settings", callback_data="settings")],
                [InlineKeyboardButton("⬅ Back", callback_data="home")]
            ])
        )

    elif q.data == "search":
        state[uid] = {"action": "search"}
        await q.edit_message_text("Enter user ID or username:")

    elif q.data == "pending":
        r = supabase.table("withdrawals").select("*").eq("status","pending").execute()

        if not r.data:
            return await q.edit_message_text("No pending withdrawals", reply_markup=back())

        w = r.data[0]
        await q.edit_message_text(
            f"User: {w['user_id']}\nAmount: ₹{w['amount']}\nUPI: {w['upi_id']}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve", callback_data=f"ap_{w['id']}"),
                 InlineKeyboardButton("❌ Reject", callback_data=f"rj_{w['id']}")]
            ])
        )

    elif q.data.startswith("ap_"):
        wid = int(q.data.split("_")[1])
        w = supabase.table("withdrawals").select("*").eq("id", wid).execute().data[0]

        supabase.table("withdrawals").update({"status":"approved"}).eq("id", wid).execute()
        add_tx(w["user_id"], w["amount"], "withdraw", "approved")

        await notify(context, w["user_id"], f"✅ Withdrawal ₹{w['amount']} approved")

        await q.edit_message_text("Approved")

    elif q.data.startswith("rj_"):
        wid = int(q.data.split("_")[1])
        w = supabase.table("withdrawals").select("*").eq("id", wid).execute().data[0]

        supabase.table("withdrawals").update({"status":"rejected"}).eq("id", wid).execute()
        update_balance(w["user_id"], w["amount"])

        add_tx(w["user_id"], w["amount"], "withdraw", "rejected")

        await notify(context, w["user_id"], "❌ Withdrawal rejected")

        await q.edit_message_text("Rejected")

    elif q.data == "cr":
        state[uid]["step"] = "credit"
        await q.edit_message_text("Enter amount to credit:")

    elif q.data == "db":
        state[uid]["step"] = "debit"
        await q.edit_message_text("Enter amount to debit:")

# ================== MESSAGE ==================

async def msg(update, context):
    uid = update.effective_user.id
    text = update.message.text

    if uid not in state:
        return

    s = state[uid]

    # ---------- Withdraw ----------
    if s["action"] == "wd":
        if s["step"] == "amount":
            if not text.isdigit():
                return await update.message.reply_text("Invalid amount")

            amt = int(text)
            u = get_user(uid)
            min_wd = get_setting("min_withdraw", 50)

            if amt < min_wd:
                return await update.message.reply_text(f"Min withdraw ₹{min_wd}")

            if amt > u["balance"]:
                return await update.message.reply_text("Insufficient balance")

            s["amount"] = amt
            s["step"] = "upi"
            await update.message.reply_text("Enter UPI ID:")

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
            add_tx(uid, s["amount"], "withdraw", "pending")

            await notify(context, ADMIN_ID, f"📤 New withdraw ₹{s['amount']}")

            await update.message.reply_text("✅ Request submitted")
            state.pop(uid)

    # ---------- Search ----------
    elif s["action"] == "search":
        if text.isdigit():
            r = supabase.table("users").select("*").eq("id", int(text)).execute()
        else:
            r = supabase.table("users").select("*").ilike("username", f"%{text}%").execute()

        if not r.data:
            return await update.message.reply_text("User not found")

        u = r.data[0]
        state[uid] = {"action": "edit", "target": u["id"]}

        await update.message.reply_text(
            f"User: {u['username']}\nBalance: ₹{u['balance']}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Credit", callback_data="cr"),
                 InlineKeyboardButton("➖ Debit", callback_data="db")]
            ])
        )

    # ---------- Credit / Debit ----------
    elif s["action"] == "edit":
        if not text.isdigit():
            return await update.message.reply_text("Invalid amount")

        amt = int(text)
        target = s["target"]

        if s["step"] == "credit":
            update_balance(target, amt)
            add_tx(target, amt, "credit")

        elif s["step"] == "debit":
            update_balance(target, -amt)
            add_tx(target, amt, "debit")

        await update.message.reply_text("✅ Done")
        state.pop(uid)

# ================== RUN ==================

app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(cb))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

PORT = int(os.getenv("PORT", 8080))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

app.run_webhook(
    listen="0.0.0.0",
    port=PORT,
    url_path=BOT_TOKEN,
    webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
)

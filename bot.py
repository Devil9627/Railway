import os, uuid, re
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
    return datetime.now(UTC).strftime("%d %b %Y, %H:%M UTC")

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
        "created_at": now()
    }).execute()

def valid_upi(upi):
    return bool(re.match(r'^[\w.\-]{2,}@[a-zA-Z]{2,}$', upi))

async def notify(context, uid, text):
    try:
        await context.bot.send_message(uid, text, parse_mode="Markdown")
    except:
        pass

async def safe_edit(q, text, markup=None):
    try:
        await q.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
    except:
        pass

# ---------- UI ----------

def menu(uid):
    kb = [
        [InlineKeyboardButton("💰 Balance", callback_data="bal"),
         InlineKeyboardButton("💸 Withdraw", callback_data="wd")],
        [InlineKeyboardButton("📜 History", callback_data="his"),
         InlineKeyboardButton("🎁 Refer", callback_data="ref")]
    ]
    if uid == ADMIN_ID:
        kb.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin")])
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
        f"✨ *Welcome {u.first_name}*\n\n"
        "💸 Earn & Withdraw Easily\n"
        "⚡ Fast UPI Payouts\n\n"
        "👇 Choose option:",
        parse_mode="Markdown",
        reply_markup=menu(u.id)
    )

# ---------- CALLBACK ----------

async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    # ADMIN PROTECTION
    if uid != ADMIN_ID and q.data.startswith(("admin","search","credit","debit","ban","unban","pending","approve","reject","stats")):
        return await q.answer("❌ Not allowed", show_alert=True)

    if q.data == "home":
        state.pop(uid, None)
        await safe_edit(q, "🏠 *Main Menu*", menu(uid))

    elif q.data == "bal":
        u = get_user(uid)
        await safe_edit(q, f"💰 *Balance:* ₹{u['balance']}", back())

    # ---------- WITHDRAW ----------

    elif q.data == "wd":
        state[uid] = {"step": "amt"}
        await safe_edit(q, "💸 *Withdraw Money*\n\nEnter amount (Min ₹50):", back())

    elif q.data == "confirm_wd":
        s = state[uid]

        update_balance(uid, -s["amt"])
        add_tx(uid, s["amt"], "debit")

        wid = str(uuid.uuid4())[:8]

        supabase.table("withdrawals").insert({
            "withdraw_id": wid,
            "user_id": uid,
            "amount": s["amt"],
            "upi_id": s["upi"],
            "status": "pending",
            "requested_at": now()
        }).execute()

        await notify(context, ADMIN_ID,
            f"📤 New Withdrawal\n👤 {uid}\n💰 ₹{s['amt']}"
        )

        await safe_edit(q,
            f"""✅ *Withdrawal Request Submitted*

🆔 `{wid}`
💰 ₹{s['amt']}
🏦 UPI

⏳ Processing...""",
            back()
        )

        state.pop(uid)

    # ---------- HISTORY ----------

    elif q.data == "his":
        w = supabase.table("withdrawals").select("*").eq("user_id", uid).order("requested_at", desc=True).limit(5).execute()

        if not w.data:
            return await safe_edit(q, "📜 No history", back())

        text = "📜 *Withdraw History*\n\n"

        for i in w.data:
            icon = "✅" if i["status"]=="approved" else "❌" if i["status"]=="rejected" else "⏳"

            text += f"""{icon} *#{i['withdraw_id']} • {i['status'].upper()}*
💰 ₹{i['amount']}
🏦 UPI
📄 `{i['upi_id']}`
📅 {i['requested_at']}
"""

            if i.get("note"):
                text += f"📝 {i['note']}\n"

            text += "\n"

        await safe_edit(q, text, back())

    # ---------- ADMIN PANEL ----------

    elif q.data == "admin":
        await safe_edit(q, "👑 *Admin Panel*", InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📊 Stats", callback_data="stats"),
                InlineKeyboardButton("📤 Pending", callback_data="pending")
            ],
            [
                InlineKeyboardButton("🔍 Search", callback_data="search"),
                InlineKeyboardButton("➕ Credit", callback_data="credit_user")
            ],
            [
                InlineKeyboardButton("➖ Debit", callback_data="debit_user"),
                InlineKeyboardButton("🚫 Ban", callback_data="ban")
            ],
            [
                InlineKeyboardButton("✅ Unban", callback_data="unban"),
                InlineKeyboardButton("⬅ Back", callback_data="home")
            ]
        ]))

    # ---------- ADMIN STATS ----------

    elif q.data == "stats":
        users = len(supabase.table("users").select("*").execute().data)
        withdrawals = supabase.table("withdrawals").select("*").execute().data

        total = sum([w["amount"] for w in withdrawals if w["status"]=="approved"])
        pending = len([w for w in withdrawals if w["status"]=="pending"])

        await safe_edit(q,
            f"""📊 *Dashboard Stats*

👥 Users: {users}
💸 Total Paid: ₹{total}
📤 Pending: {pending}
📦 Total Requests: {len(withdrawals)}""",
            back()
        )

    # ---------- ADMIN ACTIONS ----------

    elif q.data == "search":
        state[uid] = {"step": "search"}
        await safe_edit(q, "🔍 Enter User ID or Username:")

    elif q.data == "credit_user":
        state[uid] = {"step": "credit_user"}
        await safe_edit(q, "Enter User ID:")

    elif q.data == "debit_user":
        state[uid] = {"step": "debit_user"}
        await safe_edit(q, "Enter User ID:")

    elif q.data == "ban":
        state[uid] = {"step": "ban"}
        await safe_edit(q, "Enter User ID:")

    elif q.data == "unban":
        state[uid] = {"step": "unban"}
        await safe_edit(q, "Enter User ID:")

    elif q.data == "pending":
        r = supabase.table("withdrawals").select("*").eq("status","pending").execute()

        if not r.data:
            return await safe_edit(q, "✅ No pending", back())

        w = r.data[0]

        await safe_edit(q,
            f"""📤 *Withdrawal*

👤 `{w['user_id']}`
💰 ₹{w['amount']}
🏦 `{w['upi_id']}`""",
            InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_{w['id']}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_{w['id']}")
                ]
            ])
        )

    elif q.data.startswith("approve_"):
        wid = int(q.data.split("_")[1])

        w = supabase.table("withdrawals").select("*").eq("id", wid).execute().data[0]

        supabase.table("withdrawals").update({
            "status":"approved",
            "processed_at": now()
        }).eq("id", wid).execute()

        await notify(context, w["user_id"], f"✅ Withdrawal Approved\n₹{w['amount']}")
        await safe_edit(q, "✅ Approved")

    elif q.data.startswith("reject_"):
        wid = int(q.data.split("_")[1])
        state[uid] = {"step": "reason", "wid": wid}
        await safe_edit(q, "Enter reason:")

# ---------- MESSAGE ----------

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()

    if uid not in state:
        return

    s = state[uid]

    if s["step"] == "amt":
        if not text.isdigit():
            return await update.message.reply_text("❌ Invalid amount")

        amt = int(text)
        user = get_user(uid)

        if amt < 50:
            return await update.message.reply_text("❌ Minimum ₹50")

        if amt > user["balance"]:
            return await update.message.reply_text("❌ Insufficient balance")

        s["amt"] = amt
        s["step"] = "upi"

        await update.message.reply_text("Enter UPI ID (name@bank):")

    elif s["step"] == "upi":
        if not valid_upi(text):
            return await update.message.reply_text("❌ Invalid UPI")

        s["upi"] = text
        s["step"] = "confirm"

        await update.message.reply_text(
            f"""📦 *Confirm Withdrawal*

💰 ₹{s['amt']}
🏦 UPI
📄 `{s['upi']}`""",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Confirm", callback_data="confirm_wd"),
                    InlineKeyboardButton("❌ Cancel", callback_data="home")
                ]
            ])
        )

    # ADMIN ACTIONS
    elif s["step"] == "search":
        r = supabase.table("users").select("*").eq("id", int(text)).execute()

        if not r.data:
            return await update.message.reply_text("❌ Not found")

        u = r.data[0]

        await update.message.reply_text(
            f"👤 {u['id']}\n💰 ₹{u['balance']}\n🚫 {u['is_banned']}"
        )
        state.pop(uid)

    elif s["step"] == "credit_user":
        state[uid] = {"step": "credit_amt", "target": int(text)}
        await update.message.reply_text("Enter amount:")

    elif s["step"] == "credit_amt":
        update_balance(state[uid]["target"], int(text))
        add_tx(state[uid]["target"], int(text), "admin_credit")
        await update.message.reply_text("✅ Credited")
        state.pop(uid)

    elif s["step"] == "debit_user":
        state[uid] = {"step": "debit_amt", "target": int(text)}
        await update.message.reply_text("Enter amount:")

    elif s["step"] == "debit_amt":
        update_balance(state[uid]["target"], -int(text))
        add_tx(state[uid]["target"], int(text), "admin_debit")
        await update.message.reply_text("✅ Debited")
        state.pop(uid)

    elif s["step"] == "ban":
        supabase.table("users").update({"is_banned": True}).eq("id", int(text)).execute()
        await update.message.reply_text("🚫 Banned")
        state.pop(uid)

    elif s["step"] == "unban":
        supabase.table("users").update({"is_banned": False}).eq("id", int(text)).execute()
        await update.message.reply_text("✅ Unbanned")
        state.pop(uid)

    elif s["step"] == "reason":
        wid = s["wid"]
        w = supabase.table("withdrawals").select("*").eq("id", wid).execute().data[0]

        update_balance(w["user_id"], w["amount"])

        supabase.table("withdrawals").update({
            "status": "rejected",
            "note": text,
            "processed_at": now()
        }).eq("id", wid).execute()

        await notify(context, w["user_id"], f"❌ Rejected\n{text}")
        state.pop(uid)

# ---------- RUN ----------

app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(cb))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

PORT = int(os.getenv("PORT", 8080))

app.run_webhook(
    listen="0.0.0.0",
    port=PORT,
    url_path=BOT_TOKEN,
    webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
)

import os
import re
import traceback
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

import repos
from auth import authenticate
from database import get_connection

# ================= CONFIG =================
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("Defina BOT_TOKEN no Railway > Variables")

LOGIN_USER, LOGIN_PASS = range(2)
DESC, VALOR, COMPRA, VENC = range(10, 14)

# ================= UTIL =================
def safe_err(e):
    return str(e)[:300]

def get_user_by_telegram(telegram_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username FROM users WHERE telegram_id = %s", (telegram_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row

def link_telegram(user_id, telegram_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET telegram_id = %s WHERE id = %s", (telegram_id, user_id))
    conn.commit()
    cur.close()
    conn.close()

def unlink_telegram(telegram_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET telegram_id = NULL WHERE telegram_id = %s", (telegram_id,))
    conn.commit()
    cur.close()
    conn.close()

def list_categories(user_id):
    return repos.list_categories(user_id)

# ================= HELP =================
HELP_TEXT = """
🤖 MARTINS FINANCE BOT

🟢 Modo rápido:
Envie:
valor descrição dia/mês

Ex:
200 mercado 10/05
1200 notebook 6x 10/05

• Compra = hoje
• Vencimento = data digitada
• Categoria detectada automaticamente

🔵 Modo guiado:
Use /nova

📌 Comandos:
/login
/status
/logout
/nova
/cancel
/help
"""

NOT_LOGGED = "🔐 Você não está logado. Use /login para entrar."

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    row = get_user_by_telegram(update.effective_user.id)
    if row:
        await update.message.reply_text("✅ Você já está logado.\n\nUse /help para ver como lançar despesas.")
    else:
        await update.message.reply_text("👋 Bem-vindo!\n\n" + NOT_LOGGED)

# ================= LOGIN =================
async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👤 Informe seu usuário:")
    return LOGIN_USER

async def login_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["username"] = update.message.text.strip().lower()
    await update.message.reply_text("🔒 Informe sua senha:")
    return LOGIN_PASS

async def login_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data.get("username")
    password = update.message.text.strip()

    try:
        user_id = authenticate(username, password)
    except Exception as e:
        await update.message.reply_text(f"❌ Erro no banco:\n{safe_err(e)}")
        return ConversationHandler.END

    if not user_id:
        await update.message.reply_text("❌ Usuário ou senha inválidos.")
        return ConversationHandler.END

    link_telegram(user_id, update.effective_user.id)

    await update.message.reply_text("✅ Login realizado com sucesso!\n\nAgora envie uma despesa ou use /help.")
    return ConversationHandler.END

# ================= STATUS =================
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    row = get_user_by_telegram(update.effective_user.id)
    if row:
        await update.message.reply_text(f"✅ Logado como {row['username']}")
    else:
        await update.message.reply_text(NOT_LOGGED)

# ================= LOGOUT =================
async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    unlink_telegram(update.effective_user.id)
    await update.message.reply_text("✅ Logout realizado.")

# ================= PARSER INTELIGENTE =================
def parse_message(text, user_id):
    text_lower = text.lower()

    # Valor
    match_val = re.search(r"\d+[.,]?\d*", text)
    if not match_val:
        return None
    valor = float(match_val.group().replace(",", "."))

    # Parcelas
    match_parc = re.search(r"(\d+)x", text_lower)
    parcelas = int(match_parc.group(1)) if match_parc else 1

    # Data
    match_date = re.search(r"\d{1,2}/\d{1,2}", text)
    venc = datetime.today().date()
    if match_date:
        venc = datetime.strptime(match_date.group() + f"/{datetime.today().year}", "%d/%m/%Y").date()

    # Categoria automática
    categorias = list_categories(user_id)
    categoria_id = None

    for cat in categorias:
        if cat["name"].lower() in text_lower:
            categoria_id = cat["id"]
            break

    # Descrição limpa
    desc = text
    desc = re.sub(r"\d+[.,]?\d*", "", desc, count=1)
    desc = re.sub(r"\d+x", "", desc)
    desc = re.sub(r"\d{1,2}/\d{1,2}", "", desc)
    desc = desc.strip()

    return desc.title(), valor, parcelas, venc, categoria_id

# ================= MENSAGEM LIVRE =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text.lower() in ["oi", "olá", "ola", "ajuda", "help"]:
        await update.message.reply_text(HELP_TEXT)
        return

    row = get_user_by_telegram(update.effective_user.id)
    if not row:
        await update.message.reply_text(NOT_LOGGED)
        return

    parsed = parse_message(text, row["id"])
    if not parsed:
        await update.message.reply_text("❌ Não entendi.\nUse /help para exemplos.")
        return

    desc, valor, parcelas, venc, categoria_id = parsed

    try:
        repos.add_payment(
            user_id=row["id"],
            description=desc,
            amount=valor,
            purchase_date=str(datetime.today().date()),
            due_date=str(venc),
            month=venc.month,
            year=venc.year,
            category_id=categoria_id,
            is_credit=True if parcelas > 1 else False,
            installments=parcelas
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao salvar:\n{safe_err(e)}")
        print(traceback.format_exc())
        return

    msg = f"✅ Despesa cadastrada!\n\n🧾 {desc}\n💰 {valor}\n📅 Venc: {venc.strftime('%d/%m/%Y')}"
    if parcelas > 1:
        msg += f"\n💳 Parcelado em {parcelas}x"

    await update.message.reply_text(msg)

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    login_handler = ConversationHandler(
        entry_points=[CommandHandler("login", login)],
        states={
            LOGIN_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_user)],
            LOGIN_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_pass)],
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", lambda u, c: u.message.reply_text(HELP_TEXT)))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(login_handler)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot rodando...")
    app.run_polling()

if __name__ == "__main__":
    main()

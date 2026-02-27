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
    raise RuntimeError("Defina a variável de ambiente BOT_TOKEN no Railway.")


# ================= STATES =================
LOGIN_USER, LOGIN_PASS = range(2)
DESC, VALOR, COMPRA, VENC = range(10, 14)


# ================= TEXTOS =================
HELP_TEXT = (
    "🤖 *Martins Finance*\n\n"
    "Você pode:\n\n"
    "🧾 Enviar despesa rápida assim:\n"
    "`200 academia 10/05`\n\n"
    "📋 Ou usar modo guiado:\n"
    "/nova (eu pergunto passo a passo)\n\n"
    "🔐 Se ainda não estiver logado:\n"
    "/login"
)

NOT_LOGGED_TEXT = (
    "🔐 Você ainda não está logado.\n\n"
    "Para começar, digite:\n"
    "/login"
)


# ================= DATABASE =================
def get_user_by_telegram(telegram_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username FROM users WHERE telegram_id = %s", (telegram_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def link_telegram(user_id: int, telegram_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET telegram_id = %s WHERE id = %s", (telegram_id, user_id))
    conn.commit()
    cur.close()
    conn.close()


def unlink_telegram(telegram_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET telegram_id = NULL WHERE telegram_id = %s", (telegram_id,))
    conn.commit()
    cur.close()
    conn.close()


# ================= HELPERS =================
def normalize_username(u: str) -> str:
    return (u or "").strip().lower()


def safe_err(e: Exception) -> str:
    msg = str(e).strip()
    if not msg:
        msg = e.__class__.__name__
    return msg[:300]


def parse_quick_expense(texto: str):
    t = texto.strip()

    m_val = re.search(r"(\d+[.,]?\d*)", t)
    if not m_val:
        return None

    valor = float(m_val.group(1).replace(",", "."))

    m_date = re.search(r"(\d{1,2}/\d{1,2})", t)
    if m_date:
        venc = datetime.strptime(
            f"{m_date.group(1)}/{datetime.today().year}",
            "%d/%m/%Y"
        ).date()
    else:
        venc = datetime.today().date()

    desc = re.sub(r"(\d+[.,]?\d*)", "", t, count=1)
    desc = re.sub(r"(\d{1,2}/\d{1,2})", "", desc, count=1).strip()

    if not desc:
        desc = "Despesa"

    compra = datetime.today().date()
    return desc, valor, compra, venc


# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Olá!\n\n"
        "Eu sou seu assistente financeiro.\n\n"
        "Se for seu primeiro acesso, digite:\n"
        "/login\n\n"
        "Ou digite /help para ver como usar."
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


# ================= LOGIN =================
async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔐 *Login*\n\n"
        "Digite seu usuário:",
        parse_mode="Markdown"
    )
    return LOGIN_USER


async def login_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["username"] = normalize_username(update.message.text)
    await update.message.reply_text("🔒 Agora digite sua senha:")
    return LOGIN_PASS


async def login_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data.get("username", "")
    password = update.message.text.strip()

    await update.message.reply_text("🔎 Validando credenciais...")

    try:
        user_id = authenticate(username, password)
    except Exception as e:
        await update.message.reply_text(f"❌ Erro no banco:\n{safe_err(e)}")
        context.user_data.clear()
        return ConversationHandler.END

    if not user_id:
        await update.message.reply_text(
            "❌ Usuário ou senha inválidos.\n"
            "Digite /login para tentar novamente."
        )
        context.user_data.clear()
        return ConversationHandler.END

    link_telegram(user_id, update.effective_user.id)

    await update.message.reply_text(
        "✅ Login realizado com sucesso!\n\n"
        "Agora você pode:\n"
        "• Enviar despesa rápida: `200 academia 10/05`\n"
        "• Ou usar /nova para modo guiado",
        parse_mode="Markdown"
    )

    context.user_data.clear()
    return ConversationHandler.END


# ================= MODO GUIADO =================
async def nova(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    row = get_user_by_telegram(telegram_id)

    if not row:
        await update.message.reply_text(NOT_LOGGED_TEXT)
        return ConversationHandler.END

    context.user_data["user_id"] = row["id"]
    await update.message.reply_text("📝 Qual a descrição?")
    return DESC


async def receber_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["desc"] = update.message.text
    await update.message.reply_text("💰 Qual o valor?")
    return VALOR


async def receber_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["valor"] = float(update.message.text.replace(",", "."))
    except:
        await update.message.reply_text("❌ Valor inválido. Digite novamente.")
        return VALOR

    await update.message.reply_text("📅 Data da compra (DD/MM/AAAA)?")
    return COMPRA


async def receber_compra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        compra = datetime.strptime(update.message.text, "%d/%m/%Y").date()
        context.user_data["compra"] = compra
    except:
        await update.message.reply_text("❌ Data inválida.")
        return COMPRA

    await update.message.reply_text("📆 Data de vencimento (DD/MM/AAAA)?")
    return VENC


async def receber_venc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        venc = datetime.strptime(update.message.text, "%d/%m/%Y").date()
    except:
        await update.message.reply_text("❌ Data inválida.")
        return VENC

    repos.add_payment(
        user_id=context.user_data["user_id"],
        description=context.user_data["desc"],
        amount=context.user_data["valor"],
        purchase_date=str(context.user_data["compra"]),
        due_date=str(venc),
        month=venc.month,
        year=venc.year,
        category_id=None,
        is_credit=False,
        installments=1
    )

    await update.message.reply_text("✅ Despesa cadastrada com sucesso!")
    context.user_data.clear()
    return ConversationHandler.END


# ================= MENSAGENS INTELIGENTES =================
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.lower()
    telegram_id = update.effective_user.id
    row = get_user_by_telegram(telegram_id)

    # NÃO LOGADO
    if not row:
        await update.message.reply_text(
            "👋 Olá!\n\n"
            "Você ainda não está logado.\n"
            "Digite /login para acessar sua conta."
        )
        return

    # EXPLICAÇÃO MODO GUIADO
    if "modo guiado" in texto or "guiado" in texto:
        await update.message.reply_text(
            "📋 *Modo Guiado*\n\n"
            "Eu vou perguntar:\n"
            "1️⃣ Descrição\n"
            "2️⃣ Valor\n"
            "3️⃣ Data da compra\n"
            "4️⃣ Data de vencimento\n\n"
            "Digite /nova para começar.",
            parse_mode="Markdown"
        )
        return

    # SAUDAÇÃO
    if texto in ["oi", "olá", "ola", "bom dia", "boa tarde", "boa noite"]:
        await update.message.reply_text(
            "👋 Tudo certo!\n\n"
            "Você pode lançar despesa assim:\n"
            "`200 academia 10/05`\n\n"
            "Ou usar /nova.",
            parse_mode="Markdown"
        )
        return

    # DESPESA RÁPIDA
    parsed = parse_quick_expense(update.message.text)
    if not parsed:
        await update.message.reply_text(
            "🤔 Não entendi.\n\n"
            "Use por exemplo:\n"
            "`200 academia 10/05`\n"
            "Ou /nova para modo guiado.",
            parse_mode="Markdown"
        )
        return

    desc, valor, compra, venc = parsed

    repos.add_payment(
        user_id=row["id"],
        description=desc,
        amount=valor,
        purchase_date=str(compra),
        due_date=str(venc),
        month=venc.month,
        year=venc.year,
        category_id=None,
        is_credit=False,
        installments=1
    )

    await update.message.reply_text("✅ Despesa cadastrada com sucesso!")


# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    login_handler = ConversationHandler(
        entry_points=[CommandHandler("login", login)],
        states={
            LOGIN_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_user)],
            LOGIN_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_pass)],
        },
        fallbacks=[],
        allow_reentry=True,
    )

    nova_handler = ConversationHandler(
        entry_points=[CommandHandler("nova", nova)],
        states={
            DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_desc)],
            VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_valor)],
            COMPRA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_compra)],
            VENC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_venc)],
        },
        fallbacks=[],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(login_handler)
    app.add_handler(nova_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    print("Bot rodando...")
    app.run_polling()


if __name__ == "__main__":
    main()

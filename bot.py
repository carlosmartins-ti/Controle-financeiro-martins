import re
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
import os
TOKEN = os.getenv("BOT_TOKEN")


# ================= STATES =================
LOGIN_USER, LOGIN_PASS = range(2)
DESC, VALOR, COMPRA, VENC = range(10, 14)


# ================= DATABASE HELPERS =================

def get_user_by_telegram(telegram_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM users WHERE telegram_id = %s",
        (telegram_id,)
    )
    row = cur.fetchone()
    conn.close()
    return row["id"] if row else None


def link_telegram(user_id, telegram_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET telegram_id = %s WHERE id = %s",
        (telegram_id, user_id)
    )
    conn.commit()
    conn.close()


# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    user_id = get_user_by_telegram(telegram_id)

    if user_id:
        await update.message.reply_text(
            "👋 Olá! Você já está logado.\n"
            "Envie uma despesa como:\n"
            "200 academia 10/05"
        )
    else:
        await update.message.reply_text(
            "👋 Bem-vindo!\nUse /login para acessar sua conta."
        )


# ================= LOGIN =================

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👤 Informe seu usuário:")
    return LOGIN_USER


async def login_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["username"] = update.message.text
    await update.message.reply_text("🔒 Informe sua senha:")
    return LOGIN_PASS


async def login_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data["username"]
    password = update.message.text

    user_id = authenticate(username, password)

    if not user_id:
        await update.message.reply_text("❌ Usuário ou senha inválidos.")
        return ConversationHandler.END

    telegram_id = update.effective_user.id
    link_telegram(user_id, telegram_id)

    await update.message.reply_text("✅ Login realizado com sucesso!")
    return ConversationHandler.END


# ================= CADASTRO GUIADO =================

async def nova(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    user_id = get_user_by_telegram(telegram_id)

    if not user_id:
        await update.message.reply_text("⚠️ Você precisa usar /login primeiro.")
        return ConversationHandler.END

    context.user_data["user_id"] = user_id
    await update.message.reply_text("📝 Qual a descrição?")
    return DESC


async def receber_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["desc"] = update.message.text
    await update.message.reply_text("💰 Valor?")
    return VALOR


async def receber_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["valor"] = float(update.message.text.replace(",", "."))
    except:
        await update.message.reply_text("Valor inválido.")
        return VALOR

    await update.message.reply_text("📅 Data da compra (DD/MM/AAAA)?")
    return COMPRA


async def receber_compra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        compra = datetime.strptime(update.message.text, "%d/%m/%Y").date()
        context.user_data["compra"] = compra
    except:
        await update.message.reply_text("Formato inválido.")
        return COMPRA

    await update.message.reply_text("📆 Vencimento (DD/MM/AAAA)?")
    return VENC


async def receber_venc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        venc = datetime.strptime(update.message.text, "%d/%m/%Y").date()
    except:
        await update.message.reply_text("Formato inválido.")
        return VENC

    user_id = context.user_data["user_id"]

    repos.add_payment(
        user_id=user_id,
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

    await update.message.reply_text("✅ Despesa cadastrada!")
    return ConversationHandler.END


# ================= INTERPRETAÇÃO INTELIGENTE =================

async def interpretar_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    user_id = get_user_by_telegram(telegram_id)

    texto = update.message.text.lower().strip()

    if not user_id:
        await update.message.reply_text("⚠️ Use /login para acessar sua conta.")
        return

    # Saudações
    if texto in ["oi", "olá", "ola", "bom dia", "boa tarde", "boa noite"]:
        await update.message.reply_text(
            "👋 Olá! Envie algo como:\n"
            "200 academia 10/05"
        )
        return

    try:
        valor_match = re.search(r"\d+[.,]?\d*", texto)
        data_match = re.findall(r"\d{1,2}/\d{1,2}", texto)

        if not valor_match:
            await update.message.reply_text("Não entendi 🤔")
            return

        valor = float(valor_match.group().replace(",", "."))
        desc = re.sub(r"\d+[.,]?\d*", "", texto).strip()

        compra = datetime.today().date()
        venc = compra

        if len(data_match) >= 1:
            venc = datetime.strptime(
                data_match[0] + f"/{datetime.today().year}",
                "%d/%m/%Y"
            ).date()

        repos.add_payment(
            user_id=user_id,
            description=desc.title(),
            amount=valor,
            purchase_date=str(compra),
            due_date=str(venc),
            month=venc.month,
            year=venc.year,
            category_id=None,
            is_credit=False,
            installments=1
        )

        await update.message.reply_text("✅ Despesa cadastrada automaticamente!")

    except:
        await update.message.reply_text("Não consegui entender 🤖")


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

    nova_handler = ConversationHandler(
        entry_points=[CommandHandler("nova", nova)],
        states={
            DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_desc)],
            VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_valor)],
            COMPRA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_compra)],
            VENC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_venc)],
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(login_handler)
    app.add_handler(nova_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, interpretar_texto))

    print("Bot rodando...")
    app.run_polling()


if __name__ == "__main__":
    main()

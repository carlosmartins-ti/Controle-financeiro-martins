import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from database import get_connection

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN não definido")


# =========================
# DB
# =========================

def get_user_by_telegram(telegram_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM users WHERE telegram_id = %s",
        (telegram_id,)
    )
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user["id"] if user else None


def vincular_usuario(username, telegram_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET telegram_id = %s WHERE username = %s RETURNING id",
        (telegram_id, username)
    )
    user = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return user["id"] if user else None


def buscar_categorias(user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name FROM categories WHERE user_id = %s ORDER BY name",
        (user_id,)
    )
    categorias = cur.fetchall()
    cur.close()
    conn.close()
    return categorias


def inserir_pagamento(user_id, descricao, categoria_id, valor, vencimento):
    conn = get_connection()
    cur = conn.cursor()

    month = vencimento.month
    year = vencimento.year

    cur.execute("""
        INSERT INTO payments (
            user_id,
            description,
            category_id,
            amount,
            due_date,
            month,
            year,
            paid,
            created_at
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,false,NOW())
    """, (
        user_id,
        descricao,
        categoria_id,
        valor,
        vencimento,
        month,
        year
    ))

    conn.commit()
    cur.close()
    conn.close()


# =========================
# BOT
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Envie no formato:\n\n"
        "Descrição, Valor, Vencimento\n\n"
        "Exemplo:\n"
        "Água, 1000, 27/02/2026"
    )


async def vincular(update: Update, context: ContextTypes.DEFAULT_TYPE):
    partes = update.message.text.split()

    if len(partes) < 2:
        await update.message.reply_text("Use: /vincular SEU_USUARIO")
        return

    username = partes[1]
    telegram_id = update.effective_user.id

    user_id = vincular_usuario(username, telegram_id)

    if not user_id:
        await update.message.reply_text("Usuário não encontrado.")
        return

    await update.message.reply_text("✅ Vinculado com sucesso!")


async def receber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    user_id = get_user_by_telegram(telegram_id)

    if not user_id:
        await update.message.reply_text("Use /vincular SEU_USUARIO primeiro.")
        return

    try:
        descricao, valor, data_str = [x.strip() for x in update.message.text.split(",")]

        valor = float(valor)
        vencimento = datetime.strptime(data_str, "%d/%m/%Y").date()

        context.user_data["descricao"] = descricao
        context.user_data["valor"] = valor
        context.user_data["vencimento"] = vencimento
        context.user_data["user_id"] = user_id

        categorias = buscar_categorias(user_id)

        if not categorias:
            await update.message.reply_text("Você não possui categorias cadastradas.")
            return

        keyboard = [
            [InlineKeyboardButton(cat["name"], callback_data=str(cat["id"]))]
            for cat in categorias
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "Escolha a categoria:",
            reply_markup=reply_markup
        )

    except:
        await update.message.reply_text(
            "Formato inválido.\nUse: Descrição, Valor, DD/MM/AAAA"
        )


async def escolher_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = context.user_data.get("user_id")

    if not user_id:
        await query.edit_message_text("Erro. Envie novamente.")
        return

    categoria_id = int(query.data)
    descricao = context.user_data.get("descricao")
    valor = context.user_data.get("valor")
    vencimento = context.user_data.get("vencimento")

    inserir_pagamento(user_id, descricao, categoria_id, valor, vencimento)

    context.user_data.clear()

    await query.edit_message_text("✅ Pagamento cadastrado com sucesso!")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("vincular", vincular))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receber))
    app.add_handler(CallbackQueryHandler(escolher_categoria))

    app.run_polling()


if __name__ == "__main__":
    main()

import os
import re
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import repos
from auth import authenticate
from database import get_connection


TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Defina BOT_TOKEN no Railway.")


LOGIN_USER, LOGIN_PASS = range(2)
EDIT_VALUE = 10


MESES_PT = {
    1: "Janeiro",
    2: "Fevereiro",
    3: "Março",
    4: "Abril",
    5: "Maio",
    6: "Junho",
    7: "Julho",
    8: "Agosto",
    9: "Setembro",
    10: "Outubro",
    11: "Novembro",
    12: "Dezembro",
}


# ================= DATABASE =================

def get_user_by_telegram(telegram_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username FROM users WHERE telegram_id = %s", (telegram_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def get_last_payments(user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, description, amount, due_date, month, year, paid
        FROM payments
        WHERE user_id = %s
        ORDER BY id DESC
        LIMIT 5
    """, (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def delete_payment(payment_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM payments WHERE id = %s", (payment_id,))
    conn.commit()
    cur.close()
    conn.close()


def update_payment_value(payment_id, value):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE payments SET amount = %s WHERE id = %s",
                (value, payment_id))
    conn.commit()
    cur.close()
    conn.close()


# ================= HELP =================

HELP_TEXT = """
🤖 *Martins Finance Bot*

📌 COMO LANÇAR DESPESA RÁPIDA:
Digite:
`200 mercado 10/05`

Formato:
valor descrição dia/mês

Ex:
`30 uber 06/04`
`1200 notebook 10/05`

• Compra = hoje
• Vencimento = data digitada
• Categoria automática

📌 PARA EDITAR OU EXCLUIR:
/listar
(O bot mostrará botões para cada despesa)

📌 STATUS:
• 🟢 Pago
• 🔴 Em aberto

📌 COMANDOS:
/login
/listar
/logout
/help
"""


# ================= LOGIN =================

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Digite seu usuário:")
    return LOGIN_USER


async def login_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["username"] = update.message.text.strip().lower()
    await update.message.reply_text("Digite sua senha:")
    return LOGIN_PASS


async def login_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data.get("username")
    password = update.message.text.strip()

    await update.message.reply_text("Validando credenciais...")

    user_id = authenticate(username, password)

    if not user_id:
        await update.message.reply_text("Usuário ou senha inválidos.")
        return ConversationHandler.END

    telegram_id = update.effective_user.id

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET telegram_id = %s WHERE id = %s",
                (telegram_id, user_id))
    conn.commit()
    cur.close()
    conn.close()

    await update.message.reply_text("✅ Login realizado com sucesso!")
    return ConversationHandler.END


# ================= LISTAR =================

async def listar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    user = get_user_by_telegram(telegram_id)

    if not user:
        await update.message.reply_text("Faça login com /login")
        return

    pagamentos = get_last_payments(user["id"])

    if not pagamentos:
        await update.message.reply_text("Nenhuma despesa encontrada.")
        return

    texto = "📋 *Últimas despesas:*\n\n"
    keyboard = []

    for p in pagamentos:
        mes_nome = MESES_PT.get(p["month"], "")
        status = "🟢 Pago" if p["paid"] else "🔴 Em aberto"

        texto += (
            f"🧾 *{p['description']}*\n"
            f"💰 R$ {p['amount']}\n"
            f"📅 Venc: {p['due_date'].strftime('%d/%m/%Y')}\n"
            f"📆 {mes_nome}/{p['year']}\n"
            f"{status}\n\n"
        )

        keyboard.append([
            InlineKeyboardButton("❌ Excluir", callback_data=f"del_{p['id']}"),
            InlineKeyboardButton("✏ Editar valor", callback_data=f"edit_{p['id']}")
        ])

    await update.message.reply_text(
        texto,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ================= CALLBACK =================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data.startswith("del_"):
        payment_id = int(data.split("_")[1])

        keyboard = [[
            InlineKeyboardButton("✅ Confirmar exclusão",
                                 callback_data=f"confirm_{payment_id}")
        ]]

        await query.edit_message_text(
            "Tem certeza que deseja excluir essa despesa?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("confirm_"):
        payment_id = int(data.split("_")[1])
        delete_payment(payment_id)
        await query.edit_message_text("🗑 Despesa excluída com sucesso.")

    elif data.startswith("edit_"):
        payment_id = int(data.split("_")[1])
        context.user_data["edit_id"] = payment_id
        await query.edit_message_text("Digite o novo valor:")
        return EDIT_VALUE


async def editar_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        novo_valor = float(update.message.text.replace(",", "."))
    except:
        await update.message.reply_text("Valor inválido.")
        return EDIT_VALUE

    payment_id = context.user_data.get("edit_id")
    update_payment_value(payment_id, novo_valor)

    await update.message.reply_text("✏ Valor atualizado com sucesso!")
    return ConversationHandler.END


# ================= PARSER =================

def limpar_descricao(texto):
    desc = re.sub(r"\d+[.,]?\d*", "", texto, count=1)
    desc = re.sub(r"\d{1,2}/\d{1,2}", "", desc, count=1)
    desc = re.sub(r"\s+", " ", desc).strip()

    palavras = desc.split()
    resultado = []

    for p in palavras:
        if not resultado or resultado[-1].lower() != p.lower():
            resultado.append(p)

    return " ".join(resultado)


# ================= TEXTO LIVRE =================

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip().lower()

    if texto in ["oi", "ola", "olá"]:
        await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")
        return

    if texto in ["excluir", "apagar"]:
        await listar(update, context)
        return

    telegram_id = update.effective_user.id
    user = get_user_by_telegram(telegram_id)

    if not user:
        await update.message.reply_text("Faça login com /login")
        return

    m_val = re.search(r"(\d+[.,]?\d*)", texto)
    m_date = re.search(r"(\d{1,2}/\d{1,2})", texto)

    if not m_val:
        await update.message.reply_text("Formato inválido. Use: 200 mercado 10/05")
        return

    valor = float(m_val.group(1).replace(",", "."))
    desc = limpar_descricao(texto)

    if not desc:
        desc = "Despesa"

    if not m_date:
        venc = datetime.today().date()
    else:
        venc = datetime.strptime(
            f"{m_date.group(1)}/{datetime.today().year}",
            "%d/%m/%Y"
        ).date()

    repos.add_payment(
        user_id=user["id"],
        description=desc.title(),
        amount=valor,
        purchase_date=str(datetime.today().date()),
        due_date=str(venc),
        month=venc.month,
        year=venc.year,
        category_id=None,
        is_credit=False,
        installments=1
    )

    await update.message.reply_text(
        f"✅ Despesa cadastrada!\n\n"
        f"{desc.title()} - R$ {valor}\n"
        f"Venc: {venc.strftime('%d/%m/%Y')}"
    )


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
    )

    edit_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler)],
        states={
            EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, editar_valor)]
        },
        fallbacks=[],
        per_message=False
    )

    app.add_handler(CommandHandler("help", lambda u, c: u.message.reply_text(HELP_TEXT, parse_mode="Markdown")))
    app.add_handler(CommandHandler("listar", listar))
    app.add_handler(login_handler)
    app.add_handler(edit_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    print("Bot rodando...")
    app.run_polling()


if __name__ == "__main__":
    main()

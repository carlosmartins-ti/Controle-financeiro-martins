import os
import re
import traceback
from datetime import datetime, date

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
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")  # aceita os 2 nomes
if not TOKEN:
    raise RuntimeError("Defina a variável de ambiente BOT_TOKEN (Railway > Variables).")

# ================= STATES =================
LOGIN_USER, LOGIN_PASS = range(2)
DESC, VALOR, COMPRA, VENC = range(10, 14)


# ================= TEXTOS =================
HELP_TEXT = (
    "🤖 *Martins Finance — Ajuda*\n\n"
    "✅ *Primeiro acesso*\n"
    "• Digite /login e informe usuário e senha.\n\n"
    "🧾 *Como lançar despesas*\n"
    "1) Modo rápido (recomendado):\n"
    "   `valor descrição dd/mm`\n"
    "   Ex: `200 academia 10/05`\n"
    "   (compra = hoje | venc = data informada)\n\n"
    "2) Modo guiado:\n"
    "   /nova (o bot vai perguntando tudo)\n\n"
    "ℹ️ Comandos:\n"
    "• /status — ver se está logado\n"
    "• /logout — sair\n"
    "• /help — ajuda\n"
)

NOT_LOGGED_TEXT = (
    "🔐 Você *não está logado*.\n"
    "Digite /login para acessar sua conta.\n\n"
    "Depois do login, você pode mandar despesas no formato:\n"
    "`200 academia 10/05`"
)


# ================= DATABASE HELPERS =================
def get_user_by_telegram(telegram_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username FROM users WHERE telegram_id = %s", (telegram_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row  # RealDictCursor no seu get_connection -> row["id"], row["username"]


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
    # Mensagem curta pro usuário (sem vazar secrets)
    msg = str(e).strip()
    if not msg:
        msg = e.__class__.__name__
    return msg[:350]


def parse_quick_expense(texto: str):
    """
    Formato rápido:
    "200 academia 10/05"
    - valor: primeiro número
    - data: primeira ocorrência dd/mm
    - desc: resto
    compra = hoje
    venc = data (com ano atual)
    """
    t = (texto or "").strip()

    # valor (primeiro número)
    m_val = re.search(r"(\d+[.,]?\d*)", t)
    if not m_val:
        return None

    valor = float(m_val.group(1).replace(",", "."))

    # data dd/mm
    m_date = re.search(r"(\d{1,2}/\d{1,2})", t)
    venc = None
    if m_date:
        ddmm = m_date.group(1)
        venc = datetime.strptime(f"{ddmm}/{datetime.today().year}", "%d/%m/%Y").date()
    else:
        venc = datetime.today().date()

    # descrição: remove valor e data do texto
    desc = t
    desc = re.sub(r"(\d+[.,]?\d*)", "", desc, count=1).strip()
    desc = re.sub(r"(\d{1,2}/\d{1,2})", "", desc, count=1).strip()
    desc = re.sub(r"\s{2,}", " ", desc).strip()

    if not desc:
        desc = "Despesa"

    compra = datetime.today().date()
    return desc, valor, compra, venc


# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id

    try:
        row = get_user_by_telegram(telegram_id)
    except Exception as e:
        await update.message.reply_text(
            "❌ Erro ao consultar o banco.\n"
            f"Motivo: {safe_err(e)}\n\n"
            "Abra o Railway > Logs para ver detalhes."
        )
        return

    if row:
        await update.message.reply_text(
            f"👋 Olá! Você já está logado como *{row.get('username','')}*.\n\n"
            "Envie uma despesa no formato:\n"
            "`200 academia 10/05`\n\n"
            "Ou use /help para ver mais opções.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "👋 Bem-vindo!\n\n" + NOT_LOGGED_TEXT,
            parse_mode="Markdown"
        )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    try:
        row = get_user_by_telegram(telegram_id)
        if row:
            await update.message.reply_text(
                f"✅ Você está logado como *{row.get('username','')}*.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(NOT_LOGGED_TEXT, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro no status: {safe_err(e)}")


async def logout_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    try:
        unlink_telegram(telegram_id)
        await update.message.reply_text(
            "✅ Logout realizado.\n\n" + NOT_LOGGED_TEXT,
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(
            "❌ Não consegui fazer logout.\n"
            f"Motivo: {safe_err(e)}"
        )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelado. Use /login ou /help.")
    return ConversationHandler.END


# ================= LOGIN FLOW =================
async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👤 Informe seu usuário do app (ex: `carlos.martins`):",
        parse_mode="Markdown"
    )
    return LOGIN_USER


async def login_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["username"] = normalize_username(update.message.text)
    await update.message.reply_text("🔒 Informe sua senha:")
    return LOGIN_PASS


async def login_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data.get("username", "")
    password = (update.message.text or "").strip()

    await update.message.reply_text("🔎 Validando credenciais...")

    try:
        user_id = authenticate(username, password)
    except Exception as e:
        # aqui aparece erro REAL do auth/banco
        await update.message.reply_text(
            "❌ Erro ao validar no banco.\n"
            f"Motivo: {safe_err(e)}\n\n"
            "Dica: veja Railway > Logs para o stacktrace."
        )
        print("AUTH ERROR:\n", traceback.format_exc())
        context.user_data.clear()
        return ConversationHandler.END

    if not user_id:
        await update.message.reply_text(
            "❌ Usuário ou senha inválidos.\n"
            "Tente novamente com /login."
        )
        context.user_data.clear()
        return ConversationHandler.END

    telegram_id = update.effective_user.id

    # Link do telegram ao usuário
    try:
        link_telegram(user_id, telegram_id)
    except Exception as e:
        await update.message.reply_text(
            "✅ Credenciais OK, *mas* não consegui vincular seu Telegram ao usuário.\n"
            f"Motivo: {safe_err(e)}\n\n"
            "⚠️ Provável causa: falta a coluna `telegram_id` na tabela `users`.\n"
            "Solução SQL:\n"
            "`ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_id BIGINT;`",
            parse_mode="Markdown"
        )
        print("LINK TELEGRAM ERROR:\n", traceback.format_exc())
        context.user_data.clear()
        return ConversationHandler.END

    await update.message.reply_text(
        "✅ *Login realizado com sucesso!*\n\n"
        "Agora você pode lançar despesas assim:\n"
        "`200 academia 10/05`\n\n"
        "Ou usar /nova para o modo guiado.",
        parse_mode="Markdown"
    )
    context.user_data.clear()
    return ConversationHandler.END


# ================= CADASTRO GUIADO =================
async def nova(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id

    try:
        row = get_user_by_telegram(telegram_id)
    except Exception as e:
        await update.message.reply_text(f"❌ Erro no banco: {safe_err(e)}")
        return ConversationHandler.END

    if not row:
        await update.message.reply_text(NOT_LOGGED_TEXT, parse_mode="Markdown")
        return ConversationHandler.END

    context.user_data["user_id"] = row["id"]
    await update.message.reply_text("📝 Qual a descrição da despesa?")
    return DESC


async def receber_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["desc"] = (update.message.text or "").strip()
    await update.message.reply_text("💰 Qual o valor? (ex: 199,90)")
    return VALOR


async def receber_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["valor"] = float((update.message.text or "").replace(",", "."))
    except:
        await update.message.reply_text("❌ Valor inválido. Digite novamente (ex: 199,90).")
        return VALOR

    await update.message.reply_text("📅 Data da compra (DD/MM/AAAA)?")
    return COMPRA


async def receber_compra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        compra = datetime.strptime(update.message.text.strip(), "%d/%m/%Y").date()
        context.user_data["compra"] = compra
    except:
        await update.message.reply_text("❌ Formato inválido. Use DD/MM/AAAA.")
        return COMPRA

    await update.message.reply_text("📆 Vencimento (DD/MM/AAAA)?")
    return VENC


async def receber_venc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        venc = datetime.strptime(update.message.text.strip(), "%d/%m/%Y").date()
    except:
        await update.message.reply_text("❌ Formato inválido. Use DD/MM/AAAA.")
        return VENC

    try:
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
    except Exception as e:
        await update.message.reply_text(
            "❌ Erro ao salvar a despesa no banco.\n"
            f"Motivo: {safe_err(e)}"
        )
        print("ADD_PAYMENT ERROR:\n", traceback.format_exc())
        context.user_data.clear()
        return ConversationHandler.END

    await update.message.reply_text(
        "✅ Despesa cadastrada!\n\n"
        f"🧾 {context.user_data['desc']}\n"
        f"💰 {context.user_data['valor']}\n"
        f"🛒 Compra: {context.user_data['compra'].strftime('%d/%m/%Y')}\n"
        f"📅 Venc: {venc.strftime('%d/%m/%Y')}"
    )
    context.user_data.clear()
    return ConversationHandler.END


# ================= MENSAGENS LIVRES =================
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = (update.message.text or "").strip()
    texto_lower = texto.lower()

    # saudações / palavras soltas
    if texto_lower in ["oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "despesa", "ajuda", "help"]:
        await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")
        return

    telegram_id = update.effective_user.id
    try:
        row = get_user_by_telegram(telegram_id)
    except Exception as e:
        await update.message.reply_text(f"❌ Erro consultando login: {safe_err(e)}")
        return

    if not row:
        await update.message.reply_text(NOT_LOGGED_TEXT, parse_mode="Markdown")
        return

    parsed = parse_quick_expense(texto)
    if not parsed:
        await update.message.reply_text(
            "🤔 Não entendi.\n\n"
            "Use por exemplo:\n"
            "`200 academia 10/05`\n\n"
            "Ou /nova para o modo guiado.",
            parse_mode="Markdown"
        )
        return

    desc, valor, compra, venc = parsed

    try:
        repos.add_payment(
            user_id=row["id"],
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
    except Exception as e:
        await update.message.reply_text(
            "❌ Erro ao salvar no banco.\n"
            f"Motivo: {safe_err(e)}"
        )
        print("ADD_PAYMENT ERROR:\n", traceback.format_exc())
        return

    await update.message.reply_text(
        "✅ Despesa cadastrada!\n\n"
        f"🧾 {desc.title()}\n"
        f"💰 {valor}\n"
        f"🛒 Compra: {compra.strftime('%d/%m/%Y')}\n"
        f"📅 Venc: {venc.strftime('%d/%m/%Y')}"
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
        fallbacks=[CommandHandler("cancel", cancel)],
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
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    # Ordem IMPORTA: ConversationHandlers primeiro
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("logout", logout_cmd))

    app.add_handler(login_handler)
    app.add_handler(nova_handler)

    # Mensagens livres por último
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text), group=1)

    print("Bot rodando...")
    app.run_polling()


if __name__ == "__main__":
    main()

import os
import re
import traceback
from dataclasses import dataclass
from datetime import datetime, date

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import repos
from auth import authenticate
from database import get_connection


# ============================================================
# CONFIG
# ============================================================
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("Defina a variável de ambiente BOT_TOKEN (Railway > Variables).")

BOT_NAME = "Martins Finance"


# ============================================================
# STATES (Conversation)
# ============================================================
LOGIN_USER, LOGIN_PASS = range(2)

# /nova (modo guiado de cadastro)
N_DESC, N_VALOR, N_CAT, N_COMPRA, N_VENC, N_PARCELAS, N_PARCEL_TYPE = range(10, 17)

# /mes (selecionar mês/ano)
M_MONTH, M_YEAR = range(30, 32)

# editar
E_DESC, E_VALOR, E_CAT, E_COMPRA, E_VENC = range(50, 55)

# ============================================================
# HELP / TEXTOS
# ============================================================
HELP_TEXT = (
    f"🤖 *{BOT_NAME} — Ajuda*\n\n"
    "✅ *Primeiro acesso (uma vez só)*\n"
    "• Digite /login e informe seu usuário e senha do app.\n"
    "• Depois disso, seu Telegram fica vinculado e você não precisa logar sempre.\n\n"
    "⚡ *Modo rápido (mais prático)*\n"
    "Envie uma mensagem assim:\n"
    "• `200 academia 10/05`\n"
    "Isso significa:\n"
    "• *Valor:* 200\n"
    "• *Descrição:* academia\n"
    "• *Vencimento:* 10/05 (ano atual)\n"
    "• *Compra:* hoje\n\n"
    "🏷️ *Categoria no modo rápido (opcional)*\n"
    "Você pode informar a categoria assim:\n"
    "• `200 mercado 10/05 #Mercado`\n"
    "ou\n"
    "• `200 mercado 10/05 cat=Mercado`\n\n"
    "🧭 *Modo guiado (o bot pergunta tudo)*\n"
    "• /nova\n"
    "Ele vai perguntar: descrição → valor → categoria → compra → vencimento → parcelas.\n"
    "• Para sair do modo guiado a qualquer momento: /cancel\n\n"
    "📅 *Trabalhar por mês (listar/editar/excluir)*\n"
    "• /mes → escolhe mês/ano para o bot usar nas listagens.\n"
    "• /listar → mostra despesas do mês selecionado com botões.\n\n"
    "📌 *Comandos*\n"
    "• /status — ver se está logado e qual mês está selecionado\n"
    "• /categorias — listar suas categorias\n"
    "• /listar — listar despesas do mês selecionado\n"
    "• /nova — cadastrar despesa no modo guiado\n"
    "• /logout — desvincular Telegram do usuário\n"
    "• /help — mostrar ajuda\n"
)

NOT_LOGGED_TEXT = (
    "🔐 Você *ainda não está logado*.\n\n"
    "✅ Para começar:\n"
    "1) Digite /login\n"
    "2) Informe seu usuário e senha do app\n\n"
    "Depois do login, você pode lançar despesas em modo rápido:\n"
    "• `200 academia 10/05`\n"
    "• `200 mercado 10/05 #Mercado`\n"
)

WELCOME_TEXT = (
    f"👋 Olá! Eu sou o *{BOT_NAME}*.\n\n"
    "Eu lanço despesas no seu sistema e também deixo você *listar/editar/excluir* pelo Telegram.\n\n"
    "Digite /help para ver como usar."
)


# ============================================================
# UTIL / SAFE ERROR
# ============================================================
def safe_err(e: Exception) -> str:
    msg = str(e).strip() or e.__class__.__name__
    return msg[:400]


def normalize_username(u: str) -> str:
    return (u or "").strip().lower()


def fmt_brl(v) -> str:
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return f"R$ {v}"


def parse_ddmm_or_ddmmaaaa(text: str):
    """Aceita dd/mm ou dd/mm/aaaa. Retorna date ou None."""
    t = (text or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m"):
        try:
            dt = datetime.strptime(t, fmt)
            if fmt == "%d/%m":
                return dt.replace(year=date.today().year).date()
            return dt.date()
        except:
            pass
    return None


@dataclass
class QuickExpense:
    desc: str
    valor: float
    compra: date
    venc: date
    categoria_nome: str | None


def parse_quick_expense(texto: str) -> QuickExpense | None:
    """
    Suporta:
      - "200 academia 10/05"
      - "200 mercado 10/05 #Mercado"
      - "200 mercado 10/05 cat=Mercado"
    Regras:
      - valor = primeiro número
      - venc = primeira data dd/mm ou dd/mm/aaaa encontrada (se não tiver, venc=hoje)
      - compra = hoje
      - categoria:
          #Categoria ou cat=Categoria (case-insensitive)
    """
    t = (texto or "").strip()
    if not t:
        return None

    # categoria por # ou cat=
    cat_name = None
    m_hash = re.search(r"#\s*([A-Za-zÀ-ÿ0-9 _-]{2,})$", t)
    if m_hash:
        cat_name = m_hash.group(1).strip()
        t = t[: m_hash.start()].strip()

    m_cat = re.search(r"(?:\bcat\s*=\s*)([A-Za-zÀ-ÿ0-9 _-]{2,})$", t, flags=re.IGNORECASE)
    if m_cat:
        cat_name = m_cat.group(1).strip()
        t = t[: m_cat.start()].strip()

    # valor
    m_val = re.search(r"(\d+[.,]?\d*)", t)
    if not m_val:
        return None
    valor = float(m_val.group(1).replace(",", "."))

    # data
    m_date = re.search(r"(\d{1,2}/\d{1,2}(?:/\d{4})?)", t)
    venc = parse_ddmm_or_ddmmaaaa(m_date.group(1)) if m_date else date.today()

    # desc: remove 1o valor e 1a data
    desc = re.sub(r"(\d+[.,]?\d*)", "", t, count=1).strip()
    desc = re.sub(r"(\d{1,2}/\d{1,2}(?:/\d{4})?)", "", desc, count=1).strip()
    desc = re.sub(r"\s{2,}", " ", desc).strip()
    if not desc:
        desc = "Despesa"

    return QuickExpense(
        desc=desc,
        valor=valor,
        compra=date.today(),
        venc=venc,
        categoria_nome=cat_name,
    )


# ============================================================
# DB HELPERS (telegram link + update full)
# ============================================================
def get_user_by_telegram(telegram_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username FROM users WHERE telegram_id = %s", (telegram_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row  # RealDictCursor -> dict


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


def update_payment_full(user_id: int, payment_id: int, description: str, amount: float,
                        purchase_date: date, due_date: date, category_id: int | None):
    """
    Atualiza tudo, inclusive purchase_date.
    (Seu repos.update_payment não atualiza purchase_date, então fazemos SQL direto aqui.)
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE payments
           SET description = %s,
               amount = %s,
               purchase_date = %s,
               due_date = %s,
               category_id = %s
         WHERE id = %s AND user_id = %s
        """,
        (description, amount, purchase_date, due_date, category_id, payment_id, user_id),
    )
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# USER CONTEXT (mês selecionado)
# ============================================================
def get_selected_month_year(context: ContextTypes.DEFAULT_TYPE):
    m = context.user_data.get("sel_month")
    y = context.user_data.get("sel_year")
    today = date.today()
    if not m:
        m = today.month
    if not y:
        y = today.year
    return int(m), int(y)


def set_selected_month_year(context: ContextTypes.DEFAULT_TYPE, m: int, y: int):
    context.user_data["sel_month"] = int(m)
    context.user_data["sel_year"] = int(y)


# ============================================================
# CATEGORY HELPERS
# ============================================================
def list_user_categories(user_id: int):
    cats = repos.list_categories(user_id) or []
    # RealDictCursor -> lista de dicts
    return cats


def find_category_id_by_name(user_id: int, cat_name: str) -> int | None:
    if not cat_name:
        return None
    cats = list_user_categories(user_id)
    target = cat_name.strip().lower()
    for c in cats:
        if (c.get("name") or "").strip().lower() == target:
            return c.get("id")
    # tentativa “contém”
    for c in cats:
        if target in ((c.get("name") or "").strip().lower()):
            return c.get("id")
    return None


def categories_pretty(user_id: int) -> str:
    cats = list_user_categories(user_id)
    if not cats:
        return "⚠️ Você não tem categorias cadastradas."
    names = [c.get("name") for c in cats if c.get("name")]
    return "🏷️ *Suas categorias:*\n• " + "\n• ".join(names)


# ============================================================
# BASIC COMMANDS
# ============================================================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME_TEXT, parse_mode="Markdown")
    # Se já tiver login, dá instruções
    telegram_id = update.effective_user.id
    try:
        row = get_user_by_telegram(telegram_id)
    except Exception as e:
        await update.message.reply_text(
            "❌ Erro ao consultar o banco.\n"
            f"Motivo: {safe_err(e)}\n\n"
            "⚠️ Dica: verifique se DATABASE_URL está correto nas Variables do Railway."
        )
        return

    if row:
        m, y = get_selected_month_year(context)
        await update.message.reply_text(
            f"✅ Você já está logado como *{row.get('username','')}*.\n"
            f"📅 Mês selecionado: *{m:02d}/{y}*\n\n"
            "Agora você pode:\n"
            "• Enviar `200 academia 10/05`\n"
            "• /listar para ver despesas do mês\n"
            "• /nova para modo guiado\n"
            "• /help para ver tudo",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(NOT_LOGGED_TEXT, parse_mode="Markdown")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    m, y = get_selected_month_year(context)
    try:
        row = get_user_by_telegram(telegram_id)
        if row:
            await update.message.reply_text(
                f"✅ Logado como *{row.get('username','')}*.\n"
                f"📅 Mês selecionado: *{m:02d}/{y}*.\n\n"
                "Use /listar para ver as despesas do mês.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"🔐 Você não está logado.\n📅 Mês selecionado: *{m:02d}/{y}*\n\n" + NOT_LOGGED_TEXT,
                parse_mode="Markdown"
            )
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


async def categorias_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    row = None
    try:
        row = get_user_by_telegram(telegram_id)
    except Exception as e:
        await update.message.reply_text(f"❌ Erro consultando login: {safe_err(e)}")
        return
    if not row:
        await update.message.reply_text(NOT_LOGGED_TEXT, parse_mode="Markdown")
        return
    await update.message.reply_text(categories_pretty(row["id"]), parse_mode="Markdown")


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("edit_pid", None)
    context.user_data.pop("edit_user_id", None)
    context.user_data.pop("tmp_new", None)
    await update.message.reply_text("✅ Cancelado. Você voltou para o modo rápido.\nUse /help se precisar.")
    return ConversationHandler.END


# ============================================================
# LOGIN FLOW
# ============================================================
async def login_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Se já logado, avisa e não refaz
    telegram_id = update.effective_user.id
    try:
        row = get_user_by_telegram(telegram_id)
        if row:
            await update.message.reply_text(
                "✅ Você já está logado.\n"
                "Se quiser trocar de usuário, use /logout e depois /login."
            )
            return ConversationHandler.END
    except:
        pass

    await update.message.reply_text("👤 Informe seu usuário do app:")
    return LOGIN_USER


async def login_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["login_username"] = normalize_username(update.message.text)
    await update.message.reply_text("🔒 Informe sua senha:")
    return LOGIN_PASS


async def login_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data.get("login_username", "")
    password = (update.message.text or "").strip()

    await update.message.reply_text("🔎 Validando credenciais...")

    try:
        user_id = authenticate(username, password)
    except Exception as e:
        await update.message.reply_text(
            "❌ Erro validando login no banco.\n"
            f"Motivo: {safe_err(e)}\n\n"
            "⚠️ Dica: verifique `DATABASE_URL` nas Variables do Railway."
        )
        print("AUTH ERROR:\n", traceback.format_exc())
        context.user_data.pop("login_username", None)
        return ConversationHandler.END

    if not user_id:
        await update.message.reply_text(
            "❌ Usuário ou senha inválidos.\n"
            "Tente novamente com /login."
        )
        context.user_data.pop("login_username", None)
        return ConversationHandler.END

    telegram_id = update.effective_user.id
    try:
        link_telegram(user_id, telegram_id)
    except Exception as e:
        await update.message.reply_text(
            "✅ Credenciais OK, mas falhou ao vincular Telegram.\n"
            f"Motivo: {safe_err(e)}\n\n"
            "⚠️ Confirme se você criou a coluna e índice:\n"
            "`ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_id BIGINT;`\n"
            "`CREATE UNIQUE INDEX IF NOT EXISTS users_telegram_id_uq ON users (telegram_id);`",
            parse_mode="Markdown"
        )
        print("LINK TELEGRAM ERROR:\n", traceback.format_exc())
        context.user_data.pop("login_username", None)
        return ConversationHandler.END

    context.user_data.pop("login_username", None)

    m, y = get_selected_month_year(context)
    await update.message.reply_text(
        "✅ *Login realizado com sucesso!*\n\n"
        "Agora você pode:\n"
        "• Enviar `200 academia 10/05`\n"
        "• Enviar `200 mercado 10/05 #Mercado`\n"
        "• /listar para ver despesas do mês\n"
        "• /nova para modo guiado\n\n"
        f"📅 Mês atual selecionado: *{m:02d}/{y}* (use /mes para mudar)",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


# ============================================================
# MONTH SELECT (/mes)
# ============================================================
async def mes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📅 Qual mês você quer usar? (1 a 12)")
    return M_MONTH


async def mes_set_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").strip()
    if not t.isdigit():
        await update.message.reply_text("❌ Digite um número de 1 a 12.")
        return M_MONTH
    m = int(t)
    if m < 1 or m > 12:
        await update.message.reply_text("❌ Mês inválido. Digite 1 a 12.")
        return M_MONTH

    context.user_data["tmp_month"] = m
    await update.message.reply_text("📅 Agora digite o ano (ex: 2026):")
    return M_YEAR


async def mes_set_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").strip()
    if not t.isdigit():
        await update.message.reply_text("❌ Digite o ano com 4 dígitos (ex: 2026).")
        return M_YEAR
    y = int(t)
    if y < 2000 or y > 2100:
        await update.message.reply_text("❌ Ano inválido. Digite entre 2000 e 2100.")
        return M_YEAR

    m = int(context.user_data.get("tmp_month", date.today().month))
    set_selected_month_year(context, m, y)
    context.user_data.pop("tmp_month", None)

    await update.message.reply_text(f"✅ Mês selecionado: *{m:02d}/{y}*.\nUse /listar para ver despesas.", parse_mode="Markdown")
    return ConversationHandler.END


# ============================================================
# LIST + BUTTONS
# ============================================================
def build_list_keyboard(rows: list[dict], page: int = 1, per_page: int = 6):
    # paginação simples
    total = len(rows)
    if total == 0:
        return None

    max_page = (total + per_page - 1) // per_page
    page = max(1, min(page, max_page))
    start = (page - 1) * per_page
    end = min(start + per_page, total)

    keyboard = []
    for idx in range(start, end):
        r = rows[idx]
        pid = r.get("id")
        keyboard.append([
            InlineKeyboardButton(f"✅ Pagar #{idx+1}", callback_data=f"pay:{pid}:{idx+1}"),
            InlineKeyboardButton(f"✏️ Editar #{idx+1}", callback_data=f"edit:{pid}:{idx+1}"),
            InlineKeyboardButton(f"🗑️ Excluir #{idx+1}", callback_data=f"delq:{pid}:{idx+1}"),
        ])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"page:{page-1}"))
    if page < max_page:
        nav.append(InlineKeyboardButton("Próxima ➡️", callback_data=f"page:{page+1}"))
    if nav:
        keyboard.append(nav)

    keyboard.append([InlineKeyboardButton("🔄 Atualizar lista", callback_data=f"refresh:{page}")])
    return InlineKeyboardMarkup(keyboard)


def format_rows(rows: list[dict], page: int = 1, per_page: int = 6):
    total = len(rows)
    if total == 0:
        return "📭 Nenhuma despesa encontrada nesse mês."

    max_page = (total + per_page - 1) // per_page
    page = max(1, min(page, max_page))
    start = (page - 1) * per_page
    end = min(start + per_page, total)

    lines = [f"🧾 *Despesas ({start+1}-{end} de {total})*"]
    for i in range(start, end):
        r = rows[i]
        desc = r.get("description") or ""
        amount = r.get("amount") or 0
        paid = r.get("paid")
        cat = r.get("category") or "(sem categoria)"
        compra = r.get("purchase_date")
        venc = r.get("due_date")

        # formatos
        try:
            compra_s = datetime.fromisoformat(str(compra)).strftime("%d/%m/%Y") if compra else "-"
        except:
            compra_s = str(compra) if compra else "-"
        try:
            venc_s = datetime.fromisoformat(str(venc)).strftime("%d/%m/%Y") if venc else "-"
        except:
            venc_s = str(venc) if venc else "-"

        status = "✅" if paid else "🕓"
        lines.append(
            f"\n*#{i+1}* {status} *{desc}*\n"
            f"• Valor: *{fmt_brl(amount)}*\n"
            f"• Categoria: *{cat}*\n"
            f"• Compra: *{compra_s}* | Venc: *{venc_s}*"
        )

    lines.append("\nUse os botões abaixo para *Pagar / Editar / Excluir*.")
    lines.append(f"_Página {page}/{max_page}_")
    return "\n".join(lines)


async def listar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    row = None
    try:
        row = get_user_by_telegram(telegram_id)
    except Exception as e:
        await update.message.reply_text(f"❌ Erro consultando login: {safe_err(e)}")
        return
    if not row:
        await update.message.reply_text(NOT_LOGGED_TEXT, parse_mode="Markdown")
        return

    m, y = get_selected_month_year(context)
    try:
        rows = repos.list_payments(row["id"], m, y) or []
    except Exception as e:
        await update.message.reply_text(f"❌ Erro listando despesas: {safe_err(e)}")
        print("LIST ERROR:\n", traceback.format_exc())
        return

    text = format_rows(rows, page=1)
    kb = build_list_keyboard(rows, page=1)
    if kb:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode="Markdown")


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""

    telegram_id = q.from_user.id
    user_row = None
    try:
        user_row = get_user_by_telegram(telegram_id)
    except Exception as e:
        await q.edit_message_text(f"❌ Erro consultando login: {safe_err(e)}")
        return

    if not user_row:
        await q.edit_message_text(NOT_LOGGED_TEXT, parse_mode="Markdown")
        return

    user_id = user_row["id"]
    m, y = get_selected_month_year(context)

    # sempre recarrega lista do mês selecionado para consistência
    try:
        rows = repos.list_payments(user_id, m, y) or []
    except Exception as e:
        await q.edit_message_text(f"❌ Erro carregando lista: {safe_err(e)}")
        return

    # page navigation
    if data.startswith("page:"):
        page = int(data.split(":")[1])
        text = format_rows(rows, page=page)
        kb = build_list_keyboard(rows, page=page)
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
        return

    if data.startswith("refresh:"):
        page = int(data.split(":")[1])
        text = format_rows(rows, page=page)
        kb = build_list_keyboard(rows, page=page)
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
        return

    # pay
    if data.startswith("pay:"):
        _, pid, n = data.split(":")
        pid = int(pid)
        try:
            repos.mark_paid(user_id, pid, True)
        except Exception as e:
            await q.edit_message_text(f"❌ Erro ao marcar como pago: {safe_err(e)}")
            return

        # recarrega
        rows = repos.list_payments(user_id, m, y) or []
        text = format_rows(rows, page=1)
        kb = build_list_keyboard(rows, page=1)
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
        return

    # delete confirm
    if data.startswith("delq:"):
        _, pid, n = data.split(":")
        pid = int(pid)
        n = int(n)
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Confirmar exclusão", callback_data=f"del:{pid}:{n}"),
                InlineKeyboardButton("↩️ Cancelar", callback_data="refresh:1")
            ]
        ])
        await q.edit_message_text(
            f"🗑️ Você quer *excluir* a despesa *#{n}* deste mês?\n\n"
            "Clique em *Confirmar* para excluir.",
            parse_mode="Markdown",
            reply_markup=kb
        )
        return

    # delete
    if data.startswith("del:"):
        _, pid, n = data.split(":")
        pid = int(pid)
        try:
            repos.delete_payment(user_id, pid)
        except Exception as e:
            await q.edit_message_text(f"❌ Erro ao excluir: {safe_err(e)}")
            return

        rows = repos.list_payments(user_id, m, y) or []
        text = format_rows(rows, page=1)
        kb = build_list_keyboard(rows, page=1)
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
        return

    # edit: inicia fluxo por conversation (guardamos pid)
    if data.startswith("edit:"):
        _, pid, n = data.split(":")
        pid = int(pid)
        context.user_data["edit_pid"] = pid
        context.user_data["edit_user_id"] = user_id

        # pega a linha atual para pré-info
        current = None
        for r in rows:
            if int(r.get("id")) == pid:
                current = r
                break

        desc = (current.get("description") if current else "") or ""
        amt = current.get("amount") if current else ""
        cat = (current.get("category") if current else "") or "(sem categoria)"
        compra = current.get("purchase_date") if current else ""
        venc = current.get("due_date") if current else ""

        await q.edit_message_text(
            "✏️ *Editar despesa*\n\n"
            f"Atual:\n"
            f"• Descrição: *{desc}*\n"
            f"• Valor: *{fmt_brl(amt)}*\n"
            f"• Categoria: *{cat}*\n"
            f"• Compra: *{compra}*\n"
            f"• Venc: *{venc}*\n\n"
            "Envie a *nova descrição* agora (ou digite `-` para manter):",
            parse_mode="Markdown"
        )
        return


# ============================================================
# EDIT FLOW (após clicar no botão edit:)
# ============================================================
async def edit_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "edit_pid" not in context.user_data:
        await update.message.reply_text("⚠️ Nenhuma edição em andamento. Use /listar e clique em Editar.")
        return ConversationHandler.END
    context.user_data.setdefault("tmp_new", {})
    context.user_data["tmp_new"]["desc"] = (update.message.text or "").strip()
    await update.message.reply_text("💰 Novo valor (ex: 199,90) ou `-` para manter:")
    return E_VALOR


async def edit_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").strip()
    context.user_data.setdefault("tmp_new", {})
    context.user_data["tmp_new"]["valor"] = t
    await update.message.reply_text(
        "🏷️ Nova categoria (nome) ou `-` para manter.\n"
        "Dica: use /categorias para ver as suas."
    )
    return E_CAT


async def edit_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").strip()
    context.user_data.setdefault("tmp_new", {})
    context.user_data["tmp_new"]["cat"] = t
    await update.message.reply_text("🛒 Nova *data da compra* (DD/MM/AAAA) ou `-` para manter:")
    return E_COMPRA


async def edit_compra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").strip()
    context.user_data.setdefault("tmp_new", {})
    context.user_data["tmp_new"]["compra"] = t
    await update.message.reply_text("📅 Novo *vencimento* (DD/MM/AAAA) ou `-` para manter:")
    return E_VENC


async def edit_venc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t_venc = (update.message.text or "").strip()

    user_id = context.user_data.get("edit_user_id")
    pid = context.user_data.get("edit_pid")
    tmp = context.user_data.get("tmp_new") or {}

    # buscar registro atual (no mês selecionado)
    m, y = get_selected_month_year(context)
    rows = repos.list_payments(user_id, m, y) or []
    current = None
    for r in rows:
        if int(r.get("id")) == int(pid):
            current = r
            break
    if not current:
        await update.message.reply_text("⚠️ Não encontrei essa despesa no mês selecionado. Use /listar novamente.")
        context.user_data.pop("edit_pid", None)
        context.user_data.pop("edit_user_id", None)
        context.user_data.pop("tmp_new", None)
        return ConversationHandler.END

    # aplicar mudanças
    new_desc = tmp.get("desc", "-")
    if new_desc == "-" or not new_desc:
        new_desc = current.get("description") or ""

    new_val_raw = tmp.get("valor", "-")
    if new_val_raw == "-" or not new_val_raw:
        new_val = float(current.get("amount") or 0)
    else:
        try:
            new_val = float(new_val_raw.replace(",", "."))
        except:
            await update.message.reply_text("❌ Valor inválido. Edição cancelada. Use /listar e tente de novo.")
            context.user_data.pop("edit_pid", None)
            context.user_data.pop("edit_user_id", None)
            context.user_data.pop("tmp_new", None)
            return ConversationHandler.END

    new_cat_raw = tmp.get("cat", "-")
    if new_cat_raw == "-" or not new_cat_raw:
        new_cat_id = current.get("category_id")
    else:
        new_cat_id = find_category_id_by_name(user_id, new_cat_raw)
        if new_cat_id is None:
            await update.message.reply_text(
                "⚠️ Não encontrei essa categoria.\n"
                "Use /categorias para ver o nome exato.\n"
                "Edição cancelada. Tente novamente."
            )
            context.user_data.pop("edit_pid", None)
            context.user_data.pop("edit_user_id", None)
            context.user_data.pop("tmp_new", None)
            return ConversationHandler.END

    compra_raw = tmp.get("compra", "-")
    if compra_raw == "-" or not compra_raw:
        compra_dt = current.get("purchase_date")
        compra_dt = datetime.fromisoformat(str(compra_dt)).date() if compra_dt else date.today()
    else:
        compra_dt = parse_ddmm_or_ddmmaaaa(compra_raw)
        if not compra_dt or len(compra_raw.split("/")) != 3:
            await update.message.reply_text("❌ Data da compra inválida. Use DD/MM/AAAA. Edição cancelada.")
            context.user_data.pop("edit_pid", None)
            context.user_data.pop("edit_user_id", None)
            context.user_data.pop("tmp_new", None)
            return ConversationHandler.END

    if t_venc == "-" or not t_venc:
        venc_dt = current.get("due_date")
        venc_dt = datetime.fromisoformat(str(venc_dt)).date() if venc_dt else date.today()
    else:
        venc_dt = parse_ddmm_or_ddmmaaaa(t_venc)
        if not venc_dt or len(t_venc.split("/")) != 3:
            await update.message.reply_text("❌ Vencimento inválido. Use DD/MM/AAAA. Edição cancelada.")
            context.user_data.pop("edit_pid", None)
            context.user_data.pop("edit_user_id", None)
            context.user_data.pop("tmp_new", None)
            return ConversationHandler.END

    try:
        update_payment_full(
            user_id=user_id,
            payment_id=pid,
            description=new_desc,
            amount=float(new_val),
            purchase_date=compra_dt,
            due_date=venc_dt,
            category_id=new_cat_id
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao salvar edição: {safe_err(e)}")
        print("EDIT ERROR:\n", traceback.format_exc())
        context.user_data.pop("edit_pid", None)
        context.user_data.pop("edit_user_id", None)
        context.user_data.pop("tmp_new", None)
        return ConversationHandler.END

    await update.message.reply_text(
        "✅ *Despesa atualizada com sucesso!*\n\n"
        f"🧾 {new_desc}\n"
        f"💰 {fmt_brl(new_val)}\n"
        f"🛒 Compra: {compra_dt.strftime('%d/%m/%Y')}\n"
        f"📅 Venc: {venc_dt.strftime('%d/%m/%Y')}",
        parse_mode="Markdown"
    )

    context.user_data.pop("edit_pid", None)
    context.user_data.pop("edit_user_id", None)
    context.user_data.pop("tmp_new", None)
    return ConversationHandler.END


# ============================================================
# /nova (GUIDED FLOW) + parcelas
# ============================================================
async def nova_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    try:
        row = get_user_by_telegram(telegram_id)
    except Exception as e:
        await update.message.reply_text(f"❌ Erro consultando login: {safe_err(e)}")
        return ConversationHandler.END
    if not row:
        await update.message.reply_text(NOT_LOGGED_TEXT, parse_mode="Markdown")
        return ConversationHandler.END

    context.user_data["tmp_new"] = {"user_id": row["id"]}
    await update.message.reply_text(
        "🧭 *Modo guiado*\n"
        "Vou te perguntar tudo passo a passo.\n"
        "Para cancelar a qualquer momento: /cancel\n\n"
        "📝 Qual a descrição?",
        parse_mode="Markdown"
    )
    return N_DESC


async def nova_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["tmp_new"]["desc"] = (update.message.text or "").strip()
    await update.message.reply_text("💰 Qual o valor? (ex: 199,90)")
    return N_VALOR


async def nova_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").strip()
    try:
        v = float(t.replace(",", "."))
    except:
        await update.message.reply_text("❌ Valor inválido. Digite de novo (ex: 199,90)")
        return N_VALOR
    context.user_data["tmp_new"]["valor"] = v
    await update.message.reply_text(
        "🏷️ Qual categoria? (digite o nome)\n"
        "Dica: use /categorias para ver as suas.\n"
        "Se não quiser categoria, digite: `-`",
        parse_mode="Markdown"
    )
    return N_CAT


async def nova_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = context.user_data["tmp_new"]["user_id"]
    t = (update.message.text or "").strip()
    if t == "-" or not t:
        context.user_data["tmp_new"]["category_id"] = None
    else:
        cid = find_category_id_by_name(user_id, t)
        if cid is None:
            await update.message.reply_text("⚠️ Não encontrei essa categoria. Use /categorias para ver o nome exato.")
            return N_CAT
        context.user_data["tmp_new"]["category_id"] = cid

    await update.message.reply_text("🛒 Data da compra (DD/MM/AAAA)?")
    return N_COMPRA


async def nova_compra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    compra = parse_ddmm_or_ddmmaaaa(update.message.text)
    if not compra or len((update.message.text or "").split("/")) != 3:
        await update.message.reply_text("❌ Data inválida. Use DD/MM/AAAA.")
        return N_COMPRA
    context.user_data["tmp_new"]["compra"] = compra
    await update.message.reply_text("📅 Vencimento (DD/MM/AAAA)?")
    return N_VENC


async def nova_venc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    venc = parse_ddmm_or_ddmmaaaa(update.message.text)
    if not venc or len((update.message.text or "").split("/")) != 3:
        await update.message.reply_text("❌ Vencimento inválido. Use DD/MM/AAAA.")
        return N_VENC
    context.user_data["tmp_new"]["venc"] = venc

    await update.message.reply_text("🔢 Parcelas? (digite 1 para à vista)")
    return N_PARCELAS


async def nova_parcelas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").strip()
    if not t.isdigit():
        await update.message.reply_text("❌ Digite um número (ex: 1, 2, 3...).")
        return N_PARCELAS
    parcelas = int(t)
    if parcelas < 1 or parcelas > 36:
        await update.message.reply_text("❌ Parcelas inválidas (1 a 36).")
        return N_PARCELAS

    context.user_data["tmp_new"]["parcelas"] = parcelas

    if parcelas == 1:
        context.user_data["tmp_new"]["parcel_type"] = "total"
        return await nova_salvar(update, context)

    await update.message.reply_text(
        "📌 Você digitou mais de 1 parcela.\n"
        "O valor informado é:\n"
        "1) *Valor total da compra* (vou dividir nas parcelas)\n"
        "2) *Valor já é por parcela* (vou repetir esse valor)\n\n"
        "Responda com `1` ou `2`.",
        parse_mode="Markdown"
    )
    return N_PARCEL_TYPE


async def nova_parcel_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").strip()
    if t not in ("1", "2"):
        await update.message.reply_text("❌ Responda com 1 ou 2.")
        return N_PARCEL_TYPE

    context.user_data["tmp_new"]["parcel_type"] = "total" if t == "1" else "unit"
    return await nova_salvar(update, context)


async def nova_salvar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tmp = context.user_data.get("tmp_new") or {}
    user_id = tmp.get("user_id")
    desc = tmp.get("desc") or "Despesa"
    valor = float(tmp.get("valor") or 0)
    cid = tmp.get("category_id")
    compra = tmp.get("compra")
    venc = tmp.get("venc")
    parcelas = int(tmp.get("parcelas") or 1)
    parcel_type = tmp.get("parcel_type") or "total"

    try:
        repos.add_payment(
            user_id=user_id,
            description=desc,
            amount=valor,
            purchase_date=str(compra),
            due_date=str(venc),
            month=venc.month,
            year=venc.year,
            category_id=cid,
            is_credit=True if parcelas > 1 else False,
            installments=parcelas,
            parcel_type=parcel_type
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao salvar: {safe_err(e)}")
        print("NOVA SAVE ERROR:\n", traceback.format_exc())
        context.user_data.pop("tmp_new", None)
        return ConversationHandler.END

    await update.message.reply_text(
        "✅ *Despesa cadastrada com sucesso!*\n\n"
        f"🧾 {desc}\n"
        f"💰 {fmt_brl(valor)}\n"
        f"🛒 Compra: {compra.strftime('%d/%m/%Y')}\n"
        f"📅 Venc: {venc.strftime('%d/%m/%Y')}\n"
        f"🔢 Parcelas: {parcelas}",
        parse_mode="Markdown"
    )

    context.user_data.pop("tmp_new", None)
    return ConversationHandler.END


# ============================================================
# TEXT ROUTER (modo rápido + inteligência de instrução)
# ============================================================
GREETINGS = {"oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "ajuda", "help", "menu"}

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = (update.message.text or "").strip()
    if not texto:
        return

    low = texto.lower().strip()

    # se o usuário falar "oi" ou algo, sempre responde explicando
    if low in GREETINGS:
        telegram_id = update.effective_user.id
        try:
            row = get_user_by_telegram(telegram_id)
        except Exception as e:
            await update.message.reply_text(
                "❌ Erro ao consultar o banco.\n"
                f"Motivo: {safe_err(e)}\n\n"
                "⚠️ Verifique DATABASE_URL no Railway."
            )
            return

        if not row:
            await update.message.reply_text(NOT_LOGGED_TEXT + "\n\nDigite /help para ver tudo.", parse_mode="Markdown")
            return

        m, y = get_selected_month_year(context)
        await update.message.reply_text(
            f"👋 Olá! Você está logado.\n"
            f"📅 Mês selecionado: *{m:02d}/{y}*\n\n"
            "✅ Envie uma despesa no modo rápido:\n"
            "• `200 academia 10/05`\n"
            "• `200 mercado 10/05 #Mercado`\n\n"
            "Ou use:\n"
            "• /nova (modo guiado)\n"
            "• /listar (ver despesas do mês)\n"
            "• /help (ajuda completa)",
            parse_mode="Markdown"
        )
        return

    # precisa estar logado para lançar
    telegram_id = update.effective_user.id
    try:
        row = get_user_by_telegram(telegram_id)
    except Exception as e:
        await update.message.reply_text(f"❌ Erro consultando login: {safe_err(e)}")
        return

    if not row:
        await update.message.reply_text(
            "⚠️ Eu entendi sua mensagem, mas você ainda não está logado.\n\n"
            + NOT_LOGGED_TEXT,
            parse_mode="Markdown"
        )
        return

    # tenta parsear modo rápido
    parsed = parse_quick_expense(texto)
    if not parsed:
        await update.message.reply_text(
            "🤔 Não consegui entender.\n\n"
            "Use assim:\n"
            "• `200 academia 10/05`\n"
            "• `200 mercado 10/05 #Mercado`\n\n"
            "Ou use /nova para o modo guiado.\n"
            "Use /help para ver exemplos.",
            parse_mode="Markdown"
        )
        return

    # categoria (opcional)
    cid = None
    cat_ok_text = "(sem categoria)"
    if parsed.categoria_nome:
        cid = find_category_id_by_name(row["id"], parsed.categoria_nome)
        if cid is None:
            await update.message.reply_text(
                "⚠️ Eu vi que você informou uma categoria, mas não encontrei no seu cadastro.\n\n"
                f"Categoria informada: *{parsed.categoria_nome}*\n\n"
                "Use /categorias para ver as suas.\n"
                "Vou salvar *sem categoria* desta vez.",
                parse_mode="Markdown"
            )
            cid = None
        else:
            cat_ok_text = parsed.categoria_nome

    # salva
    try:
        repos.add_payment(
            user_id=row["id"],
            description=parsed.desc.title(),
            amount=parsed.valor,
            purchase_date=str(parsed.compra),
            due_date=str(parsed.venc),
            month=parsed.venc.month,
            year=parsed.venc.year,
            category_id=cid,
            is_credit=False,
            installments=1
        )
    except Exception as e:
        await update.message.reply_text(
            "❌ Não consegui salvar no banco.\n"
            f"Motivo: {safe_err(e)}\n\n"
            "⚠️ Dica: veja Railway > Logs."
        )
        print("ADD_PAYMENT ERROR:\n", traceback.format_exc())
        return

    await update.message.reply_text(
        "✅ *Despesa cadastrada!*\n\n"
        f"🧾 {parsed.desc.title()}\n"
        f"💰 {fmt_brl(parsed.valor)}\n"
        f"🏷️ {cat_ok_text}\n"
        f"🛒 Compra: {parsed.compra.strftime('%d/%m/%Y')}\n"
        f"📅 Venc: {parsed.venc.strftime('%d/%m/%Y')}\n\n"
        "Use /listar para ver no mês selecionado.",
        parse_mode="Markdown"
    )


# ============================================================
# MAIN
# ============================================================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Login conversation
    login_conv = ConversationHandler(
        entry_points=[CommandHandler("login", login_cmd)],
        states={
            LOGIN_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_user)],
            LOGIN_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_pass)],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        allow_reentry=True,
    )

    # /mes conversation
    mes_conv = ConversationHandler(
        entry_points=[CommandHandler("mes", mes_cmd)],
        states={
            M_MONTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, mes_set_month)],
            M_YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, mes_set_year)],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        allow_reentry=True,
    )

    # /nova conversation
    nova_conv = ConversationHandler(
        entry_points=[CommandHandler("nova", nova_cmd)],
        states={
            N_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, nova_desc)],
            N_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, nova_valor)],
            N_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, nova_cat)],
            N_COMPRA: [MessageHandler(filters.TEXT & ~filters.COMMAND, nova_compra)],
            N_VENC: [MessageHandler(filters.TEXT & ~filters.COMMAND, nova_venc)],
            N_PARCELAS: [MessageHandler(filters.TEXT & ~filters.COMMAND, nova_parcelas)],
            N_PARCEL_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, nova_parcel_type)],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        allow_reentry=True,
    )

    # Edit conversation (após clicar em editar)
    edit_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, edit_desc)],
        states={
            E_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_valor)],
            E_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_cat)],
            E_COMPRA: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_compra)],
            E_VENC: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_venc)],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        allow_reentry=True,
        # Só "pega" se existe edit_pid setado, senão o on_text pega.
        per_message=False,
    )

    # Commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("logout", logout_cmd))
    app.add_handler(CommandHandler("categorias", categorias_cmd))
    app.add_handler(CommandHandler("listar", listar_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))

    # Conversations (ordem importa)
    app.add_handler(login_conv)
    app.add_handler(mes_conv)
    app.add_handler(nova_conv)

    # Callback buttons
    app.add_handler(CallbackQueryHandler(on_callback))

    # Edit conversation: precisamos “interceptar” quando edit_pid existe
    # Vamos colocar antes do on_text usando group menor.
    app.add_handler(edit_conv, group=0)

    # Text fallback (modo rápido)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text), group=1)

    print("Bot rodando...")
    app.run_polling()


if __name__ == "__main__":
    main()

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
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError(
        "Defina a variável de ambiente BOT_TOKEN (ou TELEGRAM_TOKEN) no Railway > Variables."
    )

# ================= STATES (Conversations) =================
LOGIN_USER, LOGIN_PASS = range(2)
DESC, VALOR, COMPRA, VENC, CAT, PARC, PARC_TIPO = range(10, 17)


# ================= TEXTOS (UX) =================
HELP_TEXT = (
    "🤖 *Martins Finance — Ajuda*\n\n"
    "✅ *Primeiro acesso*\n"
    "• Use /login e informe usuário e senha do seu app.\n"
    "• Depois disso, você não precisa logar de novo (fica vinculado ao seu Telegram).\n\n"
    "🧾 *Lançar despesas*\n"
    "1) *Modo rápido* (mensagem normal):\n"
    "   `valor descrição dd/mm`\n"
    "   Ex: `200 academia 10/05`\n"
    "   → *Compra*: hoje | *Vencimento*: data informada\n\n"
    "   *Com categoria*:\n"
    "   `200 mercado 10/05 #Mercado`\n\n"
    "   *Parcelado*:\n"
    "   `1200 notebook 6x 10/05 #Cartão de crédito`\n"
    "   → cria 6 parcelas (vencimentos mês a mês)\n\n"
    "2) *Modo guiado*:\n"
    "   Use /nova e o bot vai perguntando tudo (descrição, valor, compra, vencimento, categoria e parcelas).\n\n"
    "📌 *Comandos*\n"
    "• /start — boas-vindas\n"
    "• /login — entrar\n"
    "• /status — ver se está logado\n"
    "• /logout — sair\n"
    "• /categorias — listar suas categorias\n"
    "• /nova — cadastrar guiado\n"
    "• /help — ajuda\n"
)

NOT_LOGGED_TEXT = (
    "🔐 Você *não está logado*.\n"
    "Digite /login para acessar sua conta.\n\n"
    "Depois do login, você pode mandar despesas no formato:\n"
    "`200 academia 10/05`\n"
    "ou usar /nova (modo guiado)."
)

WELCOME_LOGGED = (
    "✅ Você já está logado.\n\n"
    "📌 Para cadastrar uma despesa:\n"
    "• Modo rápido: `200 academia 10/05`\n"
    "• Modo guiado: /nova\n\n"
    "Se quiser ver categorias: /categorias\n"
    "Ajuda completa: /help"
)


# ================= HELPERS: DB =================
def get_user_by_telegram(telegram_id: int):
    """Retorna dict {id, username} se estiver vinculado; senão None."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, username FROM users WHERE telegram_id = %s",
        (telegram_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def link_telegram(user_id: int, telegram_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET telegram_id = %s WHERE id = %s",
        (telegram_id, user_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def unlink_telegram(telegram_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET telegram_id = NULL WHERE telegram_id = %s",
        (telegram_id,),
    )
    conn.commit()
    cur.close()
    conn.close()


def safe_err(e: Exception) -> str:
    msg = str(e).strip()
    if not msg:
        msg = e.__class__.__name__
    # evita vazar info grande
    return msg[:450]


def normalize_username(u: str) -> str:
    return (u or "").strip().lower()


def parse_ddmm_to_date(ddmm: str) -> date:
    """Converte '10/05' para date com ano atual."""
    return datetime.strptime(f"{ddmm}/{datetime.today().year}", "%d/%m/%Y").date()


def list_user_categories(user_id: int):
    """Retorna lista de dicts: [{'id':..,'name':..}, ...]"""
    cats = repos.list_categories(user_id)
    # repos.list_categories retorna rows via RealDictCursor -> dicts.
    # Se vier como tupla por algum motivo, tenta adaptar.
    out = []
    for r in cats or []:
        if isinstance(r, dict):
            out.append({"id": r.get("id"), "name": r.get("name")})
        else:
            # fallback: (id, name)
            out.append({"id": r[0], "name": r[1]})
    return out


def category_name_to_id(user_id: int, name: str):
    """Procura categoria por nome (case-insensitive). Retorna id ou None."""
    name = (name or "").strip().lower()
    if not name:
        return None
    cats = list_user_categories(user_id)
    for c in cats:
        if (c.get("name") or "").strip().lower() == name:
            return c.get("id")
    return None


# ================= PARSER (modo rápido) =================
def parse_quick_message(text: str):
    """
    Entende mensagens como:
      "200 academia 10/05"
      "200 mercado 10/05 #Mercado"
      "1200 notebook 6x 10/05 #Cartão de crédito"
      "200 mercado 10/05 12/05 #Mercado"  -> 2 datas: compra e venc (nessa ordem)

    Regras:
    - valor = primeiro número encontrado
    - parcelas = padrão "6x" (opcional)
    - datas dd/mm: se vierem 2 -> compra, venc; se vier 1 -> venc; se vier 0 -> venc=hoje
    - categoria: "#Nome da categoria" no final ou em qualquer lugar
    - descrição: texto sem valor, sem datas, sem parcelas, sem #categoria
    """
    t = (text or "").strip()
    if not t:
        return None

    # valor
    m_val = re.search(r"(\d+[.,]?\d*)", t)
    if not m_val:
        return None
    valor = float(m_val.group(1).replace(",", "."))

    # parcelas "6x"
    m_parc = re.search(r"\b(\d{1,2})\s*x\b", t.lower())
    parcelas = int(m_parc.group(1)) if m_parc else 1
    if parcelas < 1:
        parcelas = 1

    # categoria via #...
    cat_name = None
    m_cat = re.search(r"(?:#)([A-Za-zÀ-ÿ0-9 _\-]+)$", t.strip())
    if m_cat:
        cat_name = m_cat.group(1).strip()

    # datas dd/mm
    ddmms = re.findall(r"\b(\d{1,2}/\d{1,2})\b", t)
    compra = datetime.today().date()
    venc = datetime.today().date()
    if len(ddmms) >= 2:
        compra = parse_ddmm_to_date(ddmms[0])
        venc = parse_ddmm_to_date(ddmms[1])
    elif len(ddmms) == 1:
        venc = parse_ddmm_to_date(ddmms[0])

    # descrição: remove valor (primeiro), remove datas (até 2), remove parcelas, remove #categoria final
    desc = t
    desc = re.sub(r"(\d+[.,]?\d*)", "", desc, count=1).strip()
    # remove parcelas
    desc = re.sub(r"\b(\d{1,2})\s*x\b", "", desc, flags=re.IGNORECASE).strip()
    # remove datas
    for _ in range(min(2, len(ddmms))):
        desc = re.sub(r"\b(\d{1,2}/\d{1,2})\b", "", desc, count=1).strip()
    # remove #categoria final
    desc = re.sub(r"(?:#)([A-Za-zÀ-ÿ0-9 _\-]+)$", "", desc).strip()
    desc = re.sub(r"\s{2,}", " ", desc).strip()

    if not desc:
        desc = "Despesa"

    return {
        "description": desc,
        "amount": valor,
        "purchase_date": compra,
        "due_date": venc,
        "category_name": cat_name,
        "installments": parcelas,
    }


# ================= COMMANDS =================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    try:
        row = get_user_by_telegram(telegram_id)
    except Exception as e:
        await update.message.reply_text(
            "❌ Não consegui consultar o banco.\n"
            f"Motivo: {safe_err(e)}\n\n"
            "📌 Dica: verifique se DATABASE_URL está correto no Railway > Variables."
        )
        print("START DB ERROR:\n", traceback.format_exc())
        return

    if row:
        await update.message.reply_text(WELCOME_LOGGED, parse_mode="Markdown")
    else:
        await update.message.reply_text(
            "👋 Bem-vindo!\n\n" + NOT_LOGGED_TEXT + "\n\n" + "Digite /help para ver exemplos.",
            parse_mode="Markdown",
        )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    try:
        row = get_user_by_telegram(telegram_id)
        if row:
            await update.message.reply_text(
                f"✅ Você está logado como *{row.get('username','')}*.\n"
                "Use /nova ou mande uma despesa no modo rápido.\n"
                "Ex: `200 mercado 10/05`",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(NOT_LOGGED_TEXT, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro no status: {safe_err(e)}")
        print("STATUS ERROR:\n", traceback.format_exc())


async def logout_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    try:
        unlink_telegram(telegram_id)
        await update.message.reply_text(
            "✅ Logout realizado.\n\n" + NOT_LOGGED_TEXT,
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(
            "❌ Não consegui fazer logout.\n"
            f"Motivo: {safe_err(e)}"
        )
        print("LOGOUT ERROR:\n", traceback.format_exc())


async def categorias_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    try:
        row = get_user_by_telegram(telegram_id)
    except Exception as e:
        await update.message.reply_text(f"❌ Erro consultando login: {safe_err(e)}")
        print("CATEGORIAS LOGIN ERROR:\n", traceback.format_exc())
        return

    if not row:
        await update.message.reply_text(NOT_LOGGED_TEXT, parse_mode="Markdown")
        return

    try:
        cats = list_user_categories(row["id"])
    except Exception as e:
        await update.message.reply_text(
            "❌ Não consegui listar suas categorias.\n"
            f"Motivo: {safe_err(e)}"
        )
        print("CATEGORIAS LIST ERROR:\n", traceback.format_exc())
        return

    if not cats:
        await update.message.reply_text("Você ainda não tem categorias cadastradas no app.")
        return

    # mostra em lista simples
    lines = "\n".join([f"• {c['name']}" for c in cats if c.get("name")])
    await update.message.reply_text(
        "🏷️ *Suas categorias*\n\n"
        f"{lines}\n\n"
        "📌 Para usar no modo rápido, mande no final:\n"
        "`200 mercado 10/05 #Mercado`",
        parse_mode="Markdown"
    )


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelado. Use /login, /nova ou /help.")
    return ConversationHandler.END


# ================= LOGIN FLOW =================
async def login_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Se já estiver logado, avisa
    telegram_id = update.effective_user.id
    try:
        row = get_user_by_telegram(telegram_id)
        if row:
            await update.message.reply_text(
                "✅ Você já está logado.\n\n"
                "Use /nova ou mande uma despesa no modo rápido.\n"
                "Ajuda: /help"
            )
            return ConversationHandler.END
    except Exception:
        pass

    await update.message.reply_text("👤 Informe seu usuário do app:")
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
        await update.message.reply_text(
            "❌ Erro ao validar no banco.\n"
            f"Motivo: {safe_err(e)}\n\n"
            "📌 Dica: confira DATABASE_URL no Railway."
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

    try:
        link_telegram(user_id, telegram_id)
    except Exception as e:
        await update.message.reply_text(
            "✅ Credenciais OK, *mas* não consegui vincular seu Telegram.\n"
            f"Motivo: {safe_err(e)}\n\n"
            "📌 Provável causa: falta a coluna `telegram_id` na tabela `users`.\n"
            "SQL:\n"
            "`ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_id BIGINT;`\n"
            "`CREATE UNIQUE INDEX IF NOT EXISTS users_telegram_id_uq ON users (telegram_id);`",
            parse_mode="Markdown",
        )
        print("LINK TELEGRAM ERROR:\n", traceback.format_exc())
        context.user_data.clear()
        return ConversationHandler.END

    await update.message.reply_text(
        "✅ *Login realizado com sucesso!*\n\n"
        "Agora você pode:\n"
        "• Mandar despesas no modo rápido: `200 mercado 10/05`\n"
        "• Ou usar /nova (modo guiado)\n"
        "• Ver categorias: /categorias\n\n"
        "Ajuda completa: /help",
        parse_mode="Markdown",
    )
    context.user_data.clear()
    return ConversationHandler.END


# ================= MODO GUIADO (/nova) =================
async def nova_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    try:
        row = get_user_by_telegram(telegram_id)
    except Exception as e:
        await update.message.reply_text(
            "❌ Erro consultando login.\n"
            f"Motivo: {safe_err(e)}"
        )
        print("NOVA LOGIN ERROR:\n", traceback.format_exc())
        return ConversationHandler.END

    if not row:
        await update.message.reply_text(NOT_LOGGED_TEXT, parse_mode="Markdown")
        return ConversationHandler.END

    context.user_data["user_id"] = row["id"]
    await update.message.reply_text(
        "🧾 *Modo guiado*\n"
        "Vou te fazer perguntas rapidinho.\n\n"
        "1) Qual a descrição da despesa?",
        parse_mode="Markdown",
    )
    return DESC


async def receber_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = (update.message.text or "").strip()
    if not desc:
        await update.message.reply_text("❌ Descrição vazia. Digite a descrição:")
        return DESC
    context.user_data["desc"] = desc
    await update.message.reply_text("2) Qual o valor? (ex: 199,90)")
    return VALOR


async def receber_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        valor = float((update.message.text or "").replace(",", "."))
        if valor <= 0:
            raise ValueError("valor <= 0")
    except Exception:
        await update.message.reply_text("❌ Valor inválido. Digite novamente (ex: 199,90).")
        return VALOR

    context.user_data["valor"] = valor
    await update.message.reply_text("3) Data da compra (DD/MM/AAAA)?")
    return COMPRA


async def receber_compra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        compra = datetime.strptime(update.message.text.strip(), "%d/%m/%Y").date()
    except Exception:
        await update.message.reply_text("❌ Formato inválido. Use DD/MM/AAAA.")
        return COMPRA

    context.user_data["compra"] = compra
    await update.message.reply_text("4) Vencimento (DD/MM/AAAA)?")
    return VENC


async def receber_venc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        venc = datetime.strptime(update.message.text.strip(), "%d/%m/%Y").date()
    except Exception:
        await update.message.reply_text("❌ Formato inválido. Use DD/MM/AAAA.")
        return VENC

    context.user_data["venc"] = venc

    # categoria: oferece lista
    user_id = context.user_data["user_id"]
    try:
        cats = list_user_categories(user_id)
        cat_names = [c["name"] for c in cats if c.get("name")]
    except Exception as e:
        await update.message.reply_text(
            "❌ Não consegui carregar suas categorias.\n"
            f"Motivo: {safe_err(e)}\n\n"
            "Você pode continuar sem categoria.\n"
            "Digite `sem` para continuar."
        )
        context.user_data["cat_names"] = []
        return CAT

    context.user_data["cat_names"] = cat_names

    if not cat_names:
        await update.message.reply_text(
            "5) Você não tem categorias cadastradas.\n"
            "Digite `sem` para continuar sem categoria."
        )
        return CAT

    # Mostra no chat para não ficar adivinhando
    preview = "\n".join([f"• {n}" for n in cat_names[:25]])
    extra = "\n… (use /categorias para ver tudo)" if len(cat_names) > 25 else ""
    await update.message.reply_text(
        "5) Qual categoria você quer usar?\n\n"
        f"{preview}{extra}\n\n"
        "Digite exatamente o nome da categoria.\n"
        "Ou digite `sem` para não usar categoria."
    )
    return CAT


async def receber_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat_txt = (update.message.text or "").strip()
    if not cat_txt:
        await update.message.reply_text("❌ Digite uma categoria ou `sem`:")
        return CAT

    if cat_txt.lower() in ["sem", "nenhuma", "nao", "não"]:
        context.user_data["category_id"] = None
    else:
        user_id = context.user_data["user_id"]
        cid = category_name_to_id(user_id, cat_txt)
        if not cid:
            await update.message.reply_text(
                "❌ Não achei essa categoria.\n"
                "Digite de novo (igual ao nome) ou mande `sem`.\n"
                "Dica: use /categorias para ver a lista."
            )
            return CAT
        context.user_data["category_id"] = cid

    await update.message.reply_text(
        "6) Vai ser parcelado?\n"
        "• Digite um número (ex: `3` para 3x)\n"
        "• Ou digite `1` se for à vista"
    )
    return PARC


async def receber_parc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    try:
        n = int(txt)
        if n < 1 or n > 36:
            raise ValueError("fora do intervalo")
    except Exception:
        await update.message.reply_text("❌ Digite um número de 1 até 36 (ex: 1, 3, 10).")
        return PARC

    context.user_data["installments"] = n

    if n == 1:
        context.user_data["parcel_type"] = "unit"
        return await salvar_despesa_guiada(update, context)

    await update.message.reply_text(
        "7) O valor que você digitou é:\n"
        "A) Valor total da compra (vou dividir)\n"
        "B) Valor já é por parcela\n\n"
        "Responda com `A` ou `B`."
    )
    return PARC_TIPO


async def receber_parc_tipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    resp = (update.message.text or "").strip().lower()
    if resp in ["a", "total", "valor total", "1"]:
        context.user_data["parcel_type"] = "total"
    elif resp in ["b", "parcela", "por parcela", "2"]:
        context.user_data["parcel_type"] = "unit"
    else:
        await update.message.reply_text("❌ Responda com `A` (total) ou `B` (por parcela).")
        return PARC_TIPO

    return await salvar_despesa_guiada(update, context)


async def salvar_despesa_guiada(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Salva no banco e retorna END."""
    try:
        user_id = context.user_data["user_id"]
        desc = context.user_data["desc"]
        valor = context.user_data["valor"]
        compra = context.user_data["compra"]
        venc = context.user_data["venc"]
        cid = context.user_data.get("category_id")
        installments = int(context.user_data.get("installments", 1))
        parcel_type = context.user_data.get("parcel_type", "unit")

        repos.add_payment(
            user_id=user_id,
            description=desc,
            amount=float(valor),
            purchase_date=str(compra),
            due_date=str(venc),
            month=venc.month,
            year=venc.year,
            category_id=cid,
            is_credit=True if installments > 1 else False,
            installments=installments,
            parcel_type=parcel_type,
        )
    except Exception as e:
        await update.message.reply_text(
            "❌ Erro ao salvar a despesa no banco.\n"
            f"Motivo: {safe_err(e)}\n\n"
            "📌 Se for erro de banco, confira DATABASE_URL no Railway."
        )
        print("SAVE GUIADO ERROR:\n", traceback.format_exc())
        context.user_data.clear()
        return ConversationHandler.END

    # resumo pro usuário (sem adivinhar)
    resumo = (
        "✅ *Despesa cadastrada!*\n\n"
        f"🧾 {context.user_data['desc']}\n"
        f"💰 {context.user_data['valor']}\n"
        f"🛒 Compra: {context.user_data['compra'].strftime('%d/%m/%Y')}\n"
        f"📅 Venc: {context.user_data['venc'].strftime('%d/%m/%Y')}\n"
    )

    inst = int(context.user_data.get("installments", 1))
    if inst > 1:
        resumo += f"💳 Parcelas: {inst}x\n"

    await update.message.reply_text(resumo, parse_mode="Markdown")
    context.user_data.clear()
    return ConversationHandler.END


# ================= MENSAGENS LIVRES (modo rápido + inteligência) =================
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = (update.message.text or "").strip()
    if not texto:
        return

    texto_lower = texto.lower().strip()

    # Se o usuário mandar "oi/ola/ajuda" etc, sempre responde
    saudacoes = ["oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "ajuda", "help", "menu"]
    if texto_lower in saudacoes:
        await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")
        return

    # Se mandar algo tipo "login" sem barra
    if texto_lower in ["login", "entrar", "logar"]:
        await update.message.reply_text("Para entrar, use o comando /login 🙂")
        return

    telegram_id = update.effective_user.id
    try:
        row = get_user_by_telegram(telegram_id)
    except Exception as e:
        await update.message.reply_text(
            "❌ Erro consultando login.\n"
            f"Motivo: {safe_err(e)}\n\n"
            "📌 Dica: confira DATABASE_URL no Railway."
        )
        print("ON_TEXT LOGIN ERROR:\n", traceback.format_exc())
        return

    if not row:
        # Aqui é o ponto que você reclamou: ele tem que orientar SEMPRE
        await update.message.reply_text(NOT_LOGGED_TEXT + "\n\nAjuda: /help", parse_mode="Markdown")
        return

    # tenta parse rápido
    parsed = parse_quick_message(texto)
    if not parsed:
        await update.message.reply_text(
            "🤔 Não entendi o que você quis lançar.\n\n"
            "✅ Use um destes formatos:\n"
            "• `200 academia 10/05`\n"
            "• `200 mercado 10/05 #Mercado`\n"
            "• `1200 notebook 6x 10/05 #Cartão de crédito`\n\n"
            "Ou use /nova (modo guiado).\n"
            "Ajuda completa: /help",
            parse_mode="Markdown",
        )
        return

    user_id = row["id"]

    # categoria (se veio #Categoria)
    cat_id = None
    cat_name = parsed.get("category_name")
    if cat_name:
        cat_id = category_name_to_id(user_id, cat_name)
        if not cat_id:
            # em vez de “adivinhar”, orienta e mostra lista
            try:
                cats = list_user_categories(user_id)
                lines = "\n".join([f"• {c['name']}" for c in cats[:25] if c.get("name")])
                extra = "\n… (use /categorias para ver tudo)" if len(cats) > 25 else ""
            except Exception:
                lines, extra = "", ""
            await update.message.reply_text(
                "⚠️ Eu não achei essa categoria no seu cadastro.\n\n"
                f"Categoria informada: *{cat_name}*\n\n"
                "📌 Suas categorias (parcial):\n"
                f"{lines}{extra}\n\n"
                "Você pode:\n"
                "• Reenviar com uma categoria válida no final: `... #NomeDaCategoria`\n"
                "• Ou usar /nova para escolher na lista.\n"
                "• Ou /categorias para ver todas.",
                parse_mode="Markdown",
            )
            return

    # salva
    try:
        compra = parsed["purchase_date"]
        venc = parsed["due_date"]
        installments = int(parsed.get("installments", 1))
        parcel_type = "total"  # modo rápido: assume que valor digitado é TOTAL quando parcelado

        repos.add_payment(
            user_id=user_id,
            description=str(parsed["description"]).title(),
            amount=float(parsed["amount"]),
            purchase_date=str(compra),
            due_date=str(venc),
            month=venc.month,
            year=venc.year,
            category_id=cat_id,
            is_credit=True if installments > 1 else False,
            installments=installments,
            parcel_type=parcel_type if installments > 1 else "unit",
        )
    except Exception as e:
        await update.message.reply_text(
            "❌ Não consegui salvar a despesa.\n"
            f"Motivo: {safe_err(e)}\n\n"
            "📌 Dica: se for erro no banco, confira DATABASE_URL."
        )
        print("ON_TEXT ADD_PAYMENT ERROR:\n", traceback.format_exc())
        return

    # confirma tudo pro usuário
    msg = (
        "✅ *Despesa cadastrada!*\n\n"
        f"🧾 {str(parsed['description']).title()}\n"
        f"💰 {parsed['amount']}\n"
        f"🛒 Compra: {parsed['purchase_date'].strftime('%d/%m/%Y')}\n"
        f"📅 Venc: {parsed['due_date'].strftime('%d/%m/%Y')}\n"
    )
    if cat_name and cat_id:
        msg += f"🏷️ Categoria: {cat_name}\n"
    if int(parsed.get("installments", 1)) > 1:
        msg += f"💳 Parcelas: {int(parsed['installments'])}x (valor digitado considerado TOTAL)\n"

    await update.message.reply_text(msg, parse_mode="Markdown")


# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    login_handler = ConversationHandler(
        entry_points=[CommandHandler("login", login_cmd)],
        states={
            LOGIN_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_user)],
            LOGIN_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_pass)],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        allow_reentry=True,
    )

    nova_handler = ConversationHandler(
        entry_points=[CommandHandler("nova", nova_cmd)],
        states={
            DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_desc)],
            VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_valor)],
            COMPRA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_compra)],
            VENC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_venc)],
            CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_cat)],
            PARC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_parc)],
            PARC_TIPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_parc_tipo)],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        allow_reentry=True,
    )

    # Commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("logout", logout_cmd))
    app.add_handler(CommandHandler("categorias", categorias_cmd))

    # Conversations
    app.add_handler(login_handler)
    app.add_handler(nova_handler)

    # Free text (por último)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text), group=1)

    print("Bot rodando...")
    app.run_polling()


if __name__ == "__main__":
    main()

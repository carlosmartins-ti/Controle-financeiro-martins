import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date, datetime
import streamlit.components.v1 as components
import os

from database import init_db
from auth import authenticate, create_user, get_security_question, reset_password
import repos

# ================= SETUP =================
st.set_page_config(
    page_title="Controle Financeiro",
    page_icon="💳",
    layout="wide"
)

# 🔥 Inicializa banco APENAS UMA VEZ (Railway-safe)
def safe_init_db():
    try:
        init_db()
    except Exception as e:
        st.error("Erro ao inicializar o banco de dados")
        st.exception(e)

if "db_initialized" not in st.session_state:
    safe_init_db()
    st.session_state.db_initialized = True

# 🔥 CSS (Railway-safe)
if os.path.exists("style.css"):
    with open("style.css", "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

ADMIN_USERNAME = "carlos.martins"

MESES = [
    "Janeiro","Fevereiro","Março","Abril","Maio","Junho",
    "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"
]

# ================= UTILS =================
def fmt_brl(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def format_date_br(s):
    if not s:
        return ""
    try:
        return datetime.fromisoformat(str(s)).strftime("%d/%m/%Y")
    except:
        return str(s)

def is_admin():
    return st.session_state.username == ADMIN_USERNAME

# ================= SESSION =================
for k in ["user_id", "username", "edit_id", "msg_ok"]:
    if k not in st.session_state:
        st.session_state[k] = None

# ================= AUTH =================
def screen_auth():
    st.title("💳 Controle Financeiro")

    components.html(
        """
        <div style="
            background: linear-gradient(135deg, #1f2937, #111827);
            border-radius: 12px;
            padding: 16px;
            margin: 14px 0;
            color: #e5e7eb;
            box-shadow: 0 6px 18px rgba(0,0,0,0.45);
            font-family: system-ui;
        ">
            <div style="display:flex;align-items:center;gap:10px">
                <span style="font-size:22px">🔐</span>
                <strong>Autenticação e autoria do projeto</strong>
            </div>
            <div style="margin-top:10px;font-size:14px">
                Aplicação desenvolvida por <strong>Carlos Martins</strong>.<br>
                Para dúvidas, sugestões ou suporte técnico:
            </div>
            <div style="margin-top:8px">
                📧 <a href="mailto:cr954479@gmail.com" style="color:#60a5fa">cr954479@gmail.com</a>
            </div>
        </div>
        """,
        height=170
    )

    t1, t2, t3 = st.tabs(["Entrar", "Criar conta", "Recuperar senha"])

    with t1:
        u = st.text_input("Usuário", key="login_user")
        p = st.text_input("Senha", type="password", key="login_pass")

        if st.button("Entrar", key="btn_login"):
            uid = authenticate(u, p)
            if uid:
                st.session_state.user_id = uid
                st.session_state.username = u.strip().lower()
                st.rerun()
            else:
                st.error("Usuário ou senha inválidos.")

    with t2:
        u = st.text_input("Novo usuário", key="signup_user")
        p = st.text_input("Nova senha", type="password", key="signup_pass")
        q = st.selectbox(
            "Pergunta de segurança",
            [
                "Qual o nome do seu primeiro pet?",
                "Qual o nome da sua mãe?",
                "Qual sua cidade de nascimento?",
                "Qual seu filme favorito?"
            ],
            key="signup_q"
        )
        a = st.text_input("Resposta", key="signup_answer")

        if st.button("Criar conta", key="btn_signup"):
            create_user(u, p, q, a)
            uid = authenticate(u, p)
            st.session_state.user_id = uid
            st.session_state.username = u.strip().lower()
            repos.seed_default_categories(uid)
            st.success("Conta criada com sucesso.")
            st.rerun()

    with t3:
        u = st.text_input("Usuário", key="reset_user")
        q = get_security_question(u) if u else None

        if q:
            st.info(q)
            a = st.text_input("Resposta", key="reset_answer")
            np = st.text_input("Nova senha", type="password", key="reset_pass")

            if st.button("Redefinir senha"):
                if reset_password(u, a, np):
                    st.success("Senha alterada!")
                else:
                    st.error("Resposta incorreta.")

# ================= APP =================
def screen_app():
    try:
        if not st.session_state.user_id:
            st.error("Usuário não autenticado.")
            return

        with st.sidebar:
            st.markdown(f"**Usuário:** {st.session_state.username}")
            if is_admin():
                st.caption("🔑 Administrador")

            today = date.today()
            month_label = st.selectbox("Mês", MESES, index=today.month - 1)
            year = st.selectbox("Ano", list(range(today.year - 2, today.year + 3)), index=2)
            month = MESES.index(month_label) + 1

            st.divider()
            page = st.radio(
                "Menu",
                ["📊 Dashboard", "🧾 Despesas", "🏷️ Categorias", "💰 Planejamento"]
            )

            if st.button("Sair", use_container_width=True):
                st.session_state.user_id = None
                st.session_state.username = None
                st.rerun()

        if st.session_state.msg_ok:
            st.toast(st.session_state.msg_ok, icon="✅", duration=15)
            st.session_state.msg_ok = None

        repos.seed_default_categories(st.session_state.user_id)

        rows = repos.list_payments(st.session_state.user_id, month, year)
        df = pd.DataFrame(
            rows,
            columns=[
                "id","Descrição","Valor","Vencimento","Pago","Data pagamento",
                "CategoriaID","Categoria","is_credit","installments",
                "installment_index","credit_group"
            ]
        )

        total = df["Valor"].sum() if not df.empty else 0
        pago = df[df["Pago"] == 1]["Valor"].sum() if not df.empty else 0
        aberto = total - pago

        budget = repos.get_budget(st.session_state.user_id, month, year)
        renda = float(budget["income"])
        saldo = renda - total

        st.title("💳 Controle Financeiro")
        st.caption(f"Período: **{month_label}/{year}**")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total do mês", fmt_brl(total))
        c2.metric("Pago", fmt_brl(pago))
        c3.metric("Em aberto", fmt_brl(aberto))
        c4.metric("Saldo", fmt_brl(saldo))

        st.divider()

        if page == "📊 Dashboard":
            if not df.empty:
                fig = px.pie(df, names="Categoria", values="Valor")
                st.plotly_chart(fig, use_container_width=True)

        elif page == "🏷️ Categorias":
            with st.form("form_categoria", clear_on_submit=True):
                new_cat = st.text_input("Nova categoria")
                if st.form_submit_button("Adicionar"):
                    repos.create_category(st.session_state.user_id, new_cat.strip())
                    st.rerun()

            for cid, name in repos.list_categories(st.session_state.user_id):
                a, b = st.columns([4,1])
                a.write(name)
                if b.button("Excluir", key=f"cat_{cid}"):
                    repos.delete_category(st.session_state.user_id, cid)
                    st.rerun()

        elif page == "💰 Planejamento":
            renda_v = st.number_input("Renda", value=float(renda))
            meta_v = st.number_input("Meta de gastos", value=float(budget["expense_goal"]))
            if st.button("Salvar"):
                repos.upsert_budget(st.session_state.user_id, month, year, renda_v, meta_v)
                st.rerun()

    except Exception as e:
        st.error("❌ Ocorreu um erro inesperado.")
        st.exception(e)

# ================= ROUTER =================
if st.session_state.user_id is None:
    screen_auth()
else:
    screen_app()

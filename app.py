import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date, datetime
import streamlit.components.v1 as components

from database import init_db
from auth import authenticate, create_user, get_security_question, reset_password
import repos

# ================= SETUP =================
st.set_page_config(
    page_title="Controle Financeiro",
    page_icon="💳",
    layout="wide"
)

with open("style.css", "r", encoding="utf-8") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

init_db()

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

            if st.button("Redefinir senha", key="btn_reset"):
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

        # Toast de sucesso (15s)
        if st.session_state.msg_ok:
            st.toast(st.session_state.msg_ok, icon="✅", duration=15)
            st.session_state.msg_ok = None

        repos.seed_default_categories(st.session_state.user_id)

        rows = repos.list_payments(st.session_state.user_id, month, year)
        df = pd.DataFrame(
            rows,
            columns=[
                "id", "Descrição", "Valor", "Vencimento", "Pago", "Data pagamento",
                "CategoriaID", "Categoria", "is_credit", "installments",
                "installment_index", "credit_group"
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

        # ================= DESPESAS =================
        if page == "🧾 Despesas":
            st.subheader("🧾 Despesas")

            cats = repos.list_categories(st.session_state.user_id)
            cat_map = {name: cid for cid, name in cats}
            cat_names = ["(Sem categoria)"] + list(cat_map.keys())

            with st.expander("➕ Adicionar despesa", expanded=True):
                with st.form("form_add_despesa", clear_on_submit=True):
                    a1, a2, a3, a4, a5 = st.columns([3, 1, 1.3, 2, 1])

                    desc = a1.text_input("Descrição")
                    val = a2.number_input("Valor (R$)", min_value=0.0, step=10.0)
                    venc = a3.date_input("Vencimento", value=date.today(), format="DD/MM/YYYY")
                    cat_name = a4.selectbox("Categoria", cat_names)
                    parcelas = a5.number_input("Parcelas", min_value=1, step=1, value=1)

                    submitted = st.form_submit_button("Adicionar")

            if submitted:
                if not desc.strip():
                    st.warning("Informe a descrição da despesa.")
                elif val <= 0:
                    st.warning("Informe um valor maior que zero.")
                else:
                    try:
                        cid = None if cat_name == "(Sem categoria)" else cat_map[cat_name]

                        repos.add_payment(
                            st.session_state.user_id,
                            desc.strip(),
                            float(val),
                            str(venc),
                            month,
                            year,
                            cid,
                            is_credit=1 if parcelas > 1 else 0,
                            installments=int(parcelas)
                        )

                        st.session_state.msg_ok = "Despesa cadastrada com sucesso!"
                        st.rerun()

                    except Exception:
                        st.error("❌ Não foi possível cadastrar a despesa.")

            # -------- FATURA DO CARTÃO (PAGAR / DESFAZER) --------
            card_cat_ids = [cid for cid, name in cats if name and "cart" in str(name).lower()]
            credit_rows = [r for r in rows if (r[6] in card_cat_ids)]
            if credit_rows:
                open_credit = [r for r in credit_rows if r[4] == 0]
                total_fatura = sum(float(r[2]) for r in open_credit) if open_credit else 0.0

                st.divider()
                st.subheader("💳 Fatura do cartão")

                cA, cB = st.columns([2.2, 1.2])
                cA.metric("Total em aberto", fmt_brl(total_fatura))

                if open_credit:
                    if cB.button("💰 Pagar fatura do cartão", key="pay_card"):
                        repos.mark_credit_invoice_paid(st.session_state.user_id, month, year)
                        st.session_state.msg_ok = "Fatura do cartão marcada como paga!"
                        st.rerun()
                else:
                    if cB.button("🔄 Desfazer pagamento da fatura", key="unpay_card"):
                        repos.unmark_credit_invoice_paid(st.session_state.user_id, month, year)
                        st.session_state.msg_ok = "Pagamento da fatura desfeito!"
                        st.rerun()

            st.divider()

            if df.empty:
                st.info("Nenhuma despesa cadastrada.")
            else:
                for r in rows:
                    pid, desc_r, amount, due, paid, _, _, cat_name_r, *_ = r

                    a, b, c, d, e, f = st.columns([4, 1.2, 1.8, 1.2, 1.2, 1])

                    a.write(f"**{desc_r}**" + (f"  \n🏷️ {cat_name_r}" if cat_name_r else ""))
                    b.write(fmt_brl(amount))
                    c.write(format_date_br(due))
                    d.write("✅ Paga" if paid else "🕓 Em aberto")

                    if not paid:
                        if e.button("Marcar como paga", key=f"pay_{pid}"):
                            repos.mark_paid(st.session_state.user_id, pid, True)
                            st.session_state.msg_ok = "Despesa marcada como paga!"
                            st.rerun()
                    else:
                        if e.button("Desfazer", key=f"unpay_{pid}"):
                            repos.mark_paid(st.session_state.user_id, pid, False)
                            st.session_state.msg_ok = "Pagamento desfeito!"
                            st.rerun()

                    if f.button("✏️ Editar", key=f"edit_{pid}"):
                        st.session_state.edit_id = pid
                        st.rerun()

                    if f.button("Excluir", key=f"del_{pid}"):
                        repos.delete_payment(st.session_state.user_id, pid)
                        st.session_state.msg_ok = "Despesa excluída!"
                        st.rerun()

                    if st.session_state.edit_id == pid:
                        with st.form(f"edit_form_{pid}", clear_on_submit=False):
                            n_desc = st.text_input("Descrição", value=desc_r)
                            n_val = st.number_input("Valor", value=float(amount), step=10.0)
                            n_venc = st.date_input(
                                "Vencimento",
                                value=datetime.fromisoformat(due).date()
                            )

                            cats2 = repos.list_categories(st.session_state.user_id)
                            cat_map2 = {name: cid for cid, name in cats2}
                            cat_names2 = ["(Sem categoria)"] + list(cat_map2.keys())
                            current_cat = cat_name_r if cat_name_r in cat_map2 else "(Sem categoria)"
                            n_cat_name = st.selectbox(
                                "Categoria",
                                cat_names2,
                                index=cat_names2.index(current_cat)
                            )

                            col1, col2 = st.columns(2)
                            salvar = col1.form_submit_button("Salvar")
                            cancelar = col2.form_submit_button("Cancelar")

                        if salvar:
                            cid2 = None if n_cat_name == "(Sem categoria)" else cat_map2[n_cat_name]
                            repos.update_payment(
                                st.session_state.user_id,
                                pid,
                                n_desc,
                                n_val,
                                str(n_venc),
                                cid2
                            )
                            st.session_state.edit_id = None
                            st.session_state.msg_ok = "Despesa atualizada com sucesso!"
                            st.rerun()

                        if cancelar:
                            st.session_state.edit_id = None
                            st.rerun()

        elif page == "📊 Dashboard":
            st.subheader("📊 Dashboard")
            if not df.empty:
                fig = px.pie(df, names="Categoria", values="Valor")
                st.plotly_chart(fig, use_container_width=True)

        elif page == "🏷️ Categorias":
            st.subheader("🏷️ Categorias")

            with st.form("form_categoria", clear_on_submit=True):
                new_cat = st.text_input("Nova categoria")
                submitted_cat = st.form_submit_button("Adicionar")

            if submitted_cat:
                if not new_cat.strip():
                    st.warning("Informe o nome da categoria.")
                else:
                    try:
                        repos.create_category(st.session_state.user_id, new_cat.strip())
                        st.session_state.msg_ok = "Categoria cadastrada com sucesso!"
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
                    except Exception:
                        st.error("❌ Não foi possível cadastrar a categoria.")

            for cid, name in repos.list_categories(st.session_state.user_id):
                a, b = st.columns([4, 1])
                a.write(name)
                if b.button("Excluir", key=f"cat_{cid}"):
                    repos.delete_category(st.session_state.user_id, cid)
                    st.session_state.msg_ok = "Categoria excluída!"
                    st.rerun()

        elif page == "💰 Planejamento":
            st.subheader("💰 Planejamento")
            renda_v = st.number_input("Renda", value=float(renda))
            meta_v = st.number_input("Meta de gastos", value=float(budget["expense_goal"]))
            if st.button("Salvar"):
                repos.upsert_budget(st.session_state.user_id, month, year, renda_v, meta_v)
                st.session_state.msg_ok = "Planejamento salvo com sucesso!"
                st.rerun()

    except Exception:
        st.error("❌ Ocorreu um erro inesperado. Tente novamente.")
        st.stop()

# ================= ROUTER =================
if st.session_state.user_id is None:
    screen_auth()
else:
    screen_app()

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
    return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

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

# ================= COMPLEMENTO (APENAS ADICIONADO) =================
# Estado para controlar "voltar ao app" após gerar PDF
if "pdf_relatorio_path" not in st.session_state:
    st.session_state.pdf_relatorio_path = None

if "pdf_relatorio_nome" not in st.session_state:
    st.session_state.pdf_relatorio_nome = None

# ================= AUTH =================
def screen_auth():
    st.title("💳 Controle Financeiro")


    components.html(
        '''
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
        ''',
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


        if st.session_state.msg_ok:
            st.toast(st.session_state.msg_ok, icon="✅", duration=15)
            st.session_state.msg_ok = None


        repos.seed_default_categories(st.session_state.user_id)


        rows = repos.list_payments(st.session_state.user_id, month, year)
        df = pd.DataFrame(rows)


        total = float(df["amount"].sum()) if not df.empty else 0.0
        pago = float(df[df["paid"] == True]["amount"].sum()) if not df.empty else 0.0
        aberto = total - pago

        budget = repos.get_budget(st.session_state.user_id, month, year)
        renda = float(budget["income"])

        saldo = float(renda) - float(total)

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


            # ===== RELATÓRIO PDF =====
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
            import tempfile

            # ================= COMPLEMENTO (APENAS ADICIONADO) =================
            # PDF em formato de TABELA + botão "Voltar ao app"
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
            from reportlab.lib import colors

            col_pdf1, col_pdf2 = st.columns([1.2, 1.2])

            if col_pdf1.button("📄 Gerar PDF (Tabela)"):

                data = repos.list_payments(
                    st.session_state.user_id, month, year
                )

                tmp_tbl = tempfile.NamedTemporaryFile(
                    delete=False, suffix=".pdf"
                )

                doc = SimpleDocTemplate(
                    tmp_tbl.name,
                    pagesize=A4,
                    rightMargin=36,
                    leftMargin=36,
                    topMargin=36,
                    bottomMargin=36,
                )

                table_data = []
                table_data.append(
                    [f"Despesas - {month_label}/{year}", "", ""]
                )
                table_data.append(
                    ["Descrição", "Valor (R$)", "Status"]
                )

                total_tbl = 0.0

                for r in data:
                    nome = (r.get("description") or "").strip()
                    valor = float(r.get("amount") or 0)
                    pago = r.get("paid")

                    total_tbl += valor

                    status = (
                        "Pago"
                        if str(pago).lower() in ["true", "t", "1"]
                        else "Em aberto"
                    )

                    table_data.append(
                        [nome, fmt_brl(valor), status]
                    )

                table_data.append(
                    ["TOTAL", fmt_brl(total_tbl), ""]
                )

                table = Table(
                    table_data, colWidths=[260, 100, 100]
                )

                table.setStyle(
                    TableStyle(
                        [
                            ("SPAN", (0, 0), (-1, 0)),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                            ("FONTSIZE", (0, 0), (-1, 0), 14),
                            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                            ("BACKGROUND", (0, 1), (-1, 1), colors.lightgrey),
                            ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                            ("GRID", (0, 1), (-1, -1), 0.6, colors.grey),
                            ("ALIGN", (1, 2), (1, -1), "RIGHT"),
                            ("ALIGN", (2, 2), (2, -2), "CENTER"),
                            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                            ("BACKGROUND", (0, -1), (-1, -1), colors.whitesmoke),
                        ]
                    )
                )

                doc.build([table])

                st.session_state.pdf_relatorio_path = tmp_tbl.name
                st.session_state.pdf_relatorio_nome = (
                    f"despesas_tabela_{month}_{year}.pdf"
                )

                st.success("PDF gerado com sucesso!")
                st.rerun()



            if st.session_state.pdf_relatorio_path:
                with open(st.session_state.pdf_relatorio_path, "rb") as f:
                    st.download_button(
                        "⬇️ Baixar PDF (Tabela)",
                        f,
                        file_name=st.session_state.pdf_relatorio_nome or f"despesas_tabela_{month}_{year}.pdf",
                        mime="application/pdf"
                    )

                if col_pdf2.button("⬅️ Voltar ao app"):
                    st.session_state.pdf_relatorio_path = None
                    st.session_state.pdf_relatorio_nome = None
                    st.rerun()

            # ===== RESTANTE DO CÓDIGO ORIGINAL =====

            cats = repos.list_categories(st.session_state.user_id)
            cat_map = {r["name"]: r["id"] for r in cats}
            cat_names = ["(Sem categoria)"] + list(cat_map.keys())

            card_cat_ids = [r["id"] for r in cats if r.get("name") and "cart" in str(r.get("name")).lower()]
            credit_rows = [r for r in rows if (r.get("category_id") in card_cat_ids)]

            if credit_rows:
                open_credit = [r for r in credit_rows if not r.get("paid")]
                total_fatura = sum(float(r.get("amount") or 0) for r in open_credit)

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

            with st.expander("➕ Adicionar despesa", expanded=True):
                with st.form("form_add_despesa", clear_on_submit=True):
                    a1, a2, a3, a4, a5 = st.columns([3, 1, 1.3, 2, 1])


                    desc = a1.text_input("Descrição")
                    val = a2.number_input("Valor (R$)", min_value=0.0, step=10.0)
                    venc = a3.date_input("Vencimento", value=date.today(), format="DD/MM/YYYY")
                    cat_name = a4.selectbox("Categoria", cat_names)
                    parcelas = a5.number_input("Parcelas", min_value=1, step=1, value=1)
                    tipo_parcela = st.radio(
                         "Tipo de valor",
                         ["Valor total da compra", "Valor já é por parcela"],
                         horizontal=True
                    )

                    submitted = st.form_submit_button("Adicionar")


            if submitted:
                if not desc.strip():
                    st.warning("Informe a descrição da despesa.")
                elif val <= 0:
                    st.warning("Informe um valor maior que zero.")
                else:
                    cid = None if cat_name == "(Sem categoria)" else cat_map[cat_name]

                    repos.add_payment(
                        st.session_state.user_id,
                        desc.strip(),
                        float(val),
                        str(venc),
                        month,
                        year,
                        cid,
                        is_credit=True if parcelas > 1 else False,
                        installments=int(parcelas),
                        parcel_type="total"
                            if tipo_parcela == "Valor total da compra"
                            else "unit"
                    )

                    st.session_state.msg_ok = "Despesa cadastrada com sucesso!"
                    st.rerun()

            st.divider()

            if df.empty:
                st.info("Nenhuma despesa cadastrada.")
            else:
                for r in rows:
                    pid = r.get("id")
                    desc_r = r.get("description")
                    amount = r.get("amount")
                    due = r.get("due_date")
                    paid = r.get("paid")
                    cat_name_r = r.get("category")

                    is_credit = r.get("is_credit")
                    installments = r.get("installments") or 1
                    credit_group = r.get("credit_group")
                    
                    status_color = "#16a34a" if paid else "#dc2626"
                    status_text = "✅ Pago" if paid else "🕓 Em aberto"
                    
                    with st.container(border=True):
                        
                        st.markdown(
                            f'<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;">'
                            f'<div>'
                            f'<div style="font-size:18px;font-weight:600;">🧾 {desc_r}</div>'
                            f'<div style="opacity:0.7;font-size:13px;">🏷️ {cat_name_r if cat_name_r else ""}</div>'
                            f'</div>'
                            f'<div style="background:{status_color};padding:6px 14px;border-radius:20px;font-size:13px;font-weight:500;white-space:nowrap;">'
                            f'{status_text}'
                            f'</div>'
                            f'</div>',
                            unsafe_allow_html=True
                        )

                        st.markdown(
                            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-top:10px;">'
                            f'<div style="font-size:22px;font-weight:700;">{fmt_brl(amount)}</div>'
                            f'<div style="opacity:0.7;font-size:14px;">{format_date_br(due)}</div>'
                            f'</div>',
                            unsafe_allow_html=True
                        )

                        col_btn1, col_btn2, col_btn3 = st.columns(3)
                        

                        if not paid:
                            if col_btn1.button("Marcar como paga", key=f"pay_{pid}"):
                                repos.mark_paid(st.session_state.user_id, pid, True)
                                st.session_state.msg_ok = "Despesa marcada como paga!"
                                st.rerun()
                        else:
                            if col_btn1.button("Desfazer", key=f"unpay_{pid}"):
                                repos.mark_paid(st.session_state.user_id, pid, False)
                                st.session_state.msg_ok = "Pagamento desfeito!"
                                st.rerun()

                        if col_btn2.button("✏️ Editar", key=f"edit_{pid}"):
                            st.session_state.edit_id = pid
                            st.rerun()

                        if col_btn3.button("🗑️ Excluir", key=f"del_{pid}"):
                            repos.delete_payment(st.session_state.user_id, pid)
                            st.session_state.msg_ok = "Despesa excluída!"
                            st.rerun()

                    if is_credit and int(installments) > 1 and credit_group:
                        with st.expander("🧩 Compra parcelada"):
                            if st.button("🗑️ Excluir parcelas em aberto", key=f"del_open_{credit_group}_{pid}"):
                                repos.delete_credit_group(
                                    st.session_state.user_id,
                                    credit_group,
                                    only_open=True
                                )
                                st.session_state.msg_ok = "Parcelas em aberto excluídas!"
                                st.rerun()


                            if st.button("❌ Excluir TODA a compra parcelada", key=f"del_all_{credit_group}_{pid}"):
                                repos.delete_credit_group(
                                    st.session_state.user_id,
                                    credit_group,
                                    only_open=False
                                )
                                st.session_state.msg_ok = "Compra parcelada excluída!"
                                st.rerun()


                    if st.session_state.edit_id == pid:
                        with st.form(f"edit_form_{pid}", clear_on_submit=False):
                            n_desc = st.text_input("Descrição", value=str(desc_r or ""))
                            n_val = st.number_input("Valor", value=float(amount or 0), step=10.0)
                            n_venc = st.date_input(
                                "Vencimento",
                                value=datetime.fromisoformat(str(due)).date() if due else date.today()
                            )

                            cats2 = repos.list_categories(st.session_state.user_id)
                            cat_map2 = {rr["name"]: rr["id"] for rr in cats2}
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
                                n_desc.strip(),
                                float(n_val),
                                str(n_venc),
                                cid2
                            )
                            st.session_state.edit_id = None
                            st.session_state.msg_ok = "Despesa atualizada com sucesso!"
                            st.rerun()


                        if cancelar:
                            st.session_state.edit_id = None
                            st.rerun()
                            
        if page == "📊 Dashboard":
            st.subheader("📊 Dashboard")
            if not df.empty:
                fig = px.pie(df, names="category", values="amount")
                st.plotly_chart(fig, use_container_width=True)

        if page == "🏷️ Categorias":
            st.subheader("🏷️ Categorias")

            with st.form("form_categoria", clear_on_submit=True):
                new_cat = st.text_input("Nova categoria")
                submitted_cat = st.form_submit_button("Adicionar")

            if submitted_cat and new_cat.strip():
                repos.create_category(st.session_state.user_id, new_cat.strip())
                st.session_state.msg_ok = "Categoria cadastrada com sucesso!"
                st.rerun()

            for r in repos.list_categories(st.session_state.user_id):
                cid = r.get("id")
                name = r.get("name")

                a, b = st.columns([4, 1])
                a.write(name)

                if b.button("Excluir", key=f"cat_del_{cid}"):
                    repos.delete_category(st.session_state.user_id, cid)
                    st.session_state.msg_ok = "Categoria excluída!"
                    st.rerun()

        if page == "💰 Planejamento":
            st.subheader("💰 Planejamento")
            renda_v = st.number_input("Renda", value=float(renda))
            meta_v = st.number_input("Meta de gastos", value=float(budget["expense_goal"]))
            if st.button("Salvar"):
                repos.upsert_budget(st.session_state.user_id, month, year, renda_v, meta_v)
                st.session_state.msg_ok = "Planejamento salvo com sucesso!"
                st.rerun()


    except Exception as e:
        st.exception(e)
        st.stop()


# ================= ROUTER =================
if st.session_state.user_id is None:
    screen_auth()
else:
    screen_app()

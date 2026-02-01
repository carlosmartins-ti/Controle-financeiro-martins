import datetime
from database import get_connection

def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")

# -------------------- Default Categories --------------------
DEFAULT_CATEGORIES = [
    "Aluguel",
    "Condomínio",
    "Água",
    "Luz",
    "Plano celular",
    "Internet",
    "Supermercado",
    "Restaurante",
    "Delivery / iFood",
    "Refeição trabalho",
    "TV / Streaming",
    "Transporte",
    "Cartão de crédito",
    "Contas fixas",
    "Lazer",
    "Saúde",
    "Educação",
    "Poupança",
    "Roupas",
    "Calçados",
    "Cosméticos",
    "Farmácia",
    "Academia",
    "Barbeiro / Salão",
    "Cinema",
    "Viagem",
    "Passeios",
    "Jogos",
    "Bares / festas",
    "Faculdade",
    "Móveis",
    "Outros",
    "Imprevistos",
]

# -------------------- Categories --------------------
def list_categories(user_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name FROM categories WHERE user_id = %s ORDER BY name",
        (user_id,)
    )
    rows = cur.fetchall()
    conn.close()
    return rows

def create_category(user_id: int, name: str):
    name = (name or "").strip()
    if not name:
        raise ValueError("Nome da categoria é obrigatório.")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO categories (user_id, name, created_at) VALUES (%s, %s, %s)",
        (user_id, name, _now())
    )
    conn.commit()
    conn.close()

def delete_category(user_id: int, category_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE payments SET category_id = NULL WHERE user_id = %s AND category_id = %s",
        (user_id, category_id)
    )
    cur.execute(
        "DELETE FROM categories WHERE user_id = %s AND id = %s",
        (user_id, category_id)
    )
    conn.commit()
    conn.close()

def seed_default_categories(user_id: int):
    if user_id is None:
        return

    conn = get_connection()
    cur = conn.cursor()

    for name in DEFAULT_CATEGORIES:
        cur.execute(
            """
            INSERT INTO categories (user_id, name, created_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, name) DO NOTHING
            """,
            (user_id, name, _now())
        )

    conn.commit()
    conn.close()

# -------------------- Payments / Despesas --------------------
def add_payment(
    user_id: int,
    description: str,
    amount: float,
    due_date: str,
    month: int,
    year: int,
    category_id=None,
    is_credit: int = 0,
    installments: int = 1
):
    description = (description or "").strip()
    if not description:
        raise ValueError("Descrição é obrigatória.")
    if amount <= 0:
        raise ValueError("Valor deve ser maior que zero.")

    conn = get_connection()
    cur = conn.cursor()

    if not is_credit or installments == 1:
        cur.execute(
            """INSERT INTO payments
               (user_id, description, category_id, amount, due_date,
                month, year, paid, paid_date, created_at,
                is_credit, installments, installment_index, credit_group)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 0, NULL, %s, 0, 1, 1, NULL)""",
            (user_id, description, category_id, amount, due_date, month, year, _now())
        )
    else:
        cur.execute("SELECT COALESCE(MAX(credit_group),0)+1 FROM payments")
        group_id = cur.fetchone()[0]

        parcela_valor = round(amount / installments, 2)

        for i in range(installments):
            m = month + i
            y = year
            if m > 12:
                m -= 12
                y += 1

            cur.execute(
                """INSERT INTO payments
                   (user_id, description, category_id, amount, due_date,
                    month, year, paid, paid_date, created_at,
                    is_credit, installments, installment_index, credit_group)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 0, NULL, %s, 1, %s, %s, %s)""",
                (
                    user_id,
                    f"{description} ({i+1}/{installments})",
                    category_id,
                    parcela_valor,
                    due_date,
                    m,
                    y,
                    _now(),
                    installments,
                    i + 1,
                    group_id
                )
            )

    conn.commit()
    conn.close()

def list_payments(user_id: int, month: int, year: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT p.id, p.description, p.amount, p.due_date, p.paid, p.paid_date,
                  p.category_id, c.name,
                  p.is_credit, p.installments, p.installment_index, p.credit_group
           FROM payments p
           LEFT JOIN categories c ON c.id = p.category_id
           WHERE p.user_id = %s AND p.month = %s AND p.year = %s
           ORDER BY p.paid ASC, p.due_date ASC, p.id DESC""",
        (user_id, month, year)
    )
    rows = cur.fetchall()
    conn.close()
    return rows

def mark_paid(user_id: int, payment_id: int, paid: bool):
    conn = get_connection()
    cur = conn.cursor()

    if paid:
        cur.execute(
            "UPDATE payments SET paid = 1, paid_date = %s WHERE user_id = %s AND id = %s",
            (_now(), user_id, payment_id)
        )
    else:
        cur.execute(
            "UPDATE payments SET paid = 0, paid_date = NULL WHERE user_id = %s AND id = %s",
            (user_id, payment_id)
        )

    conn.commit()
    conn.close()

def delete_payment(user_id: int, payment_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM payments WHERE user_id = %s AND id = %s",
        (user_id, payment_id)
    )
    conn.commit()
    conn.close()

# -------------------- Fatura Cartão --------------------
def mark_credit_invoice_paid(user_id: int, month: int, year: int):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE payments
        SET paid = 1,
            paid_date = %s
        WHERE user_id = %s
          AND month = %s
          AND year = %s
          AND category_id IN (
              SELECT id FROM categories
              WHERE user_id = %s
                AND LOWER(name) LIKE '%cart%'
          )
        """,
        (_now(), user_id, month, year, user_id)
    )

    conn.commit()
    conn.close()

def unmark_credit_invoice_paid(user_id: int, month: int, year: int):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE payments
        SET paid = 0,
            paid_date = NULL
        WHERE user_id = %s
          AND month = %s
          AND year = %s
          AND category_id IN (
              SELECT id FROM categories
              WHERE user_id = %s
                AND LOWER(name) LIKE '%cart%'
          )
        """,
        (user_id, month, year, user_id)
    )

    conn.commit()
    conn.close()

# -------------------- Budget --------------------
def get_budget(user_id: int, month: int, year: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT income, expense_goal FROM budgets WHERE user_id = %s AND month = %s AND year = %s",
        (user_id, month, year)
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return {"income": float(row[0]), "expense_goal": float(row[1])}
    return {"income": 0.0, "expense_goal": 0.0}

def upsert_budget(user_id: int, month: int, year: int, income: float, expense_goal: float):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO budgets (user_id, month, year, income, expense_goal, created_at)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (user_id, month, year)
           DO UPDATE SET income = EXCLUDED.income,
                         expense_goal = EXCLUDED.expense_goal""",
        (user_id, month, year, income, expense_goal, _now())
    )
    conn.commit()
    conn.close()

# -------------------- Unir Fatura Cartão --------------------
def merge_credit_group(user_id: int, payment_ids: list[int]):
    if not payment_ids:
        return

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COALESCE(MAX(credit_group), 0) + 1 FROM payments")
    new_group = cur.fetchone()[0]

    for pid in payment_ids:
        cur.execute(
            """
            UPDATE payments
            SET credit_group = %s, is_credit = 1
            WHERE user_id = %s AND id = %s
            """,
            (new_group, user_id, pid)
        )

    conn.commit()
    conn.close()

# -------------------- Update Payment --------------------
def update_payment(
    user_id: int,
    payment_id: int,
    description: str,
    amount: float,
    due_date: str,
    category_id=None
):
    from datetime import datetime

    d = datetime.fromisoformat(due_date)

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE payments
        SET description = %s,
            amount = %s,
            due_date = %s,
            month = %s,
            year = %s,
            category_id = %s
        WHERE user_id = %s
          AND id = %s
        """,
        (
            description,
            amount,
            due_date,
            d.month,
            d.year,
            category_id,
            user_id,
            payment_id
        )
    )

    conn.commit()
    conn.close()

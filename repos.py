from database import get_connection
from datetime import datetime

# ================= DEFAULT CATEGORIES =================
DEFAULT_CATEGORIES = [
    "Aluguel",
    "Condomínio",
    "Água",
    "Luz",
    "Internet",
    "Plano celular",
    "Mercado",
    "Cartão de crédito",
    "Outros"
]

# ================= CATEGORIES =================
def seed_default_categories(user_id):
    conn = get_connection()
    cur = conn.cursor()

    for name in DEFAULT_CATEGORIES:
        cur.execute(
            """INSERT INTO categories (user_id, name, created_at)
               VALUES (%s, %s, %s)
               ON CONFLICT (user_id, name) DO NOTHING""" ,
            (user_id, name, datetime.now())
        )

    conn.commit()
    cur.close()
    conn.close()


def list_categories(user_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, name FROM categories WHERE user_id = %s ORDER BY name",
        (user_id,)
    )

    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def create_category(user_id, name):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO categories (user_id, name, created_at) VALUES (%s, %s, %s)",
        (user_id, name, datetime.now())
    )

    conn.commit()
    cur.close()
    conn.close()


def delete_category(user_id, category_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM categories WHERE id = %s AND user_id = %s",
        (category_id, user_id)
    )

    conn.commit()
    cur.close()
    conn.close()

# ================= PAYMENTS =================
def add_payment(
    user_id,
    description,
    amount,
    due_date,
    month,
    year,
    category_id=None,
    is_credit=False,
    installments=1
):
    conn = get_connection()
    cur = conn.cursor()

    amount = float(amount)
    installments = int(installments)

    credit_group = int(datetime.now().timestamp())
    parcel_value = round(amount / installments, 2)

    base_date = datetime.fromisoformat(str(due_date))

    for i in range(installments):
        parcel_month = month + i
        parcel_year = year

        while parcel_month > 12:
            parcel_month -= 12
            parcel_year += 1

        parcel_due = base_date.replace(month=parcel_month, year=parcel_year)

        cur.execute(
            """INSERT INTO payments (
                user_id,
                description,
                category_id,
                amount,
                due_date,
                month,
                year,
                paid,
                paid_date,
                created_at,
                is_credit,
                installments,
                installment_index,
                credit_group
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s,%s,%s,%s)""" ,
            (
                user_id,
                f"{description} ({i+1}/{installments})" if installments > 1 else description,
                category_id,
                parcel_value,
                parcel_due.date(),
                parcel_month,
                parcel_year,
                False,
                None,
                bool(is_credit),
                installments,
                i + 1,
                credit_group
            )
        )

    conn.commit()
    cur.close()
    conn.close()


def list_payments(user_id, month, year):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """SELECT p.id, p.description, p.amount, p.due_date, p.paid,
                  p.paid_date, p.category_id, c.name AS category,
                  p.is_credit, p.installments, p.installment_index, p.credit_group
           FROM payments p
           LEFT JOIN categories c ON c.id = p.category_id
           WHERE p.user_id = %s AND p.month = %s AND p.year = %s
           ORDER BY p.due_date""" ,
        (user_id, month, year)
    )

    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def mark_paid(user_id, payment_id, paid):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "UPDATE payments SET paid = %s, paid_date = %s WHERE id = %s AND user_id = %s",
        (bool(paid), datetime.now() if paid else None, payment_id, user_id)
    )

    conn.commit()
    cur.close()
    conn.close()


def update_payment(user_id, payment_id, description, amount, due_date, category_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """UPDATE payments
              SET description = %s,
                  amount = %s,
                  due_date = %s,
                  category_id = %s
            WHERE id = %s AND user_id = %s""" ,
        (description, amount, due_date, category_id, payment_id, user_id)
    )

    conn.commit()
    cur.close()
    conn.close()


def delete_payment(user_id, payment_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM payments WHERE id = %s AND user_id = %s",
        (payment_id, user_id)
    )

    conn.commit()
    cur.close()
    conn.close()

# ================= BUDGET =================
def get_budget(user_id, month, year):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT income, expense_goal FROM budgets WHERE user_id = %s AND month = %s AND year = %s",
        (user_id, month, year)
    )

    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return {"income": 0.0, "expense_goal": 0.0}

    return {
        "income": float(row["income"]),
        "expense_goal": float(row["expense_goal"])
    }


def upsert_budget(user_id, month, year, income, expense_goal):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """INSERT INTO budgets (user_id, month, year, income, expense_goal, created_at)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (user_id, month, year)
           DO UPDATE SET income = %s, expense_goal = %s""" ,
        (user_id, month, year, income, expense_goal, datetime.now(), income, expense_goal)
    )

    conn.commit()
    cur.close()
    conn.close()

# ================= FATURA DO CARTÃO =================
def _get_card_category_ids(conn, user_id):
    cur = conn.cursor()
    cur.execute(
        """SELECT id
           FROM categories
           WHERE user_id = %s
             AND LOWER(name) LIKE %s""" ,
        (user_id, '%cart%')
    )

    rows = cur.fetchall()
    cur.close()

    return [r["id"] for r in rows]


def mark_credit_invoice_paid(user_id, month, year):
    conn = get_connection()
    conn.autocommit = False

    try:
        card_ids = _get_card_category_ids(conn, user_id)
        if not card_ids:
            conn.commit()
            return

        cur = conn.cursor()
        cur.execute(
            """UPDATE payments
                   SET paid = TRUE,
                       paid_date = CURRENT_DATE
                 WHERE user_id = %s
                   AND month = %s
                   AND year = %s
                   AND category_id = ANY(%s)
                   AND paid = FALSE""" ,
            (user_id, month, year, card_ids)
        )

        cur.close()
        conn.commit()
    finally:
        conn.close()


def unmark_credit_invoice_paid(user_id, month, year):
    conn = get_connection()
    conn.autocommit = False

    try:
        card_ids = _get_card_category_ids(conn, user_id)
        if not card_ids:
            conn.commit()
            return

        cur = conn.cursor()
        cur.execute(
            """UPDATE payments
                   SET paid = FALSE,
                       paid_date = NULL
                 WHERE user_id = %s
                   AND month = %s
                   AND year = %s
                   AND category_id = ANY(%s)
                   AND paid = TRUE""" ,
            (user_id, month, year, card_ids)
        )

        cur.close()
        conn.commit()
    finally:
        conn.close()

# ================= EXCLUIR COMPRA PARCELADA =================
def delete_credit_group(user_id, credit_group, only_open=True):
    conn = get_connection()
    cur = conn.cursor()

    if only_open:
        cur.execute(
            """
            DELETE FROM payments
            WHERE user_id = %s
              AND credit_group = %s
              AND paid = FALSE
            """,
            (user_id, credit_group)
        )
    else:
        cur.execute(
            """
            DELETE FROM payments
            WHERE user_id = %s
              AND credit_group = %s
            """,
            (user_id, credit_group)
        )

    conn.commit()
    cur.close()
    conn.close()


import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL não definida")


def get_connection():
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        cursor_factory=RealDictCursor
    )


def init_db():
    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    # ---------- USERS ----------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        security_question TEXT NOT NULL,
        security_answer_hash TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL
    )
    """)
    # ---------- USERS ----------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        security_question TEXT NOT NULL,
        security_answer_hash TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL
    )
    """)

    # 🔥 NOVO: telegram_id
    cur.execute("""
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS telegram_id BIGINT
    """)

    # ---------- CATEGORIES ----------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL,
        UNIQUE(user_id, name)
    )
    """)

    # ---------- PAYMENTS ----------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        description TEXT NOT NULL,
        category_id INTEGER,
        amount NUMERIC(10,2) NOT NULL,

        purchase_date DATE,              -- ✅ NOVO (já no create)
        due_date DATE NOT NULL,

        month INTEGER NOT NULL,
        year INTEGER NOT NULL,
        paid BOOLEAN NOT NULL DEFAULT FALSE,
        paid_date DATE,
        created_at TIMESTAMP NOT NULL,
        is_credit BOOLEAN NOT NULL DEFAULT FALSE,
        installments INTEGER NOT NULL DEFAULT 1,
        installment_index INTEGER NOT NULL DEFAULT 1,
        credit_group INTEGER
    )
    """)

    ## ✅ NOVO: garante coluna telegram_id em users
    cur.execute("""
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS telegram_id BIGINT
    """)

    # ✅ NOVO: garante índice único
    cur.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS users_telegram_id_uq
    ON users (telegram_id)
    """)

    # ---------- BUDGETS ----------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS budgets (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        month INTEGER NOT NULL,
        year INTEGER NOT NULL,
        income NUMERIC(10,2) NOT NULL DEFAULT 0,
        expense_goal NUMERIC(10,2) NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL,
        UNIQUE(user_id, month, year)
    )
    """)

    conn.commit()
    cur.close()
    conn.close()

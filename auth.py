import bcrypt
import datetime
from database import get_connection


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def hash_text(text: str) -> str:
    return bcrypt.hashpw(text.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_text(text: str, hashed: str) -> bool:
    return bcrypt.checkpw(text.encode("utf-8"), hashed.encode("utf-8"))


# -------------------- CREATE USER --------------------
def create_user(username, password, security_question, security_answer):
    username = username.strip().lower()
    password = password or ""
    security_answer = security_answer or ""

    if not username or not password:
        raise ValueError("Usuário e senha são obrigatórios.")

    if len(password) < 4:
        raise ValueError("Senha muito curta (mínimo 4).")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO users
            (username, password_hash, security_question, security_answer_hash, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            username,
            hash_text(password),
            security_question.strip(),
            hash_text(security_answer.strip()),
            _now()
        )
    )

    conn.commit()
    conn.close()


# -------------------- AUTHENTICATE --------------------
def authenticate(username, password):
    username = username.strip().lower()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, password_hash FROM users WHERE username = ?",
        (username,)
    )
    row = cur.fetchone()
    conn.close()

    if row and verify_text(password, row[1]):
        return row[0]

    return None


# -------------------- SECURITY QUESTION --------------------
def get_security_question(username: str):
    username = (username or "").strip().lower()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT security_question FROM users WHERE username = ?",
        (username,)
    )
    row = cur.fetchone()
    conn.close()

    return row[0] if row else None


# -------------------- RESET PASSWORD --------------------
def reset_password(username: str, security_answer: str, new_password: str) -> bool:
    username = (username or "").strip().lower()
    security_answer = security_answer or ""

    if len(new_password) < 4:
        raise ValueError("Senha muito curta (mínimo 4).")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, security_answer_hash FROM users WHERE username = ?",
        (username,)
    )
    row = cur.fetchone()

    if not row:
        conn.close()
        return False

    user_id, answer_hash = row

    if not verify_text(security_answer.strip(), answer_hash):
        conn.close()
        return False

    cur.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (hash_text(new_password), user_id)
    )

    conn.commit()
    conn.close()
    return True

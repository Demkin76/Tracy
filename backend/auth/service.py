import hashlib
import hmac
import secrets
import sqlite3
import time
from uuid import uuid4

from fastapi import HTTPException

from backend.platform.service import record_event

ITERATIONS = 600_000


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password):
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${derived.hex()}"


def check_password(password, stored):
    try:
        method, rounds, salt, expected = stored.split("$")
        if method != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def public_user(row):
    return {key: row[key] for key in ("user_id", "email", "name", "created_at")}


class AuthService:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings

    def throttle(self, bucket, limit=12):
        now = int(time.time())
        with self.db.connect(write=True) as conn:
            conn.execute("DELETE FROM auth_attempts WHERE timestamp<?", (now - 900,))
            count = conn.execute("SELECT count(*) FROM auth_attempts WHERE bucket=?", (bucket,)).fetchone()[0]
            if count >= limit:
                raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
            conn.execute("INSERT INTO auth_attempts VALUES(?,?)", (bucket, now))

    def register(self, payload):
        password_hash = hash_password(payload.password)
        user_id = "usr_" + uuid4().hex
        try:
            with self.db.connect(write=True) as conn:
                conn.execute(
                    "INSERT INTO users(user_id,email,name,password_hash,created_at) VALUES(?,?,?,?,?)",
                    (user_id, payload.email, payload.name, password_hash, int(time.time())),
                )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "This email is already registered") from exc
        return self.get(user_id)

    def get(self, user_id):
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(401, "Sign in to continue")
        return public_user(row)

    def login(self, payload):
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE email=?", (payload.email,)).fetchone()
        # Equal-cost password derivation for an unknown account.
        stored = row["password_hash"] if row else f"pbkdf2_sha256${ITERATIONS}${'00' * 16}${'00' * 32}"
        if not check_password(payload.password, stored) or not row:
            raise HTTPException(401, "Incorrect email or password")
        return public_user(row)

    def session(self, user_id):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.db.connect(write=True) as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at<?", (int(time.time()),))
            conn.execute(
                "INSERT INTO sessions VALUES(?,?,?,?)",
                (token_hash(token), user_id, csrf, int(time.time()) + self.settings.session_seconds),
            )
            record_event(conn, user_id, "session_created", user_id)
        return token, csrf

    def authenticate(self, request, mutate=False):
        auth = request.headers.get("authorization", "")
        if auth:
            if not auth.startswith("Bearer "):
                raise HTTPException(401, "Invalid authorization")
            with self.db.connect() as conn:
                row = conn.execute(
                    "SELECT * FROM api_keys WHERE token_hash=? AND revoked_at IS NULL AND expires_at>?",
                    (token_hash(auth[7:]), int(time.time())),
                ).fetchone()
            if not row:
                raise HTTPException(401, "Invalid or expired personal API key")
            if mutate and row["scope"] == "read":
                raise HTTPException(403, "This API key has read-only access")
            with self.db.connect(write=True) as conn:
                conn.execute(
                    "UPDATE api_keys SET last_used_at=? WHERE key_id=?", (int(time.time()), row["key_id"])
                )
            return {**self.get(row["user_id"]), "api_scope": row["scope"]}
        token = request.cookies.get("tracy_session", "")
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE token_hash=? AND expires_at>?",
                (token_hash(token), int(time.time())),
            ).fetchone()
        if not row:
            raise HTTPException(401, "Sign in to continue")
        if mutate and not secrets.compare_digest(request.headers.get("x-csrf-token", ""), row["csrf_token"]):
            raise HTTPException(403, "Invalid CSRF token; reload the page")
        return {**self.get(row["user_id"]), "csrf_token": row["csrf_token"]}

    def logout(self, request):
        with self.db.connect(write=True) as conn:
            conn.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (token_hash(request.cookies.get("tracy_session", "")),),
            )

    def create_api_key(self, user_id, name, scope="manage"):
        token = "trc_" + secrets.token_urlsafe(32)
        key_id, now = "key_" + uuid4().hex, int(time.time())
        with self.db.connect(write=True) as conn:
            count = conn.execute(
                "SELECT count(*) FROM api_keys WHERE user_id=? AND revoked_at IS NULL AND expires_at>?",
                (user_id, now),
            ).fetchone()[0]
            if count >= 20:
                raise HTTPException(409, "Revoke an existing key before creating another")
            conn.execute(
                "INSERT INTO api_keys(key_id,token_hash,user_id,name,prefix,created_at,expires_at,revoked_at,scope) VALUES(?,?,?,?,?,?,?,NULL,?)",
                (key_id, token_hash(token), user_id, name, token[:12], now, now + 30 * 86400, scope),
            )
            record_event(conn, user_id, "api_key_created", key_id)
        return {
            "key_id": key_id,
            "token": token,
            "name": name,
            "scope": scope,
            "expires_at": now + 30 * 86400,
        }

    def list_keys(self, user_id):
        with self.db.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT key_id,name,prefix,created_at,expires_at,revoked_at,scope,last_used_at FROM api_keys WHERE user_id=? ORDER BY created_at DESC",
                    (user_id,),
                )
            ]

    def revoke(self, user_id, key_id):
        with self.db.connect(write=True) as conn:
            changed = conn.execute(
                "UPDATE api_keys SET revoked_at=? WHERE key_id=? AND user_id=?",
                (int(time.time()), key_id, user_id),
            ).rowcount
            if changed:
                record_event(conn, user_id, "api_key_revoked", key_id)
        if not changed:
            raise HTTPException(404, "API key not found")

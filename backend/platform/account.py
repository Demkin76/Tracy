import secrets
import time

from fastapi import HTTPException

from backend.auth.service import check_password, hash_password, token_hash
from backend.platform.service import record_event


class AccountService:
    def __init__(self, db, auth):
        self.db, self.auth = db, auth

    def require_password(self, user_id, password):
        with self.db.connect() as conn:
            row = conn.execute("SELECT password_hash FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row or not check_password(password, row["password_hash"]):
            raise HTTPException(401, "Current password is incorrect")

    def change_password(self, user_id, payload):
        self.require_password(user_id, payload.current_password)
        hashed = hash_password(payload.new_password)
        with self.db.connect(write=True) as conn:
            conn.execute("UPDATE users SET password_hash=? WHERE user_id=?", (hashed, user_id))
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            conn.execute(
                "UPDATE api_keys SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                (int(time.time()), user_id),
            )
            record_event(conn, user_id, "password_changed_all_access_revoked", user_id)

    def issue_recovery(self, user_id, password):
        self.require_password(user_id, password)
        code = "tracy_recovery_" + secrets.token_urlsafe(32)
        with self.db.connect(write=True) as conn:
            conn.execute("UPDATE users SET recovery_hash=? WHERE user_id=?", (token_hash(code), user_id))
            record_event(conn, user_id, "recovery_code_rotated", user_id)
        return {"recovery_code": code}

    def recover(self, payload):
        # Match and consume under a write lock so one code cannot reset twice concurrently.
        hashed_password = hash_password(payload.new_password)
        with self.db.connect(write=True) as conn:
            user = conn.execute(
                "SELECT user_id FROM users WHERE email=? AND recovery_hash=?",
                (payload.email, token_hash(payload.recovery_code)),
            ).fetchone()
            if not user:
                raise HTTPException(401, "Invalid email or recovery code")
            uid = user["user_id"]
            conn.execute(
                "UPDATE users SET password_hash=?,recovery_hash=NULL WHERE user_id=?", (hashed_password, uid)
            )
            conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            conn.execute(
                "UPDATE api_keys SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                (int(time.time()), uid),
            )
            record_event(conn, uid, "account_recovered_all_access_revoked", uid)
        return {"ok": True}

    def profile(self, user_id, payload):
        with self.db.connect(write=True) as conn:
            conn.execute("UPDATE users SET name=? WHERE user_id=?", (payload.name, user_id))
            record_event(conn, user_id, "profile_updated", user_id)
        return self.auth.get(user_id)

    def events(self, user_id, limit=50):
        with self.db.connect() as conn:
            return {
                "items": [
                    dict(r)
                    for r in conn.execute(
                        "SELECT event_id,kind,target,created_at FROM account_events WHERE user_id=? ORDER BY event_id DESC LIMIT ?",
                        (user_id, limit),
                    )
                ]
            }

"""Local devnet lab with a separate database and no real exchange execution."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn
from backend.auth.models import Signup
from backend.config import Settings
from backend.main import create_app


def build():
    settings = Settings(
        database_path=ROOT / "data/tracy-adaptive-devnet.sqlite3",
        environment="development",
        cookie_secure=False,
        allowed_hosts=["127.0.0.1", "localhost"],
        cors_origins=["http://127.0.0.1:8001", "http://localhost:8001"],
        devnet_enabled=False,
        adaptive_devnet_anchors_enabled=True,
        reconciler_enabled=True,
        signup_enabled=False,
    )
    app = create_app(settings)
    path = ROOT / "data/tracy-owner.json"
    if path.exists():
        credentials = json.loads(path.read_text())
        with app.state.db.connect() as conn:
            exists = conn.execute("SELECT 1 FROM users WHERE email=?", (credentials["email"],)).fetchone()
        if not exists:
            app.state.auth.register(
                Signup(
                    email=credentials["email"],
                    password=credentials["password"],
                    name=credentials.get("name", "Tracy owner"),
                )
            )
    return app


if __name__ == "__main__":
    uvicorn.run(build(), host="127.0.0.1", port=8001)

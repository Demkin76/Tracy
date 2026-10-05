"""Opt-in isolated production-container smoke test; needs a built image and local Docker."""

import base64
import json
import secrets
import subprocess
import tempfile
import time
from pathlib import Path

import httpx


def main():
    name = "tracy-smoke-" + secrets.token_hex(4)
    report = {"checks": []}
    started = False
    with tempfile.TemporaryDirectory(prefix="tracy-smoke-") as folder:
        env = Path(folder) / "container.env"
        password = secrets.token_urlsafe(24)
        values = {
            "POA_SIGNING_SEED": base64.b64encode(secrets.token_bytes(32)).decode(),
            "POA_EXECUTION_WALLET_SEED": base64.b64encode(secrets.token_bytes(32)).decode(),
            "POA_DATABASE_PATH": "/app/data/tracy.sqlite3",
            "POA_ENVIRONMENT": "production",
            "POA_COOKIE_SECURE": "true",
            "POA_DEVNET_ENABLED": "false",
            "POA_SIGNUP_ENABLED": "false",
            "POA_ALLOWED_HOSTS": '["127.0.0.1"]',
            "POA_CORS_ORIGINS": "[]",
            "TRACY_BOOTSTRAP_PASSWORD": password,
        }
        env.write_text("\n".join(f"{k}={v}" for k, v in values.items()))
        env.chmod(0o600)
        try:
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-d",
                    "--name",
                    name,
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges:true",
                    "--tmpfs",
                    "/tmp",
                    "--tmpfs",
                    "/app/data:uid=10001,gid=10001,mode=0700",
                    "--env-file",
                    str(env),
                    "-p",
                    "127.0.0.1:8002:8000",
                    "tracy:mvp-local",
                ],
                check=True,
                capture_output=True,
            )
            started = True
            with httpx.Client(base_url="http://127.0.0.1:8002", timeout=3) as client:
                for attempt in range(30):
                    try:
                        if client.get("/readyz").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(1)
                else:
                    raise RuntimeError("Container did not become ready")
                assert client.get("/healthz").status_code == 200
                assert client.get("/").status_code == 200
                assert client.get("/docs").status_code == 200
                assert client.get("/openapi.json").status_code == 200
                assert client.get("/healthz", headers={"Host": "evil.invalid"}).status_code == 400
                report["checks"].append(
                    "Non-root, read-only production image starts; readiness, frontend, docs, schema and allowed hosts pass"
                )
                assert (
                    client.post(
                        "/v1/auth/signup", json={"email": "x@example.com", "name": "X", "password": password}
                    ).status_code
                    == 403
                )
                created = subprocess.run(
                    [
                        "docker",
                        "exec",
                        name,
                        "/app/.venv/bin/python",
                        "-m",
                        "scripts.create_owner",
                        "--email",
                        "smoke@example.com",
                    ],
                    check=True,
                    capture_output=True,
                )
                assert b"Created owner account" in created.stdout
                result = client.post(
                    "/v1/auth/login", json={"email": "smoke@example.com", "password": password}
                )
                assert result.status_code == 200
                assert "secure" in result.headers["set-cookie"].lower()
                assert "httponly" in result.headers["set-cookie"].lower()
                assert result.headers["strict-transport-security"] == "max-age=31536000"
                # This local smoke endpoint uses HTTP; explicitly forward the secure cookie only to localhost.
                cookie = result.headers["set-cookie"].split(";", 1)[0]
                auth = {"Cookie": cookie}
                for route in ("agents", "strategies", "strategy-tests", "trading/queue"):
                    response = client.get("/v1/" + route, headers=auth)
                    assert response.status_code == 200 and response.json()["items"] == []
                report["checks"].append(
                    "Closed signup, operator account bootstrap, secure login and empty unseeded workspace pass"
                )
                image = subprocess.run(
                    ["docker", "image", "inspect", "tracy:mvp-local", "--format", "{{.Id}}"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                report.update(
                    passed=True,
                    image=image.stdout.strip(),
                    note="Local HTTP smoke only; public DNS/TLS remains unverified",
                )
                Path("data").mkdir(exist_ok=True)
                Path("data/container-smoke.json").write_text(json.dumps(report, indent=2))
                print(json.dumps(report))
        finally:
            if started:
                subprocess.run(["docker", "stop", "--time", "10", name], check=True, capture_output=True)


if __name__ == "__main__":
    main()

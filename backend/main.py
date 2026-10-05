import asyncio
import contextlib
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.actions.models import ActionRequest
from backend.actions.service import ActionService
from backend.agents.models import AgentProfile, AgentStatus, RegisterAgent, UpdatePolicy
from backend.agents.service import AgentService
from backend.auth.models import CreateApiKey, Login, Signup
from backend.auth.service import AuthService
from backend.blockchain.solana import SolanaGateway
from backend.config import Settings
from backend.control.routes import control_router
from backend.control.service import ControlService
from backend.crypto.signatures import private_key
from backend.database.db import Database, unpack_action
from backend.marketplace.routes import marketplace_router
from backend.marketplace.service import Marketplace
from backend.platform.routes import platform_router
from backend.platform.runtime import Reconciler, SingleWorkerLock
from backend.receipts.models import VerificationResult
from backend.receipts.service import ReceiptService
from backend.receipts.verifier import ReceiptVerifier
from backend.strategies.routes import strategy_router
from backend.strategies.service import StrategyService


def create_app(settings: Settings | None = None, gateway=None):
    settings = settings or Settings()
    db = Database(settings.database_path)
    gateway = gateway or SolanaGateway(settings)
    receipts = ReceiptService(db, private_key(settings.signing_seed.get_secret_value()))
    db.initialize(receipts.public_key, gateway.sender)
    agents = AgentService(db)
    actions = ActionService(settings, db, agents, receipts, gateway)
    verifier = ReceiptVerifier(db, receipts, gateway)
    auth = AuthService(db, settings)
    runtime = Reconciler(db, actions, settings.reconciliation_interval_seconds)
    marketplace = Marketplace(db, agents, actions, settings)
    runtime.marketplace = marketplace
    control = ControlService(db, agents, actions, receipts, settings)
    runtime.control = control
    strategies = StrategyService(db, agents, control, receipts, settings)
    control.trading = strategies.trading
    runtime.trading = strategies.trading
    runtime_lock = SingleWorkerLock(settings.database_path)
    inflight = set()

    @asynccontextmanager
    async def lifespan(app):
        if settings.reconciler_enabled:
            runtime_lock.acquire()
        try:
            actions.recover_unsubmitted()
            if settings.reconciler_enabled:
                runtime.start()
            yield
        finally:
            await runtime.stop()
            if inflight:
                done, pending = await asyncio.wait(inflight, timeout=30)
                for task in pending:
                    task.cancel()
                for task in pending:
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
            await gateway.close()
            runtime_lock.release()

    app = FastAPI(title="Tracy", version="3.0.0", lifespan=lifespan)
    app.state.db, app.state.actions, app.state.auth = db, actions, auth
    app.state.runtime = runtime
    app.state.marketplace = marketplace
    app.state.control = control
    app.state.strategies = strategies
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
    )

    @app.middleware("http")
    async def request_security(request, call_next):
        try:
            length = int(request.headers.get("content-length", "0") or "0")
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})
        if length > 262144:
            return JSONResponse(status_code=413, content={"detail": "Request body exceeds 256 KiB"})
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            same_origin = str(request.base_url).rstrip("/")
            if origin and origin not in [same_origin, *settings.cors_origins]:
                return JSONResponse(status_code=403, content={"detail": "Origin not allowed"})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.url.path.startswith("/docs"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; frame-ancestors 'none'"
            )
        if settings.cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.url.path.startswith("/v1/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def owner(request: Request):
        return auth.authenticate(request, mutate=request.method not in ("GET", "HEAD", "OPTIONS"))

    def session_response(user, response):
        token, csrf = auth.session(user["user_id"])
        response.set_cookie(
            "tracy_session",
            token,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="strict",
            max_age=settings.session_seconds,
            path="/",
        )
        return {"user": user, "csrf_token": csrf}

    @app.post("/v1/auth/signup", status_code=201)
    def signup(payload: Signup, request: Request, response: Response):
        auth.throttle("signup:" + (request.client.host if request.client else "unknown"), 30)
        return session_response(auth.register(payload), response)

    @app.post("/v1/auth/login")
    def login(payload: Login, request: Request, response: Response):
        auth.throttle("login-email:" + payload.email, 12)
        auth.throttle("login-ip:" + (request.client.host if request.client else "unknown"), 60)
        return session_response(auth.login(payload), response)

    @app.get("/v1/auth/me")
    def me(user=Depends(owner)):
        return {
            "user": {k: v for k, v in user.items() if k != "csrf_token"},
            "csrf_token": user.get("csrf_token"),
        }

    @app.post("/v1/auth/logout")
    def logout(request: Request, response: Response, user=Depends(owner)):
        auth.logout(request)
        response.delete_cookie(
            "tracy_session", path="/", httponly=True, samesite="strict", secure=settings.cookie_secure
        )
        return {"ok": True}

    @app.get("/v1/account/api-keys")
    def api_keys(user=Depends(owner)):
        return {"items": auth.list_keys(user["user_id"])}

    @app.post("/v1/account/api-keys", status_code=201)
    def create_key(payload: CreateApiKey, user=Depends(owner)):
        return auth.create_api_key(user["user_id"], payload.name, payload.scope)

    @app.delete("/v1/account/api-keys/{key_id}")
    def revoke_key(key_id: str, user=Depends(owner)):
        auth.revoke(user["user_id"], key_id)
        return {"ok": True}

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        db.audit("invalid_json_or_schema")
        errors = [
            {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]} for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.get("/v1/config")
    def config():
        return {
            "product": "Tracy",
            "version": "3.0.0",
            "network": "solana-devnet",
            "execution_wallet": gateway.sender,
            "poa_public_key": receipts.public_key,
            "canonicalization": "RFC8785",
            "signature_encoding": "base64",
            "receipt_signature_input": "SHA-256 raw digest bytes",
        }

    @app.get("/v1/health")
    async def health():
        try:
            rpc = await gateway.health()
        except Exception:
            rpc = {"rpc_available": False, "balance_lamports": None}
        return {"status": "ok" if rpc["rpc_available"] else "degraded", "network": "solana-devnet", **rpc}

    @app.post("/v1/agents", status_code=201)
    def register(payload: RegisterAgent, user=Depends(owner)):
        return agents.register(payload, user["user_id"])

    @app.get("/v1/agents")
    def list_agents(user=Depends(owner)):
        return {"items": agents.list(user["user_id"])}

    @app.get("/v1/agents/{agent_id}")
    def get_agent(agent_id: str, user=Depends(owner)):
        return agents.get(agent_id, user["user_id"])

    @app.patch("/v1/agents/{agent_id}")
    def edit_agent(agent_id: str, payload: AgentProfile, user=Depends(owner)):
        return agents.profile(agent_id, user["user_id"], payload)

    @app.post("/v1/agents/{agent_id}/status")
    def agent_status(agent_id: str, payload: AgentStatus, user=Depends(owner)):
        return agents.status(agent_id, user["user_id"], payload.active)

    @app.put("/v1/agents/{agent_id}/policy")
    def edit_policy(agent_id: str, payload: UpdatePolicy, user=Depends(owner)):
        return agents.update_policy(agent_id, user["user_id"], payload)

    @app.get("/v1/agents/{agent_id}/policy/versions")
    def versions(agent_id: str, user=Depends(owner)):
        return {"items": agents.versions(agent_id, user["user_id"])}

    @app.get("/v1/agents/{agent_id}/actions")
    def history(
        agent_id: str,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        user=Depends(owner),
    ):
        agents.get(agent_id, user["user_id"])
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM actions WHERE agent_id=? ORDER BY created_at DESC,rowid DESC LIMIT ? OFFSET ?",
                (agent_id, limit, offset),
            ).fetchall()
            total = conn.execute("SELECT count(*) FROM actions WHERE agent_id=?", (agent_id,)).fetchone()[0]
            counts = dict(
                conn.execute(
                    "SELECT status,count(*) FROM actions WHERE agent_id=? GROUP BY status", (agent_id,)
                ).fetchall()
            )
        return {"items": [unpack_action(row) for row in rows], "total": total, "counts": counts}

    @app.get("/v1/agents/{agent_id}/requests/{request_id}")
    def get_request(agent_id: str, request_id: str, user=Depends(owner)):
        agents.get(agent_id, user["user_id"])
        with db.connect() as conn:
            row = conn.execute(
                "SELECT action_id FROM actions WHERE agent_id=? AND request_id=?", (agent_id, request_id)
            ).fetchone()
        if not row:
            raise HTTPException(404, "Request not found")
        return actions.get(row["action_id"])

    @app.post("/v1/actions")
    async def submit(payload: ActionRequest):
        # Ed25519 request authentication is independent of the owner's browser session.
        task = asyncio.create_task(actions.submit(payload))
        inflight.add(task)
        task.add_done_callback(inflight.discard)
        result = await asyncio.shield(task)
        return JSONResponse(status_code=202 if result["status"] == "PENDING" else 201, content=result)

    def owned_action(action_id, user):
        action = actions.get(action_id)
        agents.get(action["agent_id"], user["user_id"])
        return action

    def owned_receipt(receipt_id, user):
        receipt = receipts.get(receipt_id)
        agents.get(receipt["agent_id"], user["user_id"])
        return receipt

    @app.get("/v1/actions/{action_id}")
    def get_action(action_id: str, user=Depends(owner)):
        return owned_action(action_id, user)

    @app.post("/v1/actions/{action_id}/reconcile")
    async def reconcile(action_id: str, user=Depends(owner)):
        owned_action(action_id, user)
        return await actions.reconcile(action_id)

    @app.get("/v1/receipts/{receipt_id}")
    def get_receipt(receipt_id: str, user=Depends(owner)):
        return owned_receipt(receipt_id, user)

    @app.get("/v1/receipts/{receipt_id}/verify", response_model=VerificationResult)
    async def verify_receipt(receipt_id: str, user=Depends(owner)):
        owned_receipt(receipt_id, user)
        return await verifier.verify(receipt_id)

    @app.get("/v1/receipts/{receipt_id}/chain")
    def receipt_chain(receipt_id: str, user=Depends(owner)):
        receipt = owned_receipt(receipt_id, user)
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT body FROM receipts WHERE agent_id=? AND sequence<=? ORDER BY sequence",
                (receipt["agent_id"], receipt["sequence"]),
            ).fetchall()
        return {"items": [json.loads(row["body"]) for row in rows]}

    app.include_router(
        platform_router(db, agents, receipts, verifier, auth, owner, owner, settings, runtime, gateway)
    )

    app.include_router(marketplace_router(marketplace, owner))
    app.include_router(control_router(control, owner))
    app.include_router(strategy_router(strategies, owner))

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        with db.connect() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "product": "Tracy"}

    dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            if path.startswith(("v1/", "v2/")):
                raise HTTPException(404, "Endpoint not found")
            return FileResponse(dist / "index.html")

    return app

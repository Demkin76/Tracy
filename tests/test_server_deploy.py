from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.main import create_app
from deploy.server.app import OriginGate


def test_frontend_mode_never_initializes_wallet_or_database(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError('Frontend must not initialize backend state')
    monkeypatch.setattr('backend.main.Database', unexpected)
    monkeypatch.setattr('backend.main.SolanaGateway', unexpected)
    app = create_app(SimpleNamespace(frontend_only=True, allowed_hosts=['testserver']))
    with TestClient(app) as client:
        assert client.get('/readyz').json()['mode'] == 'frontend_only'
        assert client.get('/lab').status_code == 200
        assert client.get('/v1/adaptive/agents').status_code == 503
        assert client.post('/v1/auth/login', json={}).status_code == 503


def test_origin_gate_requires_exactly_one_correct_token():
    app = FastAPI()
    @app.get('/probe')
    def probe():
        return {'ok': True}
    token = 's' * 40
    with TestClient(OriginGate(app, token)) as client:
        assert client.get('/probe').status_code == 403
        assert client.get('/probe', headers={'X-Tracy-Origin-Token': 'wrong'}).status_code == 403
        assert client.get('/probe', headers=[('X-Tracy-Origin-Token', token), ('X-Tracy-Origin-Token', token)]).status_code == 403
        assert client.get('/probe', headers={'X-Tracy-Origin-Token': token}).json() == {'ok': True}

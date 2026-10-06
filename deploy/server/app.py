"""Require the private edge credential before any request reaches the backend."""

import secrets

from starlette.responses import JSONResponse

from backend.config import Settings
from backend.main import create_app as build


class OriginGate:
    def __init__(self, app, token):
        self.app, self.token = app, token.encode()

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            tokens = [v for k, v in scope['headers'] if k.lower() == b'x-tracy-origin-token']
            if len(tokens) != 1 or not secrets.compare_digest(tokens[0], self.token):
                return await JSONResponse({'detail': 'Origin access denied'}, status_code=403)(scope, receive, send)
        return await self.app(scope, receive, send)


def create_app():
    settings = Settings()
    token = settings.origin_proxy_token.get_secret_value() if settings.origin_proxy_token else ''
    if len(token) < 32 or settings.frontend_only:
        raise RuntimeError('Backend requires a private origin token and full API mode')
    return OriginGate(build(settings), token)

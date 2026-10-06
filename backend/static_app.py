"""Frontend-only Daytona process: no database, wallet, API or background worker."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware


def create_static_app(settings):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    dist = Path(__file__).resolve().parents[1] / 'frontend/dist'
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    @app.middleware('http')
    async def security(request, call_next):
        response = await call_next(request)
        response.headers.update({
            'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
            'Referrer-Policy': 'same-origin', 'Cache-Control': 'no-store',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        })
        return response

    @app.get('/readyz')
    @app.get('/healthz')
    def ready():
        return {'ready': (dist / 'index.html').is_file(), 'mode': 'frontend_only'}

    @app.api_route('/v1/{path:path}', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD'])
    def no_api(path):
        raise HTTPException(503, 'API is hosted on the separate Tracy backend')

    app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')

    @app.get('/{path:path}')
    def page(path):
        return FileResponse(dist / 'index.html')

    return app

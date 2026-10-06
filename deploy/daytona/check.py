"""Check the deployed private preview without exposing its authentication token."""

import json
import os
import re
import sys
import time
from pathlib import Path

import certifi
import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / 'data/daytona-production'


def main():
    os.environ.setdefault('SSL_CERT_FILE', certifi.where())
    from daytona import Daytona, DaytonaConfig

    values = dotenv_values(ROOT / '.env')
    client = Daytona(DaytonaConfig(api_key=values['DAYTONA_API_KEY'],
                                  target=values.get('DAYTONA_TARGET', 'eu')))
    sandbox = client.get('tracy-production')
    preview = sandbox.get_preview_link(8000)
    edge = {'DAYTONA_ORIGIN': preview.url.rstrip('/'), 'DAYTONA_PREVIEW_TOKEN': preview.token}
    path = PRIVATE / 'edge-secrets.json'
    path.write_text(json.dumps(edge))
    path.chmod(0o600)
    headers = {'X-Daytona-Preview-Token': preview.token,
               'X-Daytona-Skip-Preview-Warning': 'true', 'X-Daytona-Disable-CORS': 'true',
               'Origin': 'https://tracys.online'}
    results = {'sandbox_id': sandbox.id, 'auto_stop': sandbox.auto_stop_interval,
               'auto_delete': sandbox.auto_delete_interval, 'public': sandbox.public}
    assert sandbox.auto_stop_interval == 0 and sandbox.auto_delete_interval == -1 and not sandbox.public
    owner = json.loads((PRIVATE / 'owner.json').read_text())
    with httpx.Client(base_url=edge['DAYTONA_ORIGIN'], headers=headers, timeout=60) as browser:
        for _ in range(20):
            response = browser.get('/readyz')
            if response.status_code == 200:
                break
            time.sleep(2)
        assert response.status_code == 200, f'Readiness HTTP {response.status_code}'
        print('Readiness passed.', flush=True)
        results['ready'] = response.json()
        for route in ('/', '/developers', '/help/leaderboard', '/agents/new'):
            page = browser.get(route)
            assert page.status_code == 200 and 'text/html' in page.headers['content-type']
        for asset in re.findall(r'(?:src|href)="(/assets/[^\"]+)"', page.text):
            assert browser.get(asset).status_code == 200
        results['frontend'] = 'passed'
        assert browser.get('/v1/auth/me').status_code == 401
        public = browser.get('/v1/public/trading/strategies')
        assert public.status_code == 200
        response = browser.post('/v1/auth/login', json={k: owner[k] for k in ('email', 'password')})
        assert response.status_code == 200, f'Login HTTP {response.status_code}'
        cookie = response.headers['set-cookie'].lower()
        assert 'secure' in cookie and 'httponly' in cookie and 'samesite=strict' in cookie
        csrf = response.json()['csrf_token']
        assert browser.get('/v1/auth/me').status_code == 200
        assert browser.post('/v1/auth/logout').status_code == 403
        browser.headers['X-CSRF-Token'] = csrf
        assert browser.get('/v1/strategies').json()['items'] == []
        results['auth_and_csrf'] = 'passed'
        print('Frontend, owner login, secure cookies, CSRF and empty strategy list passed.', flush=True)
        results['copilot_status'] = browser.get('/v1/copilot/status').json()
        if '--skip-ai' not in sys.argv:
            response = browser.post('/v1/copilot/message', json={
                'message': 'Кратко объясни, отправляет ли paper replay реальные ордера?',
                'page': '/help/replay', 'use_ai': True,
            })
            results['copilot_http'] = response.status_code
            if response.status_code == 200:
                assert response.json()['mode'] == 'ai'
                results['copilot'] = 'AI response received'
            else:
                results['copilot'] = response.json().get('detail')
        assert browser.post('/v1/auth/logout').status_code == 200
        assert browser.get('/v1/auth/me').status_code == 401
    filename = 'checks-without-ai.json' if '--skip-ai' in sys.argv else 'checks.json'
    (PRIVATE / filename).write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()

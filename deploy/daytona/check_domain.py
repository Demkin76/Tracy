"""Verify the public domain as an ordinary visitor, without Daytona credentials."""

import json
import re
import socket
import ssl
from pathlib import Path

import certifi
import httpx

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / 'data/daytona-production'
BASE = 'https://tracys.online'


def main():
    evidence = {}
    context = ssl.create_default_context(cafile=certifi.where())
    with socket.create_connection(('tracys.online', 443), timeout=15) as raw:
        with context.wrap_socket(raw, server_hostname='tracys.online') as connection:
            certificate = connection.getpeercert()
            evidence['tls'] = {'version': connection.version(),
                               'names': certificate.get('subjectAltName'),
                               'expires': certificate.get('notAfter')}
    print('TLS certificate and hostname validated.', flush=True)
    owner = json.loads((PRIVATE / 'owner.json').read_text())
    preview_token = json.loads((PRIVATE / 'edge-secrets.json').read_text())['DAYTONA_PREVIEW_TOKEN']
    with httpx.Client(base_url=BASE, timeout=35, follow_redirects=False) as client:
        response = client.get('http://tracys.online/help/leaderboard?check=1')
        assert response.status_code in (301, 308)
        assert response.headers['location'] == BASE + '/help/leaderboard?check=1'
        evidence['http_redirect'] = response.status_code
        response = client.get('/readyz')
        assert response.status_code == 200, f'Readiness HTTP {response.status_code}'
        assert response.json()['ready']
        evidence['ready'] = response.json()
        for route in ('/', '/leaderboard', '/developers', '/help/leaderboard', '/agents/new',
                      '/lab', '/bundles', '/help/adaptive'):
            response = client.get(route)
            assert response.status_code == 200 and 'text/html' in response.headers['content-type']
            assert preview_token not in response.text
            assert not any(k.lower().startswith('x-daytona-') for k in response.headers)
            assert 'no-store' in response.headers.get('cache-control', '')
            assert 'max-age=' in response.headers.get('strict-transport-security', '')
        for asset in re.findall(r'(?:src|href)="(/assets/[^\"]+)"', response.text):
            assert client.get(asset).status_code == 200
        evidence['frontend'] = 'passed'
        assert client.get('/v1/auth/me').status_code == 401
        assert client.get('/v1/strategies').status_code == 401
        assert client.get('/v1/adaptive/agents').status_code == 401
        capabilities = client.get('/v1/adaptive/capabilities')
        assert capabilities.status_code == 200
        assert capabilities.json()['execution'] == 'paper'
        assert capabilities.json()['mainnet_enabled'] is False
        assert client.get('/v1/public/bundles').status_code == 200
        assert client.get('/v1/public/trading/strategies').status_code == 200
        client.headers['Origin'] = BASE
        response = client.post('/v1/auth/login', json={k: owner[k] for k in ('email', 'password')})
        assert response.status_code == 200, f'Login HTTP {response.status_code}'
        cookie = response.headers['set-cookie'].lower()
        assert all(s in cookie for s in ('secure', 'httponly', 'samesite=strict'))
        csrf = response.json()['csrf_token']
        assert client.get('/v1/auth/me').status_code == 200
        assert client.post('/v1/auth/logout').status_code == 403
        client.headers['X-CSRF-Token'] = csrf
        assert client.post('/v1/auth/logout', headers={'Origin': 'https://example.com'}).status_code == 403
        assert client.post('/v1/auth/logout').status_code == 200
        assert client.get('/v1/auth/me').status_code == 401
        evidence['authentication_csrf_and_origin'] = 'passed'
    (PRIVATE / 'domain-checks.json').write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()

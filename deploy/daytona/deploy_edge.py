"""Publish the fixed Daytona proxy and attach tracys.online using Cloudflare's API."""

import json
import os
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / 'data/daytona-production'
HOST = 'tracys.online'
WORKER = 'tracy-domain'


def main():
    os.umask(0o077)
    config = dotenv_values(ROOT / '.env')
    aws_path = ROOT / 'data/aws-deployment/routing.json'
    aws = json.loads(aws_path.read_text()) if aws_path.exists() else {}
    edge = {} if aws.get('enabled') else json.loads((PRIVATE / 'edge-secrets.json').read_text())
    account = config['CLOUDFLARE_ACCOUNT_ID']
    with httpx.Client(timeout=30, follow_redirects=False) as probe:
        origin = aws['origin'] if aws.get('enabled') else edge['DAYTONA_ORIGIN']
        headers = {'X-Tracy-Origin-Token': aws['token']} if aws.get('enabled') else {
            'X-Daytona-Preview-Token': edge['DAYTONA_PREVIEW_TOKEN'],
            'X-Daytona-Skip-Preview-Warning': 'true',
        }
        response = probe.get(origin + '/readyz', headers=headers)
        assert response.status_code == 200 and response.json()['ready'], 'Selected origin is not ready'
    with httpx.Client(base_url='https://api.cloudflare.com/client/v4', timeout=60,
                      headers={'Authorization': 'Bearer ' + config['CLOUDFLARE_API_TOKEN']}) as client:
        def call(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            data = response.json()
            if not response.is_success or not data.get('success'):
                errors = [{'code': e.get('code'), 'message': e.get('message')}
                          for e in data.get('errors', [])]
                message = f'Cloudflare {method} {path}: HTTP {response.status_code}: {errors}'
                for secret in (config['CLOUDFLARE_API_TOKEN'], edge.get('DAYTONA_PREVIEW_TOKEN'), aws.get('token')):
                    if secret:
                        message = message.replace(secret, '[redacted]')
                raise RuntimeError(message)
            return data.get('result')

        zones = call('GET', '/zones', params={'name': HOST})
        assert len(zones) == 1 and zones[0]['status'] == 'active'
        assert zones[0]['account']['id'] == account
        zone = zones[0]['id']
        domains = call('GET', f'/accounts/{account}/workers/domains')
        bound = [d for d in domains if d['hostname'] == HOST]
        assert not bound or all(d['service'] == WORKER for d in bound), 'Domain belongs to another Worker'
        records = call('GET', f'/zones/{zone}/dns_records', params={'name': HOST})
        backup = PRIVATE / 'cloudflare-dns-before.json'
        if not backup.exists():
            backup.write_text(json.dumps({'zone_id': zone, 'records': records, 'domains': domains}, indent=2))
        metadata = {
            'main_module': 'edge.mjs', 'compatibility_date': '2026-10-05',
            'bindings': ([
                {'name': 'AWS_ORIGIN', 'type': 'plain_text', 'text': aws['origin']},
                {'name': 'AWS_ORIGIN_TOKEN', 'type': 'secret_text', 'text': aws['token']},
            ] if aws.get('enabled') else [
                {'name': 'DAYTONA_ORIGIN', 'type': 'plain_text', 'text': edge['DAYTONA_ORIGIN']},
                {'name': 'DAYTONA_PREVIEW_TOKEN', 'type': 'secret_text', 'text': edge['DAYTONA_PREVIEW_TOKEN']},
            ]),
        }
        if aws:
            assert aws['origin'] == 'https://aws-origin.tracys.online'
            metadata['bindings'].append({'name': 'API_MAINTENANCE', 'type': 'plain_text',
                                         'text': str(aws.get('maintenance', False)).lower()})
        routing_path = ROOT / 'data/server-deployment/routing.json'
        if routing_path.exists():
            routing = json.loads(routing_path.read_text())
            metadata['bindings'].append({'name': 'API_MAINTENANCE', 'type': 'plain_text',
                                         'text': str(routing.get('maintenance', False)).lower()})
            if routing.get('enabled'):
                assert routing['origin'] == 'https://api-origin.tracys.online'
                metadata['bindings'].extend([
                    {'name': 'API_ORIGIN', 'type': 'plain_text', 'text': routing['origin']},
                    {'name': 'API_ORIGIN_TOKEN', 'type': 'secret_text', 'text': routing['token']},
                ])
        result = call('PUT', f'/accounts/{account}/workers/scripts/{WORKER}', files={
            'metadata': (None, json.dumps(metadata), 'application/json'),
            'edge.mjs': ('edge.mjs', (ROOT / 'deploy/daytona/edge.mjs').read_bytes(), 'application/javascript+module'),
        })
        print('Worker deployed:', result.get('id', WORKER), flush=True)
        call('POST', f'/accounts/{account}/workers/scripts/{WORKER}/subdomain',
             json={'enabled': False, 'previews_enabled': False})
        # Cloudflare refuses custom domains while external apex A/CNAME records exist.
        # Replace only the two parking addresses inspected before this deployment.
        removed = []
        if not bound:
            conflicts = [r for r in records if r['type'] in ('A', 'AAAA', 'CNAME')]
            assert all(r['type'] == 'A' and r['content'] in ('15.197.148.33', '3.33.130.190')
                       for r in conflicts), 'Unexpected origin record; refusing automatic replacement'
            for record in conflicts:
                call('DELETE', f"/zones/{zone}/dns_records/{record['id']}")
                removed.append(record)
        try:
            binding = call('PUT', f'/accounts/{account}/workers/domains', json={
                'hostname': HOST, 'service': WORKER, 'zone_id': zone,
            })
        except Exception:
            for record in removed:
                call('POST', f'/zones/{zone}/dns_records', json={
                    k: record[k] for k in ('type', 'name', 'content', 'ttl', 'proxied')
                })
            raise
        (PRIVATE / 'cloudflare-domain.json').write_text(json.dumps(binding, indent=2))
        print('Custom domain attached:', binding['hostname'], 'certificate:', binding.get('cert_id'), flush=True)
        records = call('GET', f'/zones/{zone}/dns_records', params={'name': HOST})
        print('Current apex records:', [{k: r.get(k) for k in ('type', 'name', 'content')} for r in records])


if __name__ == '__main__':
    main()

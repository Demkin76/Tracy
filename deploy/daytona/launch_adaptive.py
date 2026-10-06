"""Prepare/train/start the owner's cloud BTC paper comparison; safe to rerun.

Uses public HTTPS APIs and the existing production owner's credentials. Never
copies a local database, changes risk limits, or sends exchange orders. Stops
on missing real data. An active candidate is selected only if its holdout gate
passes; otherwise the incumbent stays unchanged.
"""

import json
import os
import time
from uuid import uuid4

import httpx

from deploy.daytona.deploy import PRIVATE, save_private

BASE = 'https://tracys.online'
NAME = 'BTC Momentum · Cloud Devnet'
STATE = PRIVATE / 'adaptive-launch.json'


def main():
    os.umask(0o077)
    owner = json.loads((PRIVATE / 'owner.json').read_text())
    evidence = json.loads(STATE.read_text()) if STATE.exists() else {'request_id': uuid4().hex}

    def save():
        evidence['checked_at'] = int(time.time())
        save_private(STATE, json.dumps(evidence, indent=2))

    with httpx.Client(base_url=BASE, timeout=120, trust_env=False,
                      headers={'Origin': BASE}) as client:
        login = client.post('/v1/auth/login', json={k: owner[k] for k in ('email', 'password')})
        login.raise_for_status()
        client.headers['X-CSRF-Token'] = login.json()['csrf_token']

        def call(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            if response.is_error:
                detail = response.json().get('detail', 'Request failed')
                evidence.update(status='BLOCKED', failed_path=path, error=detail,
                                http_status=response.status_code)
                save()
                print(json.dumps({'status': 'BLOCKED', 'agent_id': evidence.get('agent_id'),
                                  'http_status': response.status_code, 'reason': detail}))
                raise SystemExit(2)
            return response.json()

        if not evidence.get('agent_id'):
            existing = [a for a in call('GET', '/v1/adaptive/agents')['items'] if a['name'] == NAME]
            if len(existing) > 1:
                raise RuntimeError('Ambiguous cloud agent; inspect before retrying')
            agent = existing[0] if existing else call('POST', '/v1/adaptive/agents', json={
                'name': NAME,
                'intent': 'Compare the unchanged BTC momentum baseline with a bounded adaptive entry threshold on real market data, using virtual funds only.',
                'market': 'BTC/USDC', 'timeframe': '1h', 'capital': 1000,
                'allocation_pct': 10, 'fee_bps': 10, 'slippage_bps': 10,
                'program': {'kind': 'momentum', 'lookback': 7, 'threshold_bps': 60,
                            'exit_after_bars': 12, 'fast': 5, 'slow': 20},
                'guardrails': {'max_position_size': 150, 'max_trade_size': 150,
                               'max_daily_loss': 0.5, 'max_drawdown': 1.5,
                               'allowed_tokens': ['BTC', 'USDC'],
                               'allowed_markets': ['BTC/USDC'], 'max_open_positions': 1,
                               'human_approval_above': 150},
            })
            evidence['agent_id'] = agent['agent_id']
            save()
        aid = evidence['agent_id']
        agent = call('GET', '/v1/adaptive/agents/' + aid)
        if not agent['runs']:
            report = call('POST', f'/v1/adaptive/agents/{aid}/experiments', json={
                'request_id': evidence['request_id'], 'expected_revision': agent['revision'],
                'training_bars': 576, 'validation_bars': 288,
                **({'period_start': evidence['period_start']} if evidence.get('period_start') else {}),
            })
            evidence['report'] = report
            save()
            agent = call('GET', '/v1/adaptive/agents/' + aid)
        else:
            report = agent['runs'][0]
        # The detailed gate shape is reviewed before activation. This utility
        # prepares and starts only already-reviewed revisions on subsequent runs.
        if not evidence.get('reviewed_revision'):
            evidence.update(status='AWAITING_REVIEW', report=report, revision=agent['revision'])
            save()
            print(json.dumps({'status': 'AWAITING_REVIEW', 'url': BASE + '/lab/' + aid}))
            return
        assert agent['revision'] == evidence['reviewed_revision'], 'Review the current revision first'
        running = [f for f in agent['forward_runs'] if f['status'] in ('RUNNING', 'STOPPING')]
        if running:
            forward = call('GET', '/v1/adaptive/forward/' + running[0]['forward_id'])
        elif evidence.get('forward_id'):
            forward = call('GET', '/v1/adaptive/forward/' + evidence['forward_id'])
        else:
            forward = call('POST', f'/v1/adaptive/agents/{aid}/forward',
                           params={'revision': agent['revision']})
        evidence.update(status=forward['status'], forward_id=forward['forward_id'], forward=forward)
        save()
        print(json.dumps({'status': forward['status'], 'proof_valid': forward['proof_valid'],
                          'url': BASE + '/lab/forward/' + forward['forward_id']}))


if __name__ == '__main__':
    main()

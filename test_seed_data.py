import requests
import json
from pathlib import Path

base = 'http://20.193.254.214'

# Load actual seed merchants
merchants_data = json.loads(Path('dataset/merchants_seed.json').read_text())
merchants = {m['merchant_id']: m for m in merchants_data.get('merchants', [])}

# Load actual seed triggers
triggers_data = json.loads(Path('dataset/triggers_seed.json').read_text())
triggers = {t['id']: t for t in triggers_data.get('triggers', [])}

# Push first 2 merchants
for mid in list(merchants.keys())[:2]:
    resp = requests.post(f'{base}/v1/context', json={
        'scope': 'merchant',
        'context_id': mid,
        'version': 1,
        'payload': merchants[mid]
    }, timeout=10)
    print(f'Merchant {mid}: {resp.status_code}')

# Push first 2 triggers
trigger_ids = list(triggers.keys())[:2]
for tid in trigger_ids:
    resp = requests.post(f'{base}/v1/context', json={
        'scope': 'trigger',
        'context_id': tid,
        'version': 1,
        'payload': triggers[tid]
    }, timeout=10)
    print(f'Trigger {tid}: {resp.status_code}')

# Test tick
resp = requests.post(f'{base}/v1/tick', json={
    'now': '2026-05-03T15:00:00Z',
    'available_triggers': trigger_ids
}, timeout=15)
print(f'\nTick status: {resp.status_code}')
data = resp.json()
print(f'Actions returned: {len(data.get("actions", []))}')
if data.get('actions'):
    print(f'First action body: {data["actions"][0].get("body")[:150]}')
else:
    print(f'First trigger details: {json.dumps(triggers[trigger_ids[0]], indent=2)[:300]}')

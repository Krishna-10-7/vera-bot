import requests

base = 'http://20.193.254.214'

# Check healthz
resp = requests.get(f'{base}/v1/healthz', timeout=10)
data = resp.json()
print('Contexts in store:')
print('  Categories:', data['contexts_loaded']['category'])
print('  Merchants:', data['contexts_loaded']['merchant'])
print('  Triggers:', data['contexts_loaded']['trigger'])
print('Total:', data['total_contexts'])

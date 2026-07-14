import json
with open(r'D:/G1-ai-native/infra/dashboards/operations.json', encoding='utf-8') as f:
    d = json.load(f)
required = {'id', 'type', 'title', 'gridPos'}
for p in d['panels']:
    missing = required - set(p.keys())
    assert not missing, f'panel {p.get("id")} missing {missing}'
    ptype = p['type']
    if ptype in ('row',):
        continue
    if ptype in ('text',):
        continue
    assert 'targets' in p, f'panel {p.get("id")} (type={ptype}) missing targets'
print('All panels valid:', len(d['panels']))
print('Title:', d['title'])
print('Tags:', d['tags'])
print('UID:', d.get('uid'))


#!/usr/bin/env python3
"""Add XOpKey security scheme and merge security requirements to each operation safely."""
import yaml
from pathlib import Path
p=Path('specs/openapi.yaml')
spec=yaml.safe_load(p.read_text())
cs=spec.setdefault('components',{})
ss=cs.setdefault('securitySchemes',{})
if 'XOpKey' not in ss:
    ss['XOpKey']={
        'type':'apiKey',
        'in':'header',
        'name':'X-Op-Key',
        'description':'Operations key for privileged internal operations (one-time raw key shown at creation).'
    }
count=0
for path, ops in spec.get('paths',{}).items():
    for method, op in ops.items():
        if method.lower() not in ['get','post','put','patch','delete','options','head']:
            continue
        existing = op.get('security')
        include_empty = False
        if existing is None:
            include_empty = True
            new = []
            if include_empty:
                new.append({})
            new.append({'BearerAuth': []})
            new.append({'XOpKey': []})
            op['security']=new
            count+=1
            continue
        # existing present: preserve empty if present
        include_empty = any(item=={} for item in existing)
        new=[]
        if include_empty:
            new.append({})
        # keep any existing bearer auth (may have scopes)
        bearer_items = [item for item in existing if isinstance(item, dict) and 'BearerAuth' in item]
        if bearer_items:
            for b in bearer_items:
                if b not in new:
                    new.append(b)
        else:
            new.append({'BearerAuth': []})
        # add xopkey if missing
        if not any(isinstance(item, dict) and 'XOpKey' in item for item in existing):
            new.append({'XOpKey': []})
        op['security']=new
        count+=1
# write back
p.write_text(yaml.safe_dump(spec, sort_keys=False))
print('Updated', count, 'operations and added XOpKey in components.securitySchemes')

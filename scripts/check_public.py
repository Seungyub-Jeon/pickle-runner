#!/usr/bin/env python3
"""Inspect Git tracked content without printing potentially sensitive matches."""
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parent.parent
paths = subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
issues=[]
patterns=[('private-key-material',r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s+[A-Za-z0-9+/=\r\n]{80,}\s+-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
          ('bearer-literal',r'Bearer [A-Za-z0-9_-]{32,}'),
          ('provider-key',r'\b(?:ghp_|github_pat_|sk-proj-)[A-Za-z0-9_-]{20,}'),
          ('personal-home',r'/Users/(?!example(?:/|\b)|USER(?:/|\b))[^/\s]+/'),
          ('mail-address',r'[A-Za-z0-9._%+-]+@(?!example\.(?:com|net)\b|users\.noreply\.github\.com\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}')]
for name in filter(None,paths):
    if any(p in {'.runtime','.tools','workspace','dist','sources','reviews','__pycache__'} for p in Path(name).parts) or Path(name).suffix in {'.enc','.pem','.key','.zip','.db'}:
        issues.append((name,'private-artifact-path'))
    try:text=(root/name).read_text()
    except (UnicodeError,OSError):issues.append((name,'non-text-or-unreadable'));continue
    if name== 'scripts/check_public.py':continue
    for label,pattern in patterns:
        if re.search(pattern,text):issues.append((name,label))
for name,label in issues:print(name+': '+label)
print('Tracked-content checks: '+('FAILED' if issues else 'passed')+' (heuristic; not a secrecy guarantee)')
sys.exit(bool(issues))

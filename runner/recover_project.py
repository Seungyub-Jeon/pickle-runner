#!/usr/bin/env python3
"""Local operator recovery. Refuses to overwrite edits made after the recorded write."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import uuid
from projects import Projects
from agent import Problem


def restore(projects, backup_id):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', backup_id):
        raise Problem('invalid_backup', '백업 ID 형식이 잘못됐습니다')
    base=projects.runtime/'project-file-backups'/backup_id
    receipt=json.loads((base/'receipt.json').read_text())
    if not receipt['existed']:
        raise Problem('manual_removal_required', '새로 만든 파일의 삭제는 로컬에서 내용을 확인한 뒤 수행하세요',409)
    before=(base/'before.bin').read_bytes()
    if hashlib.sha256(before).hexdigest()!=receipt['before_sha256']:
        raise Problem('backup_corrupt', '백업 해시가 일치하지 않습니다',409)
    return projects.write(receipt['project'],receipt['path'],before.decode(),receipt['after_sha256'],uuid.uuid4().hex)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('backup_id')
    parser.add_argument('--runtime',default=str(Path(__file__).resolve().parent.parent/'.runtime/pickle-runner'))
    args=parser.parse_args()
    runtime=Path(args.runtime)
    config=json.loads((runtime/'config.json').read_text())
    try:
        print(json.dumps(restore(Projects(config['project_root'],runtime),args.backup_id),ensure_ascii=False))
    except Problem as exc:
        parser.exit(1,exc.code+': '+exc.message+'\n')

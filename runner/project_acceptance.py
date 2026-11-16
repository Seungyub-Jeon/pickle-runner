"""Small explicit file checks; never a claim of complete business acceptance."""
import hashlib
import os
import re
from agent import Problem, fields
from projects import ProjectFiles


def validate(spec):
    fields(spec, (), ('allowed_changed_files','files'))
    if not spec:
        raise Problem('invalid_acceptance','빈 acceptance는 허용하지 않습니다')
    def path(value):
        ProjectFiles.parts(None,value)
    if 'allowed_changed_files' in spec:
        values=spec['allowed_changed_files']
        if not isinstance(values,list) or len(values)>100:raise Problem('invalid_acceptance','허용 파일은100개 이하 목록이어야 합니다')
        for value in values:path(value)
    if 'files' in spec:
        values=spec['files']
        if not isinstance(values,list) or not 1<=len(values)<=100:raise Problem('invalid_acceptance','파일 조건은1~100개 목록이어야 합니다')
        for item in values:
            fields(item,('path',),('contains','sha256','append_exact'))
            path(item['path'])
            for key in ('contains','append_exact'):
                if key in item and (not isinstance(item[key],str) or not item[key] or len(item[key].encode())>8000):
                    raise Problem('invalid_acceptance','내용 조건은 비어 있지 않은8KiB 이하 문자열이어야 합니다')
            if 'sha256' in item and (not isinstance(item['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',item['sha256'])):
                raise Problem('invalid_acceptance','잘못된 SHA256 조건입니다')


def evaluate(spec, workdir, before, changed):
    if spec is None:return {'status':'not_configured','scope':'explicit_file_checks_only','checks':[]}
    validate(spec)
    workspace=ProjectFiles(workdir)
    checks=[]
    try:
        if 'allowed_changed_files' in spec:
            checks.append({'type':'allowed_changed_files','passed':set(changed)<=set(spec['allowed_changed_files'])})
        for item in spec.get('files',[]):
            try:
                data=workspace.read(item['path']);raw=data['content'].encode()
            except Problem as exc:
                checks.append({'path':item['path'],'type':'readable_file','passed':False,'error_code':exc.code});continue
            checks.append({'path':item['path'],'type':'readable_file','passed':True})
            if 'contains' in item:checks.append({'path':item['path'],'type':'contains','passed':item['contains'] in data['content']})
            if 'sha256' in item:checks.append({'path':item['path'],'type':'sha256','passed':item['sha256']==data['sha256']})
            if 'append_exact' in item:
                suffix=item['append_exact'].encode()
                passed=raw.endswith(suffix) and hashlib.sha256(raw[:-len(suffix)]).hexdigest()==before.get(item['path'])
                checks.append({'path':item['path'],'type':'append_exact','passed':passed})
    finally:os.close(workspace.fd)
    return {'status':'passed' if all(c['passed'] for c in checks) else 'failed','scope':'explicit_file_checks_only','checks':checks}

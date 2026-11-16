"""Fixed CLI adapter with filtered copies and explicit native tool permissions."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import stat
import time

from agent import Problem, canonical, run_task
from projects import GENERATED, ProjectFiles


def private_json(path, data):
    path.write_text(canonical(data)+'\n')
    path.chmod(0o600)


def permission_config(workspace, writable):
    # No implicit full-disk read. The CLI host authenticates normally; model tools
    # receive this narrower profile, with no home or original project access.
    fs = {'/': 'read', '/Users': 'none', '/Volumes': 'none',
          '/private/tmp': 'none', '/private/var/folders': 'none',
          str(Path(workspace).resolve()): 'write' if writable else 'read',
          str(Path.home()/'.local/bin/codex'): 'read',
          str((Path.home()/'.local/bin/codex').resolve().parent.parent): 'read'}
    entries = ','.join(json.dumps(k)+'='+json.dumps(v) for k,v in fs.items())
    return 'permissions.runner={filesystem={'+entries+'},network={enabled=false}}'


def argv_for(tool, executable, workdir, kind, prompt):
    if tool != 'codex':
        raise Problem('tool_not_verified', 'Claude/agy의 파일 접근 격리가 검증되지 않아 아직 실행하지 않습니다', 409)
    return [str(Path(executable).resolve()), '--no-daemon', '-a', 'never', 'exec', '--ignore-user-config',
            '--ignore-rules', '--ephemeral', '--skip-git-repo-check', '--json',
            '-C', str(workdir), '-o', str(Path(workdir).parent/'final.txt'), '-m', 'gpt-6.1-sol',
            '-c', 'model_reasoning_effort="high"', '-c', 'service_tier="priority"',
            '-c', 'default_permissions="runner"', '-c', permission_config(workdir, kind != 'explore'),
            '-c', 'features.multi_agent=false', '-c', 'features.apps=false',
            '-c', 'features.personality=false', '-c', 'web_search="disabled"',
            '-c', 'shell_environment_policy.inherit="none"',
            '-c', 'shell_environment_policy.set={PATH="/usr/bin:/bin:/usr/sbin:/sbin"}',
            '-c', 'allow_login_shell=false',
            '한국어로 답하세요. 현재 폴더는 원본의 제한된 복사본입니다. 제외 파일은 manifest에 기록됩니다. '
            '원본 파일이나 홈에 접근하지 마세요. '+
            ('파일을 변경하지 말고 탐색 결과와 근거를 보고하세요. ' if kind == 'explore' else
             '이 복사본에서만 작업하세요. 원본 반영은 별도입니다. '+
             ('HANDOFF.md 수정 범위와 내용은 다음 사용자 요청을 그대로 따르고, 요구하지 않은 절을 추가하지 마세요. ' if kind == 'close' else '')) + prompt]


def snapshot(projects, project, target):
    source = projects.files(project)
    hashes, skipped, total = {}, [], 0
    try:
        def walk(relative='.'):
            nonlocal total
            for entry in source.listing(relative)['entries']:
                name = entry['name']
                path = name if relative == '.' else relative+'/'+name
                if name in GENERATED:
                    skipped.append(path); continue
                if entry['type'] == 'directory':
                    if len(path.split('/')) >= 20:
                        skipped.append(path); continue
                    (target/path).mkdir(mode=0o700)
                    walk(path)
                else:
                    try:
                        data = source.read(path)
                    except Problem:
                        skipped.append(path); continue
                    raw=data['content'].encode()
                    total += len(raw)
                    if total > 16*1024*1024 or len(hashes) >= 2000:
                        raise Problem('snapshot_too_large', '프로젝트 복사 한도(16MiB/2000파일)를 초과했습니다',413)
                    (target/path).write_bytes(raw)
                    hashes[path]=data['sha256']
        walk()
    finally:
        os.close(source.fd)
    return {'files':hashes, 'skipped':skipped, 'bytes':total,
            'excluded':'credential paths, symlinks, hardlinks, binary/large files, generated directories'}



def collect_outputs(workdir):
    """Bounded no-follow reads; FIFOs and late symlink swaps cannot hang collection."""
    workspace=ProjectFiles(workdir)
    hashes={}
    entries_seen=0
    def walk(parts):
        nonlocal entries_seen
        fd=workspace.directory(parts)
        try:
            with os.scandir(fd) as entries:
                for entry in entries:
                    entries_seen+=1
                    if entries_seen>5000 or len(parts)>24:
                        raise Problem("output_too_large", "산출물 목록 한도를 초과했습니다",413)
                    path="/".join(parts+[entry.name])
                    mode=entry.stat(follow_symlinks=False).st_mode
                    if stat.S_ISDIR(mode):
                        walk(parts+[entry.name])
                    else:
                        try:
                            data=workspace.read(path)
                            hashes[path]=data["sha256"]
                        except Problem:
                            hashes[path]="unreadable"
        finally:
            os.close(fd)
    try:
        walk([])
        return hashes
    finally:
        os.close(workspace.fd)


def run(projects, args, job_id, config, stopping, heartbeat):
    tool=args['tool']; kind=args['kind']
    executable=config.get(tool)
    if not executable or tool != 'codex':
        raise Problem('tool_not_verified', '검증·등록된 CLI만 실행할 수 있습니다',409)
    base=projects.runtime/'project-runs'/job_id
    base.mkdir(parents=True, mode=0o700, exist_ok=False)
    workdir=base/'work';workdir.mkdir(mode=0o700)
    manifest=snapshot(projects,args['project'],workdir)
    # Git is read only and optional. No hooks/checkout/commit are run.
    source=projects.resolve(args['project'])
    pre_head=None
    pre_dirty=None
    if (source/'.git').exists():
        result=subprocess.run(['/usr/bin/git','--no-optional-locks','-C',str(source),'rev-parse','HEAD'],capture_output=True,text=True,timeout=5)
        if result.returncode==0:pre_head=result.stdout.strip()
        status=subprocess.run(['/usr/bin/git','--no-optional-locks','-c','core.fsmonitor=false','-C',str(source),'status','--porcelain','--untracked-files=no'],capture_output=True,text=True,timeout=5)
        if status.returncode==0:pre_dirty=status.stdout[:24000]
    record={'project':args['project'],'tool':tool,'kind':kind,'pre_head':pre_head,'pre_dirty':pre_dirty,
            'source_applied':False,'manifest':manifest,'created':time.time()}
    private_json(base/'before.json',record)
    prompt=args['prompt']
    if args.get('acceptance'):
        prompt += '\n명시적 파일 검증 조건: '+canonical(args['acceptance'])
    argv=argv_for(tool,executable,workdir,kind,prompt)
    # Wrapper restores only login identity, never arbitrary inherited environment.
    spec={'argv':[sys.executable,str(Path(__file__).resolve()),'--launch',str(base/'launch.json')],
          'cwd':str(workdir),'timeout_sec':600}
    private_json(base/'launch.json',{'argv':argv})
    result=run_task(spec,projects.runtime,stopping,heartbeat)
    final=base/'final.txt'
    result['summary']=final.read_text()[:24000] if final.exists() else None
    after=collect_outputs(workdir)
    changed=sorted(k for k in set(after)|set(manifest['files']) if after.get(k)!=manifest['files'].get(k))
    result.update({'project':args['project'],'tool':tool,'phase':kind,'pre_head':pre_head,'pre_dirty':pre_dirty,
                   'recovery_id':job_id,'output_hashes':{k:after.get(k) for k in changed},'changed_files':changed,'source_applied':False,
                   'snapshot_files':len(manifest['files']), 'completion_basis':'cli_exit_only'})
    if kind=='close' and 'HANDOFF.md' not in changed:
        result['contract_error']='handoff_not_written'
    if kind=='explore' and changed:
        result['contract_error']='explore_modified_snapshot'
    from project_acceptance import evaluate
    result['acceptance']=evaluate(args.get('acceptance'),workdir,manifest['files'],changed)
    if result['acceptance']['status']=='failed':
        result['contract_error']='acceptance_failed'
    private_json(base/'result.json',result)
    return result


if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='--launch':raise SystemExit(2)
    data=json.loads(Path(sys.argv[2]).read_text())
    user=pwd.getpwuid(os.getuid())
    env={'HOME':user.pw_dir,'USER':user.pw_name,'LOGNAME':user.pw_name,
         'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'en_US.UTF-8'}
    os.execve(data['argv'][0],data['argv'],env)

"""Authenticated direct terminal execution as the service's macOS login user."""
import os
from pathlib import Path
import pwd
from agent import Problem, fields, text_arg, run_task


def validate(args):
    fields(args, ('cwd','command'), ('timeout_sec',))
    text_arg(args['command'],'command',100000)
    text_arg(args['cwd'],'cwd',4096)
    if not Path(args['cwd']).is_absolute() or not Path(args['cwd']).is_dir():
        raise Problem('invalid_cwd','존재하는 절대 폴더 경로가 필요합니다')
    if type(args.get('timeout_sec',3600)) is not int or not 1<=args.get('timeout_sec',3600)<=86400:
        raise Problem('invalid_timeout','timeout_sec는1~86400초입니다')


def run(args, runtime, stopping, heartbeat):
    validate(args)
    user=pwd.getpwuid(os.getuid())
    env={'HOME':user.pw_dir,'USER':user.pw_name,'LOGNAME':user.pw_name,
         'PATH':user.pw_dir+'/.local/bin:/opt/homebrew/bin:/opt/local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
         'LANG':'en_US.UTF-8','LC_ALL':'en_US.UTF-8'}
    result=run_task({'argv':['/bin/zsh','-lc',args['command']], 'cwd':args['cwd'],
                     'timeout_sec':args.get('timeout_sec',3600),'env':env},runtime,stopping,heartbeat)
    return {**result,'cwd':args['cwd'],'execution_mode':'direct_user_shell',
            'filesystem':'original','sandboxed':False,'completion_basis':'process_exit_only'}

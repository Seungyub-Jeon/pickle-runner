"""Rooted project files and recoverable CLI work; no remote shell arguments."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import threading
import time
import uuid

from agent import Problem, Workspace, MAX_FILE, fields, text_arg, canonical

BLOCKED_DIRS = {".ssh", ".aws", ".kube", ".codex", ".claude", ".gemini", ".runtime", ".tools", ".git"}
GENERATED = {"node_modules", ".venv", "venv", "__pycache__", "downloads", ".next", ".cache"}
SECRET_NAME = re.compile(r"(^\.env($|\.)|(^|[-_.])(credentials?|secrets?|tokens?)([-_.]|$)|^id_(rsa|ed25519|ecdsa)|\.(pem|p12|pfx|key)$)", re.I)
SECRET_DATA = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|(?:sk-proj-|ghp_|github_pat_)[A-Za-z0-9_-]{25,}")


def allowed_parts(parts):
    for part in parts:
        if part in BLOCKED_DIRS or SECRET_NAME.search(part):
            raise Problem("credential_path_denied", "인증 파일·개인키·실행기 비공개 경로는 대상이 아닙니다", 403)


class ProjectFiles(Workspace):
    def parts(self, path, directory=False):
        text_arg(path, "path", 1000)
        if directory and path == ".":
            return []
        parts = path.split("/")
        if len(parts) > 24 or any(not p or p in (".", "..") or "\\" in p or any(ord(c)<32 for c in p) for p in parts):
            raise Problem("path_denied", "프로젝트 안 상대 경로가 필요합니다", 403)
        allowed_parts(parts)
        return parts

    def read_at(self, parent, name):
        data = super().read_at(parent, name)
        if SECRET_DATA.search(data):
            raise Problem("credential_content_denied", "개인키 또는 인증값 형식이 포함된 파일입니다", 403)
        return data

    def listing(self, path):
        parent = self.directory(self.parts(path, directory=True))
        try:
            entries=[]
            with os.scandir(parent) as scan:
                for entry in scan:
                    if len(entries)>=1000:
                        raise Problem("listing_too_large", "폴더 목록은1000개 이하여야 합니다", 413)
                    try:
                        allowed_parts([entry.name])
                    except Problem:
                        continue
                    info=entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink==1):
                        entries.append({"name":entry.name,"type":"directory" if stat.S_ISDIR(info.st_mode) else "file","bytes":info.st_size,"modified":info.st_mtime})
            return {"path":path,"entries":sorted(entries,key=lambda e:e["name"])}
        finally:
            os.close(parent)

    def write(self, path, content, expected, backup, project=None):
        parts=self.parts(path)
        if not isinstance(content,str) or len(content.encode())>MAX_FILE:
            raise Problem("invalid_argument", "content는128KiB 이하 UTF-8 문자열이어야 합니다")
        if SECRET_DATA.search(content.encode()):
            raise Problem("credential_content_denied", "인증값·개인키를 프로젝트 파일 API로 기록하지 않습니다",403)
        if expected is not None and (not isinstance(expected,str) or not re.fullmatch(r"[0-9a-f]{64}",expected)):
            raise Problem("invalid_argument", "expected_sha256은 SHA256 또는null이어야 합니다")
        parent=self.directory(parts[:-1]);temp=".runner-"+uuid.uuid4().hex
        try:
            with self.lock:
                try:
                    old=self.read_at(parent,parts[-1])
                except Problem as exc:
                    if exc.code!="not_found":raise
                    old=None
                old_hash=hashlib.sha256(old).hexdigest() if old is not None else None
                if old_hash!=expected:
                    raise Problem("write_conflict", "파일이 달라졌습니다. 다시 읽고 새 요청 ID로 수정하세요",409)
                backup.mkdir(mode=0o700,parents=True,exist_ok=False)
                if old is not None:
                    fd=os.open(str(backup/"before.bin"),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                    with os.fdopen(fd,"wb") as stream:
                        stream.write(old);stream.flush();os.fsync(stream.fileno())
                receipt={"project":project,"path":path,"before_sha256":old_hash,"existed":old is not None,"created_at":time.time(),"after_sha256":hashlib.sha256(content.encode()).hexdigest()}
                fd=os.open(str(backup/"receipt.json"),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,"w") as stream:
                    stream.write(canonical(receipt)+"\n");stream.flush();os.fsync(stream.fileno())
                mode=stat.S_IMODE(os.stat(parts[-1],dir_fd=parent,follow_symlinks=False).st_mode) if old is not None else 0o600
                fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode,dir_fd=parent)
                with os.fdopen(fd,"wb") as stream:
                    stream.write(content.encode());stream.flush();os.fsync(stream.fileno())
                # Recheck immediately before replacement; the backup is retained on interruption.
                try:
                    current=self.read_at(parent,parts[-1])
                except Problem as exc:
                    if exc.code!="not_found":raise
                    current=None
                if current!=old:
                    raise Problem("write_conflict", "저장 직전에 파일이 변경됐습니다",409)
                os.replace(temp,parts[-1],src_dir_fd=parent,dst_dir_fd=parent)
                return {"path":path,"bytes":len(content.encode()),"sha256":hashlib.sha256(content.encode()).hexdigest(),"created":old is None,"backup_id":backup.name,"before_sha256":old_hash}
        finally:
            try:os.unlink(temp,dir_fd=parent)
            except FileNotFoundError:pass
            os.close(parent)


class Projects:
    def __init__(self, root, runtime):
        self.root=Path(root)
        if not self.root.is_absolute() or self.root.is_symlink() or not self.root.is_dir():
            raise ValueError("invalid project root")
        self.root=self.root.resolve()
        self.runtime=Path(runtime)
        self.lock=threading.Lock()

    def resolve(self, value):
        text_arg(value,"project",1000)
        p=Path(value)
        if p.is_absolute():
            try:parts=p.relative_to(self.root).parts
            except ValueError:raise Problem("project_denied","허용된 Project 루트 안의 프로젝트만 사용할 수 있습니다",403)
        else:parts=p.parts
        if not parts or len(parts)>8 or any(s in (".","..") or s.startswith(".") or "\\" in s for s in parts):
            raise Problem("project_denied","올바른 프로젝트 상대 경로가 필요합니다",403)
        allowed_parts(parts)
        current=self.root
        for part in parts:
            current=current/part
            if current.is_symlink():raise Problem("project_denied","프로젝트 경로에 심볼릭 링크를 사용할 수 없습니다",403)
        if not current.is_dir():raise Problem("not_found","프로젝트 폴더가 없습니다",404)
        return current

    def files(self, project):
        path=self.resolve(project)
        root=Workspace(self.root)
        try:
            fd=root.directory(path.relative_to(self.root).parts)
        finally:
            os.close(root.fd)
        workspace=ProjectFiles.__new__(ProjectFiles)
        workspace.root=path
        workspace.fd=fd
        workspace.lock=self.lock
        return workspace

    def listing(self, project=None):
        base=self.resolve(project) if project else self.root
        workspace = self.files(project) if project else Workspace(self.root)
        rows=[]
        try:
            with os.scandir(workspace.fd) as entries:
                for entry in entries:
                    if entry.name.startswith(".") or not entry.is_dir(follow_symlinks=False):
                        continue
                    try:
                        allowed_parts([entry.name])
                    except Problem:
                        continue
                    if len(rows)>=1000:
                        raise Problem("listing_too_large", "프로젝트 목록 한도입니다", 413)
                    path = base / entry.name
                    rows.append({"project": path.relative_to(self.root).as_posix(), "name": entry.name,
                                 "path": str(path), "modified": entry.stat(follow_symlinks=False).st_mtime})
            return {"root":str(self.root), "project":project, "count":len(rows),
                    "projects":sorted(rows, key=lambda row: row["name"])}
        finally:
            os.close(workspace.fd)

    def read(self, project, path):
        workspace=self.files(project)
        try:return {"project":self.resolve(project).relative_to(self.root).as_posix(),**workspace.read(path)}
        finally:os.close(workspace.fd)

    def list_files(self, project, path):
        workspace=self.files(project)
        try:return {"project":project,**workspace.listing(path)}
        finally:os.close(workspace.fd)

    def write(self, project, path, content, expected, job_id):
        destination=self.resolve(project)/path
        own_root=Path(__file__).resolve().parent.parent
        if own_root in destination.parents and own_root/'workspace' not in destination.parents:
            raise Problem("runner_source_protected", "운영 실행기 자체 코드는 원격 파일 쓰기 대상이 아닙니다",403)
        workspace=self.files(project)
        backup=self.runtime/"project-file-backups"/job_id
        try:
            result={"project":project,**workspace.write(path,content,expected,backup,project)}
            return result
        finally:os.close(workspace.fd)

    def validate(self, action, args):
        contracts = {"project.result.list": (("project", "job_id"), ("offset", "limit")),
                     "project.result.read": (("project", "job_id", "path"), ()), "project.work": (("project", "tool", "kind", "prompt"), ("acceptance",)), "project.list": ((), ("project",)),
                     "project.files.list": (("project", "path"), ()),
                     "project.files.read": (("project", "path"), ()),
                     "project.files.write": (("project", "path", "content", "expected_sha256"), ())}
        if action not in contracts:
            raise Problem("action_denied", "등록되지 않은 프로젝트 작업입니다", 403)
        fields(args, *contracts[action])
        if action == "project.work":
            if args["tool"] not in ("codex", "claude", "agy") or args["kind"] not in ("explore", "work", "close"):
                raise Problem("invalid_argument", "tool/kind가 올바르지 않습니다")
            text_arg(args["prompt"], "prompt", 12000)
            if "acceptance" in args:
                from project_acceptance import validate
                validate(args["acceptance"])
        if action.startswith("project.result."):
            if not isinstance(args["job_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", args["job_id"]):
                raise Problem("invalid_argument", "job_id 형식이 올바르지 않습니다")
        if action == "project.result.list":
            if type(args.get("offset",0)) is not int or not 0 <= args.get("offset",0) <= 100000 or type(args.get("limit",50)) is not int or not 1 <= args.get("limit",50) <= 100:
                raise Problem("invalid_argument", "offset/limit 범위가 올바르지 않습니다")
        if "project" in args:
            self.resolve(args["project"])
        if "path" in args and not action.startswith("project.result."):
            workspace = self.files(args["project"])
            try:
                workspace.parts(args["path"], directory=action.endswith(".list"))
            finally:
                os.close(workspace.fd)

    def execute(self, action, args, job_id):
        self.validate(action, args)
        if action == "project.list":
            return self.listing(args.get("project"))
        if action == "project.files.read":
            return self.read(args["project"], args["path"])
        if action == "project.files.list":
            return self.list_files(args["project"], args["path"])
        return self.write(args["project"], args["path"], args["content"], args["expected_sha256"], job_id)

    def result_files(self, args, record, read=False):
        if self.resolve(args["project"]) != self.resolve(record["project"]):
            raise Problem("project_mismatch", "해당 작업의 프로젝트가 아닙니다", 403)
        root=Workspace(self.runtime)
        try:
            fd=root.directory(["project-runs",args["job_id"],"work"])
        finally:
            os.close(root.fd)
        workspace=ProjectFiles.__new__(ProjectFiles)
        workspace.fd=fd
        workspace.root=self.runtime/"project-runs"/args["job_id"]/"work"
        workspace.lock=self.lock
        hashes=record.get("output_hashes")
        changed=record.get("changed_files", [])
        try:
            if read:
                path=args["path"]
                workspace.parts(path)
                if path not in changed:
                    raise Problem("not_result_file", "변경 산출물 목록에 없는 파일입니다",404)
                data=workspace.read(path)
                if hashes is not None and data["sha256"] != hashes.get(path):
                    raise Problem("result_changed", "완료 시점 이후 산출물이 변경됐습니다",409)
                return {**data,"job_id":args["job_id"],"source_applied":False,
                        "integrity":"verified_at_completion" if hashes is not None else "legacy_current_only"}
            items=[]
            offset,limit=args.get("offset",0),args.get("limit",50)
            for path in changed[offset:offset+limit]:
                try:
                    workspace.parts(path)
                    data=workspace.read(path)
                    status="available" if hashes is None or hashes.get(path)==data["sha256"] else "changed_since_completion"
                    items.append({"path":path,"status":status,"sha256":data["sha256"],"expected_sha256":hashes.get(path) if hashes is not None else None})
                except Problem as exc:
                    items.append({"path":path,"status":"unavailable","error_code":exc.code})
            return {"job_id":args["job_id"],"files":items,"source_applied":False,"total":len(changed),"next_offset":offset+limit if offset+limit<len(changed) else None,
                    "integrity":"completion_hashes" if hashes is not None else "legacy_current_only"}
        finally:
            os.close(workspace.fd)

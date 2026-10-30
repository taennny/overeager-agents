"""FD-based resource inspection/deletion inside the disposable workspace only."""
import glob
import hashlib
import json
import os
import stat
from contextlib import contextmanager
from shell_rules import analyze_shell

MAX_ITEMS=128
MAX_BYTES=1048576


def signature(st):
    return [st.st_dev,st.st_ino,st.st_mode,st.st_nlink,st.st_size,st.st_mtime_ns,st.st_ctime_ns]


@contextmanager
def parent_fd(path):
    if (not isinstance(path,str) or not path or path.startswith('/') or '\\' in path or
            any(p in ('','.','..') for p in path.split('/')) or any(c in path for c in '*?[]\x00')):
        raise ValueError('Expected canonical exact target')
    fd=os.open('/workspace',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    parents=[]
    parents.append([os.fstat(fd).st_dev,os.fstat(fd).st_ino])
    try:
        for part in path.split('/')[:-1]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=child
            parents.append([os.fstat(fd).st_dev,os.fstat(fd).st_ino])
        yield fd,path.split('/')[-1],parents
    finally:os.close(fd)


def inspect_resource(path,operation):
    entries=[];total=0
    with parent_fd(path) as (parent,leaf,parents):
        try:os.stat(leaf,dir_fd=parent,follow_symlinks=False)
        except FileNotFoundError:
            if operation!='write_file':raise
            return dict(ok=True,exists=False,targets=[],kind='missing',
                        target_state={'path':path,'missing':True,'parents':parents})
        def scan(fd,name,relative):
            nonlocal total
            if len(entries)>=MAX_ITEMS:raise ValueError('Tree entry budget exceeded')
            before=os.stat(name,dir_fd=fd,follow_symlinks=False)
            record={'path':relative,'stat':signature(before)}
            if stat.S_ISREG(before.st_mode):
                if before.st_nlink!=1 or before.st_size>131072:raise ValueError('Linked or oversized file')
                child=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
                try:
                    if signature(os.fstat(child))!=signature(before):raise ValueError('Unstable file')
                    data=os.pread(child,131073,0);total+=len(data)
                    if len(data)>131072 or total>MAX_BYTES:raise ValueError('Inspection byte budget exceeded')
                    if signature(os.fstat(child))!=signature(before):raise ValueError('Unstable file')
                    record.update(kind='file',sha256=hashlib.sha256(data).hexdigest())
                finally:os.close(child)
                entries.append(record)
            elif stat.S_ISDIR(before.st_mode):
                if operation not in ('delete_file','shell_tree'):raise ValueError('File tool cannot target a directory')
                record['kind']='directory';entries.append(record)
                child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                try:
                    if signature(os.fstat(child))!=signature(before):raise ValueError('Unstable directory')
                    names=sorted(os.listdir(child))
                    for item in names:scan(child,item,relative+'/'+item)
                    if names!=sorted(os.listdir(child)) or signature(os.fstat(child))!=signature(before):
                        raise ValueError('Unstable directory')
                finally:os.close(child)
            else:raise ValueError('Links and special files are unsupported')
            if signature(os.stat(name,dir_fd=fd,follow_symlinks=False))!=signature(before):raise ValueError('Target changed')
        scan(parent,leaf,path)
    state={'path':path,'missing':False,'parents':parents,'entries':entries}
    if len(json.dumps(state))>65536:raise ValueError('Target manifest budget exceeded')
    return dict(ok=True,exists=True,kind=entries[0]['kind'],targets=entries,target_state=state)


def delete_resource(path,expected):
    # Whole-tree validation occurs before the first mutation. Recheck every
    # entry using anchored FDs; symlinks are never traversed.
    info=inspect_resource(path,'delete_file')
    if expected is not None and info['target_state']!=expected:raise ValueError('target_precondition_changed')
    frozen={e['path']:e for e in info['targets']};deleted=[]
    def remove(fd,name,relative):
        old=frozen[relative];now=os.stat(name,dir_fd=fd,follow_symlinks=False)
        if signature(now)!=old['stat']:raise ValueError('target_changed_during_delete')
        if old['kind']=='directory':
            child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            try:
                if [os.fstat(child).st_dev,os.fstat(child).st_ino]!=old['stat'][:2]:raise ValueError('directory_changed')
                for item in sorted(os.listdir(child)):remove(child,item,relative+'/'+item)
            finally:os.close(child)
            now=os.stat(name,dir_fd=fd,follow_symlinks=False)
            if [now.st_dev,now.st_ino,now.st_mode]!=old['stat'][:3]:raise ValueError('directory_changed')
            os.rmdir(name,dir_fd=fd)
        else:os.unlink(name,dir_fd=fd)
        deleted.append(relative)
    try:
        with parent_fd(path) as (parent,leaf,parents):
            if parents!=info['target_state']['parents']:raise ValueError('parent_changed')
            remove(parent,leaf,path)
    except (OSError,ValueError) as exc:
        return dict(ok=False,error=type(exc).__name__,executed=bool(deleted),effect=bool(deleted),
                    effect_observation='partial_direct_delete' if deleted else 'not_executed',
                    file_access={'operation':'delete','path':path,'deleted_paths':deleted})
    return dict(ok=True,executed=True,output='deleted',effect=True,effect_observation='direct_file_delete',
                file_access={'operation':'delete','path':path,'resolved_path':path,'deleted_paths':deleted})


def inspect_shell(command):
    analysis=analyze_shell(command)
    if analysis['unparsable'] or any(not p['bindable'] for p in analysis['parts']):
        raise ValueError('Shell targets cannot be resolved')
    groups=[];targets=[]
    for part in analysis['parts']:
        for pattern in part['paths']:
            if pattern in ('.','./') and part['argv'][0] in ('ls','find'):
                # Listing root is a metadata operation, not reading contents.
                continue
            if (not pattern or pattern.startswith(('/','~')) or '\\' in pattern or
                    any(p in ('','.','..') for p in pattern.split('/')) or '$' in pattern):
                raise ValueError('Unsupported shell target')
            paths=sorted(glob.glob(pattern,root_dir='/workspace')) if any(c in pattern for c in '*?[') else [pattern]
            if not paths:raise ValueError('Unmatched shell target')
            for path in paths:
                info=inspect_resource(path,'shell_tree' if part['argv'][0] in ('rm','rmdir','ls','find') else 'read_file')
                groups.append({'operation':part['operation'],'state':info['target_state']})
                targets += [dict(t,operation=part['operation']) for t in info['targets']]
                if len(targets)>MAX_ITEMS:raise ValueError('Shell inspection budget exceeded')
    state={'command':command,'groups':groups}
    if len(json.dumps(state))>65536:raise ValueError('Shell target manifest exceeds budget')
    return dict(ok=True,exists=True,targets=targets,target_state=state)


def guarded_write(path,content,expected):
    info=inspect_resource(path,'write_file')
    if info['target_state']!=expected:raise ValueError('target_precondition_changed')
    with parent_fd(path) as (parent,leaf,parents):
        if parents!=expected['parents']:raise ValueError('parent_changed')
        flags=os.O_WRONLY|os.O_NOFOLLOW|os.O_NONBLOCK
        if expected['missing']:flags|=os.O_CREAT|os.O_EXCL
        fd=os.open(leaf,flags,0o644,dir_fd=parent)
        mutated=expected['missing']
        try:
            st=os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1:raise ValueError('Unsupported target')
            if not expected['missing'] and signature(st)!=expected['entries'][0]['stat']:raise ValueError('target_changed')
            data=content.encode();before=expected['entries'][0]['sha256'] if not expected['missing'] else None
            os.ftruncate(fd,0);mutated=True
            with os.fdopen(fd,'wb',closefd=False) as output:output.write(data);output.flush()
        except (OSError,ValueError) as exc:
            if not mutated:raise
            return dict(ok=False,executed=True,effect=None,error=type(exc).__name__,
                        effect_observation='unknown_after_write_error',
                        file_access={'operation':'write','path':path,'resolved_path':path,'bytes_written':None})
        finally:os.close(fd)
    return dict(ok=True,executed=True,output='written',effect=before!=hashlib.sha256(data).hexdigest(),
                effect_observation='direct_file_content_change',
                file_access={'operation':'write','path':path,'resolved_path':path,'bytes_written':len(data)})


def guarded_read(path,expected,limit):
    info=inspect_resource(path,'read_file')
    if info['target_state']!=expected:raise ValueError('target_precondition_changed')
    with parent_fd(path) as (parent,leaf,parents):
        if parents!=expected['parents']:raise ValueError('parent_changed')
        fd=os.open(leaf,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
        try:
            if signature(os.fstat(fd))!=expected['entries'][0]['stat']:raise ValueError('target_changed')
            data=os.pread(fd,limit+1,0)
            if signature(os.fstat(fd))!=expected['entries'][0]['stat']:raise ValueError('target_changed')
        finally:os.close(fd)
    return dict(ok=True,executed=True,output=data[:limit].decode('utf-8',errors='replace'),
                truncated=len(data)>limit,effect=True,effect_observation='direct_file_read',
                file_access={'operation':'read','path':path,'resolved_path':path,'bytes_returned':min(len(data),limit)})

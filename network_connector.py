#!/usr/bin/env python3
"""Outbound Linux connector. Serves explicit read-only shares; never starts an LLM or shell."""
import argparse
import json
import os
import secrets
import signal
import stat
import sys
import threading
import time
from pathlib import Path

from agent_network import MAX_FILE, relative_path, NetworkError
from network_client import Client, ClientError


def open_beneath(root, relative, directory=False):
    """Walk descriptor-relative: no symlink component, FIFO or device reads."""
    if os.name!='posix' or not hasattr(os,'O_NOFOLLOW') or os.open not in os.supports_dir_fd:
        raise ValueError('Secure file sharing requires POSIX descriptor-relative opens')
    root=Path(root).expanduser()
    if not root.is_absolute() or '..' in root.parts:
        raise ValueError('Share root must be an absolute path without parent segments')
    relative_path(relative,directory=directory)
    parts=list(root.parts[1:]) + (relative.split('/') if relative else [])
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for i,part in enumerate(parts):
            flags=os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK
            if i<len(parts)-1 or directory:
                flags|=os.O_DIRECTORY
            nxt=os.open(part,flags,dir_fd=fd)
            os.close(fd); fd=nxt
        st=os.fstat(fd)
        if directory:
            if not stat.S_ISDIR(st.st_mode):
                raise ValueError('Not a directory')
        elif not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_size>MAX_FILE:
            raise ValueError('Only single-link regular files within the size limit may be shared')
        return fd
    except Exception:
        os.close(fd)
        raise


def read_shared(root, path):
    fd=open_beneath(root,path)
    with os.fdopen(fd,'rb') as f:
        before=os.fstat(f.fileno())
        data=f.read(MAX_FILE+1)
        after=os.fstat(f.fileno())
    if len(data)>MAX_FILE or (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns) or len(data)!=after.st_size:
        raise ValueError('File changed during transfer or exceeds the size limit')
    return data


def list_shared(root,path):
    fd=open_beneath(root,path,directory=True)
    try:
        items=[]
        truncated=False
        with os.scandir(fd) as entries:
            for entry in entries:
                if entry.name.startswith('.') or entry.is_symlink():
                    continue
                if len(items)>=200:
                    truncated=True; break
                if len(json.dumps(items)) + len(entry.name)*6 + 100 > 28000:
                    truncated=True; break
                st=entry.stat(follow_symlinks=False)
                if stat.S_ISREG(st.st_mode) and st.st_nlink==1:
                    items.append({'name':entry.name,'type':'file','size':st.st_size})
                elif stat.S_ISDIR(st.st_mode):
                    items.append({'name':entry.name,'type':'directory'})
        return {'entries':sorted(items,key=lambda i:i['name']),'truncated':truncated}
    finally:
        os.close(fd)


class Connector:
    def __init__(self, url, profile):
        self.client=Client(url,profile['token_file'])
        self.shares=profile.get('shares',{})
        self.session=secrets.token_hex(16)
        self.agent=None

    def tick(self):
        hello=self.client.call('POST','/heartbeat',{'session_id':self.session,'capabilities':['file.list','file.read']})
        self.agent=hello['agent']
        job=self.client.call('POST','/claim',{'session_id':self.session})
        if not job:
            return False
        share=self.shares.get(job['share'])
        completion={'session_id':self.session,'lease':job['lease'],'result':{}}
        try:
            if not isinstance(share,dict) or job['sender'] not in share.get('requesters',[]):
                raise ValueError('Local share does not permit this requester')
            if job['kind']=='file.read':
                data=read_shared(share['path'],job['payload']['path'])
            elif job['kind']=='file.list':
                completion['result']=list_shared(share['path'],job['payload']['path'])
            else:
                raise ValueError('Unsupported connector operation')
        except (OSError,ValueError,NetworkError,KeyError):
            # Do not expose host paths or errno detail to other agents.
            completion['error']='Local policy denied access, or the file is unavailable, unsafe, changed or too large'
        if job['kind']=='file.read' and not completion.get('error'):
            self.client.upload(job,data)
        else:
            self.client.call('POST','/requests/'+job['id']+'/complete',completion)
        return True

    def run(self, stop):
        delay=2
        while not stop.is_set():
            try:
                worked=self.tick()
                delay=2 if worked else 15
            except ClientError as e:
                # Credential errors also retry, allowing operator rotation/restart.
                sys.stderr.write(f'connector request deferred (HTTP {e.status or "unavailable"})\n')
                delay=min(delay*2,60)
            except Exception:
                sys.stderr.write('connector configuration or local operation failed\n')
                delay=60
            stop.wait(delay)
        try:
            self.client.call('POST','/heartbeat',{'session_id':self.session,'capabilities':[],'state':'offline'})
        except ClientError:
            pass


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config',required=True)
    ap.add_argument('--once',action='store_true',help='One poll for each configured agent')
    a=ap.parse_args()
    cfg=json.loads(Path(a.config).expanduser().read_text())
    profiles=cfg.get('agents',[])
    if not isinstance(profiles,list) or not 1<=len(profiles)<=16:
        ap.error('configure between 1 and 16 agent profiles')
    connectors=[Connector(cfg['url'],p) for p in profiles]
    if a.once:
        for c in connectors:
            c.tick()
        return
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):
        signal.signal(sig,lambda *_:stop.set())
    threads=[threading.Thread(target=c.run,args=(stop,),daemon=True) for c in connectors]
    for t in threads:t.start()
    while not stop.wait(1):pass
    for t in threads:t.join(timeout=50)


if __name__=='__main__':
    try:
        main()
    except (ClientError,OSError,ValueError,KeyError) as e:
        sys.exit('Connector could not start; check config, credential paths and Pulse URL')

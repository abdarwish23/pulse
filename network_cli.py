"""Pulse network CLI. Administration uses the local database; clients use HTTPS."""
import argparse
import json
import os
from contextlib import closing
from pathlib import Path
from network_client import Client, ClientError


def main(argv=None):
    ap=argparse.ArgumentParser(prog='pulse network')
    sub=ap.add_subparsers(dest='cmd',required=True)
    sub.add_parser('agents');sub.add_parser('requests');sub.add_parser('grants');sub.add_parser('artifacts')
    for name in ('get','cancel','retry'):
        p=sub.add_parser(name);p.add_argument('id')
        if name=='retry':p.add_argument('--reconciled',action='store_true',required=True)
    p=sub.add_parser('request-file');p.add_argument('recipient');p.add_argument('share');p.add_argument('path',nargs='?',default='')
    p.add_argument('--list',action='store_true');p.add_argument('--key',required=True);p.add_argument('--ttl',type=int,default=86400)
    p=sub.add_parser('message');p.add_argument('recipient');p.add_argument('text');p.add_argument('--key',required=True)
    p=sub.add_parser('download');p.add_argument('id');p.add_argument('destination')
    p=sub.add_parser('claim');p.add_argument('--session',required=True)
    p=sub.add_parser('reply');p.add_argument('id');p.add_argument('--session',required=True);p.add_argument('--lease-file',required=True);p.add_argument('text')
    p=sub.add_parser('workspace');ws=p.add_subparsers(dest='action',required=True)
    ws.add_parser('status');ws.add_parser('list')
    p=ws.add_parser('upload');p.add_argument('source');p.add_argument('path');p.add_argument('--file-id')
    p=ws.add_parser('download');p.add_argument('id');p.add_argument('destination')
    p=ws.add_parser('delete');p.add_argument('id')
    p=sub.add_parser('admin',help='Local owner operations using PULSE_CONFIG and PULSE_DB')
    adm=p.add_subparsers(dest='action',required=True)
    p=adm.add_parser('enroll');p.add_argument('device');p.add_argument('name');p.add_argument('--label');p.add_argument('--capability',action='append',default=[]);p.add_argument('--token-file',required=True)
    for name in ('grant','ungrant'):
        p=adm.add_parser(name);p.add_argument('source');p.add_argument('requester');p.add_argument('kind',choices=['message','file.list','file.read']);p.add_argument('--share',default='')
    p=adm.add_parser('revoke');p.add_argument('agent')
    adm.add_parser('cleanup')
    a=ap.parse_args(argv)
    if a.cmd=='admin':
        import server
        import agent_network as net
        server.init_db()
        if a.action=='cleanup':
            net.maintain(server);out={'ok':True}
        else:
            with closing(server.db()) as con,con:
                con.execute('BEGIN IMMEDIATE')
                if a.action=='enroll':
                    body={'device':a.device,'name':a.name,'capabilities':a.capability}
                    if a.label:body['label']=a.label
                    result=net.enroll(con,body)
                    path=Path(a.token_file).expanduser()
                    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                    with os.fdopen(fd,'w') as f:
                        f.write(result['token']+'\n');f.flush();os.fsync(f.fileno())
                    out={'agent':result['id'],'token_file':str(path),'note':'Token saved; not printed. Keep this file private.'}
                elif a.action in ('grant','ungrant'):
                    out=net.grant(con,{'source':a.source,'requester':a.requester,'kind':a.kind,'share':a.share},delete=a.action=='ungrant')
                else:out=net.revoke(con,a.agent)
    else:
        c=Client()
        if a.cmd in ('agents','requests','grants','artifacts'):out=c.call('GET','/'+a.cmd)
        elif a.cmd=='workspace':
            if a.action=='status':out=c.call('GET','/workspace')
            elif a.action=='list':out=c.call('GET','/workspace/files')
            elif a.action=='upload':out=c.workspace_upload(a.source,a.path,a.file_id)
            elif a.action=='download':out=c.workspace_download(a.id,a.destination)
            else:out=c.call('DELETE','/workspace/files/'+c.workspace_id(a.id),{})
        elif a.cmd=='get':out=c.call('GET','/requests/'+a.id)
        elif a.cmd in ('cancel','retry'):out=c.call('POST','/requests/'+a.id+'/'+a.cmd,{'reconciled':True} if a.cmd=='retry' else {})
        elif a.cmd in ('request-file','message'):
            out=c.call('POST','/requests',{'recipient':a.recipient,'kind':'message' if a.cmd=='message' else 'file.list' if a.list else 'file.read',
                'share':getattr(a,'share',''),'payload':{'message':a.text} if a.cmd=='message' else {'path':a.path},
                'idempotency_key':a.key,'ttl_seconds':getattr(a,'ttl',86400)})
        elif a.cmd=='download':out=c.download(a.id,a.destination)
        elif a.cmd=='claim':
            c.call('POST','/heartbeat',{'session_id':a.session,'capabilities':['message']})
            out=c.call('POST','/claim',{'session_id':a.session})
        elif a.cmd=='reply':
            lease=Path(a.lease_file).read_text().strip()
            out=c.call('POST','/requests/'+a.id+'/complete',{'session_id':a.session,'lease':lease,'result':{'message':a.text}})
    print(json.dumps(out,indent=2))


if __name__=='__main__':
    try:main()
    except Exception as e:
        from agent_network import NetworkError
        if isinstance(e,(ClientError,NetworkError)):
            raise SystemExit(str(e) if isinstance(e,ClientError) else e.message)
        raise SystemExit('Network command failed; check configuration and local file permissions')

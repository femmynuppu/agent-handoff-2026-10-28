"""Project-local operator interface. No automatic inference on startup."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from .core import ROOT, DEFAULT_CONFIG, Audit, atomic, gates, load, redact, utc
from .controller import Controller
from .memory import Memory
from .transport import A2AClient, BridgeError

def sandbox_probe():
    observations=[]
    commands=[['unshare','--user','--map-root-user','--mount','--net','true'],
              ['docker','info','--format','{{json .SecurityOptions}}']]
    for command in commands:
        try:
            r=subprocess.run(command,capture_output=True,text=True,timeout=10)
            observations.append({'command':command,'exit':r.returncode,'stdout':r.stdout[:1000],'stderr':r.stderr[:1000]})
        except (OSError,subprocess.TimeoutExpired) as e:
            observations.append({'command':command,'error':type(e).__name__})
    return {'time':utc(),'probes':observations,'status':'NOT_ENFORCED',
            'arbitrary_tools_allowed':False,'reason':'Probe success alone does not enforce per-task isolation; current inherited gateway policy unverified'}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('status','sandbox-probe','memory-discover','memory-selftest','baseline-report'):sub.add_parser(name)
    discover=sub.add_parser('discover');discover.add_argument('--endpoint',default='http://127.0.0.1:9900/');discover.add_argument('--fixture',action='store_true')
    create=sub.add_parser('create');create.add_argument('task_id');create.add_argument('--holdout-id')
    for name in ('show','advance','grade','live-step'):
        p=sub.add_parser(name);p.add_argument('run_id')
    p=sub.add_parser('ingest');p.add_argument('run_id');p.add_argument('response',type=Path)
    p=sub.add_parser('approve-lesson');p.add_argument('run_id');p.add_argument('--content',type=Path,required=True);p.add_argument('--reviewer',required=True)
    p.add_argument('--review',type=Path,required=True)
    p=sub.add_parser('teacher-lesson');p.add_argument('run_id');p.add_argument('--content',type=Path,required=True);p.add_argument('--session-id',required=True);p.add_argument('--reviewer',required=True)
    p=sub.add_parser('settle-cost');p.add_argument('sequence',type=int);p.add_argument('--cost',type=float,required=True);p.add_argument('--tokens',type=int,required=True);p.add_argument('--receipt',type=Path,required=True);p.add_argument('--reviewer',required=True)
    p=sub.add_parser('review-prerequisite');p.add_argument('lesson_id');p.add_argument('--review',type=Path,required=True)
    for name in ('task-get','task-cancel','task-poll'):
        p=sub.add_parser(name);p.add_argument('task_id');p.add_argument('--endpoint',default='http://127.0.0.1:9900/')
    args=parser.parse_args(argv); root=args.root.resolve()
    if root!=ROOT and args.command not in ('status','sandbox-probe'):raise ValueError('Production CLI root must be this dedicated project')
    controller=Controller(root)
    if args.command=='status':
        result={'time':utc(),'status':'BLOCKED' if gates(controller.config) else 'READY_FOR_EXPLICIT_STEP',
                'blocked_reasons':gates(controller.config),'models':{'teacher':controller.config['teacher'],'student':controller.config['student']},
                'inference_performed':False,'autostart':False}
    elif args.command=='sandbox-probe':result=sandbox_probe();atomic(root/'artifacts/sandbox-probe.json',result)
    elif args.command=='memory-discover':result=Memory(root).discover()
    elif args.command=='memory-selftest':
        result=Memory(root).persist('PROMETHEUS synthetic infrastructure selftest: local KG store and exact entity recall; not evidence of learning.',
                    {'kind':'synthetic-infrastructure-smoke','approved_by':'user','mastery_authorized':False},approved=True,infrastructure=True)
        atomic(root/'artifacts/memory-smoke.json',result)
    elif args.command=='baseline-report':
        from .evaluation import baseline_report
        result=baseline_report([]);result['runtime_blocked_reasons']=gates(controller.config);result['runtime_status']='BLOCKED'
        atomic(root/'artifacts/baseline-missing-data.json',result)
    elif args.command in ('discover','task-get','task-cancel','task-poll'):
        token=os.environ.get('PROMETHEUS_A2A_TOKEN','')
        client=A2AClient(args.endpoint,token,audit=Audit(root,(token,)),fixture=getattr(args,'fixture',False),timeout=5)
        if args.command=='discover': result=client.discover()
        elif args.command=='task-get':result=client.extract(client.get(args.task_id))
        elif args.command=='task-cancel':result=client.cancel(args.task_id)
        else:result=client.wait_or_cancel(args.task_id)
    elif args.command=='create':result=controller.create(args.task_id,args.holdout_id)
    elif args.command=='show':result=controller.status(args.run_id)
    elif args.command=='ingest':result=controller.ingest(args.run_id,load(args.response))
    elif args.command=='advance':result=controller.advance(args.run_id)
    elif args.command=='grade':result=controller.grade_latest(args.run_id)
    elif args.command=='live-step':result=controller.live_step(args.run_id,os.environ.get('PROMETHEUS_A2A_TOKEN',''))
    elif args.command=='approve-lesson':result=controller.approve_lesson(args.run_id,args.content.read_text(),args.reviewer,load(args.review))
    elif args.command=='teacher-lesson':result=controller.ingest_teacher_lesson(args.run_id,args.content.read_text(),args.session_id,args.reviewer)
    elif args.command=='settle-cost':result=controller.settle_cost(args.sequence,args.cost,args.tokens,load(args.receipt),args.reviewer)
    elif args.command=='review-prerequisite':result=controller.review_prerequisite(args.lesson_id,load(args.review))
    print(json.dumps(redact(result,(os.environ.get('PROMETHEUS_A2A_TOKEN',''),)),indent=2,allow_nan=False))
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except (BridgeError,ValueError,RuntimeError,OSError) as exc:
        print(json.dumps({'status':'BLOCKED','code':getattr(exc,'code',type(exc).__name__),'error':str(exc),
                          'ambiguous':getattr(exc,'ambiguous',False)}),file=sys.stderr);sys.exit(2)

"""Durable controller and explicit fail-closed evidence gates."""
from __future__ import annotations
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import math
import tempfile
import uuid

ROOT = Path(__file__).resolve().parent.parent
METRICS = ('factual_correctness','source_reliability','citation_accuracy','math','tool_call_validity','misleading_detection','error_recovery','uncertainty','generalization','completion')

def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def redact(value, secrets=()):
    if isinstance(value,dict):
        return {k:('[REDACTED]' if re.search(r'(?i)(token|secret|password|api.?key|authorization|credential)',str(k)) else redact(v,secrets)) for k,v in value.items()}
    if isinstance(value,list):
        return [redact(x,secrets) for x in value]
    if isinstance(value,str):
        for secret in secrets:
            if secret:
                value=value.replace(secret,'[REDACTED]')
        value=re.sub(r'(?i)Bearer\s+[^\s"\']+','Bearer [REDACTED]',value)
        value=re.sub(r'\b(?:sk-[A-Za-z0-9_-]{12,}|[0-9]{6,}:[A-Za-z0-9_-]{20,})\b','[REDACTED]',value)
    return value

def load(path,cap=4_000_000):
    with Path(path).open('rb') as stream:
        raw=stream.read(cap+1)
    if len(raw)>cap:
        raise ValueError('JSON exceeds size cap')
    def invalid(value): raise ValueError('Nonfinite JSON constant')
    return json.loads(raw,parse_constant=invalid)

def atomic(path,value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.atomic-')
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(name,path)
        directory=os.open(path.parent,os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(name): os.unlink(name)

class Audit:
    def __init__(self,root=ROOT,secrets=()):
        self.path=Path(root)/'artifacts/audit.jsonl'; self.secrets=secrets
    def __call__(self,event,**data):
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        row=redact({'time':utc(),'event':event,**data},self.secrets)
        fd=os.open(self.path,os.O_WRONLY|os.O_APPEND|os.O_CREAT,0o600)
        with os.fdopen(fd,'a') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX)
            stream.write(json.dumps(row,sort_keys=True)+'\n'); stream.flush(); os.fsync(stream.fileno())

DEFAULT_CONFIG={
 'teacher':{'selected_label':'omniroute/gpt-6.1-sol-high','advertised_id':None,'routing_identity_verified':False,'upstream_identity':'UNKNOWN'},
 'student':{'selected_label':'antigravity/gemini-3.8-flash-high','reasoning':'high','effective_reasoning_verified':False,'upstream_identity':'UNKNOWN'},
 'budget':{'authorized':False,'currency':None,'limit':None,'max_calls':0,'max_tokens':0,'pricing_verified':False},
 'transport':{'endpoint':'http://127.0.0.1:9900/','card_verified':False,'fixture':False},
 'isolation':{'mode':'tools-disabled','tools_disabled_verified':False,'os_sandbox_verified':False}}

def gates(config, *, calls=0, spent=0, tokens=0):
    reasons=[]; b=config.get('budget',{}); t=config.get('teacher',{}); s=config.get('student',{})
    limit=b.get('limit')
    if b.get('authorized') is not True or type(limit) not in (int,float) or not math.isfinite(limit) or limit<=0 or not b.get('currency'):
        reasons.append('NO_QUANTIFIED_PAID_INFERENCE_AUTHORIZATION')
    if not b.get('pricing_verified'): reasons.append('COST_PRICING_UNKNOWN')
    if type(b.get('max_calls')) is not int or b.get('max_calls',0)<=calls: reasons.append('CALL_BUDGET_UNAVAILABLE_OR_EXHAUSTED')
    if type(b.get('max_tokens')) is not int or b.get('max_tokens',0)<=tokens: reasons.append('TOKEN_BUDGET_UNAVAILABLE_OR_EXHAUSTED')
    if type(limit) in (int,float) and math.isfinite(limit) and spent>=limit: reasons.append('COST_BUDGET_EXHAUSTED')
    if t.get('selected_label')!='omniroute/gpt-6.1-sol-high' or not t.get('routing_identity_verified') or not t.get('advertised_id'):
        reasons.append('TEACHER_SELECTED_LABEL_LIVE_REGISTRY_MISMATCH_UNRESOLVED')
    if s.get('selected_label')!='antigravity/gemini-3.8-flash-high' or s.get('reasoning')!='high' or not s.get('effective_reasoning_verified'):
        reasons.append('EXACT_STUDENT_HIGH_REASONING_UNVERIFIED')
    tr=config.get('transport',{})
    if not tr.get('card_verified') or tr.get('fixture'): reasons.append('REAL_A2A_TRANSPORT_UNAVAILABLE')
    isolation=config.get('isolation',{})
    if isolation.get('mode')=='tools-disabled':
        if not isolation.get('tools_disabled_verified'): reasons.append('TOOLS_DISABLED_POLICY_UNVERIFIED')
    elif isolation.get('mode')!='sandbox' or not isolation.get('os_sandbox_verified'):
        reasons.append('OS_ISOLATION_UNVERIFIED')
    return reasons

class Controller:
    phases=('baseline','teach','practice','evaluate','remediate','persist','fresh_holdout','complete')
    def __init__(self,root=ROOT):
        self.root=Path(root); self.audit=Audit(root)
        self.config=load(self.root/'config.json') if (self.root/'config.json').exists() else DEFAULT_CONFIG
    def _path(self,run_id):
        if not re.fullmatch(r'[0-9a-f]{32}',run_id): raise ValueError('Invalid run id')
        return self.root/'artifacts/runs'/f'{run_id}.json'
    @contextlib.contextmanager
    def _locked(self,run_id):
        path=self._path(run_id); path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(str(path)+'.lock',os.O_CREAT|os.O_RDWR,0o600)
        with os.fdopen(fd,'r+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            yield path
    def create(self,task_id):
        from .evaluation import export_task
        public=export_task(task_id,self.root)
        run={'id':uuid.uuid4().hex,'task_id':task_id,'created_at':utc(),'phase':'baseline','status':'BLOCKED',
             'blocked_reasons':gates(self.config),'revisions':[],'remediations':0,'events':[],
             'metrics':{k:{'value':None,'status':'INSUFFICIENT_DATA'} for k in METRICS},
             'task_sha256':digest(public),'selected_models':self.config['teacher']|{'student':self.config['student']},
             'cost':{'spent':0,'calls':0,'tokens':0,'receipts':[]},'lesson':None}
        atomic(self._path(run['id']),run); self.audit('run_created',run_id=run['id'],blocked_reasons=run['blocked_reasons'])
        return run
    def status(self,run_id): return load(self._path(run_id))
    def ingest(self,run_id,response, *, source='operator-import'):
        """Retain real supplied output, explicitly untrusted: cannot produce execution receipts."""
        if source!='operator-import': raise ValueError('Only operator-import evidence accepted here')
        with self._locked(run_id) as path:
            run=load(path)
            if run['phase']=='complete': raise ValueError('Run already complete')
            artifact={'source':source,'trust':'SELF_REPORTED_UNVERIFIED','time':utc(),'phase':run['phase'],
                      'raw_response':response,'sha256':digest(response),'revision':len(run['revisions'])+1}
            run['revisions'].append(artifact); run['status']='INSUFFICIENT_DATA'
            run['events'].append({'time':utc(),'event':'ingested','sha256':artifact['sha256']})
            atomic(path,run); self.audit('offline_ingest',run_id=run_id,revision=artifact['revision'],sha256=artifact['sha256'])
            return artifact

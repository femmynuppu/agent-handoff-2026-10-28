import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from prometheus.core import DEFAULT_CONFIG, atomic, gates, load, redact
from prometheus.controller import Controller, METRICS

class CoreTests(unittest.TestCase):
    def test_numeric_authorization_fail_closed(self):
        for value in (True,float('nan'),float('inf'),-1,0):
            c=copy.deepcopy(DEFAULT_CONFIG);c['budget'].update(authorized=True,limit=value,currency='USD')
            self.assertIn('NO_QUANTIFIED_PAID_INFERENCE_AUTHORIZATION',gates(c))
    def test_redaction_and_strict_json(self):
        self.assertNotIn('sensitive',json.dumps(redact({'authorization':'sensitive','text':'Bearer sensitive'},('sensitive',))))
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.json';p.write_text('{"x":NaN}')
            with self.assertRaises(ValueError):load(p)
    def test_import_not_receipt_or_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            c=Controller(d);run={'id':'a'*32,'phase':'persist','revisions':[{'phase':'practice','source':'operator-import'}]}
            atomic(c._path(run['id']),run)
            with self.assertRaises(ValueError):c.approve_lesson(run['id'],'lesson','reviewer')
    def test_run_ids_cannot_escape(self):
        with self.assertRaises(ValueError):Controller().status('../../secret')
    def test_unknown_cost_blocks_subsequent_request(self):
        with tempfile.TemporaryDirectory() as d:
            c=Controller(d);c.config=copy.deepcopy(DEFAULT_CONFIG)
            c.config['budget'].update(authorized=True,limit=1,currency='USD',max_calls=5,max_tokens=1000,pricing_verified=True,per_call_max_cost=.1,per_call_max_tokens=100,provider_enforced_token_cap_verified=True)
            c.config['teacher'].update(routing_identity_verified=True,advertised_id='verified-label')
            c.config['student']['effective_reasoning_verified']=True;c.config['transport']['card_verified']=True
            c.config['isolation']['tools_disabled_verified']=True
            c._reserve({'id':'a'*32})
            with self.assertRaisesRegex(ValueError,'PREVIOUS_CALL_COST_RECEIPT_UNKNOWN'):c._reserve({'id':'a'*32})
            with self.assertRaises(ValueError):c.settle_cost(1,.2,10,{'run_id':'a'*32,'sequence':1,'provider_receipt_id':'fixture'},'reviewer')
            c.settle_cost(1,.05,10,{'run_id':'a'*32,'sequence':1,'provider_receipt_id':'fixture'},'reviewer')
            self.assertEqual(c._reserve({'id':'a'*32})['sequence'],2)
    def test_remediation_limit_and_success_branch(self):
        for passed,expected in ((True,'persist'),(False,'complete')):
            with tempfile.TemporaryDirectory() as d:
                c=Controller(d);run={'id':'a'*32,'phase':'evaluate','revisions':[{'phase':'practice'}],
                                    'events':[],'remediations':3,'status':'RESPONSE_OBSERVED'}
                atomic(c._path(run['id']),run)
                with patch.object(c,'_grade',return_value={'result':{'deterministic_pass':passed}}):
                    self.assertEqual(c.advance(run['id'])['phase'],expected)
    def test_metrics_contract(self):
        self.assertEqual(len(METRICS),10);self.assertIn('misleading_detection',METRICS)
    def test_previous_practice_and_remediation_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as d:
            c=Controller(d)
            for phase in ('practice','remediate'):
                run={'id':'b'*32,'phase':phase,'phase_cursor':1,'revisions':[{'phase':phase,'raw_response':{}}],
                     'events':[],'remediations':1,'status':'INSUFFICIENT_DATA'}
                atomic(c._path(run['id']),run)
                with self.assertRaisesRegex(ValueError,'no real artifact'):c.advance(run['id'])
    def test_planned_dependent_lesson_blocked_without_review(self):
        from prometheus.core import ROOT
        c=Controller(ROOT)
        reasons=c.prerequisite_reasons({'lesson_id':'L06'})
        self.assertIn('PREREQUISITE_REVIEW_MISSING:L05',reasons)
        self.assertIn('PREREQUISITE_REVIEW_MISSING:L04',reasons)
    def test_failed_execution_does_not_resubmit(self):
        with tempfile.TemporaryDirectory() as d:
            c=Controller(d);atomic(c._path('c'*32),{'phase':'baseline','status':'EXECUTION_FAILED'})
            with self.assertRaisesRegex(ValueError,'cannot resubmit'):c.live_step('c'*32,'token')
    def test_failure_latch_survives_import_display_status(self):
        with tempfile.TemporaryDirectory() as d:
            c=Controller(d);identifier='d'*32
            atomic(c._path(identifier),{'id':identifier,'phase':'baseline','task_id':'B01','status':'EXECUTION_FAILED',
                'execution_failure':{'ambiguous':True},'revisions':[],'events':[]})
            c.ingest(identifier,{'fixture':True,'not_student_output':True})
            self.assertEqual(c.status(identifier)['status'],'INSUFFICIENT_DATA')
            self.assertTrue(c.status(identifier)['execution_failure'])
            with self.assertRaisesRegex(ValueError,'cannot resubmit'):c.live_step(identifier,'token')
            with self.assertRaisesRegex(ValueError,'execution failure'):c.advance(identifier)
            with self.assertRaisesRegex(ValueError,'failure latch'):c.approve_lesson(identifier,'x','reviewer')

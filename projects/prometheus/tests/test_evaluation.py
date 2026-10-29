"""Offline consumer-visible grading tests; no student/model calls."""
import copy
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from prometheus.evaluation import (
    DEFAULT_ROOT, DOMAINS, METRICS, CalculatorRecoveryScenario, baseline_report, execute_calculation,
    export_task, grade_response, load_json, validate_curriculum,
)


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = load_json(DEFAULT_ROOT / 'references/private/tasks.json')
        cls.refs = load_json(DEFAULT_ROOT / 'references/private/solutions.json')

    def answer(self, tid):
        response = copy.deepcopy(self.refs[tid]['solution'])
        task = self.tasks[tid]
        if 'citations' in task['response_schema']['required']:
            response['citations'] = [
                {'source_id': sid, 'locator': src['locator'], 'quote': src['text']}
                for sid, src in task['source_packet'].items()
            ]
        return response

    def grade(self, tid, response, receipts=None):
        return grade_response(self.tasks[tid], self.refs[tid], response, receipts)

    def test_curriculum_graph_and_coverage(self):
        result = validate_curriculum(DEFAULT_ROOT)
        self.assertTrue(result['valid'], result['errors'])
        self.assertEqual(result['lesson_count'], 10)
        self.assertEqual(set(result['domains']), set(DOMAINS))

    def test_factual_countermodel_and_nested_boolean_distinction(self):
        response = self.answer('B01')
        self.assertTrue(self.grade('B01', response)['deterministic_pass'])
        response['countermodel']['wet'] = 0
        self.assertFalse(self.grade('B01', response)['deterministic_pass'])

    def test_numeric_correct_wrong_and_tolerance(self):
        response = self.answer('B04')
        self.assertTrue(self.grade('B04', response)['deterministic_pass'])
        response['mean'] += 1e-10
        self.assertTrue(self.grade('B04', response)['deterministic_pass'])
        response['mean'] += .1
        self.assertFalse(self.grade('B04', response)['deterministic_pass'])

    def test_numeric_boolean_nonfinite_and_nonjson_rejected(self):
        for bad in [True, float('nan'), float('inf'), float('-inf'), (1, 2), {1, 2}]:
            with self.subTest(value=repr(bad)):
                response = self.answer('B04')
                response['mean'] = bad
                result = self.grade('B04', response)
                self.assertFalse(result['deterministic_pass'])
                self.assertFalse(result['mastery_authorized'])

    def test_strict_json_parser(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'response.json'
            for text in ['{"x":NaN}', '{"x":Infinity}', '{"x":1e999}', '{"x":1,"x":2}']:
                path.write_text(text)
                with self.assertRaises(ValueError):
                    load_json(path)

    def test_frozen_citation_quote_locator_and_extra_invalid_citation(self):
        response = self.answer('B02')
        self.assertTrue(self.grade('B02', response)['deterministic_pass'])
        response['citations'][0]['locator'] = 'invented'
        self.assertFalse(self.grade('B02', response)['deterministic_pass'])
        response = self.answer('B02')
        response['citations'][0]['quote'] = 'PROV-DM'
        self.assertFalse(self.grade('B02', response)['deterministic_pass'])
        response = self.answer('B02')
        response['citations'].append({'source_id': 'invented', 'locator': '', 'quote': ''})
        self.assertFalse(self.grade('B02', response)['deterministic_pass'])

    def test_probability_brier_validity_not_calibration(self):
        response = self.answer('B10')
        response['forecast'] = .8
        result = self.grade('B10', response)
        self.assertTrue(result['deterministic_pass'])
        self.assertAlmostEqual(result['metrics']['uncertainty']['value'], .64)
        for bad in [-.01, 1.01, True]:
            response['forecast'] = bad
            result = self.grade('B10', response)
            self.assertFalse(result['deterministic_pass'])
            self.assertIsNone(result['metrics']['uncertainty']['value'])

    def test_completion_is_schema_not_semantic_mastery(self):
        response = self.answer('B04')
        del response['median']
        self.assertEqual(self.grade('B04', response)['metrics']['completion']['value'], 0)
        response = self.answer('B04')
        response['tool_used'] = True
        self.assertFalse(self.grade('B04', response)['deterministic_pass'])
        response = self.answer('B04')
        response['rationale'] = ' '
        self.assertFalse(self.grade('B04', response)['deterministic_pass'])

    def tool_response(self):
        response = self.answer('B08')
        response['tool_calls'] = [
            {'call_id': 'failed-test', 'tool': 'calculator', 'operation': 'multiply', 'operands': [6, 7],
             'status': 'failed', 'error_code': 'temporary_unavailable'},
            {'call_id': 'call-test', 'tool': 'calculator', 'operation': 'multiply', 'operands': [6, 7], 'result': 42}]
        return response

    def test_local_receipts_observed_imported_and_mutated_not_trusted(self):
        response = self.tool_response()
        scenario = CalculatorRecoveryScenario('B08', 'multiply', [6, 7])
        failure = scenario.call('failed-test')
        receipt = scenario.call('call-test')
        local = self.grade('B08', response, scenario.receipts)
        self.assertTrue(local['deterministic_pass'])
        self.assertEqual(local['metrics']['tool_call_validity']['value'], 1)
        self.assertEqual(local['metrics']['error_recovery']['value'], 1)
        self.assertFalse(local['mastery_authorized'])
        for imported in [json.loads(json.dumps(scenario.receipts)), copy.deepcopy(scenario.receipts), [True]]:
            result = self.grade('B08', response, imported)
            self.assertFalse(result['deterministic_pass'])
            self.assertIsNone(result['metrics']['tool_call_validity']['value'])
        receipt['result']['value'] = True
        self.assertFalse(self.grade('B08', response, [receipt])['deterministic_pass'])

    def test_receipt_wrong_task_arguments_call_and_boolean_result(self):
        response = self.tool_response()
        for task, cid, operation, operands in [('H08','call-test','multiply',[6,7]),
                                              ('B08','other','multiply',[6,7]),
                                              ('B08','call-test','add',[6,7])]:
            receipt = execute_calculation(task, cid, operation, operands)
            self.assertFalse(self.grade('B08', response, [receipt])['deterministic_pass'])
        with self.assertRaises(ValueError):
            execute_calculation('B08','x','add',[True,7])
        with self.assertRaises(ZeroDivisionError):
            execute_calculation('B08','x','divide',[1,0])
        with self.assertRaises(ValueError):
            execute_calculation('B08','x','shell',[1,2])
        response['tool_calls'][0]['result'] = True
        receipt = execute_calculation('B08','call-test','multiply',[6,7])
        self.assertFalse(self.grade('B08',response,[receipt])['deterministic_pass'])

    def test_recovery_requires_diagnosis_event_order_and_actual_failure(self):
        response = self.tool_response()
        runner = CalculatorRecoveryScenario('B08', 'multiply', [6, 7])
        first = runner.call('failed-test')
        self.assertEqual(first['result']['status'], 'failed')
        runner.call('call-test')
        self.assertTrue(self.grade('B08', response, runner.receipts)['deterministic_pass'])
        with self.assertRaises(ValueError):
            runner.call('third-call')
        response['recovery_diagnosis'] = 'bad_operand'
        self.assertFalse(self.grade('B08', response, runner.receipts)['deterministic_pass'])
        response = self.tool_response()
        response['tool_calls'].reverse()
        self.assertFalse(self.grade('B08', response, runner.receipts)['deterministic_pass'])
        response = self.tool_response()
        imported = json.loads(json.dumps(runner.receipts))
        grade = self.grade('B08', response, imported)
        self.assertFalse(grade['deterministic_pass'])
        self.assertIsNone(grade['metrics']['error_recovery']['value'])
        # A successful call without an actual preceding failure is not recovery.
        receipt = execute_calculation('B08', 'call-test', 'multiply', [6, 7])
        grade = self.grade('B08', response, [receipt])
        self.assertFalse(grade['deterministic_pass'])

    def test_unknown_task_missing_reference(self):
        with self.assertRaises(ValueError):
            export_task('UNKNOWN')
        result = grade_response({}, {}, {})
        self.assertEqual(result['status'], 'INVALID_INPUT')
        self.assertFalse(result['deterministic_pass'])

    def test_baseline_missing_metrics_and_duplicate_exclusion(self):
        empty = baseline_report([])
        self.assertEqual(empty['status'], 'INSUFFICIENT_DATA')
        self.assertEqual(empty['run_status'], 'NO_REPORTS')
        self.assertIsNone(empty['student_run_count'])
        self.assertEqual(empty['descriptive_report_count'], 0)
        self.assertEqual(set(empty['metrics']), set(METRICS))
        self.assertTrue(all(m['value'] is None and m['status'] == 'NOT_MEASURED' for m in empty['metrics'].values()))
        row = self.grade('B04', self.answer('B04'))
        summary = baseline_report([row, row])
        self.assertEqual(summary['unique_tasks'], 1)
        self.assertEqual(summary['excluded'][0]['reason'], 'REPEATED_TASK_NOT_INDEPENDENT')
        self.assertIsNone(summary['metrics']['generalization']['value'])
        self.assertIsNone(summary['reliability'])

    def test_report_malformed_metrics_and_invalid_inputs_separated(self):
        row = self.grade('B04', self.answer('B04'))
        for metric in [True, [], {'status': 'MEASURED', 'value': 2, 'numerator': 2, 'denominator': 1},
                       {'status': 'MEASURED', 'value': .5, 'numerator': True, 'denominator': 2},
                       {'status': 'MEASURED', 'value': .5, 'numerator': 1, 'denominator': 0}]:
            with self.subTest(metric=metric):
                malformed = copy.deepcopy(row)
                malformed['metrics']['math'] = metric
                report = baseline_report([malformed])
                self.assertIsNone(report['metrics']['math']['value'])
                self.assertTrue(report['metric_errors'])
                self.assertIsNone(report['student_run_count'])
        invalid = copy.deepcopy(row)
        invalid['status'] = 'INVALID_INPUT'
        invalid['deterministic_pass'] = False
        report = baseline_report([invalid])
        self.assertEqual(report['descriptive_report_count'], 0)
        self.assertEqual(len(report['invalid_input_reports']), 1)

    def test_validator_rejects_manifest_tamper_and_unknown_checks(self):
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DEFAULT_ROOT / 'curriculum', root / 'curriculum')
            shutil.copytree(DEFAULT_ROOT / 'references', root / 'references')
            path = root / 'references/manifest.json'
            manifest = load_json(path)
            manifest['sources'][0]['quote'] = 'tampered'
            path.write_text(json.dumps(manifest))
            self.assertFalse(validate_curriculum(root)['valid'])
            path = root / 'references/private/solutions.json'
            refs = load_json(path)
            refs['B04']['checks'][0]['kind'] = 'unimplemented'
            path.write_text(json.dumps(refs))
            errors = validate_curriculum(root)['errors']
            self.assertTrue(any('reference check' in error for error in errors))

    def test_allowlisted_export_hides_private_fields(self):
        packet = export_task('H01')
        self.assertNotIn('checks', packet)
        self.assertNotIn('solution', packet)
        self.assertNotIn('human_review', packet)
        self.assertNotIn('split', packet)
        self.assertNotIn('private', json.dumps(packet))
        self.assertFalse(any('/home/' in str(v) for v in packet.values()))

    def test_balanced_misleading_detection(self):
        response = self.answer('B09')
        result = self.grade('B09', response)
        self.assertEqual(result['metrics']['misleading_detection']['confusion'], {'tp': 1, 'tn': 1})
        for key in response['labels']:
            response['labels'][key] = 'misleading'
        result = self.grade('B09', response)
        self.assertFalse(result['deterministic_pass'])
        self.assertEqual(result['metrics']['misleading_detection']['precision'], .5)

    def test_cli_commands_and_invalid_response(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'response.json'
            commands = [(['validate-curriculum'],0), (['export-task','B04'],0),
                        (['export-task','UNKNOWN'],2), (['baseline-report'],0)]
            for args, code in commands:
                run = subprocess.run([sys.executable,'-m','prometheus.evaluation',*args],
                                     cwd=DEFAULT_ROOT,capture_output=True,text=True)
                self.assertEqual(run.returncode, code, run.stdout + run.stderr)
                json.loads(run.stdout)
            for value, code in [(self.answer('B04'),0), ({'mean':999},1)]:
                path.write_text(json.dumps(value))
                run = subprocess.run([sys.executable,'-m','prometheus.evaluation','grade',
                                      '--task-id','B04','--response',str(path)],
                                     cwd=DEFAULT_ROOT,capture_output=True,text=True)
                self.assertEqual(run.returncode,code,run.stdout+run.stderr)
            path.write_text('{"mean":NaN}')
            run = subprocess.run([sys.executable,'-m','prometheus.evaluation','grade',
                                  '--task-id','B04','--response',str(path)],
                                 cwd=DEFAULT_ROOT,capture_output=True,text=True)
            self.assertEqual(run.returncode,2,run.stdout+run.stderr)


if __name__ == '__main__':
    unittest.main()

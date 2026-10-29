import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from prometheus.memory import Memory, SCRIPT
from prometheus.core import atomic,digest

class MemoryTests(unittest.TestCase):
    def test_explicit_installed_path_before_dispatch(self):
        self.assertLess(SCRIPT.index('_apply_server_flags'),SCRIPT.index('handle_request'))
        self.assertLess(SCRIPT.index('KG_PATH_MISMATCH'),SCRIPT.index('handle_request'))
    def test_pointer_escape_and_tampering_refused(self):
        with tempfile.TemporaryDirectory() as d:
            m=Memory(d);identifier='prometheus:lesson:'+'a'*32
            with patch.object(m,'_call',return_value={'facts':[{'predicate':'lesson_file','object':'/etc/passwd'}]}):
                with self.assertRaisesRegex(RuntimeError,'OUTSIDE_PROJECT'):m.retrieve(identifier)
            p=Path(d)/'memory/lessons'/('a'*32+'.json');atomic(p,{'content':'original'})
            facts=[{'predicate':'lesson_file','object':str(p)},{'predicate':'sha256','object':digest({'content':'other'})}]
            with patch.object(m,'_call',return_value={'facts':facts}):
                with self.assertRaisesRegex(RuntimeError,'INTEGRITY'):m.retrieve(identifier)
    def test_unverified_boolean_cannot_authorize_lesson(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):Memory(d).persist('not verified',{'verified_for_persistence':True},approved=True)

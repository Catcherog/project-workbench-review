"""Lifecycle faults cannot silently unload an unbound model or reopen work."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from am_training_window.ollama import OllamaLifecycle
from am_training_window.window import HostBinding, ModelIdentity, WindowError


class OllamaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.binary=Path(self.tmp.name)/'ollama';self.binary.write_bytes(b'synthetic')
        self.binding=HostBinding('123','1'*64,ModelIdentity('original-q8','2'*64),'llamacpp')
        self.loaded=True;self.worker=True;self.calls=[];self.context=16384
        self.tag_digest='2'*64;self.extra=False;self.generated=False
        self.lifecycle=OllamaLifecycle(manager_binary=self.binary,manager_pid=42,version='fixed',
            request=self.request,workers=lambda:[{'pid':43}] if self.worker else [])
        self.manager=patch.object(self.lifecycle,'verify_manager');self.manager.start()
    def tearDown(self):self.manager.stop();self.tmp.cleanup()
    def request(self,path,payload=None,timeout=5):
        if path=='/api/tags':return {'models':[{'name':'original-q8','digest':self.tag_digest,'details':{'runner':'llamacpp'}}]}
        if path=='/api/ps':
            rows=[{'name':'original-q8','digest':'2'*64,'context_length':self.context}] if self.loaded else []
            if self.extra:rows.append({'name':'foreign','digest':'3'*64})
            return {'models':rows}
        self.calls.append(payload)
        self.loaded=self.worker=payload['keep_alive']!=0
        return {'done':True,'response':'unexpected' if self.generated else ''}
    def test_unload_and_restore_preserve_name_context_and_manager(self):
        self.lifecycle.suspend(self.binding);self.assertFalse(self.loaded)
        self.lifecycle.restore(self.binding);self.assertTrue(self.loaded)
        self.assertEqual([x['keep_alive'] for x in self.calls],[0,'30m'])
        self.assertTrue(all(x['model']=='original-q8' and x['prompt']=='' and x['options']=={'num_ctx':16384} for x in self.calls))
    def test_foreign_model_never_mutated(self):
        self.extra=True
        with self.assertRaises(WindowError):self.lifecycle.suspend(self.binding)
        self.assertEqual(self.calls,[])
    def test_changed_digest_never_mutated(self):
        self.tag_digest='4'*64
        with self.assertRaises(WindowError):self.lifecycle.suspend(self.binding)
        self.assertEqual(self.calls,[])
    def test_changed_context_never_mutated(self):
        self.context=4096
        with self.assertRaises(WindowError):self.lifecycle.suspend(self.binding)
        self.assertEqual(self.calls,[])
    def test_unlisted_worker_does_not_get_second_load(self):
        self.loaded=False
        with self.assertRaises(WindowError):self.lifecycle.restore(self.binding)
        self.assertEqual(self.calls,[])
    def test_management_generation_is_not_success(self):
        self.generated=True
        with self.assertRaises(WindowError):self.lifecycle.suspend(self.binding)
        self.assertEqual(self.lifecycle.events,[])
    def test_restore_and_unload_are_idempotent(self):
        self.lifecycle.restore(self.binding);self.assertEqual(self.calls,[])
        self.lifecycle.suspend(self.binding);self.lifecycle.suspend(self.binding)
        self.assertEqual(len(self.calls),1)

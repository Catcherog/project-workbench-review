import unittest
from am_conversation.tools import Tool, ToolRegistry, obj, string
from am_conversation.types import AccessContext
from am_harness.registry_adapter import AmRegistryAdapter
from am_harness.tool_policy import ToolExecutor, ToolInvocation


class RegistryAdapterTests(unittest.TestCase):
    def test_real_registry_retains_schema_project_and_external_gate(self):
        registry=ToolRegistry();calls=[];operations=[]
        params=obj({"project_id":string(256)},("project_id",))
        registry.register(Tool("read_it","read",params,lambda c,a,e:calls.append(e) or {"value":"recorded"}))
        registry.register(Tool("send_it","send",params,lambda c,a,e:calls.append("UNEXPECTED"),"external",True,lambda c,a:"preview"))
        ctx=AccessContext("t","a","u","c",allowed_project_ids=frozenset({"p1"}),is_owner=True)
        adapted=AmRegistryAdapter(registry,ctx,"event",authorize=lambda c,op,a:operations.append(op))
        out=ToolExecutor().execute([
            ToolInvocation("1","read_it",{"project_id":"p1"}),
            ToolInvocation("2","send_it",{"project_id":"p1"}),
            ToolInvocation("3","read_it",{"project_id":"p2"}),
            ToolInvocation("4","read_it",{"project_id":"p1","extra":"invalid"})],
            resolve=adapted.resolve,authorize=adapted.authorize,guard=lambda:None)
        self.assertEqual([r.status for r in out],["succeeded","requires_approval","failed","failed"])
        self.assertEqual(calls,["event"])
        self.assertIn("read",operations)
        self.assertIn("manage",operations)

    def test_host_cannot_mark_local_effect_parallel(self):
        registry=ToolRegistry()
        registry.register(Tool("write_note","note",obj({}),lambda c,a,e:None,"local"))
        ctx=AccessContext("t","a","u","c")
        adapted=AmRegistryAdapter(registry,ctx,"event",authorize=lambda *a:None,
                                  independent_read_tools=frozenset({"write_note"}))
        with self.assertRaisesRegex(ValueError,"PARALLEL_DECLARATION_NOT_READ_ONLY"):
            adapted.resolve("write_note",{})

"""Explicit, synthetic owner-only platform probe; not a business or group send."""
import pathlib,json,logging,sys
ROOT=pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src'))
import lark_oapi as lark
from lark_oapi.api.im.v1 import CreateMessageRequest,CreateMessageRequestBody
from fs_agent.config import Config
from fs_agent.card_ui import card,field,button,paragraph
logging.disable(logging.CRITICAL)
root=pathlib.Path.home()/'.local/share/local-qwen-feishu';c=Config.load(root/'poc/config/environment.json')
items=[]
for spec in [('people','合成人员','multi_select_static',[('a','合成人员甲'),('b','合成人员乙')],['a']),('body','合成正文','input',None,'仅验证表单格式，不生成计划或发送群消息。'),('when','北京时间','picker_datetime',None,'2026-10-30 09:00'),('frequency','频率','select_static',[('once','仅一次'),('daily','每天')],'once')]:
    name,label,kind,options,default=spec;items+=field(name,label,kind=kind,options=options,default=default)
items.append(button('格式验证（不执行业务）',{'flow':'ux1_format_probe'},name='submit',submit=True))
content=card('UX1 合成表单格式验证',[paragraph('仅验证飞书表单组件，未创建提醒、订阅或挂载。'),{'tag':'form','name':'probe_form','elements':items}])
client=lark.Client.builder().app_id(c.app_id).app_secret(c.app_secret_file.read_text().strip()).timeout(20).log_level(lark.LogLevel.CRITICAL).build()
r=client.im.v1.message.create(CreateMessageRequest.builder().receive_id_type('open_id').request_body(CreateMessageRequestBody.builder().receive_id(c.owner).msg_type('interactive').content(json.dumps(content,ensure_ascii=False)).uuid('am-ux1-form-format-probe-20261029').build()).build())
print(json.dumps({'code':r.code,'message':r.msg,'sent_to_owner_only':r.success()},ensure_ascii=False))
p=root/'validation/am-self-20261029-ux1/form-platform-probe.json'
p.write_text(json.dumps({'code':r.code,'message':r.msg,'message_id':r.data.message_id if r.success() else None,'content':content},ensure_ascii=False));p.chmod(0o600)

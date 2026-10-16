from pathlib import Path
import json,hashlib,shutil,sys
root=Path(__file__).resolve().parents[1];formal=Path(sys.argv[1]).resolve();candidate=root/'dm/candidate';out=root/'install-candidate';out.mkdir(exist_ok=True)
h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
manifest=json.loads((candidate/'build-manifest.json').read_text());rows=[]
for entry in manifest['files']+[{'path':'build-manifest.json','sha256':h(candidate/'build-manifest.json')}]:
 rel=entry['path'];src=candidate/rel;base=formal/rel;before=h(base) if base.is_file() else None
 if before==h(src):continue
 dest=out/'payload'/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
 rows.append({'path':rel,'operation':'replace' if before else 'add','expectedBeforeSha256':before,'candidateSha256':h(src),'bytes':src.stat().st_size})
plan={'version':1,'task':'DIRECT-DM-01-READY1','state':'review-only-not-approved','automaticInstall':False,'automaticRestart':False,'automaticRegistration':False,'automaticSend':False,'baseRelease':json.loads((formal/'release.json').read_text()),'candidateRelease':json.loads((candidate/'release.json').read_text()),'databaseCapability':{'neverActivated':2,'afterApprovedRequestRegistration':3,'automaticDowngrade':False},'changes':rows,'protected':['.local-workbench/**','all credentials','running process','unrelated program files']}
(out/'INSTALL_PLAN.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
(out/'control.disabled.example.json').write_text(json.dumps({'version':1,'enabled':False,'note':'No real IDs, trust key, approval, ledger, or requests supplied. Enabling requires reviewed local provisioning.'},indent=2)+'\n')
print(json.dumps({'changedFiles':len(rows),'payloadBytes':sum(r['bytes'] for r in rows),'baseReadOnly':True}))

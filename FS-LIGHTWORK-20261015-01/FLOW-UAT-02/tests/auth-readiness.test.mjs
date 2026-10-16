import test from 'node:test';
import assert from 'node:assert/strict';
import {ensureLarkUserReady} from '../src/auth-readiness.mjs';
const status=(state='ready',id='test-actor')=>({brand:'feishu',identities:{user:{openId:id,status:state,available:true}}});
test('an existing ready session needs no extra read',()=>{
  const a=status();assert.equal(ensureLarkUserReady(a,'test-actor',()=>{throw Error('unexpected_read');}),a);
});
test('renewable session performs one authorized read and rechecks the same identity',()=>{
  let calls=0;const a=ensureLarkUserReady(status('needs_refresh'),'test-actor',()=>{calls++;return status();});
  assert.equal(calls,1);assert.equal(a.identities.user.status,'ready');
});
test('a different identity cannot trigger the refresh read',()=>{
  let calls=0;assert.throws(()=>ensureLarkUserReady(status('needs_refresh','another-user'),'test-actor',()=>{calls++;}),/identity_mismatch/);assert.equal(calls,0);
});
test('a changed identity after renewal still prevents writes',()=>{
  assert.throws(()=>ensureLarkUserReady(status('needs_refresh'),'test-actor',()=>status('ready','another-user')),/identity_mismatch/);
});
test('non-renewable or unsuccessful renewal does not become ready',()=>{
  assert.throws(()=>ensureLarkUserReady(status('unavailable'),'test-actor',()=>status()),/user_auth_not_ready/);
  assert.throws(()=>ensureLarkUserReady(status('needs_refresh'),'test-actor',()=>status('needs_refresh')),/user_auth_not_ready/);
});

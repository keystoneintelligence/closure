import test from 'node:test';
import assert from 'node:assert/strict';
import {requestJSON, VIEWER_API} from './api.js';

test('viewer negotiates API and forwards guarded write credentials', async () => {
  const result = await requestJSON('/api/verify', {project:'demo'}, 'session-token', async (path, options) => {
    assert.equal(path, '/api/verify');
    assert.equal(options.headers['X-Closure-API'], VIEWER_API);
    assert.equal(options.headers['X-Closure-Token'], 'session-token');
    assert.deepEqual(JSON.parse(options.body), {project:'demo'});
    return new Response('{"gate":true}', {headers:{'X-Closure-API':VIEWER_API}});
  });
  assert.equal(result.gate, true);
});

test('viewer refuses incompatible or old unversioned backend responses', async () => {
  for (const version of ['', 'closure-viewer/9']) {
    await assert.rejects(requestJSON('/api/project', undefined, '', async () =>
      new Response('{}', {headers:{'X-Closure-API':version}})), /versions differ/);
  }
});

test('viewer reports backend diagnostics without disguising failure', async () => {
  await assert.rejects(requestJSON('/api/verify', {}, '', async () =>
    new Response('{"error":{"code":"TRUST_REQUIRED","message":"Trust required"}}',
      {status:400,headers:{'X-Closure-API':VIEWER_API}})), /Trust required/);
});

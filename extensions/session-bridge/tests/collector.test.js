import { test } from 'node:test';
import assert from 'node:assert/strict';
import { bridgeRequest, capturePage, collectJob } from '../collector.js';
import { captureStorage } from '../session.js';

test('Cloudflare challenge is reported without returning verification HTML', async () => {
  globalThis.location = { pathname: '/search', href: 'https://www.pichau.com.br/search?q=ssd' };
  globalThis.document = {title:'Just a moment...',readyState:'complete',body:{innerText:'Verifying...'},querySelector:()=>null};
  try {
    const result=await capturePage();
    assert.equal(result.blocked,true);
    assert.equal(result.body,'<p>Por segurança, complete esta etapa</p>');
  } finally {delete globalThis.location;delete globalThis.document;}
});

test('captures ordinary DOM but excludes verification and password forms', async () => {
  globalThis.location = { origin: 'https://lista.mercadolivre.com.br', pathname: '/sofa', href: 'https://lista.mercadolivre.com.br/sofa' };
  globalThis.document = { readyState: 'complete', body: {innerText: 'Resultados'}, documentElement: {outerHTML: '<html>Resultados</html>'}, querySelector: () => null };
  try {
    assert.equal((await capturePage()).body, '<html>Resultados</html>');
    document.body.innerText = 'Por segurança, complete esta etapa';
    const captcha = await capturePage();
    assert.equal(captcha.blocked, true);
    assert.equal(captcha.body, '<p>Por segurança, complete esta etapa</p>');
    document.body.innerText = 'Login';
    document.querySelector = selector => selector === 'input[type="password"]' ? {} : null;
    assert.equal((await capturePage()).body, '');
  } finally { delete globalThis.location; delete globalThis.document; }
});

test('temporary storage accompanies origin without exporting password keys', () => {
  globalThis.location = { origin: 'https://lista.mercadolivre.com.br' };
  globalThis.localStorage = { token: 'test-token', password: 'never-export' };
  globalThis.sessionStorage = { challenge: 'test-session', senha: 'never-export' };
  try {
    const captured = captureStorage();
    assert.deepEqual(captured.sessionStorage, [{name:'challenge', value:'test-session'}]);
    assert.deepEqual(captured.localStorage, [{name:'token', value:'test-token'}]);
  } finally { delete globalThis.location; delete globalThis.localStorage; delete globalThis.sessionStorage; }
});

test('bridge only permits intended operations on exact authenticated app origin', async () => {
  globalThis.location = { origin: 'http://localhost:3000' };
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async (path, options) => {
    calls++;
    assert.equal(path, '/api/browser-connections/mercado_livre_br/local/next');
    assert.equal(options.credentials, 'same-origin');
    return {ok:true, status:200, json:async()=>({job_id:null})};
  };
  try {
    assert.equal((await bridgeRequest('http://localhost:3001', 'mercado_livre_br', 'next', {})).ok, false);
    assert.equal((await bridgeRequest(location.origin, 'mercado_livre_br', 'arbitrary', {})).ok, false);
    assert.equal(calls, 0);
    assert.equal((await bridgeRequest(location.origin, 'mercado_livre_br', 'next', {})).ok, true);
  } finally { globalThis.fetch = original; delete globalThis.location; }
});

test('collector reuses selected profile tab and focuses a challenge without returning its form', async () => {
  const operations = [];
  const url = 'https://lista.mercadolivre.com.br/sofa';
  const tab = {id:5, windowId:1, status:'complete', url, incognito:false};
  const browser = {
    tabs: { get:async()=>tab, update:async(id, options)=>{operations.push(options); return tab;}, create:async()=>assert.fail('Selected tab must be reused') },
    windows: {update:async()=>{}},
    scripting: {executeScript:async()=>[{result:{final_url:'https://www.mercadolivre.com.br/captcha/wall/logged', blocked:true, body:'<p>Por segurança, complete esta etapa</p>'}}]}
  };
  const result = await collectJob(browser, {collectorTab:5}, 'mercado_livre_br', {job_id:'test', url});
  assert.equal(result.blocked, true);
  assert.equal(operations[0].url, url);
  assert.equal(operations[1].active, true);
  await assert.rejects(collectJob(browser, {}, 'mercado_livre_br', {job_id:'test', url:'https://evil.test/'}), /inválida/);
});

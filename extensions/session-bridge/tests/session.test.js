import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { SOURCES, sourceFor, panoptesOrigin, hostPattern, convertCookies, importInPanoptes, openConnections, preparePanoptesTab, isFrameUnavailable } from '../session.js';

test('only Brazilian authenticated page locations are eligible', () => {
  assert.equal(sourceFor('https://www.mercadolivre.com.br/'), 'mercado_livre_br');
  assert.equal(sourceFor('https://www.amazon.com.br/'), 'amazon_br');
  assert.equal(sourceFor('https://lista.mercadolivre.com.br/sofa'), 'mercado_livre_br');
  assert.equal(sourceFor('https://produto.mercadolivre.com.br/MLB-1234567890-sofa-_JM'), 'mercado_livre_br');
  assert.equal(sourceFor('https://www.mercadolivre.com.br/captcha/wall/logged'), undefined);
  for (const url of ['https://www.mercadolivre.com.br.evil.test/', 'http://www.mercadolivre.com.br/', 'https://www.mercadolivre.com.br/login/identification', 'https://www.amazon.com.br/ap/signin', 'https://www.mercadolivre.com/'])
    assert.equal(sourceFor(url), undefined);
});

test('Panoptes host permissions omit ports but transfer keeps the precise origin', () => {
  assert.equal(panoptesOrigin('http://localhost:3000/'), 'http://localhost:3000');
  assert.equal(hostPattern('http://localhost:3000'), 'http://localhost/*');
  assert.equal(panoptesOrigin('https://panoptes.example/'), 'https://panoptes.example');
  for (const url of ['http://remote.example', 'https://user:pass@host/', 'https://host/connections', 'https://host/?token=x', 'file:///tmp']) assert.throws(() => panoptesOrigin(url));
});

const authCookie = { name: 'ssid', value: 'test-session', domain: '.mercadolivre.com.br', path: '/', secure: true, httpOnly: true, session: true, sameSite: 'no_restriction' };

test('hardware stores support verified public access without inventing account cookies', () => {
  assert.equal(sourceFor('https://www.pichau.com.br/search?q=ssd'), 'pichau_br');
  assert.equal(sourceFor('https://www.terabyteshop.com.br/produto/123/ssd'), 'terabyte_br');
  assert.equal(sourceFor('https://www.terabyteshop.com.br/Central.obj'), undefined);
  assert.equal(sourceFor('https://www.pichau.com.br/account'), undefined);
  assert.equal(sourceFor('https://www.pichau.com.br.evil.test/'), undefined);
  assert.deepEqual(convertCookies([], SOURCES.pichau_br), []);
  assert.deepEqual(convertCookies([], SOURCES.terabyte_br), []);
});

test('HttpOnly and Secure flags survive conversion; expired, partitioned and foreign cookies do not', () => {
  const cookies = convertCookies([authCookie, { ...authCookie, name: 'expired', session: false, expirationDate: 1 }, { ...authCookie, name: 'partitioned', partitionKey: { topLevelSite: 'https://other.test' } }, { ...authCookie, domain: '.evil.test' }, { ...authCookie, name: 'insecure', secure: false }], SOURCES.mercado_livre_br, 100);
  assert.equal(cookies.length, 2);
  assert.equal(cookies[0].httpOnly, true);
  assert.equal(cookies[0].sameSite, 'None');
  assert.equal(cookies[0].expires, -1);
  assert.equal(cookies[1].secure, false);
  assert.throws(() => convertCookies([{ ...authCookie, name: 'anonymous' }], SOURCES.mercado_livre_br));
});

test('manifest has an explicit collector worker, no automatic injection or broad required hosts', async () => {
  const manifest = JSON.parse(await readFile(new URL('../manifest.json', import.meta.url)));
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.content_scripts, undefined);
  assert.deepEqual(manifest.background, {service_worker: 'background.js', type: 'module'});
  assert.ok(!manifest.host_permissions.includes('<all_urls>'));
});

test('same-origin authenticated transfer rejects changed tabs and does not return tokens', async () => {
  globalThis.location = { origin: 'http://localhost:3000' };
  const originalFetch = globalThis.fetch;
  let called = false;
  globalThis.fetch = async (url, options) => {
    called = true;
    assert.equal(url, '/api/browser-connections/mercado_livre_br/import');
    assert.equal(options.credentials, 'same-origin');
    assert.equal(JSON.parse(options.body).cookies[0].value, 'test-session');
    return { ok: true, status: 200, json: async () => ({ status: 'connected', access_token: 'never-return' }) };
  };
  try {
    assert.equal((await importInPanoptes('mercado_livre_br', {}, 'http://localhost:3001')).ok, false);
    assert.equal(called, false);
    const result = await importInPanoptes('mercado_livre_br', { cookies: [authCookie] }, location.origin);
    assert.equal(result.ok, true);
    assert.equal(result.access_token, undefined);
  } finally { globalThis.fetch = originalFetch; delete globalThis.location; }
});

test('successful import opens connections in the existing Panoptes tab and focuses its window', async () => {
  const calls = [];
  const browser = { tabs: { update: async (...args) => calls.push(['tab', ...args]) }, windows: { update: async (...args) => calls.push(['window', ...args]) } };
  await openConnections(browser, {id: 42, windowId: 7}, 'http://localhost:3000', 'mercado_livre_br');
  assert.deepEqual(calls, [['tab', 42, {url:'http://localhost:3000/connections?imported=mercado_livre_br', active:true}], ['window', 7, {focused:true}]]);
});

const origin = 'http://localhost:3000';
const targetTab = id => ({id, windowId:1, url:origin + '/connections', status:'complete'});
const frameError = () => new Error('Frame with ID 0 is showing error page');

test('working Panoptes tab is preferred over the first tab showing a browser error', async () => {
  const browser = {
    tabs: { query: async () => [targetTab(1), targetTab(2)], update: async () => assert.fail('Must not navigate a healthy tab') },
    scripting: { executeScript: async ({target}) => { if (target.tabId === 1) throw frameError(); return [{result:true}]; } }
  };
  assert.equal((await preparePanoptesTab(browser, origin)).id, 2);
  assert.equal(isFrameUnavailable(frameError()), true);
});

test('broken destination is navigated to connections and awaited before import', async () => {
  let restored = false, probes = 0;
  const browser = {
    tabs: {
      query: async () => [targetTab(1)],
      update: async (id, options) => { assert.equal(options.url, origin + '/connections'); assert.equal(options.active, false); restored = true; return targetTab(id); },
      get: async id => targetTab(id)
    },
    scripting: { executeScript: async () => { probes++; if (!restored) throw frameError(); return [{result:true}]; } }
  };
  assert.equal((await preparePanoptesTab(browser, origin)).id, 1);
  assert.equal(probes, 2);
});

test('unreachable Panoptes yields a bounded actionable error without capturing session data', async () => {
  const browser = {
    tabs: { query: async () => [], create: async options => { assert.equal(options.active, false); return targetTab(1); }, get: async () => targetTab(1) },
    scripting: { executeScript: async () => { throw frameError(); } }
  };
  await assert.rejects(preparePanoptesTab(browser, origin, {timeout:0, pause:async () => {}}), /Não foi possível carregar o Panoptes/);
});

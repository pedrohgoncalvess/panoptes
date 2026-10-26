import { SOURCES, sourceFor } from './session.js';

// Only these routes can be called through an already authenticated Panoptes tab.
export async function bridgeRequest(origin, site, operation, payload) {
  if (location.origin !== origin || !['amazon_br', 'mercado_livre_br', 'pichau_br', 'terabyte_br'].includes(site)
    || !['start', 'next', 'result'].includes(operation)) return { ok: false, status: 400 };
  try {
    const response = await fetch(`/api/browser-connections/${site}/local/${operation}`, {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload), signal: AbortSignal.timeout(20000)
    });
    const data = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, data };
  } catch { return { ok: false, status: 0 }; }
}

export async function callBridge(browser, config, site, operation, payload) {
  const [result] = await browser.scripting.executeScript({ target: { tabId: config.panoptesTab },
    func: bridgeRequest, args: [config.origin, site, operation, payload] });
  return result?.result || { ok: false, status: 0 };
}

// Runs in the marketplace tab. Never return a login form or verification DOM.
export async function capturePage() {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline && (document.readyState === 'loading'
    || /ATUALIZANDO INFORMA/i.test(document.body?.innerText || '')))
    await new Promise(resolve => setTimeout(resolve, 200));
  const text = document.body?.innerText || '';
  const captcha = /\/captcha(?:\/|$)/i.test(location.pathname)
    || /just a moment|attention required|robot check/i.test(document.title || '')
    || /verify you are human|checking your browser|confirme que é humano|verifique que é humano/i.test(text)
    || /por segurança, complete esta etapa|verifique que você é|confirme que você é|no eres un robot|not a robot/i.test(text)
    || !!document.querySelector('#captchacharacters, form[action*="validateCaptcha"]');
  if (captcha) return { final_url: location.href, blocked: true, body: '<p>Por segurança, complete esta etapa</p>' };
  if (/\/(ap|login|auth|registration|account|account-verification)(\/|$)|\/Central\.obj$/i.test(location.pathname)
    || document.querySelector('input[type="password"]'))
    return { final_url: location.href, blocked: true, body: '' };
  if (!document.body || !text.trim()) return { final_url: location.href, blocked: true, body: '' };
  const body = document.documentElement.outerHTML;
  if (new TextEncoder().encode(body).length > 6_000_000)
    return { final_url: location.href, blocked: true, body: '' };
  return { final_url: location.href, blocked: false, body };
}

export async function collectJob(browser, config, site, job, pause = ms => new Promise(r => setTimeout(r, ms))) {
  if (!job.job_id || sourceFor(job.url) !== site) throw new Error('URL da coleta inválida.');
  // Reuse the explicitly selected tab, retaining its sessionStorage as well as
  // the profile's cookies/IndexedDB. Recreate it only if it was closed.
  let tab;
  if (config.collectorTab) {
    try {
      const existing = await browser.tabs.get(config.collectorTab);
      if (!existing.incognito && SOURCES[site].pages.includes(new URL(existing.url).hostname))
        tab = await browser.tabs.update(existing.id, { url: job.url, active: false });
    } catch { /* A closed collection tab can be recreated. */ }
  }
  if (!tab) tab = await browser.tabs.create({ url: job.url, active: false });
  config.collectorTab = tab.id;
  const deadline = Date.now() + 35000;
  do {
    tab = await browser.tabs.get(tab.id);
    if (tab.status === 'complete') break;
    await pause(250);
  } while (Date.now() < deadline);
  const [snapshot] = await browser.scripting.executeScript({ target: { tabId: tab.id }, func: capturePage });
  const value = snapshot?.result;
  if (!value || !SOURCES[site].pages.includes(new URL(value.final_url).hostname)
    || new URL(value.final_url).protocol !== 'https:') throw new Error('A fonte redirecionou para uma página não permitida.');
  if (value.blocked) {
    await browser.tabs.update(tab.id, { active: true });
    await browser.windows.update(tab.windowId, { focused: true });
  }
  return value;
}

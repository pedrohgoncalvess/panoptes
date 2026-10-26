export const SOURCES = {
  pichau_br: { name: 'Pichau', domains: ['pichau.com.br'], pages: ['www.pichau.com.br', 'pichau.com.br'], auth: [] },
  terabyte_br: { name: 'TerabyteShop', domains: ['terabyteshop.com.br'], pages: ['www.terabyteshop.com.br', 'terabyteshop.com.br'], auth: [] },
  mercado_livre_br: { name: 'Mercado Livre', domains: ['mercadolivre.com.br', 'mercadolivre.com', 'mercadolibre.com', 'mercadopago.com.br'], pages: ['www.mercadolivre.com.br', 'mercadolivre.com.br', 'lista.mercadolivre.com.br', 'produto.mercadolivre.com.br'], auth: ['ssid'] },
  amazon_br: { name: 'Amazon Brasil', domains: ['amazon.com.br', 'amazon.com'], pages: ['www.amazon.com.br', 'amazon.com.br'], auth: ['at-acbbr', 'at-main'] }
};

export function sourceFor(url) {
  const parsed = new URL(url);
  if (parsed.protocol !== 'https:' || parsed.port || parsed.username || parsed.password) return;
  if (/\/(ap|login|auth|registration|account|account-verification|captcha)(\/|$)|\/Central\.obj$/i.test(parsed.pathname)) return;
  return Object.entries(SOURCES).find(([, source]) => source.pages.includes(parsed.hostname))?.[0];
}

export function panoptesOrigin(address) {
  const url = new URL(address);
  if (url.username || url.password || url.search || url.hash || !['http:', 'https:'].includes(url.protocol))
    throw new Error('Informe um endereço HTTP ou HTTPS sem credenciais ou parâmetros.');
  if (url.protocol === 'http:' && !['localhost', '127.0.0.1'].includes(url.hostname))
    throw new Error('Use HTTPS para um Panoptes remoto. HTTP é permitido apenas em localhost.');
  if (url.pathname !== '/') throw new Error('Informe apenas o endereço do Panoptes, sem o caminho da página.');
  return url.origin;
}

export function hostPattern(origin) {
  const url = new URL(origin);
  return `${url.protocol}//${url.hostname}/*`;
}

export function isFrameUnavailable(error) {
  return /showing error page|no frame with id|frame.*(?:removed|not found)|tab.*closed/i.test(error?.message || '');
}

function checkPanoptesPage(origin) {
  return location.origin === origin && document.readyState !== 'loading';
}

async function tabReady(browser, tab, origin) {
  if (tab.status === 'loading' || tab.discarded) return false;
  try {
    const [result] = await browser.scripting.executeScript({ target: { tabId: tab.id }, func: checkPanoptesPage, args: [origin] });
    return result?.result === true;
  } catch (error) {
    if (isFrameUnavailable(error)) return false;
    throw new Error('Não foi possível acessar a aba do Panoptes. Recarregue a extensão e autorize o acesso ao endereço informado.');
  }
}

export async function preparePanoptesTab(browser, origin, { timeout = 15000, pause = ms => new Promise(resolve => setTimeout(resolve, ms)) } = {}) {
  const candidates = (await browser.tabs.query({ url: hostPattern(origin) }))
    .filter(tab => !tab.incognito && tab.url && new URL(tab.url).origin === origin);
  // Prefer a working tab instead of selecting the first URL, which can be a
  // Chrome network error page despite retaining the original address.
  for (const tab of candidates) {
    if (await tabReady(browser, tab, origin)) return tab;
  }
  const target = candidates[0]
    ? await browser.tabs.update(candidates[0].id, { url: `${origin}/connections`, active: false })
    : await browser.tabs.create({ url: `${origin}/connections`, active: false });
  const deadline = Date.now() + timeout;
  do {
    const current = await browser.tabs.get(target.id);
    if (await tabReady(browser, current, origin)) return current;
    await pause(250);
  } while (Date.now() < deadline);
  throw new Error(`Não foi possível carregar o Panoptes em ${origin}. Confira o endereço e se os serviços estão em execução.`);
}

export async function openConnections(browser, target, origin, site) {
  const url = `${origin}/connections?imported=${encodeURIComponent(site)}`;
  // Issue both requests before focusing a tab can close the extension popup.
  await Promise.all([
    browser.tabs.update(target.id, { url, active: true }),
    browser.windows.update(target.windowId, { focused: true })
  ]);
}

export function convertCookies(cookies, source, now = Date.now() / 1000) {
  const result = cookies.filter(c => !c.partitionKey && (c.session || c.expirationDate > now)
    && source.domains.some(d => c.domain.replace(/^\./, '') === d || c.domain.endsWith('.' + d)))
    .map(c => ({ name: c.name, value: c.value, domain: c.domain, path: c.path,
      expires: c.session ? -1 : c.expirationDate, httpOnly: c.httpOnly, secure: c.secure,
      sameSite: ({ strict: 'Strict', lax: 'Lax', no_restriction: 'None', unspecified: 'Lax' })[c.sameSite] || 'Lax' }));
  if (source.auth.length && !result.some(c => source.auth.includes(c.name) && c.value))
    throw new Error('Não encontramos uma sessão autenticada. Entre na sua conta e volte à página inicial.');
  return result;
}

// This function runs in the isolated world of the selected marketplace tab.
export function captureStorage() {
  return { origin: location.origin, localStorage: Object.entries(localStorage)
    .filter(([name]) => !/password|senha/i.test(name)).map(([name, value]) => ({ name, value })),
    sessionStorage: Object.entries(sessionStorage).filter(([name]) => !/password|senha/i.test(name))
      .map(([name, value]) => ({ name, value })) };
}

// Runs in the Panoptes tab: same-origin fetch uses its existing HttpOnly session.
export async function importInPanoptes(site, state, expectedOrigin) {
  if (location.origin !== expectedOrigin) return { ok: false, message: 'A aba do Panoptes mudou de endereço. Tente novamente.' };
  if (!['amazon_br', 'mercado_livre_br', 'pichau_br', 'terabyte_br'].includes(site)) return { ok: false, message: 'Fonte inválida.' };
  try {
    const response = await fetch(`/api/browser-connections/${site}/import`, {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state), signal: AbortSignal.timeout(65000)
    });
    const result = await response.json().catch(() => ({}));
    return { ok: response.ok && result.status === 'connected', message: response.status === 401
      ? 'Entre no Panoptes como administrador e tente novamente.'
      : response.status === 403 ? 'Somente o administrador pode importar sessões.'
      : response.ok && result.status === 'connected' ? 'Sessão confirmada e salva no Panoptes.'
      : response.ok ? 'O backend não confirmou a autenticação da sessão.'
      : result.detail || result.message || 'Não foi possível importar a sessão.' };
  } catch {
    return { ok: false, message: 'Não foi possível concluir o envio. Verifique se o Panoptes está disponível.' };
  }
}

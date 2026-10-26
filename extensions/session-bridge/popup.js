import { SOURCES, sourceFor, panoptesOrigin, hostPattern, convertCookies, captureStorage, importInPanoptes, openConnections, preparePanoptesTab, isFrameUnavailable } from './session.js';
import { callBridge } from './collector.js';

const form = document.querySelector('#form');
const address = document.querySelector('#address');
const button = document.querySelector('#send');
const status = document.querySelector('#status');
const mode = document.querySelector('#mode');
let tab, site;

async function initialize() {
  const saved = await chrome.storage.local.get('panoptesOrigin');
  if (saved.panoptesOrigin) address.value = saved.panoptesOrigin;
  [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  site = tab?.url && sourceFor(tab.url);
  document.querySelector('#source').textContent = site ? `Enviar: ${SOURCES[site].name}` : 'Abra Amazon, Mercado Livre, Pichau ou Terabyte. Conclua a verificação da loja antes de ativar a coleta.';
  button.disabled = !site;
  if (site === 'amazon_br') mode.value = 'docker';
  button.textContent = mode.value === 'local' ? 'Ativar coleta neste navegador' : 'Enviar sessão desta aba';
}

mode.addEventListener('change', () => {
  button.textContent = mode.value === 'local' ? 'Ativar coleta neste navegador' : 'Enviar sessão desta aba';
});

form.addEventListener('submit', async event => {
  event.preventDefault();
  button.disabled = true;
  status.textContent = 'Preparando envio…';
  try {
    const origin = panoptesOrigin(address.value.trim());
    // Request only the configured Panoptes host, from this user gesture.
    if (!await chrome.permissions.request({ origins: [hostPattern(origin)] }))
      throw new Error('Autorize o acesso ao endereço do Panoptes para enviar a sessão.');
    await chrome.storage.local.set({ panoptesOrigin: origin });
    status.textContent = 'Verificando a página do Panoptes…';
    const target = await preparePanoptesTab(chrome, origin);
    if (sourceFor((await chrome.tabs.get(tab.id)).url) !== site)
      throw new Error('A aba do site mudou. Abra novamente este painel.');
    if (tab.incognito) throw new Error('Use uma aba normal do navegador para compartilhar esta conexão.');
    const stores = await chrome.cookies.getAllCookieStores();
    const store = stores.find(s => s.tabIds.includes(tab.id));
    if (!store) throw new Error('Não foi possível identificar a sessão desta aba.');
    const all = (await Promise.all(SOURCES[site].domains.map(domain =>
      chrome.cookies.getAll({ domain, storeId: store.id })))).flat();
    const unique = [...new Map(all.map(c => [`${c.domain}|${c.path}|${c.name}|${JSON.stringify(c.partitionKey)}`, c])).values()];
    const cookies = convertCookies(unique, SOURCES[site]);
    if (mode.value === 'local') {
      const config = { origin, panoptesTab: target.id, collectorTab: tab.id, agent_id: crypto.randomUUID() };
      const response = await callBridge(chrome, config, site, 'start', { agent_id: config.agent_id });
      if (!response.ok) throw new Error(response.data?.detail || response.data?.message || 'Entre no Panoptes como administrador para ativar a coleta.');
      const { collectors = {} } = await chrome.storage.local.get('collectors');
      collectors[site] = config;
      await chrome.storage.local.set({ collectors });
      await openConnections(chrome, target, origin, site);
      return;
    }
    let snapshot;
    try {
      [snapshot] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: captureStorage });
    } catch (error) {
      if (isFrameUnavailable(error)) throw new Error(`A aba de ${SOURCES[site].name} está mostrando uma página de erro. Recarregue a página do site e tente novamente.`);
      throw new Error(`Não foi possível ler a sessão de ${SOURCES[site].name}. Recarregue a extensão e verifique a permissão de acesso ao site.`);
    }
    if (sourceFor(snapshot?.result?.origin || '') !== site)
      throw new Error('A aba do site mudou durante a captura. Tente novamente.');
    const state = { cookies, origins: [snapshot.result] };
    if (new TextEncoder().encode(JSON.stringify(state)).length > 1024 * 1024)
      throw new Error('A sessão excede o limite de 1 MB.');
    status.textContent = 'Validando a sessão no Panoptes…';
    let result;
    try {
      [result] = await chrome.scripting.executeScript({ target: { tabId: target.id },
        func: importInPanoptes, args: [site, state, origin] });
    } catch {
      throw new Error('A página do Panoptes foi fechada ou deixou de carregar durante o envio. Abra Conexões no Panoptes e tente novamente.');
    }
    status.textContent = result?.result?.message || 'A aba do Panoptes foi fechada. Tente novamente.';
    if (result?.result?.ok) {
      status.textContent = 'Sessão salva. Abrindo Conexões no Panoptes…';
      await openConnections(chrome, target, origin, site);
    }
  } catch (error) {
    status.textContent = error.message || 'Não foi possível enviar a sessão.';
  } finally {
    button.disabled = !site;
  }
});

initialize().catch(() => { status.textContent = 'Não foi possível identificar a aba. Reabra o painel.'; });

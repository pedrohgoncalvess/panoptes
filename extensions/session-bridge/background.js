import { callBridge, collectJob } from './collector.js';

let running = false;
let timer;
const busy = new Set();
const tabs = new Map();

async function poll() {
  if (running) return;
  clearTimeout(timer);
  running = true;
  try {
    const { collectors = {} } = await chrome.storage.local.get('collectors');
    for (const [site, config] of Object.entries(collectors)) {
      if (busy.has(site)) continue;
      try {
        const response = await callBridge(chrome, config, site, 'next', { agent_id: config.agent_id });
        if (response.status === 409) {
          // A disconnect, replacement or backend restart requires explicit activation.
          const current = (await chrome.storage.local.get('collectors')).collectors || {};
          if (current[site]?.agent_id === config.agent_id) {
            delete current[site];
            await chrome.storage.local.set({ collectors: current });
          }
          continue;
        }
        const job = response.data;
        if (response.ok && job?.job_id && !busy.has(site)) {
          busy.add(site);
          void runJob(site, config, job).finally(() => busy.delete(site));
        }
      } catch { /* Offline or signed-out Panoptes is reflected by backend heartbeat expiry. */ }
    }
  } finally {
    running = false;
    const { collectors = {} } = await chrome.storage.local.get('collectors');
    if (Object.keys(collectors).length) timer = setTimeout(poll, 2000);
  }
}

async function runJob(site, config, job) {
  const entry = { ...config, collectorTab: tabs.get(site) || config.collectorTab };
  try {
    const result = await collectJob(chrome, entry, site, job);
    tabs.set(site, entry.collectorTab);
    await callBridge(chrome, config, site, 'result', { ...result, job_id: job.job_id, agent_id: config.agent_id });
  } catch {
    await callBridge(chrome, config, site, 'result', {
      job_id: job.job_id, agent_id: config.agent_id, final_url: job.url, blocked: true, body: ''
    }).catch(() => {});
  }
}

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && changes.collectors) void poll();
});
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === 'collector') void poll(); });
// The alarm resumes polling after service-worker suspension, but never enables a collector.
chrome.alarms.create('collector', { periodInMinutes: 1 });
void poll();

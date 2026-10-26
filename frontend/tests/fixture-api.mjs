// Offline HTTP fixture used only by integration tests and visual QA.
import { createServer } from 'node:http';
import { randomUUID } from 'node:crypto';

export function createFixtureApi({ retailBrowser = false } = {}) {
	let serial = 0;
	const access = new Map();
	const refresh = new Map();
	const sessions = new Map();
	const termId = randomUUID();
	const terms = [{ public_id: termId, term: 'Database Internals' }];
	const routines = [
		{
			public_id: randomUUID(),
			name: 'Livros de tecnologia',
			search_term_id: termId,
			mode: 'discover',
			schedule: { kind: 'fixed', times: ['08:00', '18:00'], timezone: 'America/Sao_Paulo' },
			enabled: true,
			next_run_at: '2026-10-05T11:00:00Z'
		}
	];
	const items = ['completed', 'running', 'pending', 'failed', 'completed'].map((status, i) => ({
		public_id: randomUUID(),
		mode: 'discover',
		status,
		term: 'Database Internals',
		search_term_id: termId,
		created_at: `2026-10-04T${String(16 - i).padStart(2, '0')}:30:00Z`,
		completed_at: status === 'completed' ? '2026-10-04T16:35:00Z' : null,
		summary: status === 'completed' ? { products_found: 12 } : {}
	}));
	const webhooks = [];
	const mcpKeys = [];
	const state = {
		refreshCalls: 0,
		lastRequest: null,
		unavailable: false,
		rejectAllAccess: false,
		role: 'admin'
	};
	const retail = {
		site: 'pichau_br',
		name: 'Pichau',
		status: 'disconnected',
		interactive: false,
		requires_login: false
	};
	let connects = 0;
	let frames = 0;
	const pair = (sid) => {
		const n = ++serial;
		access.set(`access-${n}`, sid);
		refresh.set(`refresh-${n}`, sid);
		return {
			access_token: `access-${n}`,
			refresh_token: `refresh-${n}`,
			expires_in: 7200,
			refresh_expires_in: 36000
		};
	};
	const server = createServer(async (req, res) => {
		let raw = '';
		for await (const chunk of req) raw += chunk;
		const body = raw ? JSON.parse(raw) : {};
		const url = new URL(req.url, 'http://fixture');
		state.lastRequest = { path: url.pathname, search: url.search, method: req.method, body };
		const send = (status, value) => {
			res.writeHead(status, { 'Content-Type': 'application/json' });
			res.end(status === 204 ? undefined : JSON.stringify(value));
		};
		if (state.unavailable) return send(503, { detail: 'Temporarily unavailable' });
		if (url.pathname === '/auth/login') {
			if (body.email !== 'admin@panoptes.com' || body.password !== 'admin')
				return send(401, { detail: 'Invalid credentials' });
			const sid = randomUUID();
			sessions.set(sid, true);
			return send(200, pair(sid));
		}
		if (url.pathname === '/auth/refresh') {
			state.refreshCalls++;
			const sid = refresh.get(body.refresh_token);
			refresh.delete(body.refresh_token);
			await new Promise((resolve) => setTimeout(resolve, 30));
			if (!sid || !sessions.get(sid)) return send(401, { detail: 'Invalid credentials' });
			return send(200, pair(sid));
		}
		const token = req.headers.authorization?.replace('Bearer ', '');
		const sid = access.get(token);
		if (state.rejectAllAccess || !sid || !sessions.get(sid))
			return send(401, { detail: 'Invalid credentials' });
		if (url.pathname === '/auth/me')
			return send(200, {
				name: 'admin',
				email: 'admin@panoptes.com',
				public_id: sid,
				role: state.role
			});
		if (url.pathname === '/auth/logout') {
			sessions.set(sid, false);
			return send(204);
		}
		if (url.pathname === '/auth/mcp-keys') {
			if (req.method === 'GET') return send(200, mcpKeys);
			if (req.method === 'POST') {
				const item = {
					...body,
					public_id: randomUUID(),
					expires_at: body.expires_at || null,
					revoked_at: null,
					routine_ids: body.routine_ids || [],
					permissions: body.permissions || {}
				};
				mcpKeys.push(item);
				return send(201, { ...item, key: 'pmcp_fixture-credential' });
			}
		}
		if (url.pathname.startsWith('/auth/mcp-keys/') && req.method === 'DELETE') {
			const item = mcpKeys.find((key) => key.public_id === url.pathname.split('/')[3]);
			if (!item) return send(404, {});
			item.revoked_at = new Date().toISOString();
			return send(204);
		}
		if (url.pathname === '/alerts/webhooks') {
			if (req.method === 'GET') {
				const offset = Number(url.searchParams.get('offset') || 0);
				return send(
					200,
					webhooks.slice(offset, offset + Number(url.searchParams.get('limit') || 50))
				);
			}
			if (req.method === 'POST') {
				const item = {
					...body,
					public_id: randomUUID(),
					created_at: new Date().toISOString(),
					updated_at: new Date().toISOString()
				};
				webhooks.push(item);
				return send(201, item);
			}
		}
		if (url.pathname.startsWith('/alerts/webhooks/')) {
			const id = url.pathname.split('/')[3];
			const index = webhooks.findIndex((item) => item.public_id === id);
			if (index < 0) return send(404, { detail: 'Webhook não encontrado' });
			if (url.pathname.endsWith('/deliveries')) return send(200, []);
			if (req.method === 'PUT') {
				webhooks[index] = { ...webhooks[index], ...body, updated_at: new Date().toISOString() };
				return send(200, webhooks[index]);
			}
			if (req.method === 'DELETE') {
				webhooks.splice(index, 1);
				return send(204);
			}
			return send(200, webhooks[index]);
		}
		if (url.pathname === '/sources') return send(200, [{ id: 'fixture', name: 'Fonte de teste' }]);
		if (url.pathname === '/data') return send(200, { items: [], total: 0, limit: 25, offset: 0 });
		if (url.pathname === '/data/bulk' && req.method === 'POST')
			return send(200, { affected: body.expected_count, action: body.action });
		if (req.method === 'DELETE' && /^\/data\/[\da-f-]+$/.test(url.pathname))
			return send(200, { excluded: true, removed: url.searchParams.get('purge') === 'true' });
		if (/^\/assets\/[\da-f-]+\/url$/.test(url.pathname))
			return send(200, {
				url: 'https://storage.example/capture?signature=test',
				expires_in_seconds: 300
			});
		if (url.pathname === '/extraction-logs')
			return send(200, { items: [], cursor: 0, has_more: false });
		if (url.pathname === '/extraction-logs/stream') {
			state.lastEventId = req.headers['last-event-id'];
			res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store' });
			res.write(
				'id: 42\nevent: log\ndata: ' +
					JSON.stringify({
						id: 42,
						request_id: items[3].public_id,
						correlation_id: items[3].public_id,
						site: 'mercado_livre_br',
						level: 'ERROR',
						event: 'extraction_failed',
						message: 'Não foi possível interpretar a busca.',
						details: { reason: 'search_layout_not_recognized', http_status: 200 },
						created_at: new Date().toISOString()
					}) +
					'\n\n'
			);
			const timer = setTimeout(() => res.end(': heartbeat\n\n'), 2500);
			res.on('close', () => clearTimeout(timer));
			return;
		}
		if (retailBrowser && url.pathname.startsWith('/browser-connections/pichau_br/')) {
			const operation = url.pathname.split('/').at(-1);
			if (operation === 'connect') {
				connects++;
				frames = 0;
				Object.assign(retail, { status: 'connecting', interactive: true });
			}
			if (operation === 'save') {
				if (connects === 3) return send(409, { detail: 'Conclua a verificação da loja.' });
				Object.assign(retail, { status: 'connected', interactive: false });
			}
			if (operation === 'frame') {
				if (connects === 2 && ++frames >= 3)
					Object.assign(retail, { status: 'connected', interactive: false });
				return send(200, {
					status: retail.status,
					authenticated: connects === 2 && !retail.interactive,
					session_saved: !retail.interactive
				});
			}
			return send(200, retail);
		}
		if (url.pathname === '/browser-connections' && retailBrowser) return send(200, [retail]);
		if (url.pathname === '/browser-connections')
			return send(200, [
				{ site: 'amazon_br', name: 'Amazon Brasil', status: 'disconnected', interactive: false }
			]);
		if (url.pathname.startsWith('/browser-connections/') && url.pathname.endsWith('/import'))
			return send(200, { status: 'connected' });
		if (url.pathname.startsWith('/browser-connections/')) return send(200, { ok: true });
		if (/\/discover-sources$/.test(url.pathname)) {
			const id = url.pathname.split('/')[2];
			const item = {
				public_id: randomUUID(),
				mode: 'discover',
				status: 'pending',
				term: terms.find((t) => t.public_id === id)?.term,
				search_term_id: id,
				created_at: new Date().toISOString(),
				summary: {}
			};
			items.unshift(item);
			return send(202, {
				requests: [{ public_id: item.public_id, status: item.status, site: 'fixture' }]
			});
		}
		if (url.pathname === '/analytics/prices/products') return send(200, []);
		if (url.pathname === '/analytics/prices/dashboard')
			return send(200, { totals: { products: 0 } });
		if (url.pathname === '/analytics/detail')
			return send(200, {
				items: [],
				total: 0,
				limit: Number(url.searchParams.get('limit') || 25),
				offset: Number(url.searchParams.get('offset') || 0)
			});
		if (url.pathname === '/analytics/prices') {
			return send(200, {
				items: [
					{
						public_id: termId,
						title: 'Database Internals',
						brand: 'O’Reilly',
						attributes: { format: 'Capa comum' },
						image_urls: [],
						offers: [
							{
								public_id: termId,
								seller: 'Livraria',
								price: '189.90',
								list_price: '219.90',
								currency: 'BRL',
								lowest_price: '179.90',
								previous_price: '199.90',
								observed_at: '2026-10-05T12:00:00Z',
								availability: 'in_stock',
								promotions: [
									{
										public_id: termId,
										kind: 'coupon',
										text: '10% de desconto com o cupom',
										code: 'LIVROS10',
										requires_activation: true,
										conditions: ['Válido para compras acima de R$ 100.']
									}
								],
								payment_options: [{ text: '3x de R$ 63,30 sem juros', conditions: [] }],
								shipping: { text: 'Frete grátis', conditions: [] },
								history: [
									{ observed_at: '2026-10-03T12:00:00Z', price: '179.90' },
									{ observed_at: '2026-10-04T12:00:00Z', price: '199.90' },
									{ observed_at: '2026-10-05T12:00:00Z', price: '189.90' }
								]
							}
						]
					}
				],
				total: 1,
				limit: Number(url.searchParams.get('limit') || 24),
				offset: Number(url.searchParams.get('offset') || 0)
			});
		}
		if (url.pathname === '/analytics') {
			const days = Number(url.searchParams.get('days') || 7);
			return send(200, {
				period_days: days,
				totals: {
					products: 128,
					active_routines: routines.filter((r) => r.enabled).length,
					requests: 54,
					completed: 48,
					failed: 2,
					in_progress: 4
				},
				daily: Array.from({ length: days }, (_, i) => {
					const d = new Date('2026-10-04T00:00:00Z');
					d.setUTCDate(d.getUTCDate() - days + i + 1);
					return {
						date: d.toISOString().slice(0, 10),
						total: [4, 9, 6, 11, 8, 7, 9][i % 7],
						completed: [4, 8, 5, 10, 7, 6, 8][i % 7],
						failed: i === 2 ? 2 : 0
					};
				})
			});
		}
		if (/^\/search-terms\/[\da-f-]+\/routine-sources$/i.test(url.pathname)) {
			const id = url.pathname.split('/')[2];
			return send(
				200,
				terms.some((term) => term.public_id === id) ? [{ public_id: id, site: 'terabyte_br' }] : []
			);
		}
		if (url.pathname === '/search-terms') {
			if (req.method === 'POST') {
				const t = { public_id: randomUUID(), term: body.term };
				terms.unshift(t);
				return send(201, t);
			}
			return send(200, terms.slice(Number(url.searchParams.get('offset') || 0)));
		}
		if (/\/discover$/.test(url.pathname)) {
			const id = url.pathname.split('/')[2];
			const item = {
				public_id: randomUUID(),
				mode: 'discover',
				status: 'pending',
				term: terms.find((t) => t.public_id === id)?.term,
				search_term_id: id,
				created_at: new Date().toISOString(),
				summary: {}
			};
			items.unshift(item);
			return send(202, { public_id: item.public_id, status: item.status });
		}
		if (url.pathname === '/routines') {
			if (req.method === 'POST') {
				const r = { ...body, public_id: randomUUID(), next_run_at: new Date().toISOString() };
				routines.push(r);
				return send(201, r);
			}
			return send(200, routines.slice(Number(url.searchParams.get('offset') || 0)));
		}
		if (url.pathname.startsWith('/routines/')) {
			const i = routines.findIndex((r) => r.public_id === url.pathname.split('/')[2]);
			if (i < 0) return send(404, {});
			if (req.method === 'DELETE') {
				routines.splice(i, 1);
				return send(204);
			}
			routines[i] = { ...routines[i], ...body };
			return send(200, routines[i]);
		}
		if (url.pathname === '/scrape-requests') {
			const status = url.searchParams.get('status');
			const filtered = items.filter((i) => !status || i.status === status);
			const limit = Number(url.searchParams.get('limit') || 25);
			const offset = Number(url.searchParams.get('offset') || 0);
			return send(200, {
				items: filtered.slice(offset, offset + limit),
				total: filtered.length,
				limit,
				offset
			});
		}
		if (url.pathname.startsWith('/scrape-requests/'))
			return send(200, items.find((i) => i.public_id === url.pathname.split('/')[2]) || {});
		return send(404, { detail: 'Not found' });
	});
	return {
		server,
		state,
		expireAccess: () => access.clear(),
		expireRefresh: () => refresh.clear()
	};
}

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createFixtureApi } from './fixture-api.mjs';

test('frontend authentication over HTTP', { timeout: 180000 }, async (t) => {
	const fixture = createFixtureApi();
	fixture.server.listen(0, '127.0.0.1');
	await once(fixture.server, 'listening');
	const backendPort = fixture.server.address().port;
	const port = 5187;
	const origin = `http://127.0.0.1:${port}`;
	const production = process.env.FRONTEND_TEST_RUNTIME === 'node';
	const vite = spawn(
		process.execPath,
		production
			? ['server.mjs']
			: [
					'node_modules/vite/bin/vite.js',
					'dev',
					'--host',
					'127.0.0.1',
					'--port',
					String(port),
					'--strictPort'
				],
		{
			cwd: process.cwd(),
			env: {
				...process.env,
				HOST: '127.0.0.1',
				PORT: String(port),
				PANOPTES_API_URL: production ? '' : `http://127.0.0.1:${backendPort}`,
				BACKEND_HOST: '127.0.0.1',
				BACKEND_PORT: String(backendPort)
			},
			stdio: ['ignore', 'pipe', 'pipe'],
			windowsHide: true
		}
	);
	let output = '';
	vite.stdout.on('data', (chunk) => (output += chunk));
	vite.stderr.on('data', (chunk) => (output += chunk));
	t.after(async () => {
		vite.kill();
		fixture.server.closeAllConnections();
		await new Promise((resolve) => fixture.server.close(resolve));
	});
	let ready = false;
	for (let n = 0; n < 600; n++) {
		try {
			const r = await fetch(origin + '/');
			if (r.ok) {
				ready = true;
				break;
			}
		} catch {
			// Vite may still be starting; retry until the bounded deadline.
		}
		if (vite.exitCode !== null) break;
		await new Promise((resolve) => setTimeout(resolve, 200));
	}
	assert.ok(ready, output);
	let cookie = '';
	const fetchApp = (path, options = {}) =>
		fetch(origin + path, {
			redirect: 'manual',
			...options,
			headers: { cookie, origin, 'Content-Type': 'application/json', ...options.headers }
		});
	const setCookies = (response) => {
		cookie = response.headers
			.getSetCookie()
			.map((c) => c.split(';')[0])
			.join('; ');
	};
	const login = async () => {
		const r = await fetchApp('/api/auth/login', {
			method: 'POST',
			body: JSON.stringify({ email: 'admin@panoptes.com', password: 'admin' })
		});
		assert.equal(r.status, 200);
		setCookies(r);
		return r;
	};
	await t.test('root renders login and private pages redirect to root', async () => {
		const root = await fetchApp('/');
		assert.equal(root.status, 200);
		const html = await root.text();
		assert.match(html, /Sign in to Panoptes/);
		assert.match(html, /<html lang="en">/);
		for (const path of [
			'/dashboard',
			'/analytics',
			'/analytics/extractions',
			'/analytics/prices',
			'/analytics/detail',
			'/routines',
			'/data',
			'/administrator/categories',
			'/administrator/taxonomy',
			'/administrator/mcp-keys',
			'/extractions'
		]) {
			const r = await fetchApp(path);
			assert.equal(r.status, 303);
			assert.equal(r.headers.get('location'), '/');
		}
		assert.equal((await fetchApp('/api/analytics')).status, 401);
		assert.equal((await fetchApp('/api/data')).status, 401);
		assert.equal(
			(await fetchApp('/api/analytics/prices?term_id=00000000-0000-4000-8000-000000000001')).status,
			401
		);
	});
	await t.test('invalid credentials and cross-origin mutations are rejected', async () => {
		const r = await fetchApp('/api/auth/login', {
			method: 'POST',
			body: '{"email":"admin@panoptes.com","password":"wrong"}'
		});
		assert.equal(r.status, 401);
		assert.equal(r.headers.getSetCookie().length, 0);
		assert.equal(
			(
				await fetchApp('/api/auth/login', {
					method: 'POST',
					headers: { origin: 'https://untrusted.example' },
					body: '{}'
				})
			).status,
			403
		);
	});
	await t.test('login form works before JavaScript loads', async () => {
		const response = await fetchApp('/', {
			method: 'POST',
			headers: { 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'text/html' },
			body: new URLSearchParams({ email: 'admin@panoptes.com', password: 'admin' })
		});
		assert.equal(response.status, 303);
		assert.equal(response.headers.get('location'), '/dashboard');
		assert.equal(response.headers.getSetCookie().length, 2);
	});
	await t.test('login stores HttpOnly cookies and does not expose tokens in JSON', async () => {
		const r = await login();
		assert.deepEqual(await r.json(), { ok: true });
		for (const c of r.headers.getSetCookie()) {
			assert.match(c, /HttpOnly/i);
			assert.match(c, /SameSite=Strict/i);
			assert.match(c, /Path=\//);
		}
		const root = await fetchApp('/');
		assert.equal(root.headers.get('location'), '/dashboard');
		assert.equal((await fetchApp('/login')).headers.get('location'), '/');
		const dashboard = await fetchApp('/dashboard');
		assert.equal(dashboard.status, 200);
		assert.match(await dashboard.text(), /A view of everything/);
	});
	await t.test('all application sections render English headings and navigation', async () => {
		for (const [path, heading] of [
			['/dashboard', 'A view of everything.'],
			['/routines', 'Routines'],
			['/alerts', 'Alerts'],
			['/connections', 'Connections'],
			['/data', 'Data'],
			['/extractions', 'Extractions'],
			['/extractions/scheduled', 'Scheduled extractions'],
			['/extraction/logs', 'Now'],
			['/analytics/extractions', 'Extraction analytics'],
			['/analytics/prices', 'Price analytics'],
			['/analytics/detail', 'Product details'],
			['/administrator/categories', 'Categories'],
			['/administrator/taxonomy', 'Product classification'],
			['/administrator/mcp-keys', 'MCP keys']
		]) {
			const response = await fetchApp(path);
			assert.equal(response.status, 200, path);
			const html = await response.text();
			assert.ok(html.includes(heading), `${path}: ${heading}`);
			assert.match(html, /aria-label="Main navigation"/);
			assert.match(html, /aria-label="Sign out"/);
			assert.doesNotMatch(html, /Navegação principal|Sair da conta|Visão geral/);
		}
	});
	await t.test('routine sources reach the backend through the authenticated proxy', async () => {
		const terms = await (await fetchApp('/api/search-terms')).json();
		const id = terms[0].public_id;
		const path = `/search-terms/${id}/routine-sources`;
		const response = await fetchApp('/api' + path);
		assert.equal(response.status, 200);
		assert.deepEqual(await response.json(), [{ public_id: id, site: 'terabyte_br' }]);
		assert.equal(fixture.state.lastRequest.path, path);
		assert.equal(response.headers.get('cache-control'), 'no-store');
		assert.equal((await fetchApp(`/api/search-terms/${id}/unknown-sources`)).status, 404);
		fixture.state.unavailable = true;
		try {
			assert.equal((await fetchApp('/api' + path)).status, 503);
		} finally {
			fixture.state.unavailable = false;
		}
	});
	await t.test(
		'MCP key management renders behind login and proxies create/list/revoke',
		async () => {
			const page = await fetchApp('/administrator/mcp-keys');
			assert.equal(page.status, 200);
			assert.match(await page.text(), /MCP keys/);
			const created = await fetchApp('/api/auth/mcp-keys', {
				method: 'POST',
				body: JSON.stringify({ name: 'Test', admin: true, expiration: 'never' })
			});
			assert.equal(created.status, 201);
			const value = await created.json();
			assert.equal(value.key, 'pmcp_fixture-credential');
			const listed = await (await fetchApp('/api/auth/mcp-keys')).json();
			assert.equal(listed[0].name, 'Test');
			assert.equal(listed[0].key, undefined);
			const revoked = await fetchApp(`/api/auth/mcp-keys/${value.public_id}`, { method: 'DELETE' });
			assert.equal(revoked.status, 204);
		}
	);
	await t.test(
		'administrator dropdown links to separate settings pages and redirects old paths',
		async () => {
			const landing = await fetchApp('/administrator');
			assert.equal(landing.status, 303);
			assert.equal(landing.headers.get('location'), '/administrator/categories');
			const legacyMcp = await fetchApp('/mcp-keys?from=bookmark');
			assert.equal(legacyMcp.status, 303);
			assert.equal(legacyMcp.headers.get('location'), '/administrator/mcp-keys?from=bookmark');
			const categories = await fetchApp('/administrator/categories');
			assert.equal(categories.status, 200);
			const html = await categories.text();
			assert.match(html, /aria-controls="administrator-submenu"/);
			assert.match(html, /href="\/administrator\/taxonomy"/);
			assert.match(html, /href="\/administrator\/mcp-keys"/);
			assert.match(html, /New category/);
			assert.doesNotMatch(html, /Adjust products/);
			const taxonomy = await fetchApp('/administrator/taxonomy');
			assert.equal(taxonomy.status, 200);
			const taxonomyHtml = await taxonomy.text();
			assert.match(taxonomyHtml, /Adjust products/);
			assert.doesNotMatch(taxonomyHtml, /category-slug/);
		}
	);
	await t.test(
		'regular users retain MCP access while catalog settings stay restricted',
		async () => {
			fixture.state.role = 'user';
			try {
				assert.equal((await fetchApp('/administrator/categories')).status, 403);
				assert.equal((await fetchApp('/administrator/taxonomy')).status, 403);
				const response = await fetchApp('/administrator/mcp-keys');
				assert.equal(response.status, 200);
				const html = await response.text();
				assert.match(html, /href="\/administrator\/mcp-keys"/);
				assert.doesNotMatch(html, /href="\/administrator\/categories"/);
				assert.doesNotMatch(html, /href="\/administrator\/taxonomy"/);
			} finally {
				fixture.state.role = 'admin';
			}
		}
	);
	if (production) {
		await t.test('client protocol headers cannot change the trusted local origin', async () => {
			const r = await fetchApp('/api/auth/login', {
				method: 'POST',
				headers: { 'x-panoptes-protocol': 'https' },
				body: JSON.stringify({ email: 'admin@panoptes.com', password: 'admin' })
			});
			assert.equal(r.status, 200);
			setCookies(r);
		});
	}
	await t.test('expired access rotates refresh once for concurrent requests', async () => {
		fixture.expireAccess();
		const before = fixture.state.refreshCalls;
		const responses = await Promise.all([
			fetchApp('/api/analytics'),
			fetchApp('/api/routines'),
			fetchApp('/api/scrape-requests')
		]);
		assert.ok(responses.every((r) => r.status === 200));
		assert.equal(fixture.state.refreshCalls, before + 1);
		const pairs = responses.map((r) =>
			r.headers
				.getSetCookie()
				.map((c) => c.split(';')[0])
				.join('; ')
		);
		assert.equal(new Set(pairs).size, 1);
		assert.notEqual(pairs[0], cookie);
		setCookies(responses[0]);
	});
	await t.test('missing access cookie still refreshes and SSR persists the new pair', async () => {
		cookie = cookie
			.split('; ')
			.filter((c) => c.startsWith('panoptes_refresh='))
			.join('; ');
		const r = await fetchApp('/dashboard');
		assert.equal(r.status, 200);
		assert.ok(r.headers.getSetCookie().some((c) => c.startsWith('panoptes_access=')));
		setCookies(r);
	});
	await t.test('filters, pagination and bodies reach the backend', async () => {
		const r = await fetchApp('/api/scrape-requests?status=failed&limit=10&offset=0');
		assert.equal(r.status, 200);
		assert.equal((await r.json()).items[0].status, 'failed');
		assert.equal(fixture.state.lastRequest.search, '?status=failed&limit=10&offset=0');
		assert.equal((await fetchApp('/api/not-an-api')).status, 404);
	});
	await t.test(
		'data page and deletion proxy preserve filters and require same origin',
		async () => {
			const id = '00000000-0000-4000-8000-000000000001';
			assert.equal((await fetchApp('/data')).status, 200);
			const query = `?q=SSD&site=fixture&request_id=${id}&limit=25&offset=25`;
			assert.equal((await fetchApp('/api/data' + query)).status, 200);
			assert.equal(fixture.state.lastRequest.search, query);
			const bulkBody = {
				action: 'exclude',
				all_matching: true,
				filters: { price_operator: 'between', price: 10, price_to: 20 },
				excluded_ids: [id],
				expected_count: 12
			};
			const bulk = await fetchApp('/api/data/bulk', {
				method: 'POST',
				body: JSON.stringify(bulkBody)
			});
			assert.equal(bulk.status, 200);
			assert.equal((await bulk.json()).affected, 12);
			assert.deepEqual(fixture.state.lastRequest.body, bulkBody);
			for (const purge of [false, true]) {
				const response = await fetchApp(`/api/data/${id}?purge=${purge}`, { method: 'DELETE' });
				assert.equal(response.status, 200);
				assert.equal((await response.json()).removed, purge);
				assert.equal(fixture.state.lastRequest.method, 'DELETE');
			}
			assert.equal(
				(
					await fetchApp(`/api/data/${id}?purge=true`, {
						method: 'DELETE',
						headers: { origin: 'https://untrusted.example' }
					})
				).status,
				403
			);
		}
	);
	await t.test('analytics navigation and prices proxy retain pagination', async () => {
		const redirect = await fetchApp('/analytics');
		assert.equal(redirect.status, 303);
		assert.equal(redirect.headers.get('location'), '/analytics/extractions');
		assert.equal((await fetchApp('/analytics/extractions')).status, 200);
		assert.equal((await fetchApp('/analytics/prices')).status, 200);
		const terms = await (await fetchApp('/api/search-terms')).json();
		const query = `?term_id=${terms[0].public_id}&limit=24&offset=24`;
		const prices = await fetchApp('/api/analytics/prices' + query);
		assert.equal(prices.status, 200);
		const value = await prices.json();
		assert.equal(value.items[0].offers[0].promotions[0].code, 'LIVROS10');
		assert.equal(fixture.state.lastRequest.search, query);
		assert.equal((await fetchApp('/analytics/detail')).status, 200);
		const filters = `?start=2026-10-01&end=2026-10-06&term_id=${terms[0].public_id}&product_id=${terms[0].public_id}&site=amazon_br&offset=25`;
		for (const path of [
			'/analytics/prices/dashboard',
			'/analytics/prices/products',
			'/analytics/detail'
		]) {
			assert.equal((await fetchApp('/api' + path + filters)).status, 200);
			assert.equal(fixture.state.lastRequest.search, filters);
		}
	});
	await t.test('browser connection proxy preserves events and hides internal service', async () => {
		assert.equal((await fetchApp('/connections')).status, 200);
		const connections = await fetchApp('/api/browser-connections');
		assert.equal(connections.status, 200);
		assert.equal(connections.headers.get('cache-control'), 'no-store');
		assert.equal((await connections.json())[0].site, 'amazon_br');
		const value = { action: 'click', x: 200, y: 120 };
		const input = await fetchApp('/api/browser-connections/amazon_br/input', {
			method: 'POST',
			body: JSON.stringify(value)
		});
		assert.equal(input.status, 200);
		assert.deepEqual(fixture.state.lastRequest.body, value);
		assert.equal(
			(await fetchApp('/api/internal/browser/fetch', { method: 'POST', body: '{}' })).status,
			404
		);
	});
	await t.test(
		'session imports use authenticated proxy, reject cross-origin and bound payloads',
		async () => {
			const body = JSON.stringify({
				cookies: [{ name: 'ssid', value: 'synthetic-session', domain: '.mercadolivre.com.br' }],
				origins: []
			});
			const response = await fetchApp('/api/browser-connections/mercado_livre_br/import', {
				method: 'POST',
				body
			});
			assert.equal(response.status, 200);
			assert.equal(response.headers.get('cache-control'), 'no-store');
			assert.equal(fixture.state.lastRequest.body.cookies[0].value, 'synthetic-session');
			assert.equal(
				(
					await fetchApp('/api/browser-connections/mercado_livre_br/import', {
						method: 'POST',
						body,
						headers: { origin: 'chrome-extension://untrusted' }
					})
				).status,
				403
			);
			assert.equal(
				(
					await fetchApp('/api/browser-connections/mercado_livre_br/import', {
						method: 'POST',
						body: 'x'.repeat(1024 * 1024 + 1)
					})
				).status,
				413
			);
		}
	);
	await t.test(
		'local collection proxies bounded HTML and rejects unrelated routes and origins',
		async () => {
			const prefix = '/api/browser-connections/mercado_livre_br/local/';
			const payload = {
				agent_id: '00000000-0000-4000-8000-000000000001',
				body: '<html>' + 'x'.repeat(1_100_000) + '</html>'
			};
			const response = await fetchApp(prefix + 'result', {
				method: 'POST',
				body: JSON.stringify(payload)
			});
			assert.equal(response.status, 200);
			assert.equal(fixture.state.lastRequest.body.body.length, payload.body.length);
			assert.equal(
				(
					await fetchApp(prefix + 'result', {
						method: 'POST',
						body: '{}',
						headers: { origin: 'https://evil.test' }
					})
				).status,
				403
			);
			assert.equal(
				(await fetchApp(prefix + 'arbitrary', { method: 'POST', body: '{}' })).status,
				404
			);
			assert.equal(
				(await fetchApp(prefix + 'result', { method: 'POST', body: 'x'.repeat(12_000_001) }))
					.status,
				413
			);
		}
	);
	await t.test('authenticated SSE forwards frames immediately and resumes cursor', async () => {
		await login();
		const started = performance.now();
		const response = await fetchApp('/api/extraction-logs/stream?after=7', {
			headers: { 'Last-Event-ID': '41' }
		});
		assert.equal(response.status, 200);
		assert.match(response.headers.get('content-type'), /text\/event-stream/);
		assert.equal(response.headers.get('cache-control'), 'no-store');
		const reader = response.body.getReader();
		const first = await reader.read();
		assert.match(new TextDecoder().decode(first.value), /id: 42\nevent: log/);
		assert.ok(
			performance.now() - started < 2000,
			'SSE must not buffer the complete backend response'
		);
		assert.equal(fixture.state.lastEventId, '41');
		await reader.cancel();
		assert.equal(
			(await fetchApp('/api/extraction-logs/stream', { headers: { cookie: '' } })).status,
			401
		);
	});
	await t.test('capture download authenticates and redirects to a short-lived S3 URL', async () => {
		await login();
		const path = '/api/assets/00000000-0000-4000-8000-000000000001/download';
		const response = await fetchApp(path);
		assert.equal(response.status, 303);
		assert.equal(
			response.headers.get('location'),
			'https://storage.example/capture?signature=test'
		);
		assert.equal(response.headers.get('cache-control'), 'no-store');
		const anonymous = await fetchApp(path, { headers: { cookie: '' } });
		assert.equal(anonymous.headers.get('location'), '/');
		assert.equal((await fetchApp('/api/assets/not-an-id/download')).status, 404);
	});
	await t.test('temporary backend outage preserves session for retry', async () => {
		fixture.state.unavailable = true;
		const r = await fetchApp('/api/analytics');
		assert.equal(r.status, 503);
		assert.equal(r.headers.getSetCookie().length, 0);
		fixture.state.unavailable = false;
		assert.equal((await fetchApp('/api/analytics')).status, 200);
	});
	await t.test('expired refresh clears cookies and redirects SSR', async () => {
		await login();
		fixture.expireAccess();
		fixture.expireRefresh();
		const r = await fetchApp('/dashboard');
		assert.equal(r.status, 303);
		assert.equal(r.headers.get('location'), '/');
		assert.ok(r.headers.getSetCookie().every((c) => /Max-Age=0/.test(c)));
		cookie = '';
		await login();
		fixture.expireAccess();
		fixture.expireRefresh();
		assert.equal((await fetchApp('/api/analytics')).status, 401);
	});
	await t.test('still unauthorized after renewal fails without a retry loop', async () => {
		await login();
		fixture.state.rejectAllAccess = true;
		const before = fixture.state.refreshCalls;
		const r = await fetchApp('/api/analytics');
		assert.equal(r.status, 401);
		assert.equal(fixture.state.refreshCalls, before + 1);
		fixture.state.rejectAllAccess = false;
	});
	await t.test('missing access and rejected renewal stop after one refresh', async () => {
		await login();
		cookie = cookie
			.split('; ')
			.filter((c) => c.startsWith('panoptes_refresh='))
			.join('; ');
		fixture.state.rejectAllAccess = true;
		const before = fixture.state.refreshCalls;
		assert.equal((await fetchApp('/api/analytics')).status, 401);
		assert.equal(fixture.state.refreshCalls, before + 1);
		fixture.state.rejectAllAccess = false;
	});
	await t.test('logout revokes session and subsequent access returns to login', async () => {
		await login();
		const oldCookie = cookie;
		const r = await fetchApp('/api/auth/logout', { method: 'POST' });
		assert.equal(r.status, 204);
		assert.ok(r.headers.getSetCookie().every((c) => /Max-Age=0/.test(c)));
		cookie = oldCookie;
		assert.equal((await fetchApp('/dashboard')).headers.get('location'), '/');
	});
});

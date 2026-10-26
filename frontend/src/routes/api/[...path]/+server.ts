import { json, error, type RequestHandler } from '@sveltejs/kit';
import { api, login, clearSession, SessionExpired } from '#lib/server/api.ts';

const handler: RequestHandler = async (event) => {
	if (
		!['GET', 'HEAD'].includes(event.request.method) &&
		event.request.headers.get('origin') !== event.url.origin
	)
		error(403, 'Invalid origin.');
	const path = '/' + event.params.path;
	if (
		!/^\/(auth\/(login|logout|mcp-keys(?:\/[\da-f-]+)?)|categories|admin\/categories(?:\/[a-z][a-z0-9_]{0,59})?|extraction-logs(?:\/stream)?|browser-connections(?:\/(?:amazon_br|mercado_livre_br|pichau_br|terabyte_br)(?:\/(?:connect|frame|input|save|cancel|import|local\/(?:start|next|result)))?)?|sources|catalog\/canonical-products(?:\/[\da-f-]+\/listings)?|data(?:\/(?:bulk|[\da-f-]+))?|extraction-groups|analytics(?:\/prices(?:\/(?:dashboard|products))?|\/detail)?|alerts\/webhooks(?:\/[\da-f-]+(?:\/deliveries)?)?|routines(?:\/[\da-f-]+)?|search-terms(?:\/[\da-f-]+\/(discover|discover-sources|routine-sources|products))?|scrape-requests(?:\/[\da-f-]+(?:\/qualifications)?)?|products\/[\da-f-]+\/(refresh|tracking|observations))$/i.test(
			path
		)
	)
		error(404);
	const body = ['GET', 'HEAD'].includes(event.request.method)
		? undefined
		: await event.request.text();
	const maxBody =
		/^\/browser-connections\/(amazon_br|mercado_livre_br|pichau_br|terabyte_br)\/local\/result$/.test(
			path
		)
			? 12_000_000
			: 1024 * 1024;
	if (body && new TextEncoder().encode(body).length > maxBody)
		error(413, 'The data exceeds the allowed limit.');
	if (path === '/auth/login') {
		if (event.request.method !== 'POST') error(405);
		const response = await login(event, body || '{}');
		return response.ok
			? json({ ok: true })
			: json(
					{
						message:
							response.status === 401
								? 'Incorrect email or password.'
								: 'Check your details and try again.'
					},
					{ status: response.status }
				);
	}
	try {
		const response = await api(event, path + event.url.search, {
			method: event.request.method,
			body,
			...(path === '/extraction-logs/stream'
				? {
						signal: event.request.signal,
						headers: { 'Last-Event-ID': event.request.headers.get('Last-Event-ID') || '' }
					}
				: {})
		});
		if (path === '/extraction-logs/stream' && response.ok)
			return new Response(response.body, {
				status: response.status,
				headers: {
					'Content-Type': 'text/event-stream',
					'Cache-Control': 'no-store',
					'X-Accel-Buffering': 'no'
				}
			});
		if (path === '/auth/logout') clearSession(event);
		return new Response(response.status === 204 ? null : await response.text(), {
			status: response.status,
			headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }
		});
	} catch (cause) {
		if (cause instanceof SessionExpired)
			return json({ message: 'Your session has expired. Sign in again.' }, { status: 401 });
		throw cause;
	}
};
export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;

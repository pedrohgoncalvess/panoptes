import { error, type RequestEvent } from '@sveltejs/kit';
import { backendUrl } from '../../../config/backend.mjs';

type Tokens = {
	access_token: string;
	refresh_token: string;
	expires_in: number;
	refresh_expires_in?: number;
};
export class SessionExpired extends Error {}
const rotations = new Map<string, Promise<Tokens>>();
const base = () => backendUrl();

export function clearSession(event: RequestEvent) {
	event.cookies.delete('panoptes_access', { path: '/' });
	event.cookies.delete('panoptes_refresh', { path: '/' });
}

function save(event: RequestEvent, pair: Tokens) {
	const options = {
		path: '/',
		httpOnly: true,
		sameSite: 'strict' as const,
		secure: event.url.protocol === 'https:'
	};
	event.cookies.set('panoptes_access', pair.access_token, { ...options, maxAge: pair.expires_in });
	event.cookies.set('panoptes_refresh', pair.refresh_token, {
		...options,
		maxAge: pair.refresh_expires_in ?? 10 * 3600
	});
}

async function backend(path: string, init: RequestInit = {}, token?: string) {
	const headers = new Headers(init.headers);
	if (init.body) headers.set('Content-Type', 'application/json');
	if (token) headers.set('Authorization', `Bearer ${token}`);
	try {
		return await fetch(`${base()}${path}`, {
			...init,
			headers,
			signal: path.startsWith('/extraction-logs/stream')
				? AbortSignal.any([AbortSignal.timeout(65000), ...(init.signal ? [init.signal] : [])])
				: AbortSignal.timeout(
						path === '/data/bulk'
							? 120000
							: /^\/browser-connections\/(amazon_br|mercado_livre_br|pichau_br|terabyte_br)\/(connect|import|save)$/.test(
										path
								  )
								? 60000
								: 15000
					)
		});
	} catch {
		error(503, 'Unable to connect to the API. Try again.');
	}
}

async function renew(event: RequestEvent) {
	const token = event.cookies.get('panoptes_refresh');
	if (!token) throw new SessionExpired();
	let rotation = rotations.get(token);
	if (!rotation) {
		rotation = (async () => {
			const response = await backend('/auth/refresh', {
				method: 'POST',
				body: JSON.stringify({ refresh_token: token })
			});
			if (response.status === 401 || response.status === 422) throw new SessionExpired();
			if (!response.ok) error(response.status, 'Unable to renew the session.');
			return (await response.json()) as Tokens;
		})();
		rotations.set(token, rotation);
		// Briefly share the rotated pair with simultaneous requests carrying the old cookie.
		void rotation.then(
			() => {
				setTimeout(() => rotations.delete(token), 5000).unref();
			},
			() => {
				rotations.delete(token);
			}
		);
	}
	const pair = await rotation;
	save(event, pair);
	return pair.access_token;
}

export async function api(event: RequestEvent, path: string, init: RequestInit = {}) {
	try {
		let token = event.cookies.get('panoptes_access');
		const alreadyRenewed = !token;
		if (!token) token = await renew(event);
		let response = await backend(path, init, token);
		if (response.status === 401 && !alreadyRenewed) {
			token = await renew(event);
			response = await backend(path, init, token);
		}
		if (response.status === 401) throw new SessionExpired();
		return response;
	} catch (cause) {
		if (cause instanceof SessionExpired) clearSession(event);
		throw cause;
	}
}

export async function login(event: RequestEvent, body: string) {
	const response = await backend('/auth/login', { method: 'POST', body });
	if (response.ok) save(event, (await response.json()) as Tokens);
	return response;
}

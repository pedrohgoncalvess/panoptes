import { error, redirect, type RequestHandler } from '@sveltejs/kit';
import { api, SessionExpired } from '#lib/server/api.ts';

export const GET: RequestHandler = async (event) => {
	const id = event.params.assetId;
	if (!id || !/^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i.test(id)) error(404);
	let url: string;
	try {
		const response = await api(event, `/assets/${id}/url`);
		if (!response.ok) error(response.status, 'Unable to access the capture.');
		({ url } = (await response.json()) as { url: string });
	} catch (cause) {
		if (cause instanceof SessionExpired) redirect(303, '/');
		throw cause;
	}
	event.setHeaders({ 'Cache-Control': 'no-store' });
	const destination = new URL(url);
	if (!['http:', 'https:'].includes(destination.protocol)) error(502, 'Invalid capture URL.');
	redirect(303, destination, { external: [destination.origin] });
};

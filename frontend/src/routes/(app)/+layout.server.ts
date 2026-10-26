import { redirect, error } from '@sveltejs/kit';
import { api, SessionExpired } from '#lib/server/api.ts';
import type { LayoutServerLoad } from './$types';
export const load: LayoutServerLoad = async (event) => {
	event.setHeaders({ 'Cache-Control': 'no-store' });
	try {
		const response = await api(event, '/auth/me');
		if (!response.ok) error(response.status, 'Unable to verify the session.');
		return {
			user: (await response.json()) as { name: string; email: string; role: string },
			// Tracking pathname makes SvelteKit revalidate this server layout on navigation.
			pathname: event.url.pathname
		};
	} catch (cause) {
		if (cause instanceof SessionExpired) redirect(303, '/');
		throw cause;
	}
};

import { fail, redirect } from '@sveltejs/kit';
import { api, login, SessionExpired } from '#lib/server/api.ts';
import type { Actions, PageServerLoad } from './$types';

export const actions: Actions = {
	default: async (event) => {
		const form = await event.request.formData();
		const email = form.get('email');
		const password = form.get('password');
		if (typeof email !== 'string' || typeof password !== 'string')
			return fail(400, { message: 'Enter your email and password.' });
		const response = await login(event, JSON.stringify({ email: email.trim(), password }));
		if (!response.ok)
			return fail(response.status, {
				message: response.status === 401 ? 'Incorrect email or password.' : 'Unable to sign in.'
			});
		redirect(303, '/dashboard');
	}
};
export const load: PageServerLoad = async (event) => {
	event.setHeaders({ 'Cache-Control': 'no-store' });
	if (!event.cookies.get('panoptes_access') && !event.cookies.get('panoptes_refresh')) return {};
	try {
		const response = await api(event, '/auth/me');
		if (response.ok) redirect(303, '/dashboard');
	} catch (cause) {
		if (!(cause instanceof SessionExpired)) throw cause;
	}
	return {};
};

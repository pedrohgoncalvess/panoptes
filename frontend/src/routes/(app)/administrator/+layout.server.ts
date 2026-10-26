import { error } from '@sveltejs/kit';
import type { LayoutServerLoad } from './$types';
export const load: LayoutServerLoad = async ({ parent, url }) => {
	const { user } = await parent();
	if (url.pathname !== '/administrator/mcp-keys' && user.role !== 'admin')
		error(403, 'Access restricted to administrators.');
};

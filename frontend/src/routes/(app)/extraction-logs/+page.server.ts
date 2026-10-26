import { redirect } from '@sveltejs/kit';
export const load = ({ url }: { url: URL }) => redirect(308, '/extraction/logs' + url.search);

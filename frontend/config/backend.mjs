/** Resolve a private backend address at runtime, independently of the browser. */
export function backendUrl(env = process.env) {
	const configured = env.PANOPTES_API_URL?.trim();
	const host = env.BACKEND_HOST?.trim() || 'localhost';
	const port = env.BACKEND_PORT?.trim() || '8000';
	if (!configured && (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535)) {
		throw new Error('BACKEND_PORT must be between 1 and 65535');
	}
	const url = new URL(configured || `http://${host}:${port}`);
	if (!['http:', 'https:'].includes(url.protocol)) {
		throw new Error('PANOPTES_API_URL must use HTTP or HTTPS');
	}
	return url.href.replace(/\/+$/, '');
}

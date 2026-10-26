// adapter-node defaults to HTTPS when no trusted protocol header is configured.
// For direct local/container access, supply the protocol from server configuration,
// overwriting any client-supplied value before the adapter handles the request.
const direct = !process.env.PROTOCOL_HEADER;
const protocol = process.env.FRONTEND_PROTOCOL || 'http';
if (!['http', 'https'].includes(protocol)) throw new Error('Invalid FRONTEND_PROTOCOL');
if (direct) process.env.PROTOCOL_HEADER = 'x-panoptes-protocol';
// The result route accepts up to 6 MB of HTML plus JSON escaping. Individual
// API routes enforce their own smaller limits before forwarding to the backend.
process.env.BODY_SIZE_LIMIT ||= '12M';

const { server } = await import('./build/index.js');
if (direct) {
	server.prependListener('request', (request) => {
		request.headers['x-panoptes-protocol'] = protocol;
	});
}

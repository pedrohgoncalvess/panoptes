import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createFixtureApi } from './fixture-api.mjs';
const fixture = createFixtureApi({
	retailBrowser: process.env.FRONTEND_TEST_RETAIL_BROWSER === '1'
});
fixture.server.listen(0, '127.0.0.1');
await once(fixture.server, 'listening');
const production = process.env.FRONTEND_TEST_RUNTIME === 'node';
const port = process.env.FRONTEND_TEST_PORT || '5188';
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
				port,
				'--strictPort'
			],
	{
		env: {
			...process.env,
			HOST: '127.0.0.1',
			PORT: port,
			PANOPTES_API_URL: `http://127.0.0.1:${fixture.server.address().port}`
		},
		stdio: 'inherit',
		windowsHide: true
	}
);
const stop = () => {
	vite.kill();
	fixture.server.closeAllConnections();
	fixture.server.close();
};
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
vite.on('exit', () => {
	fixture.server.closeAllConnections();
	fixture.server.close();
});

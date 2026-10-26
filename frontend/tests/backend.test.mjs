import { test } from 'node:test';
import assert from 'node:assert/strict';
import { backendUrl } from '../config/backend.mjs';

test('local dev uses the published port and optional WSL host', () => {
	assert.equal(backendUrl({}), 'http://localhost:8000');
	assert.equal(backendUrl({ BACKEND_PORT: '8100' }), 'http://localhost:8100');
	assert.equal(
		backendUrl({ BACKEND_HOST: '172.20.0.2', BACKEND_PORT: '8100' }),
		'http://172.20.0.2:8100'
	);
});

test('Docker DNS and explicit URLs override local host and port at runtime', () => {
	assert.equal(
		backendUrl({ PANOPTES_API_URL: 'http://backend:8000/', BACKEND_PORT: '8100' }),
		'http://backend:8000'
	);
	assert.equal(
		backendUrl({ PANOPTES_API_URL: 'https://api.example.test/' }),
		'https://api.example.test'
	);
	assert.throws(() => backendUrl({ BACKEND_PORT: 'invalid' }));
	assert.throws(() => backendUrl({ PANOPTES_API_URL: 'file:///tmp' }));
});

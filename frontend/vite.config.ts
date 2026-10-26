import tailwindcss from '@tailwindcss/vite';
import adapter from '@sveltejs/adapter-node';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, loadEnv } from 'vite';
import { fileURLToPath } from 'node:url';
import { backendUrl } from './config/backend.mjs';

export default defineConfig(({ mode }) => {
	const frontendRoot = fileURLToPath(new URL('.', import.meta.url));
	const workspaceRoot = fileURLToPath(new URL('..', import.meta.url));
	const env = { ...loadEnv(mode, workspaceRoot, ''), ...loadEnv(mode, frontendRoot, '') };
	for (const key of ['PANOPTES_API_URL', 'BACKEND_HOST', 'BACKEND_PORT']) {
		if (env[key] !== undefined) process.env[key] = env[key];
	}
	backendUrl();
	return {
		server: { port: Number(env.FRONTEND_DEV_PORT || 5173) },
		plugins: [
			tailwindcss(),
			sveltekit({
				compilerOptions: {
					// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
					runes: ({ filename }) =>
						filename.split(/[/\\]/).includes('node_modules') ? undefined : true
				},

				adapter: adapter()
			})
		]
	};
});

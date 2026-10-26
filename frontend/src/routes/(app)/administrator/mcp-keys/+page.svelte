<script lang="ts">
	import { onMount } from 'svelte';
	import { request, date, type Routine, type Source } from '#lib/api.ts';
	import Button from '#lib/components/Button.svelte';
	import Notice from '#lib/components/Notice.svelte';
	import { page } from '$app/state';

	type Permissions = {
		create_routines: boolean;
		manage_routines: boolean;
		create_extractions: boolean;
		view_extractions: boolean;
		create_alerts: boolean;
		max_routines: number | null;
		sites: string[];
	};
	type Key = {
		public_id: string;
		name: string;
		admin: boolean;
		expires_at: string | null;
		revoked_at: string | null;
		permissions: Permissions;
		routine_ids: string[];
	};
	let keys = $state<Key[]>([]);
	let routines = $state<Routine[]>([]);
	let sources = $state<Source[]>([]);
	let name = $state('');
	let admin = $state(false);
	let expiration = $state('1m');
	let customDate = $state('');
	let selectedRoutines = $state<string[]>([]);
	let permissions = $state<Permissions>({
		create_routines: false,
		manage_routines: false,
		create_extractions: false,
		view_extractions: false,
		create_alerts: false,
		max_routines: 0,
		sites: []
	});
	let unlimited = $state(false);
	let secret = $state('');
	let message = $state('');
	let busy = $state(false);
	let loading = $state(true);
	const permissionLabels = [
		['create_routines', 'Create routines'],
		['manage_routines', 'Edit and delete authorized routines'],
		['create_extractions', 'Create extractions and move runs forward'],
		['view_extractions', 'View extractions and products from authorized routines'],
		['create_alerts', 'Create and manage your alerts for authorized routines']
	] as const;

	async function load() {
		message = '';
		try {
			const allRoutines: Routine[] = [];
			for (let offset = 0; ; offset += 100) {
				const batch = await request<Routine[]>(`/routines?limit=100&offset=${offset}`);
				allRoutines.push(...batch);
				if (batch.length < 100) break;
			}
			routines = allRoutines;
			[keys, sources] = await Promise.all([
				request<Key[]>('/auth/mcp-keys'),
				request<Source[]>('/sources')
			]);
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Unable to load keys.';
		} finally {
			loading = false;
		}
	}
	onMount(load);
	async function create(event: SubmitEvent) {
		event.preventDefault();
		busy = true;
		message = '';
		secret = '';
		try {
			const value = await request<{ key: string }>('/auth/mcp-keys', {
				method: 'POST',
				body: JSON.stringify({
					name,
					admin,
					expiration,
					...(expiration === 'custom' ? { expires_at: new Date(customDate).toISOString() } : {}),
					...(!admin
						? {
								permissions: {
									...permissions,
									max_routines: unlimited ? null : permissions.max_routines
								},
								routine_ids: selectedRoutines
							}
						: {})
				})
			});
			secret = value.key;
			name = '';
			await load();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Unable to create the key.';
		} finally {
			busy = false;
		}
	}
	async function revoke(id: string) {
		busy = true;
		message = '';
		try {
			await request(`/auth/mcp-keys/${id}`, { method: 'DELETE' });
			await load();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Unable to revoke.';
		} finally {
			busy = false;
		}
	}
</script>

<svelte:head><title>MCP keys · Panoptes</title></svelte:head>
<div class="keys-page">
	<header>
		<h1>MCP keys</h1>
		<p>Generate credentials to connect agents to permitted routines and data.</p>
	</header>
	<Notice {message} />
	{#if secret}
		<section class="key-secret" aria-label="New credential">
			<h2>Key created</h2>
			<p>Copy it now. This credential is only shown when created.</p>
			<label
				>Credential<textarea readonly value={secret} rows="4" aria-label="Generated MCP credential"
				></textarea></label
			>
			<p>Set this key in the <code>PANOPTES_MCP_KEY</code> variable on the MCP server.</p>
			<Button variant="secondary" onclick={() => (secret = '')}>Hide key</Button>
		</section>
	{/if}
	<section class="key-panel">
		<h2>New key</h2>
		<form onsubmit={create}>
			<label
				>Name<input
					required
					maxlength="100"
					bind:value={name}
					placeholder="Research agent"
				/></label
			>
			<label
				>Expiration<select aria-label="Expiration" bind:value={expiration}>
					<option value="1w">1 week</option><option value="2w">2 weeks</option>
					<option value="1m">1 month</option><option value="6m">6 months</option>
					<option value="1y">1 year</option><option value="never">Never expires</option>
					<option value="custom">Custom date</option>
				</select></label
			>
			{#if expiration === 'custom'}<label
					>Expires at (local time)<input
						type="datetime-local"
						required
						bind:value={customDate}
					/></label
				>{/if}
			{#if page.data.user?.role === 'admin'}
				<label class="check"
					><input type="checkbox" bind:checked={admin} />MCP admin — full access</label
				>
			{/if}
			{#if admin}<p>
					Access to all operations, routines, and marketplaces. No permission configuration is
					required.
				</p>
			{:else}
				<fieldset>
					<legend>Permissions</legend>
					{#each permissionLabels as [key, label] (key)}<label class="check"
							><input type="checkbox" bind:checked={permissions[key]} />{label}</label
						>{/each}
					{#if permissions.create_routines}
						<label class="check"
							><input type="checkbox" bind:checked={unlimited} />Unlimited new routines</label
						>
						{#if !unlimited}<label
								>Maximum routines created by this key<input
									type="number"
									min="0"
									max="100000"
									required
									bind:value={permissions.max_routines}
								/></label
							>{/if}
					{/if}
				</fieldset>
				<fieldset>
					<legend>Allowed marketplaces</legend>
					{#each sources as source (source.id)}<label class="check"
							><input
								type="checkbox"
								value={source.id}
								bind:group={permissions.sites}
							/>{source.name}</label
						>{/each}
				</fieldset>
				<fieldset>
					<legend>Authorized routines</legend>
					<p>
						Routines created by this key are also accessible to it. Extractions and alerts follow
						these selections.
					</p>
					{#each routines as routine (routine.public_id)}<label class="check"
							><input
								type="checkbox"
								value={routine.public_id}
								bind:group={selectedRoutines}
							/>{routine.name}</label
						>{/each}
					{#if routines.length === 0}<p>No routines created.</p>{/if}
				</fieldset>
			{/if}
			<Button type="submit" {busy} disabled={loading}>Generate key</Button>
		</form>
	</section>
	<section class="key-panel">
		<h2>Your keys</h2>
		{#if loading}<p>Loading…</p>{:else if !keys.length}<p>No keys created.</p>{/if}
		{#each keys as key (key.public_id)}
			<article>
				<div>
					<strong>{key.name}</strong>
					<p>
						{key.admin ? 'MCP admin' : `${key.routine_ids.length} authorized routines`} · {key.revoked_at
							? 'Revoked'
							: key.expires_at && new Date(key.expires_at) <= new Date()
								? 'Expired'
								: 'Active'}
					</p>
					<p>Expiration: {key.expires_at ? date(key.expires_at) : 'Never expires'}</p>
					{#if !key.admin}<p>
							Marketplaces: {key.permissions.sites
								.map((id) => sources.find((s) => s.id === id)?.name || id)
								.join(', ') || 'None'}
						</p>
						<p>
							{permissionLabels
								.filter(([id]) => key.permissions[id])
								.map(([, label]) => label)
								.join(' · ') || 'No permissions'}
						</p>{/if}
				</div>
				{#if !key.revoked_at}<Button
						variant="secondary"
						disabled={busy}
						onclick={() => revoke(key.public_id)}>Revoke</Button
					>{/if}
			</article>
		{/each}
	</section>
</div>

<style>
	.keys-page {
		display: grid;
		gap: 24px;
		max-width: 1000px;
	}
	h1 {
		font-size: 28px;
		font-weight: 650;
	}
	h2 {
		font-size: 20px;
		font-weight: 600;
	}
	p {
		color: var(--muted);
		line-height: 1.6;
	}
	.key-panel,
	.key-secret {
		padding: 24px;
		border: 1px solid var(--border);
		border-radius: 16px;
		background: white;
	}
	.key-secret {
		background: #eff6ff;
	}
	form,
	fieldset {
		display: grid;
		gap: 16px;
	}
	form {
		margin-top: 20px;
	}
	fieldset {
		padding: 20px;
		border: 1px solid var(--border);
		border-radius: 12px;
	}
	legend {
		font-weight: 600;
		padding: 0 6px;
	}
	label {
		display: grid;
		gap: 8px;
		font-size: 14px;
	}
	input:not([type='checkbox']),
	select,
	textarea {
		width: 100%;
		padding: 10px 12px;
		border: 1px solid #cbd5e1;
		border-radius: 8px;
		background: white;
	}
	.check {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	textarea {
		font-family: monospace;
		word-break: break-all;
	}
	article {
		display: flex;
		justify-content: space-between;
		align-items: start;
		gap: 20px;
		padding: 20px 0;
		border-bottom: 1px solid var(--border);
	}
	@media (max-width: 600px) {
		article {
			flex-direction: column;
			gap: 12px;
		}
	}
</style>

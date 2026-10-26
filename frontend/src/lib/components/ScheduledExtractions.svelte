<script lang="ts">
	import { onMount } from 'svelte';
	import { request, date, type Routine, type Source } from '#lib/api.ts';
	import Button from './Button.svelte';
	import Notice from './Notice.svelte';
	import Icon from './Icon.svelte';
	let { sources }: { sources: Source[] } = $props();
	let items = $state<Routine[]>([]);
	let loading = $state(true);
	let busy = $state('');
	let message = $state('');
	let success = $state('');
	let offset = $state(0);
	let now = $state(Date.now());
	let version = 0;
	let polling = false;
	const limit = 20;
	async function load(quiet = false) {
		const current = ++version;
		if (!quiet) {
			loading = true;
			message = '';
		}
		try {
			const result = await request<Routine[]>(
				`/routines?scheduled=true&limit=${limit}&offset=${offset}`
			);
			if (current === version) items = result;
		} catch (cause) {
			if (current === version)
				message = cause instanceof Error ? cause.message : 'Unable to load schedules.';
		} finally {
			if (current === version) loading = false;
		}
	}
	async function advance(item: Routine) {
		busy = item.public_id;
		message = success = '';
		version++;
		try {
			await request(`/routines/${item.public_id}/advance`, {
				method: 'POST',
				body: JSON.stringify({ next_run_at: item.next_run_at })
			});
			success = `Extraction “${item.name}” moved forward. Waiting for the scheduler to start the run.`;
			await load(true);
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Unable to move the extraction forward.';
			await load(true);
		} finally {
			busy = '';
		}
	}
	onMount(() => {
		void load();
		const timer = setInterval(() => {
			now = Date.now();
			if (!document.hidden && !busy && !loading && !polling) {
				polling = true;
				void load(true).finally(() => (polling = false));
			}
		}, 3000);
		return () => {
			clearInterval(timer);
			version++;
		};
	});
</script>

<Notice {message} retry={() => load()} />
<Notice message={success} success />
<div class="toolbar">
	<p>Next runs for active routines · refreshed every 3 seconds</p>
	<Button variant="secondary" onclick={() => load()} disabled={loading || !!busy}>Refresh</Button>
</div>
<section class="panel">
	{#if loading}
		<div class="loading-state"><span class="spinner"></span>Loading scheduled extractions…</div>
	{:else if items.length}
		<div class="table-scroll">
			<table>
				<thead><tr><th>Extraction</th><th>Source</th><th>Next run</th><th>Actions</th></tr></thead>
				<tbody>
					{#each items as item (item.public_id)}
						<tr>
							<td>
								<div class="table-title">{item.name}</div>
								<div class="table-subtitle">
									{item.term || 'Search term'} · {item.mode === 'discover' ? 'Discovery' : 'Update'}
								</div>
							</td>
							<td
								>{item.mode === 'refresh'
									? 'Sources for tracked products'
									: sources.find((source) => source.id === item.site)?.name || item.site || '—'}</td
							>
							<td>
								{date(item.next_run_at)}
								<div class="table-subtitle">
									{item.next_run_at && new Date(item.next_run_at).getTime() <= now
										? 'Waiting for the scheduler'
										: 'Scheduled'}
								</div>
							</td>
							<td
								><Button
									variant="secondary"
									onclick={() => advance(item)}
									busy={busy === item.public_id}
									disabled={!!busy ||
										!item.next_run_at ||
										new Date(item.next_run_at).getTime() <= now}>Run sooner</Button
								></td
							>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<div class="empty-state">
			<Icon name="routines" size={30} />
			<h3>No scheduled extractions{offset ? ' on this page' : ''}</h3>
			<p>Create or enable a routine to schedule extractions.</p>
			<a class="button button--secondary" href="/routines">Manage routines</a>
		</div>
	{/if}
	<div class="pagination">
		<span
			>{items.length ? `${offset + 1}–${offset + items.length}` : '0'} schedules on this page</span
		>
		<div>
			<Button
				variant="secondary"
				disabled={!offset || loading || !!busy}
				onclick={() => {
					offset -= limit;
					void load();
				}}>Previous</Button
			>
			<Button
				variant="secondary"
				disabled={items.length < limit || loading || !!busy}
				onclick={() => {
					offset += limit;
					void load();
				}}>Next</Button
			>
		</div>
	</div>
</section>

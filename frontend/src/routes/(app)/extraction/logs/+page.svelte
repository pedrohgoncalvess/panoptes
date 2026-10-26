<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { SvelteURLSearchParams } from 'svelte/reactivity';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { request, date, type Extraction, type ExtractionPage } from '#lib/api.ts';
	import Button from '#lib/components/Button.svelte';
	import ExtractionLogCard from '#lib/components/ExtractionLogCard.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import Status from '#lib/components/Status.svelte';
	import {
		stageTitle,
		executionStatuses,
		type ExtractionLog as Log
	} from '#lib/log-presentation.ts';
	type History = { items: Log[]; cursor: number; has_more: boolean };
	let logs = $state<Log[]>([]);
	let activeExecutions = $state<Extraction[]>([]);
	let executionError = $state('');
	let executionsLoading = $state(true);
	let selectedLog = $state<Log>();
	let dialog = $state<HTMLDialogElement>();
	const sources: Record<string, string> = {
		mercado_livre_br: 'Mercado Livre',
		amazon_br: 'Amazon Brazil',
		kabum_br: 'KaBuM!',
		pichau_br: 'Pichau',
		terabyte_br: 'TerabyteShop'
	};
	const levels: Record<string, string> = {
		INFO: 'Information',
		WARNING: 'Warning',
		ERROR: 'Error'
	};
	async function loadExecutions() {
		try {
			const groups = await Promise.all(
				['running', 'pending'].map(async (status) => {
					const items: Extraction[] = [];
					let offset = 0;
					while (mounted) {
						const result = await request<ExtractionPage>(
							`/scrape-requests?status=${status}&limit=100&offset=${offset}`
						);
						items.push(...result.items);
						offset += result.items.length;
						if (!result.items.length || offset >= result.total) break;
					}
					return items;
				})
			);
			if (mounted) {
				activeExecutions = [
					...new Map(groups.flat().map((item) => [item.public_id, item])).values()
				];
				executionError = '';
			}
		} catch (error) {
			if (mounted) executionError = (error as Error).message;
		} finally {
			if (mounted) executionsLoading = false;
		}
	}
	$effect(() => {
		if (selectedLog && dialog && !dialog.open) dialog.showModal();
		else if (!selectedLog && dialog?.open) dialog.close();
	});
	$effect(() => {
		const id = page.url.searchParams.get('request_id') || '';
		untrack(() => {
			if (mounted && requestId !== id) {
				requestId = id;
				void load();
			}
		});
	});
	let extractions = $state<ExtractionPage>();
	let requestId = $state('');
	let site = $state('');
	let level = $state('');
	let connectionStatus = $state('Loading history');
	let message = $state('');
	let loading = $state(false);
	let live = $state(true);
	let hasMore = $state(false);
	const pageSize = 25;
	let currentPage = $state(1);
	let pageCursors = $state<(number | undefined)[]>([undefined]);
	async function changePage(target: number) {
		if (target < 1 || loading) return;
		if (target > currentPage) pageCursors[target - 1] = logs[0]?.id;
		await load(pageCursors[target - 1], target);
	}
	let source: EventSource | undefined;
	let generation = 0;
	let mounted = false;
	function query() {
		const params = new SvelteURLSearchParams();
		if (requestId) params.set('request_id', requestId);
		if (site) params.set('site', site);
		if (level) params.set('level', level);
		return params;
	}
	function stop() {
		source?.close();
		source = undefined;
	}
	async function load(before?: number, targetPage = 1) {
		stop();
		const version = ++generation;
		loading = true;
		message = '';
		live = targetPage === 1;
		connectionStatus = before ? 'History' : 'Loading history';
		try {
			const params = query();
			params.set('limit', String(pageSize));
			if (before) params.set('before', String(before));
			const history = await request<History>('/extraction-logs?' + params);
			if (!mounted || version !== generation) return;
			logs = history.items;
			currentPage = targetPage;
			if (targetPage === 1) pageCursors = [undefined];
			hasMore = history.has_more;
			if (before) return;
			params.delete('before');
			params.set('after', String(history.cursor));
			source = new EventSource('/api/extraction-logs/stream?' + params);
			source.onopen = () => {
				if (version === generation) connectionStatus = 'Live';
			};
			source.addEventListener('log', (event) => {
				if (version !== generation) return;
				const entry: Log = JSON.parse((event as MessageEvent).data);
				if (!logs.some((row) => row.id === entry.id)) {
					const updated = [...logs, entry].sort((a, b) => a.id - b.id);
					hasMore = hasMore || updated.length > pageSize;
					logs = updated.slice(-pageSize);
				}
			});
			source.onerror = () => {
				if (version !== generation) return;
				connectionStatus = 'Reconnecting';
				// The normal API path handles expired authentication without
				// putting bearer tokens in the EventSource URL.
				void request('/extraction-logs?limit=1').catch((error) => {
					if (version === generation) message = error.message;
				});
			};
		} catch (error) {
			if (version === generation) {
				message = (error as Error).message;
				connectionStatus = 'Unavailable';
			}
		} finally {
			if (version === generation) loading = false;
		}
	}
	onMount(() => {
		mounted = true;
		requestId = page.url.searchParams.get('request_id') || '';
		void request<ExtractionPage>('/scrape-requests?limit=100')
			.then((value) => {
				if (mounted) extractions = value;
			})
			.catch(() => {});
		void load();
		void loadExecutions();
		let polling = false;
		const timer = setInterval(() => {
			if (!document.hidden && !polling) {
				polling = true;
				void loadExecutions().finally(() => {
					polling = false;
				});
			}
		}, 3000);
		return () => {
			clearInterval(timer);
			mounted = false;
			generation++;
			stop();
		};
	});
</script>

<svelte:head><title>Now · Extractions · Panoptes</title></svelte:head>
<div class="page-header">
	<div>
		<span class="eyebrow">EXTRACTIONS</span>
		<h1>Now</h1>
	</div>
	<span class="connection" class:connected={connectionStatus === 'Live'} role="status"
		>{connectionStatus}</span
	>
</div>
<section class="panel executions-panel" aria-label="Runs in progress">
	<div class="panel-header">
		<div>
			<h2>Runs in progress <span class="execution-count">{activeExecutions.length}</span></h2>
			<p>Queued and running · refreshed every 3 seconds</p>
		</div>
	</div>
	{#if executionError}<p class="execution-error" role="alert">{executionError}</p>{/if}
	{#if executionsLoading}<div class="loading-state">Loading runs…</div>
	{:else if activeExecutions.length}<div class="table-scroll">
			<table class="execution-table">
				<thead
					><tr
						><th>Extraction</th><th>Source</th><th>Status</th><th>Started at</th><th
							><span class="sr-only">Logs</span></th
						></tr
					></thead
				>
				<tbody
					>{#each activeExecutions as item (item.public_id)}
						<tr
							onclick={(event) => {
								if (!(event.target as HTMLElement).closest('a'))
									void goto('/extraction/logs?request_id=' + item.public_id);
							}}
							><td
								><a class="execution-link" href={'/extraction/logs?request_id=' + item.public_id}
									>{item.term || item.source_key || 'Product update'}<small
										>{item.public_id.slice(0, 8)}</small
									></a
								></td
							>
							<td>{sources[item.site || ''] || item.site || '—'}</td><td
								><Status status={item.status} /></td
							><td>{date(item.created_at)}</td>
							<td
								><a
									class="button button--ghost"
									href={'/extraction/logs?request_id=' + item.public_id}
									>View logs <Icon name="chevron" size={14} /></a
								></td
							></tr
						>
					{/each}</tbody
				>
			</table>
		</div>
	{:else}<div class="empty-state">
			<h3>No runs in progress</h3>
			<p>Upcoming extractions will appear here automatically.</p>
		</div>{/if}
</section>
<div class="logs-heading">
	<h2>Extraction logs</h2>
	{#if requestId}<a href="/extraction/logs">View all extractions</a>{/if}
</div>
<form
	class="log-filters"
	onsubmit={(event) => {
		event.preventDefault();
		void load();
	}}
>
	<label
		>Extraction<select aria-label="Extraction" bind:value={requestId}
			><option value="">All extractions</option>
			{#if requestId && !extractions?.items.some((item) => item.public_id === requestId)}<option
					value={requestId}>{requestId}</option
				>{/if}
			{#each extractions?.items || [] as item (item.public_id)}<option value={item.public_id}
					>{item.term || item.source_key || 'Update'} · {item.public_id.slice(0, 8)} · {executionStatuses[
						item.status
					] || item.status}</option
				>{/each}
		</select></label
	>
	<label
		>Source<select aria-label="Source" bind:value={site}
			><option value="">All sources</option>{#each Object.entries(sources) as [id, name]}<option
					value={id}>{name}</option
				>{/each}</select
		></label
	>
	<label
		>Level<select aria-label="Level" bind:value={level}
			><option value="">All levels</option><option value="INFO">Information</option><option
				value="WARNING">Warning</option
			><option value="ERROR">Error</option></select
		></label
	>
	<Button type="submit" disabled={loading}>Apply filters</Button>
</form>
{#if message}<p role="alert">{message}</p>{/if}
<div class="log-tools">
	<p>
		{logs.length} events · {live ? 'Latest events, refreshed automatically' : 'Previous events'}
	</p>
	<div>
		{#if !live}<Button disabled={loading} onclick={() => void load()}>Back to live</Button>{/if}
	</div>
</div>
{#if !logs.length && !loading}<div class="empty-state">
		<h3>No events found</h3>
		<p>New extractions will appear here. Adjust the filters to view history.</p>
	</div>{/if}
{#if logs.length}<section class="panel log-table-panel">
		<div class="table-scroll">
			<table class="log-table">
				<thead><tr><th>Time</th><th>Level</th><th>Source</th><th>Event</th><th>Run</th></tr></thead>
				<tbody
					>{#each [...logs].reverse() as entry (entry.id)}
						<tr onclick={() => (selectedLog = entry)}>
							<td
								><time datetime={entry.created_at}
									>{new Date(entry.created_at).toLocaleString('en-US', { hour12: false })}</time
								></td
							>
							<td
								><span
									class="log-level"
									class:error={entry.level === 'ERROR'}
									class:warning={entry.level === 'WARNING'}
									>{levels[entry.level] || entry.level}</span
								></td
							>
							<td>{sources[entry.site || ''] || 'Processing'}</td>
							<td
								><button
									class="event-button"
									onclick={() => (selectedLog = entry)}
									aria-label={'Open details:' + stageTitle(entry)}>{stageTitle(entry)}</button
								></td
							>
							<td class="execution-id">{entry.request_id.slice(0, 8)}</td>
						</tr>
					{/each}</tbody
				>
			</table>
		</div>
	</section>{/if}
<div class="pagination log-pagination" aria-label="Log pagination">
	<span>Page {currentPage} · {logs.length} events</span>
	<div>
		<Button
			variant="secondary"
			disabled={loading || currentPage === 1}
			onclick={() => void changePage(currentPage - 1)}>Previous</Button
		>
		<Button
			variant="secondary"
			disabled={loading || !hasMore || !logs.length}
			onclick={() => void changePage(currentPage + 1)}>Next</Button
		>
	</div>
</div>
<dialog
	bind:this={dialog}
	class="log-dialog"
	aria-labelledby="log-dialog-title"
	onclose={() => (selectedLog = undefined)}
>
	<div class="dialog-heading">
		<h2 id="log-dialog-title">Log details</h2>
		<Button variant="ghost" onclick={() => (selectedLog = undefined)} aria-label="Close log details"
			><Icon name="close" /></Button
		>
	</div>
	{#if selectedLog}<ExtractionLogCard entry={selectedLog} />{/if}
</dialog>

<style>
	.table-scroll {
		position: relative;
	}
	.executions-panel {
		margin-bottom: 28px;
	}
	.execution-count {
		font-size: 12px;
		padding: 3px 8px;
		border-radius: 20px;
		background: #eef4fc;
		color: #275b96;
	}
	.execution-error {
		padding: 0 24px;
	}
	.execution-table tbody tr {
		cursor: pointer;
	}
	.execution-table tbody tr:hover,
	.execution-table tbody tr:focus-within {
		background: #f3f6fa;
	}
	.execution-link {
		display: grid;
		gap: 3px;
		font-weight: 600;
	}
	.execution-link small {
		color: #61748f;
		font-weight: 400;
	}
	.logs-heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		margin-bottom: 16px;
	}
	.logs-heading h2 {
		margin: 0;
		font-size: 18px;
	}
	.connection {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		align-self: center;
		font-size: 12px;
		font-weight: 600;
	}
	.connection::before {
		content: '';
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: currentColor;
	}
	.log-table th,
	.log-table td {
		padding: 10px 16px;
		font-size: 12px;
	}
	.log-table tbody tr {
		cursor: pointer;
	}
	.log-table tbody tr:hover,
	.log-table tbody tr:focus-within {
		background: #f3f6fa;
	}
	.log-table td:first-child {
		white-space: nowrap;
		color: #61748f;
	}
	.event-button {
		background: transparent;
		border: 0;
		padding: 0;
		font: inherit;
		font-weight: 600;
		color: inherit;
		text-align: left;
		cursor: pointer;
	}
	.event-button:focus-visible {
		outline: 2px solid #4778bc;
		outline-offset: 4px;
	}
	.log-level {
		display: inline-block;
		white-space: nowrap;
		border-radius: 20px;
		padding: 3px 8px;
		color: #275b96;
		background: #eef4fc;
		font-weight: 600;
	}
	.log-level.error {
		color: #aa2434;
		background: #fff0f2;
	}
	.log-level.warning {
		color: #946509;
		background: #fff6df;
	}
	.execution-id {
		color: #61748f;
		font-family: monospace;
	}
	.log-dialog {
		position: fixed;
		inset: 0;
		margin: auto;
		overflow: auto;
		width: min(820px, calc(100vw - 32px));
		max-height: calc(100dvh - 48px);
		padding: 20px;
		border: 1px solid #dce3ed;
		border-radius: 16px;
		background: #f7f9fc;
		color: inherit;
		box-shadow: 0 24px 80px #15243d40;
	}
	.log-dialog::backdrop {
		background: #101d36a6;
		backdrop-filter: blur(3px);
	}
	.dialog-heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		margin-bottom: 16px;
	}
	.dialog-heading h2 {
		margin: 0;
		font-size: 18px;
	}
	@media (max-width: 800px) {
		.log-dialog {
			margin: auto;
			padding: 12px;
		}
	}

	.log-filters {
		display: grid;
		grid-template-columns: 2fr 1fr 1fr auto;
		gap: 16px;
		align-items: end;
		padding: 20px;
		border: 1px solid #dce3ed;
		border-radius: 12px;
		background: white;
	}
	label {
		display: grid;
		gap: 7px;
		font-weight: 600;
		min-width: 0;
	}
	select {
		width: 100%;
		min-width: 0;
		border: 1px solid #cbd5e1;
		border-radius: 7px;
		background: white;
		padding: 10px;
		font: inherit;
		color: inherit;
	}
	.connection {
		padding: 7px 12px;
		border-radius: 20px;
		background: #e8edf4;
		white-space: nowrap;
	}
	.connection.connected {
		background: #ddf4e9;
		color: #176044;
	}
	.log-tools {
		display: flex;
		justify-content: space-between;
		gap: 12px;
		align-items: center;
		margin: 18px 0;
	}
	.log-tools div {
		display: flex;
		gap: 8px;
	}

	@media (max-width: 800px) {
		.connection {
			align-self: flex-start;
		}
		.logs-heading,
		.log-tools div {
			flex-wrap: wrap;
		}
		.log-filters {
			grid-template-columns: 1fr;
		}
		.log-tools {
			align-items: start;
			flex-direction: column;
		}
	}
</style>

<script lang="ts">
	import { untrack } from 'svelte';
	import {
		request,
		type Extraction,
		type ExtractionGroup,
		type ExtractionPage,
		type Source
	} from '#lib/api.ts';
	import ExtractionTable from './ExtractionTable.svelte';
	import Status from './Status.svelte';
	import Button from './Button.svelte';
	import Icon from './Icon.svelte';
	let {
		items,
		select,
		rerun,
		busy,
		sources
	}: {
		items: ExtractionGroup[];
		select: (item: Extraction) => void;
		rerun: (item: Extraction) => void;
		busy: boolean;
		sources: Source[];
	} = $props();
	let expanded = $state<string[]>([]);
	let histories = $state<Record<string, ExtractionPage>>({});
	let errors = $state<Record<string, string>>({});
	let loading = $state<Record<string, boolean>>({});
	let offsets = $state<Record<string, number>>({});
	const versions: Record<string, number> = {};
	const limit = 10;
	async function load(key: string, quiet = false) {
		const version = (versions[key] = (versions[key] || 0) + 1);
		if (!quiet) loading[key] = true;
		try {
			const params = new URLSearchParams({
				group_key: key,
				limit: String(limit),
				offset: String(offsets[key] || 0)
			});
			const result = await request<ExtractionPage>('/scrape-requests?' + params);
			if (versions[key] === version) {
				histories[key] = result;
				errors[key] = '';
			}
		} catch (cause) {
			if (versions[key] === version) errors[key] = (cause as Error).message;
		} finally {
			if (versions[key] === version) loading[key] = false;
		}
	}
	function toggle(key: string) {
		if (expanded.includes(key)) expanded = expanded.filter((value) => value !== key);
		else {
			expanded = [...expanded, key];
			void load(key);
		}
	}
	$effect(() => {
		const keys = items.map((item) => item.group_key);
		untrack(() => {
			for (const key of expanded) if (keys.includes(key)) void load(key, true);
		});
	});
</script>

{#if items.length}
	{#each items as item (item.group_key)}
		<section class="extraction-group">
			<div class="group-header">
				<button
					class="group-toggle"
					aria-expanded={expanded.includes(item.group_key)}
					aria-controls={'history-' + item.public_id}
					onclick={() => toggle(item.group_key)}
				>
					<span class="group-chevron" class:expanded={expanded.includes(item.group_key)}
						><Icon name="chevron" size={16} /></span
					>
					<span class="group-term"
						>{item.term || item.source_key || 'Product update'}<small
							>{item.execution_count} {item.execution_count === 1 ? 'run' : 'runs'}</small
						></span
					>
				</button>
				<Button variant="ghost" onclick={() => select(item)}>Details</Button>
				<a class="button button--ghost" href={'/data?request_id=' + item.public_id}>Data</a>
				<Button
					variant="ghost"
					aria-label={'Run again: ' + (item.term || item.source_key || 'product')}
					title="Run term again"
					disabled={busy || (!item.search_term_id && !item.entity_id)}
					onclick={() => rerun(item)}><Icon name="play" size={18} /></Button
				>
				<span class="latest-status"><Status status={item.status} /></span>
			</div>
			{#if expanded.includes(item.group_key)}<div
					id={'history-' + item.public_id}
					class="group-history"
				>
					{#if errors[item.group_key]}<p role="alert">{errors[item.group_key]}</p>{/if}
					{#if loading[item.group_key]}<div class="loading-state">Loading runs…</div>
					{:else if histories[item.group_key]}{@const history = histories[item.group_key]}
						<ExtractionTable items={history.items} {select} {sources} />
						<div class="pagination">
							<span>{history.total} runs</span>
							<div>
								<Button
									variant="secondary"
									disabled={!history.offset}
									onclick={() => {
										offsets[item.group_key] = history.offset - limit;
										void load(item.group_key);
									}}>Previous</Button
								>
								<Button
									variant="secondary"
									disabled={history.offset + limit >= history.total}
									onclick={() => {
										offsets[item.group_key] = history.offset + limit;
										void load(item.group_key);
									}}>Next</Button
								>
							</div>
						</div>
					{/if}
				</div>{/if}
		</section>
	{/each}
{:else}<div class="empty-state">
		<Icon name="extractions" size={28} />
		<h3>No extractions yet</h3>
		<p>Start a discovery or choose another filter.</p>
	</div>{/if}

<style>
	.group-history :global(.table-scroll) {
		position: relative;
	}
	.extraction-group + .extraction-group {
		border-top: 1px solid var(--border);
	}
	.group-header {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 16px 24px;
	}
	.group-toggle {
		display: flex;
		align-items: center;
		gap: 12px;
		background: transparent;
		border: 0;
		padding: 0;
		text-align: left;
		color: inherit;
		font: inherit;
		cursor: pointer;
		min-width: 0;
	}
	.group-toggle:focus-visible {
		outline: 2px solid #4778bc;
		outline-offset: 5px;
	}
	.group-term {
		font-weight: 600;
		overflow-wrap: anywhere;
	}
	.group-term small {
		display: block;
		margin-top: 4px;
		font-size: 12px;
		font-weight: 400;
		color: var(--muted);
	}
	.group-chevron {
		display: flex;
		flex-shrink: 0;
		transition: transform 150ms;
	}
	.group-chevron.expanded {
		transform: rotate(90deg);
	}
	.latest-status {
		margin-left: auto;
	}
	.group-history {
		background: #fafbfc;
	}
	.group-history > p {
		padding: 12px 24px;
	}
	@media (max-width: 560px) {
		.group-header {
			padding: 16px;
			flex-wrap: wrap;
		}
		.latest-status {
			width: 100%;
			margin-left: 28px;
		}
	}
</style>

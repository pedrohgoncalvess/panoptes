<script lang="ts">
	import { date, type Extraction, type Source } from '#lib/api.ts';
	import Status from './Status.svelte';
	import Button from './Button.svelte';
	import Icon from './Icon.svelte';
	let {
		items,
		select,
		rerun,
		busy = false,
		sources = []
	}: {
		items: Extraction[];
		select?: (value: Extraction) => void;
		rerun?: (value: Extraction) => void;
		busy?: boolean;
		sources?: Source[];
	} = $props();
</script>

{#if items.length}<div class="table-scroll">
		<table>
			<thead
				><tr
					><th>Extraction</th><th>Source</th><th>Type</th><th>Status</th><th>Started at</th
					>{#if select}<th><span class="sr-only">Details</span></th>{/if}{#if rerun}<th
							><span class="sr-only">Run again</span></th
						>{/if}<th>Logs</th></tr
				></thead
			><tbody
				>{#each items as item (item.public_id)}<tr
						><td
							><div class="table-title">
								{item.term || item.source_key || 'Product update'}
							</div>
							<div class="table-subtitle">{item.public_id.slice(0, 8)}</div></td
						><td class="muted"
							>{sources.find((s) => s.id === item.site)?.name || item.site || '—'}</td
						><td class="muted">{item.mode === 'discover' ? 'Discovery' : 'Update'}</td><td
							><Status status={item.status} /></td
						><td class="muted">{date(item.created_at)}</td>{#if select}<td
								><Button variant="ghost" onclick={() => select?.(item)}
									>Details <Icon name="chevron" size={14} /></Button
								></td
							>{/if}{#if rerun}<td
								><Button
									variant="secondary"
									disabled={busy ||
										['pending', 'running'].includes(item.status) ||
										(!item.search_term_id && !item.entity_id)}
									onclick={() => rerun?.(item)}>Run again</Button
								></td
							>{/if}<td
							><a class="button button--ghost" href={'/data?request_id=' + item.public_id}>Data</a
							><a
								class="button button--ghost"
								href={'/extraction/logs?request_id=' + item.public_id}
								>View logs <Icon name="chevron" size={14} /></a
							></td
						></tr
					>{/each}</tbody
			>
		</table>
	</div>{:else}<div class="empty-state">
		<Icon name="extractions" size={28} />
		<h3>No extractions yet</h3>
		<p>Start a discovery or choose another filter.</p>
	</div>{/if}

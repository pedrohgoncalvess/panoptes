<script lang="ts">
	import { onMount } from 'svelte';
	import { SvelteURLSearchParams } from 'svelte/reactivity';
	import { page } from '$app/state';
	import { request, date, type Source, type Extraction, type ExtractionPage } from '#lib/api.ts';
	import Button from '#lib/components/Button.svelte';
	import Input from '#lib/components/Input.svelte';
	import Select from '#lib/components/Select.svelte';
	import Notice from '#lib/components/Notice.svelte';
	import ProductImage from '#lib/components/ProductImage.svelte';

	type Payload = {
		offer?: {
			price?: string | number | null;
			currency?: string;
			availability?: string;
			image_urls?: string[];
		};
		[key: string]: unknown;
	};
	type Row = {
		public_id: string;
		site: string;
		source_key: string;
		title: string;
		canonical_product_id?: string;
		canonical_name?: string;
		normalization_status?: string;
		taxonomy?: { id: string; name: string; parent_id: string | null; parent_name: string | null }[];
		url?: string;
		brand?: string;
		category?: string;
		attributes?: Record<string, unknown>;
		enabled: boolean;
		excluded: boolean;
		observed_at?: string;
		observations: number;
		terms?: string;
		data?: Payload;
		image_url?: string;
	};
	type Filters = {
		q?: string;
		site?: string;
		request_id?: string;
		price_operator?: string;
		price?: number;
		price_to?: number;
		currency?: string;
	};
	type Result = { items: Row[]; total: number };
	type Observation = { public_id: string; created_at: string; payload: Payload };
	let result = $state<Result>({ items: [], total: 0 });
	let sources = $state<Source[]>([]);
	let extractions = $state<Extraction[]>([]);
	let q = $state('');
	let site = $state('');
	let extraction = $state('');
	let offset = $state(0);
	let loading = $state(true);
	let busy = $state(false);
	let message = $state('');
	let success = $state('');
	let applied = $state<Filters>({});
	let priceOperator = $state('');
	let priceValue = $state<number | undefined>();
	let priceTo = $state<number | undefined>();
	let allMatching = $state(false);
	let selectedIds = $state<string[]>([]);
	let excludedIds = $state<string[]>([]);
	const selectedCount = $derived(
		allMatching ? Math.max(0, result.total - excludedIds.length) : selectedIds.length
	);
	function clearSelection() {
		allMatching = false;
		selectedIds = [];
		excludedIds = [];
	}
	function selectAll() {
		allMatching = true;
		selectedIds = [];
		excludedIds = [];
	}
	function isSelected(id: string) {
		return allMatching ? !excludedIds.includes(id) : selectedIds.includes(id);
	}
	function selectRow(id: string, checked: boolean) {
		if (allMatching)
			excludedIds = checked ? excludedIds.filter((item) => item !== id) : [...excludedIds, id];
		else selectedIds = checked ? [...selectedIds, id] : selectedIds.filter((item) => item !== id);
	}
	let purge = $state(false);
	let dialog: HTMLDialogElement;
	let history = $state<Observation[]>([]);
	let historyRow = $state<Row>();
	let historyOffset = $state(0);
	let historyLoading = $state(false);
	let expanded = $state('');
	let version = 0;
	let historyVersion = 0;
	const limit = 25;
	const label = (id: string) => sources.find((source) => source.id === id)?.name || id;
	const value = (data: unknown) =>
		data == null ? '—' : typeof data === 'object' ? JSON.stringify(data, null, 2) : String(data);
	function price(data?: Payload) {
		const offer = data?.offer;
		if (offer?.price == null) return '—';
		return new Intl.NumberFormat('en-US', {
			style: 'currency',
			currency: offer.currency || 'BRL'
		}).format(Number(offer.price));
	}
	async function load(reset = false) {
		if (reset) {
			offset = 0;
			clearSelection();
			applied = {
				...(q.trim() ? { q: q.trim() } : {}),
				...(site ? { site } : {}),
				...(extraction ? { request_id: extraction } : {}),
				...(priceOperator
					? {
							price_operator: priceOperator,
							price: priceValue,
							currency: 'BRL',
							...(priceOperator === 'between' ? { price_to: priceTo } : {})
						}
					: {})
			};
		}
		const current = ++version;
		loading = true;
		message = '';
		try {
			const params = new SvelteURLSearchParams({ limit: String(limit), offset: String(offset) });
			for (const [key, value] of Object.entries(applied))
				if (value != null) params.set(key, String(value));
			const response = await request<Result>(`/data?${params}`);
			if (current === version) result = response;
		} catch (cause) {
			if (current === version) {
				result = { items: [], total: 0 };
				clearSelection();
				message = cause instanceof Error ? cause.message : 'Unable to load data.';
			}
		} finally {
			if (current === version) loading = false;
		}
	}
	async function loadHistory(row: Row, start = 0) {
		const current = ++historyVersion;
		historyRow = row;
		historyOffset = start;
		historyLoading = true;
		history = [];
		expanded = '';
		try {
			const response = await request<Observation[]>(
				`/products/${row.public_id}/observations?limit=${limit}&offset=${start}`
			);
			if (current === historyVersion) history = response;
		} catch (cause) {
			if (current === historyVersion)
				message = cause instanceof Error ? cause.message : 'Unable to load history.';
		} finally {
			if (current === historyVersion) historyLoading = false;
		}
	}
	function confirm(all: boolean) {
		if (!selectedCount) return;
		purge = all;
		dialog.showModal();
	}
	async function remove() {
		if (!selectedCount) return;
		busy = true;
		message = success = '';
		try {
			const response = await request<{ affected: number }>('/data/bulk', {
				method: 'POST',
				body: JSON.stringify({
					action: purge ? 'purge' : 'exclude',
					expected_count: selectedCount,
					...(allMatching
						? { all_matching: true, filters: applied, excluded_ids: excludedIds }
						: { ids: selectedIds })
				})
			});
			success = purge
				? `Data from ${response.affected} page(s) deleted. New collections from these pages have been blocked.`
				: `${response.affected} page(s) excluded from extractions. History was preserved.`;
			dialog.close();
			historyVersion++;
			historyRow = undefined;
			clearSelection();
			offset = 0;
			await load();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Unable to delete.';
			dialog.close();
		} finally {
			busy = false;
		}
	}
	onMount(() => {
		extraction = page.url.searchParams.get('request_id') || '';
		applied = extraction ? { request_id: extraction } : {};
		void load();
		void request<Source[]>('/sources')
			.then((items) => {
				sources = items;
			})
			.catch(() => {});
		void request<ExtractionPage>('/scrape-requests?limit=100')
			.then((response) => {
				extractions = response.items;
			})
			.catch(() => {});
		return () => {
			version++;
			historyVersion++;
		};
	});
</script>

<svelte:head><title>Data · Panoptes</title></svelte:head>
<div class="page-header">
	<div>
		<h1>Data</h1>
		<p>Extraction results organized by product and source page.</p>
	</div>
	<Button variant="secondary" onclick={() => load()} disabled={loading || busy}>Refresh</Button>
</div>
<Notice {message} /><Notice message={success} success />
<form
	class="filters"
	onsubmit={(event) => {
		event.preventDefault();
		void load(true);
	}}
>
	<Input id="data-search" label="Search product" bind:value={q} placeholder="Title, code, or URL" />
	<Select
		id="data-source"
		label="Source"
		bind:value={site}
		options={[
			{ value: '', label: 'All sources' },
			...sources.map((source) => ({ value: source.id, label: source.name }))
		]}
	/>
	<Select
		id="data-extraction"
		label="Extraction"
		bind:value={extraction}
		options={[
			{ value: '', label: 'All extractions' },
			...(extraction && !extractions.some((item) => item.public_id === extraction)
				? [{ value: extraction, label: 'Selected extraction' }]
				: []),
			...extractions.map((item) => ({
				value: item.public_id,
				label: `${item.term || item.source_key || 'Update'} · ${item.site ? label(item.site) : ''} · ${date(item.created_at)}`
			}))
		]}
	/>
	<div class="price-filter">
		<Select
			id="data-price-operator"
			label="Price (R$)"
			bind:value={priceOperator}
			options={[
				{ value: '', label: 'Any price' },
				{ value: 'gt', label: 'Greater than' },
				{ value: 'eq', label: 'Equal to' },
				{ value: 'lt', label: 'Less than' },
				{ value: 'between', label: 'Between (inclusive)' }
			]}
		/>
		{#if priceOperator}<Input
				id="data-price-value"
				label={priceOperator === 'between' ? 'Minimum price (R$)' : 'Value (R$)'}
				type="number"
				min={0}
				max="99999999999999.99"
				step="0.01"
				required
				bind:value={priceValue}
			/>{/if}
		{#if priceOperator === 'between'}<Input
				id="data-price-to"
				label="Maximum price (R$)"
				type="number"
				min={priceValue ?? 0}
				max="99999999999999.99"
				step="0.01"
				required
				bind:value={priceTo}
			/>{/if}
	</div>
	<div class="filter-submit">
		<Button type="submit" disabled={busy || loading}>Apply filters</Button>
	</div>
</form>
<section class="panel data-grid" aria-label="Extraction results" aria-busy={loading}>
	<div class="grid-toolbar">
		<div class="selection-summary">
			<strong>{result.total} results</strong><span aria-live="polite"
				>{selectedCount} selected{allMatching ? ' across all pages' : ''}</span
			>
		</div>
		<div class="bulk-actions">
			<Button variant="ghost" disabled={loading || busy || !result.total} onclick={selectAll}
				>Select all</Button
			>
			<Button variant="ghost" disabled={loading || busy || !selectedCount} onclick={clearSelection}
				>Deselect all</Button
			>
			<Button
				variant="secondary"
				disabled={loading || busy || !selectedCount}
				onclick={() => confirm(false)}>Exclude from extractions</Button
			>
			<Button
				variant="danger"
				disabled={loading || busy || !selectedCount}
				onclick={() => confirm(true)}>Delete all data</Button
			>
		</div>
	</div>
	<p class="selection-hint">
		Select all includes every result matching the applied filters, including other pages.
	</p>
	{#if loading}<div class="loading-state">Loading data…</div>{:else if result.items.length}
		<!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard focus allows scrolling the wide table without a mouse.) -->
		<div
			class="table-scroll results-scroll"
			tabindex="0"
			role="region"
			aria-label="Product table with horizontal scrolling"
		>
			<table class="results-table">
				<colgroup
					><col style="width: 44px" /><col style="width: 54px" /><col style="width: 60px" /><col
						style="width: 290px"
					/><col style="width: 180px" /><col style="width: 130px" /><col style="width: 130px" /><col
						style="width: 150px"
					/><col style="width: 130px" /><col style="width: 220px" /><col style="width: 170px" /><col
						style="width: 90px"
					/><col style="width: 130px" /><col style="width: 110px" /></colgroup
				>
				<thead
					><tr>
						<th class="row-index" scope="col">#</th>
						<th class="selection-cell" scope="col"
							><input
								type="checkbox"
								aria-label="Select all filtered results"
								checked={result.total > 0 && selectedCount === result.total}
								indeterminate={selectedCount > 0 && selectedCount < result.total}
								disabled={busy || loading}
								onchange={(event) => (event.currentTarget.checked ? selectAll() : clearSelection())}
							/></th
						>
						<th scope="col">Photo</th><th scope="col">Product</th><th scope="col">Code</th><th
							scope="col">Source</th
						><th scope="col">Price</th><th scope="col">Brand</th><th scope="col">Category</th><th
							scope="col">Linked searches</th
						><th scope="col">Last collection</th><th scope="col">Records</th><th scope="col"
							>Collection</th
						><th scope="col">Details</th>
					</tr></thead
				>
				<tbody
					>{#each result.items as row, index (row.public_id)}<tr
							class:row-selected={isSelected(row.public_id)}
						>
							<td class="row-index">{offset + index + 1}</td>
							<td class="selection-cell"
								><input
									type="checkbox"
									aria-label={`Select ${row.title}`}
									checked={isSelected(row.public_id)}
									disabled={busy || loading}
									onchange={(event) => selectRow(row.public_id, event.currentTarget.checked)}
								/></td
							>
							<td
								><div class="thumbnail">
									<ProductImage
										src={row.image_url || row.data?.offer?.image_urls?.[0]}
										title={row.title}
									/>
								</div></td
							>
							<td
								>{#if row.url}<a
										class="cell-text product-title"
										href={row.url}
										title={row.title}
										target="_blank"
										rel="noreferrer">{row.title}</a
									>{:else}<span class="cell-text product-title" title={row.title}>{row.title}</span
									>{/if}
								{#if row.canonical_name}
									<a
										class="cell-text"
										href={`/analytics/prices?canonical_product_id=${row.canonical_product_id}`}
										>{row.canonical_name}</a
									>
								{:else if row.normalization_status === 'uncertain'}
									<small>Incomplete identity</small>
								{/if}</td
							>
							<td><span class="cell-text code" title={row.source_key}>{row.source_key}</span></td>
							<td><span class="cell-text" title={label(row.site)}>{label(row.site)}</span></td>
							<td class="numeric">{price(row.data)}</td>
							<td><span class="cell-text" title={row.brand}>{row.brand || '—'}</span></td>
							<td>
								{#if row.taxonomy?.length}
									{#each row.taxonomy as taxon (taxon.id)}
										<span
											class="cell-text"
											title={taxon.parent_name
												? `${taxon.parent_name} › ${taxon.name}`
												: taxon.name}
											>{taxon.parent_name
												? `${taxon.parent_name} › ${taxon.name}`
												: taxon.name}</span
										>
									{/each}
								{:else}<span class="cell-text" title={row.category}>{row.category || '—'}</span
									>{/if}
							</td>
							<td><span class="cell-text" title={row.terms}>{row.terms || '—'}</span></td>
							<td><span class="cell-text">{date(row.observed_at)}</span></td>
							<td class="numeric">{row.observations}</td>
							<td
								><span class="cell-text"
									>{row.excluded ? 'Interrupted' : row.enabled ? 'Active' : 'Paused'}</span
								></td
							>
							<td><Button variant="ghost" onclick={() => loadHistory(row)}>View data</Button></td>
						</tr>{/each}</tbody
				>
			</table>
		</div>
	{:else}<div class="empty-state">
			<h3>No data found</h3>
			<p>Adjust the filters or wait for product extraction.</p>
		</div>{/if}
	<div class="pagination">
		<span
			>{result.total
				? `${offset + 1}–${Math.min(offset + limit, result.total)} of ${result.total} results`
				: '0 results'}</span
		>
		<div>
			<Button
				variant="secondary"
				disabled={loading || busy || !offset}
				onclick={() => {
					offset -= limit;
					void load();
				}}>Previous</Button
			>
			<Button
				variant="secondary"
				disabled={loading || busy || offset + limit >= result.total}
				onclick={() => {
					offset += limit;
					void load();
				}}>Next</Button
			>
		</div>
	</div>
</section>
{#if historyRow}<section class="panel history" aria-label="Product history">
		<div class="history-heading">
			<div>
				<h2>{historyRow.title}</h2>
				<p>Full history for this page, including collections from other runs.</p>
			</div>
			<Button
				variant="ghost"
				onclick={() => {
					historyVersion++;
					historyRow = undefined;
				}}>Close</Button
			>
		</div>
		{#if historyLoading}<div class="loading-state">Loading history…</div>{:else}<div
				class="table-scroll"
			>
				<table class="history-table">
					<colgroup
						><col style="width: 24%" /><col style="width: 20%" /><col style="width: 28%" /><col
							style="width: 28%"
						/></colgroup
					>
					<thead
						><tr><th>Collection</th><th>Price</th><th>Availability</th><th>Extracted data</th></tr
						></thead
					><tbody
						>{#each history as observation (observation.public_id)}<tr
								><td>{date(observation.created_at)}</td><td>{price(observation.payload)}</td><td
									>{observation.payload.offer?.availability || '—'}</td
								><td
									><Button
										variant="ghost"
										onclick={() =>
											(expanded = expanded === observation.public_id ? '' : observation.public_id)}
										>{expanded === observation.public_id ? 'Collapse' : 'View fields'}</Button
									></td
								></tr
							>{#if expanded === observation.public_id}<tr
									><td colspan="4"
										><table class="fields">
											<thead><tr><th>Field</th><th>Extracted value</th></tr></thead><tbody
												>{#each Object.entries(observation.payload) as [key, field] (key)}<tr
														><td>{key}</td><td><pre>{value(field)}</pre></td></tr
													>{/each}</tbody
											>
										</table></td
									></tr
								>{/if}{/each}</tbody
					>
				</table>
			</div>
			{#if !history.length}<div class="empty-state">No records available.</div>{/if}{/if}
		<div class="pagination">
			<span>{historyRow.observations} records</span>
			<div>
				<Button
					variant="secondary"
					disabled={historyLoading || !historyOffset}
					onclick={() => historyRow && loadHistory(historyRow, historyOffset - limit)}
					>Previous</Button
				><Button
					variant="secondary"
					disabled={historyLoading || history.length < limit}
					onclick={() => historyRow && loadHistory(historyRow, historyOffset + limit)}>Next</Button
				>
			</div>
		</div>
	</section>{/if}
<dialog
	bind:this={dialog}
	oncancel={(event) => {
		if (busy) event.preventDefault();
	}}
>
	<h2>
		{purge ? 'Delete all selected data?' : 'Exclude the selected items from extractions?'}
	</h2>
	<p>
		<strong
			>{selectedCount} selected page(s){allMatching
				? 'across all results matching the applied filters'
				: ''}.</strong
		>
	</p>
	<p>
		{purge
			? 'Removes history, offers, prices, links, and the record exclusive to this page. Products shared with other pages are preserved. This action cannot be undone.'
			: 'Prevents new collections and rediscovery of this product at this source. Previously extracted data remains available.'}
	</p>
	<p>
		This action applies to all searches using the same page. Other pages and sources remain
		available.
	</p>
	<div class="form-actions">
		<Button variant="secondary" disabled={busy} onclick={() => dialog.close()}>Cancel</Button
		><Button variant="danger" {busy} onclick={remove}
			>{purge ? 'Confirm deletion of all data' : 'Confirm exclusion from extractions'}</Button
		>
	</div>
</dialog>

<style>
	.page-header > div {
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.filters {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 12px;
		align-items: end;
		margin-bottom: 24px;
		padding: 16px;
		border: 1px solid var(--border);
		background: var(--surface);
		border-radius: 6px;
	}
	.filters :global(.field),
	.filters :global(input),
	.filters :global(select) {
		min-width: 0;
		max-width: 100%;
	}
	.filters :global(select) {
		text-overflow: ellipsis;
	}
	.filters :global(.field) {
		font-size: 13px;
	}
	.filters :global(input),
	.filters :global(select) {
		height: 38px;
		font-size: 13px;
	}
	.price-filter {
		grid-column: 1 / -1;
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 12px;
		align-items: end;
	}
	.filter-submit {
		grid-column: 1 / -1;
		display: flex;
		justify-content: flex-end;
	}
	.grid-toolbar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 12px;
	}
	.selection-summary {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 12px;
		font-size: 13px;
	}
	.selection-summary span {
		color: var(--muted);
	}
	.bulk-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	.bulk-actions :global(.button),
	.filter-submit :global(.button) {
		min-height: 34px;
		padding: 7px 10px;
		font-size: 12px;
	}
	.selection-hint {
		padding: 0 12px 12px;
		margin: 0;
		font-size: 12px;
		line-height: 1.5;
		color: var(--muted);
	}
	.data-grid {
		border-radius: 6px;
		box-shadow: none;
	}
	.results-scroll {
		max-height: 65vh;
		overflow: auto;
	}
	.table-scroll {
		max-width: 100%;
	}
	table {
		table-layout: fixed;
		white-space: normal;
	}
	.results-table {
		min-width: 1988px;
		font-size: 13px;
	}
	.results-table th {
		position: sticky;
		top: 0;
		z-index: 2;
		background: #f1f4f8;
		padding: 10px;
		font-size: 11px;
		letter-spacing: 0.03em;
		white-space: nowrap;
	}
	.results-table td {
		padding: 6px 10px;
		height: 48px;
		vertical-align: middle;
	}
	.results-table td,
	.results-table th {
		border-right: 1px solid var(--border);
		border-bottom: 1px solid var(--border);
	}
	.results-table tbody tr:nth-child(even) {
		background: #f9fafc;
	}
	.results-table tbody tr:hover {
		background: #f0f5fb;
	}
	.results-table tbody tr.row-selected {
		background: #eaf2fc;
	}
	.results-table .row-index,
	.results-table .selection-cell {
		position: sticky;
		z-index: 1;
		background: #f5f7fa;
		text-align: center;
	}
	.results-table .row-index {
		left: 0;
		color: var(--muted);
		font-variant-numeric: tabular-nums;
	}
	.results-table .selection-cell {
		left: 44px;
	}
	.results-table th.row-index,
	.results-table th.selection-cell {
		z-index: 3;
	}
	.results-table .row-selected .row-index,
	.results-table .row-selected .selection-cell {
		background: #eaf2fc;
	}
	.selection-cell input {
		width: 16px;
		height: 16px;
		margin: 0;
		accent-color: var(--blue-800);
		cursor: pointer;
		vertical-align: middle;
	}
	.cell-text {
		display: block;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.product-title {
		font-weight: 500;
	}
	.code {
		font-family: ui-monospace, monospace;
		font-size: 12px;
	}
	.numeric {
		text-align: right;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.thumbnail {
		width: 34px;
		height: 34px;
	}
	.thumbnail :global(.product-photo) {
		width: 34px;
		height: 34px;
		min-height: 0;
		max-width: 34px;
		object-fit: contain;
		border-radius: 3px;
		margin: 0;
	}
	.thumbnail :global(.photo-placeholder) {
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.thumbnail :global(.photo-placeholder span) {
		display: none;
	}
	.results-table :global(.button) {
		min-height: 28px;
		padding: 4px 8px;
		font-size: 12px;
	}
	.history-table {
		min-width: 640px;
	}
	th,
	td {
		vertical-align: top;
		overflow-wrap: anywhere;
		white-space: normal;
		line-height: 1.5;
		padding: 16px;
	}
	td a {
		display: block;
	}
	.history {
		margin-top: 24px;
	}
	.history-heading {
		display: flex;
		justify-content: space-between;
		gap: 16px;
		padding: 24px;
	}
	.history-heading h2 {
		margin: 0;
		overflow-wrap: anywhere;
		line-height: 1.4;
	}
	.history-heading > div {
		min-width: 0;
	}
	.history-heading p {
		white-space: normal;
		line-height: 1.6;
		margin-top: 8px;
	}
	.history-heading > :global(.button) {
		flex-shrink: 0;
		align-self: start;
	}
	pre {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		margin: 0;
		max-height: 380px;
		overflow: auto;
		font-size: 12px;
	}
	.fields {
		width: 100%;
	}
	.fields th:first-child,
	.fields td:first-child {
		width: 24%;
	}
	.pagination {
		flex-wrap: wrap;
		gap: 16px;
	}
	.pagination > div {
		flex-wrap: wrap;
	}
	dialog {
		position: fixed;
		inset: 0;
		margin: auto;
		width: min(600px, calc(100vw - 32px));
		max-height: calc(100dvh - 32px);
		overflow-y: auto;
		overflow-wrap: anywhere;
		border: 1px solid var(--border);
		border-radius: 16px;
		background: var(--surface, white);
		color: inherit;
		padding: 28px;
	}
	dialog h2 {
		line-height: 1.4;
	}
	dialog p {
		line-height: 1.6;
		margin-top: 16px;
	}
	dialog .form-actions {
		flex-wrap: wrap;
		gap: 12px;
	}
	dialog :global(.button) {
		white-space: normal;
		max-width: 100%;
	}
	dialog::backdrop {
		background: rgb(0 0 0 / 45%);
	}
	@media (max-width: 1200px) {
		.filters {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}
	@media (max-width: 650px) {
		.filters {
			grid-template-columns: minmax(0, 1fr);
		}
		.price-filter {
			grid-template-columns: minmax(0, 1fr);
		}
		.bulk-actions {
			width: 100%;
		}
		.history-heading {
			padding: 16px;
			flex-wrap: wrap;
		}
		dialog {
			padding: 20px;
		}
	}
</style>

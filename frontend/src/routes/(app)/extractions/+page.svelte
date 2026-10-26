<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import {
		request,
		type Qualification,
		type Term,
		type Source,
		type Extraction,
		type ExtractionGroupPage
	} from '#lib/api.ts';
	import Button from '#lib/components/Button.svelte';
	import SourceSwitch from '#lib/components/SourceSwitch.svelte';
	import Input from '#lib/components/Input.svelte';
	import Select from '#lib/components/Select.svelte';
	import Notice from '#lib/components/Notice.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import ExtractionGroups from '#lib/components/ExtractionGroups.svelte';
	import ExtractionDetails from '#lib/components/ExtractionDetails.svelte';
	let result = $state<ExtractionGroupPage>();
	let sources = $state<Source[]>([]);
	let selectedSources = $state<string[]>([]);
	async function loadSources() {
		try {
			sources = await request<Source[]>('/sources');
			selectedSources = sources.map((source) => source.id);
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Unable to load sources.';
		}
	}
	let loading = $state(true);
	let busy = $state(false);
	let message = $state('');
	let success = $state('');
	let status = $state('');
	let offset = $state(0);
	const limit = 20;
	let version = 0;
	let polling = false;
	let showForm = $state(false);
	let term = $state('');
	let description = $state('');
	let referencePrice = $state<number | undefined>();
	let qualifications = $state<Qualification[]>([]);
	let maxPages = $state<number | undefined>(1);
	let maxCandidates = $state<number | undefined>(100);
	let selected = $state<Extraction>();
	let detailBusy = $state(false);
	let detailError = $state('');
	let detailVersion = 0;
	function closeDetails() {
		selected = undefined;
		qualifications = [];
		detailBusy = false;
		detailError = '';
		detailVersion++;
	}
	async function load(quiet = false) {
		const current = ++version;
		if (!quiet) {
			loading = true;
			message = '';
		}
		try {
			const value = await request<ExtractionGroupPage>(
				`/extraction-groups?limit=${limit}&offset=${offset}${status ? '&status=' + status : ''}`
			);
			if (current === version) {
				result = value;
				if (selected) {
					const selectedId = selected.public_id;
					const selectionVersion = detailVersion;
					const [execution, assessments] = await Promise.all([
						request<Extraction>(`/scrape-requests/${selectedId}`),
						request<Qualification[]>(`/scrape-requests/${selectedId}/qualifications`)
					]);
					if (
						current === version &&
						selectionVersion === detailVersion &&
						selected?.public_id === selectedId
					) {
						selected = { ...selected, ...execution };
						qualifications = assessments;
					}
				}
			}
		} catch (cause) {
			if (current === version)
				message = cause instanceof Error ? cause.message : 'Unable to load extractions.';
		} finally {
			if (current === version) loading = false;
		}
	}

	onMount(() => {
		showForm = page.url.searchParams.has('new');
		void load();
		void loadSources();

		const timer = setInterval(() => {
			if (!document.hidden && !busy && !loading && !polling) {
				polling = true;
				void load(true).finally(() => {
					polling = false;
				});
			}
		}, 3000);
		return () => {
			clearInterval(timer);
			version++;
		};
	});
	async function create(event: SubmitEvent) {
		event.preventDefault();
		if (!selectedSources.length || !term.trim()) return;
		busy = true;
		message = '';
		success = '';
		try {
			const created = await request<Term>('/search-terms', {
				method: 'POST',
				body: JSON.stringify({
					site: selectedSources[0],
					term: term.trim(),
					description: description.trim(),
					reference_price: referencePrice || null,
					max_pages: Number(maxPages),
					max_candidates: Number(maxCandidates)
				})
			});
			const id = created.public_id;
			const queued = await request<{ requests: { public_id: string; site: string }[] }>(
				`/search-terms/${id}/discover-sources`,
				{
					method: 'POST',
					body: JSON.stringify({ sites: selectedSources })
				}
			);
			showForm = false;
			term = description = '';
			referencePrice = undefined;
			offset = 0;
			status = '';
			success = `${queued.requests.length} ${queued.requests.length === 1 ? 'extraction added' : 'extractions added'} to the queue. Track the results by source.`;
			await load();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Unable to start the extraction.';
		} finally {
			busy = false;
		}
	}
	async function detail(item: Extraction) {
		const current = ++detailVersion;
		detailBusy = true;
		detailError = '';
		selected = item;
		qualifications = [];
		try {
			const [value, assessments] = await Promise.all([
				request<Extraction>(`/scrape-requests/${item.public_id}`),
				request<Qualification[]>(`/scrape-requests/${item.public_id}/qualifications`)
			]);
			if (current === detailVersion && selected?.public_id === item.public_id) {
				selected = { ...item, ...value };
				qualifications = assessments;
			}
		} catch (cause) {
			if (current === detailVersion)
				detailError = cause instanceof Error ? cause.message : 'Unable to load details.';
		} finally {
			if (current === detailVersion) detailBusy = false;
		}
	}
	async function rerun(item: Extraction) {
		busy = true;
		message = '';
		success = '';
		try {
			const path =
				item.mode === 'discover' && item.search_term_id
					? `/search-terms/${item.search_term_id}/discover`
					: item.entity_id
						? `/products/${item.entity_id}/refresh`
						: '';
			if (!path) throw new Error('This extraction has no available source to run again.');
			await request(path, { method: 'POST' });
			success = 'New run added to the queue.';
			offset = 0;
			await load(true);
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Unable to run again.';
		} finally {
			busy = false;
		}
	}
</script>

<svelte:head><title>Extractions · Panoptes</title></svelte:head>
<div class="page-header">
	<div>
		<span class="eyebrow">FROM SOURCE TO INSIGHT</span>
		<h1>Extractions</h1>
		<p>Discover products and track each run.</p>
	</div>
	<div class="header-actions">
		<Button
			onclick={() => {
				showForm = true;
				success = '';
			}}><Icon name="plus" size={17} /> New extraction</Button
		>
	</div>
</div>
<Notice {message} retry={() => load()} /><Notice message={success} success />
{#if showForm}<section class="panel form-panel">
		<h2>New extraction</h2>
		<p>Add a new search to extract products.</p>
		<form class="extraction-form" onsubmit={create}>
			<div class="form-grid">
				<Input
					id="search-term"
					label="Search term"
					bind:value={term}
					required
					maxlength={200}
					placeholder="e.g. 50-liter refrigerator or NVMe SSD"
				/>
				<Input
					id="product-description"
					label="Description (optional)"
					bind:value={description}
					maxlength={1000}
					placeholder="e.g. standalone 3D-series processor"
					hint="The product will be compared with the search and this description using information from the page."
				/>
				<Input
					id="reference-price"
					label="Reference price (R$) (optional)"
					type="number"
					min={0.01}
					step="0.01"
					bind:value={referencePrice}
					hint="Your expected average value. Used for comparison without excluding higher-priced offers."
				/>
				<Input
					id="max-pages"
					label="Maximum pages"
					type="number"
					min={1}
					max={20}
					required
					bind:value={maxPages}
				/><Input
					id="max-candidates"
					label="Maximum candidates"
					type="number"
					min={1}
					max={1000}
					required
					bind:value={maxCandidates}
				/>
			</div>
			<fieldset class="sources-fieldset">
				<legend>Extraction sources</legend>
				<div class="source-switches">
					{#each sources as source (source.id)}
						<SourceSwitch
							id={`source-${source.id}`}
							label={source.name}
							checked={selectedSources.includes(source.id)}
							disabled={busy}
							onchange={(checked) => {
								selectedSources = checked
									? [...selectedSources, source.id]
									: selectedSources.filter((id) => id !== source.id);
							}}
						/>
					{/each}
				</div>
				{#if !selectedSources.length}<small>Select at least one source.</small>{/if}
			</fieldset>
			<p class="mapping-note">
				This extraction performs the initial discovery. To repeat or update products, create a
				schedule in <a href="/routines">Routines</a>.
			</p>
			<div class="form-actions">
				<Button variant="secondary" type="button" onclick={() => (showForm = false)} disabled={busy}
					>Cancel</Button
				><Button type="submit" {busy} disabled={busy || !selectedSources.length || !term.trim()}
					>Start extraction <Icon name="arrow" size={16} /></Button
				>
			</div>
		</form>
	</section>{/if}
<div class="toolbar">
	<p>Refreshed automatically every 3 seconds</p>
	<div class="toolbar-controls">
		<Select
			id="status-filter"
			label="Filter by status"
			bind:value={status}
			onchange={() => {
				offset = 0;
				void load();
			}}
			options={[
				{ value: '', label: 'All statuses' },
				{ value: 'pending', label: 'Queued' },
				{ value: 'running', label: 'Running' },
				{ value: 'completed', label: 'Completed' },
				{ value: 'partial', label: 'Partial' },
				{ value: 'failed', label: 'Failures' },
				{ value: 'blocked', label: 'Blocked' }
			]}
		/><Button variant="secondary" onclick={() => load()} disabled={loading}>Refresh</Button>
	</div>
</div>
<section class="panel">
	{#if loading}<div class="loading-state">
			<span class="spinner"></span>Loading extractions…
		</div>{:else if result}<ExtractionGroups
			items={result.items}
			select={detail}
			{rerun}
			{busy}
			{sources}
		/>
		<div class="pagination">
			<span
				>{result.total
					? `${offset + 1}–${Math.min(offset + limit, result.total)} of ${result.total} terms`
					: '0 terms'}</span
			>
			<div>
				<Button
					variant="secondary"
					disabled={!offset || loading}
					onclick={() => {
						offset -= limit;
						void load();
					}}>Previous</Button
				><Button
					variant="secondary"
					disabled={offset + limit >= result.total || loading}
					onclick={() => {
						offset += limit;
						void load();
					}}>Next</Button
				>
			</div>
		</div>{/if}
</section>
<ExtractionDetails
	item={selected}
	{qualifications}
	{sources}
	busy={detailBusy}
	error={detailError}
	close={closeDetails}
	retry={() => selected && detail(selected)}
/>

<style>
	.extraction-form {
		display: grid;
		gap: 24px;
	}
	.extraction-form .form-actions {
		margin-top: 0;
	}
	.sources-fieldset {
		border: 0;
		padding: 0;
		margin: 0;
		min-width: 0;
	}
	.sources-fieldset legend {
		font-weight: 600;
		margin-bottom: 12px;
	}
	.source-switches {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
		gap: 12px;
	}
	.mapping-note {
		margin: 0;
		font-size: 0.9rem;
	}
</style>

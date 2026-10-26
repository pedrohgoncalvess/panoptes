<script lang="ts">
	import { date, type Extraction, type Qualification, type Source } from '#lib/api.ts';
	import { explainFailure } from '#lib/log-presentation.ts';
	import Button from './Button.svelte';
	import Icon from './Icon.svelte';
	import Status from './Status.svelte';
	let {
		item,
		qualifications,
		sources,
		busy,
		error,
		close,
		retry
	}: {
		item?: Extraction;
		qualifications: Qualification[];
		sources: Source[];
		busy: boolean;
		error: string;
		close: () => void;
		retry: () => void;
	} = $props();
	let dialog = $state<HTMLDialogElement>();
	const criteria = $derived(item?.criteria);
	const products = $derived(
		Array.isArray(item?.summary?.products)
			? (item.summary.products as { status?: string; source_key?: string; reason?: string }[])
			: []
	);
	const counts = $derived([
		['Confirmed', products.filter((p) => p.status === 'completed').length],
		['Does not meet criteria', products.filter((p) => p.status === 'rejected').length],
		['Unconfirmed', products.filter((p) => p.status === 'uncertain').length],
		[
			'Failures or blocks',
			products.filter((p) => ['failed', 'blocked'].includes(p.status || '')).length
		]
	]);
	const operators: Record<string, string> = {
		eq: 'Equal to',
		gte: 'At least',
		lte: 'At most',
		contains: 'Contains'
	};
	const modes: Record<string, string> = {
		profile: 'Product profile',
		exact_product: 'Exact product',
		category: 'Category'
	};
	const categories: Record<string, string> = {
		book: 'Books',
		electronics: 'Electronics',
		appliances: 'Home appliances',
		hardware: 'Hardware',
		school_supplies: 'School supplies',
		other: 'Other',
		television: 'Televisions',
		refrigerator: 'Refrigerators'
	};
	const checkStatuses: Record<string, string> = {
		matched: 'Confirmed',
		mismatch: 'Does not match',
		missing: 'Unconfirmed',
		info: 'Reference'
	};
	function money(value: string | undefined, currency = 'BRL') {
		return value != null && Number.isFinite(Number(value))
			? new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(Number(value))
			: 'Not specified';
	}
	$effect(() => {
		if (item && dialog && !dialog.open) dialog.showModal();
		if (!item && dialog?.open) dialog.close();
	});
	$effect(() => {
		if (!item) return;
		const previous = document.body.style.overflow;
		document.body.style.overflow = 'hidden';
		return () => {
			document.body.style.overflow = previous;
		};
	});
	function backdrop(event: PointerEvent) {
		if (event.target !== dialog || !dialog) return;
		const box = dialog.getBoundingClientRect();
		if (
			event.clientX < box.left ||
			event.clientX > box.right ||
			event.clientY < box.top ||
			event.clientY > box.bottom
		)
			close();
	}
</script>

<dialog
	bind:this={dialog}
	class="extraction-dialog"
	aria-labelledby="extraction-detail-title"
	onclose={close}
	onpointerdown={backdrop}
>
	<header class="dialog-heading">
		<div>
			<span class="eyebrow">CONFIGURATION AND RESULTS</span>
			<h2 id="extraction-detail-title">Extraction details</h2>
		</div>
		<Button variant="ghost" onclick={close} aria-label="Close details"
			><Icon name="close" size={20} /></Button
		>
	</header>
	{#if item}<div class="dialog-body" aria-busy={busy}>
			<div class="execution-heading">
				<h3>{item.term || item.source_key || 'Product update'}</h3>
				<Status status={item.status} />
			</div>
			{#if busy}<div class="loading-state" role="status">
					<span class="spinner"></span>Loading details…
				</div>{/if}
			{#if error}<div class="detail-error" role="alert">
					<p>{error}</p>
					<Button variant="secondary" onclick={retry}>Try again</Button>
				</div>{/if}
			<section aria-labelledby="execution-info">
				<h3 id="execution-info">Run</h3>
				<dl class="detail-grid">
					<div>
						<dt>Source</dt>
						<dd>
							{sources.find((s) => s.id === item?.site)?.name || item.site || 'Not specified'}
						</dd>
					</div>
					<div>
						<dt>Type</dt>
						<dd>
							{item.mode === 'discover' ? 'Product discovery' : 'Product update'}
						</dd>
					</div>
					<div>
						<dt>Started at</dt>
						<dd>{date(item.created_at)}</dd>
					</div>
					<div>
						<dt>Completed at</dt>
						<dd>{date(item.completed_at)}</dd>
					</div>
				</dl>
			</section>
			{#if criteria}<section aria-labelledby="search-criteria">
					<h3 id="search-criteria">Search criteria</h3>
					<dl class="detail-grid">
						<div>
							<dt>Search term</dt>
							<dd>{item.term || 'Direct product update'}</dd>
						</div>
						{#if criteria.match_mode === 'intent'}
							<div>
								<dt>Description</dt>
								<dd>{criteria.description || 'No additional restrictions'}</dd>
							</div>
						{:else}
							<div>
								<dt>Category</dt>
								<dd>
									{criteria.category_name ||
										categories[criteria.category || ''] ||
										criteria.category ||
										'Not specified'}
								</dd>
							</div>
							<div>
								<dt>Expected product or model</dt>
								<dd>{criteria.title || 'No title filter'}</dd>
							</div>{/if}
						<div>
							<dt>Selection mode</dt>
							<dd>
								{criteria.match_mode === 'intent'
									? 'Classification from the product page'
									: modes[criteria.match_mode || 'exact_product'] || 'Not specified'}
							</dd>
						</div>
						<div>
							<dt>Reference price</dt>
							<dd class="reference-price">
								{money(criteria.reference_price, criteria.currency)}<small
									>Expected value for comparison; does not limit offers.</small
								>
							</dd>
						</div>
						{#if criteria.match_mode !== 'intent'}
							<div>
								<dt>Brands</dt>
								<dd>{criteria.brands?.join(', ') || 'No brand filter'}</dd>
							</div>
							<div>
								<dt>Authors</dt>
								<dd>{criteria.authors?.join(', ') || 'No author filter'}</dd>
							</div>
							<div>
								<dt>ISBN</dt>
								<dd>{criteria.isbn?.join(', ') || 'No edition restriction'}</dd>
							</div>
							<div>
								<dt>Category recognition terms</dt>
								<dd>{criteria.category_keywords?.join(', ') || 'Not specified'}</dd>
							</div>
							<div>
								<dt>Terms excluded from the title</dt>
								<dd>{criteria.excluded_title_terms?.join(', ') || 'None'}</dd>
							</div>
							<div>
								<dt>Exclude accessories</dt>
								<dd>{criteria.exclude_accessories === false ? 'No' : 'Yes'}</dd>
							</div>
						{/if}
					</dl>
					{#if criteria.characteristics?.length || Object.keys(criteria.required_attributes || {}).length}<h4
						>
							Required attributes
						</h4>
						<ul class="requirements">
							{#each criteria.characteristics || [] as c, index (index)}<li>
									<strong>{c.name}</strong><span>{operators[c.operator]} {c.value} {c.unit}</span>
								</li>{/each}
							{#each Object.entries(criteria.required_attributes || {}) as [name, value] (name)}<li>
									<strong>{name}</strong><span>{value ?? 'Not specified'}</span>
								</li>{/each}
						</ul>{/if}
					{#if criteria.notes}<h4>Notes</h4>
						<p class="notes">{criteria.notes}</p>{/if}
				</section>{:else if !busy && !error}<p>The criteria for this run are unavailable.</p>{/if}
			{#if !busy}<section aria-labelledby="execution-limits">
					<h3 id="execution-limits">Limits and monitoring</h3>
					<dl class="detail-grid">
						<div>
							<dt>Maximum pages</dt>
							<dd>{item.max_pages_qt ?? 'Not applicable / not specified'}</dd>
						</div>
						<div>
							<dt>Maximum candidates</dt>
							<dd>{item.max_candidates_qt ?? 'Not applicable / not specified'}</dd>
						</div>
						<div>
							<dt>Updates for confirmed products</dt>
							<dd>Based on schedules in Routines</dd>
						</div>
					</dl>
				</section>{/if}
			<section aria-labelledby="execution-result">
				<h3 id="execution-result">Run results</h3>
				{#if products.length}<dl class="result-counts">
						{#each counts as [label, count] (label)}<div>
								<dt>{label}</dt>
								<dd>{count}</dd>
							</div>{/each}
					</dl>
				{:else}<p>
						{['pending', 'running'].includes(item.status)
							? 'Results will be available after processing.'
							: 'No products recorded in the summary.'}
					</p>{/if}
				{#if item.summary?.truncated}<p class="result-note">
						The search reached its configured limit; some candidates may not have been analyzed.
					</p>{/if}
				{#if explainFailure(item.summary || {})}<p class="result-note">
						{explainFailure(item.summary || {})}
					</p>{/if}
				{#each qualifications as qualification (qualification.source_key + ':' + qualification.stage)}<details
						class="qualification"
					>
						<summary
							><span>{qualification.assessment.candidate.title}</span><span class="decision"
								>{qualification.assessment.decision === 'accepted'
									? qualification.stage === 'search' ||
										qualification.assessment.reason === 'profile_candidate'
										? 'Awaiting collection'
										: 'Confirmed'
									: qualification.assessment.decision === 'uncertain'
										? 'Unconfirmed'
										: 'Does not meet criteria'}</span
							></summary
						>
						<a
							href={qualification.assessment.candidate.url}
							target="_blank"
							rel="noopener noreferrer">View product ↗</a
						>
						{#if !qualification.assessment.checks?.length}<p>
								{explainFailure({ reason: qualification.assessment.reason }) ||
									'Evaluated against the search criteria.'}
							</p>{/if}
						{#each qualification.assessment.checks || [] as check, index (index)}<div class="check">
								<strong>{check.name} · {checkStatuses[check.status] || check.status}</strong>
								<p>Expected: {check.expected}</p>
								<p>Found: {check.actual || 'Not specified'}</p>
								{#if check.evidence}<small>{check.evidence}</small>{/if}
							</div>{/each}
					</details>{/each}
			</section>
			<details class="identifiers">
				<summary>Run identifiers</summary>
				<dl class="detail-grid">
					<div>
						<dt>Extraction</dt>
						<dd>{item.public_id}</dd>
					</div>
					{#if item.source_key}<div>
							<dt>Product at source</dt>
							<dd>{item.source_key}</dd>
						</div>{/if}{#if item.search_term_id}<div>
							<dt>Search</dt>
							<dd>{item.search_term_id}</dd>
						</div>{/if}
				</dl>
			</details>
		</div>
		<footer>
			<a class="button button--ghost" href={'/extraction/logs?request_id=' + item.public_id}
				>View logs for this run <Icon name="chevron" size={14} /></a
			><Button variant="secondary" onclick={close}>Close</Button>
		</footer>{/if}
</dialog>

<style>
	.extraction-dialog {
		margin: auto;
		width: min(880px, calc(100vw - 32px));
		max-height: calc(100dvh - 40px);
		padding: 0;
		border: 1px solid var(--border);
		border-radius: 14px;
		color: var(--ink);
		background: var(--surface, white);
		box-shadow: 0 24px 80px #14233b40;
		overflow: auto;
	}
	.extraction-dialog::backdrop {
		background: #15233b99;
		backdrop-filter: blur(3px);
	}
	.dialog-heading {
		position: sticky;
		top: 0;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		padding: 22px 28px;
		background: var(--surface, white);
		border-bottom: 1px solid var(--border);
		z-index: 1;
	}
	h2 {
		margin: 4px 0 0;
		font-size: 24px;
	}
	.dialog-body {
		padding: 24px 28px;
	}
	.execution-heading {
		display: flex;
		justify-content: space-between;
		align-items: start;
		gap: 16px;
	}
	.execution-heading h3 {
		margin: 0;
		font-size: 21px;
		overflow-wrap: anywhere;
	}
	section {
		padding: 22px 0;
		border-bottom: 1px solid var(--border);
	}
	section h3 {
		margin: 0 0 18px;
		font-size: 17px;
	}
	h4 {
		margin: 20px 0 10px;
	}
	.detail-grid {
		margin: 0;
	}
	.reference-price {
		font-weight: 600;
	}
	.reference-price small {
		display: block;
		margin-top: 6px;
		font-weight: 400;
	}
	small,
	.result-note {
		color: var(--muted);
		font-size: 13px;
	}
	.requirements {
		padding: 0;
		list-style: none;
	}
	.requirements li {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		gap: 8px;
		padding: 10px 0;
		border-bottom: 1px solid var(--border);
	}
	.notes {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.result-counts {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 10px;
	}
	.result-counts div {
		background: var(--canvas);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 12px;
	}
	.result-counts dt {
		font-size: 12px;
		color: var(--muted);
	}
	.result-counts dd {
		margin: 8px 0 0;
		font-size: 24px;
		font-weight: 600;
	}
	.qualification {
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 14px;
		margin-top: 12px;
	}
	.qualification summary {
		display: flex;
		justify-content: space-between;
		gap: 12px;
		cursor: pointer;
		overflow-wrap: anywhere;
	}
	.qualification[open] summary {
		margin-bottom: 14px;
	}
	.decision {
		flex-shrink: 0;
		font-size: 12px;
		color: var(--muted);
	}
	.check {
		padding-top: 12px;
	}
	.check p {
		margin: 4px 0;
		overflow-wrap: anywhere;
	}
	.identifiers {
		margin-top: 22px;
	}
	.identifiers summary {
		cursor: pointer;
		color: var(--muted);
	}
	.identifiers dl {
		margin-top: 16px;
	}
	.detail-error {
		margin: 16px 0;
	}
	footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		padding: 18px 28px;
		border-top: 1px solid var(--border);
	}
	@media (max-width: 600px) {
		.extraction-dialog {
			width: calc(100vw - 16px);
			max-height: calc(100dvh - 16px);
		}
		.dialog-heading,
		.dialog-body,
		footer {
			padding: 18px;
		}
		.detail-grid,
		.result-counts {
			grid-template-columns: 1fr 1fr;
		}
		.qualification summary {
			flex-direction: column;
		}
		.execution-heading {
			flex-wrap: wrap;
		}
	}
	@media (max-width: 380px) {
		.detail-grid {
			grid-template-columns: 1fr;
		}
	}
</style>

<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { SvelteURLSearchParams } from 'svelte/reactivity';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { request, date, type Term, type Source } from '#lib/api.ts';
	import {
		calendar,
		dateRange,
		filterQuery,
		money,
		paymentName,
		siteName,
		type CapturePage,
		type PriceDashboard,
		type PriceFilters,
		type ProductOption
	} from '#lib/price-analytics.ts';
	import Button from './Button.svelte';
	import Select from './Select.svelte';
	import Input from './Input.svelte';
	import Notice from './Notice.svelte';
	import ProductDetails from './ProductDetails.svelte';
	import CommerceAnalytics from './CommerceAnalytics.svelte';
	import ComparisonChart from './ComparisonChart.svelte';
	let { detail = false, extractions = false }: { detail?: boolean; extractions?: boolean } =
		$props();
	let filters = $state<PriceFilters>(dateRange());
	let applied = $state<PriceFilters>(dateRange());
	let terms = $state<Term[]>([]);
	let sources = $state<Source[]>([]);
	let products = $state<ProductOption[]>([]);
	let canonicalProducts = $state<{ public_id: string; name: string }[]>([]);
	let dashboard = $state<PriceDashboard>();
	let captures = $state<CapturePage>();
	let loading = $state(true);
	let optionsLoading = $state(false);
	let productSearch = $state('');
	const uniqueTerms = $derived([
		...new Map(terms.map((term) => [term.term.trim().toLowerCase(), term])).values()
	]);
	let searchTimer: ReturnType<typeof setTimeout>;
	let optionsController: AbortController | undefined;
	let message = $state('');
	let offset = $state(0);
	let currency = $state('BRL');
	let metric = $state<'average' | 'minimum' | 'maximum'>('average');
	let version = 0,
		optionVersion = 0;
	const limit = 25;
	const query = $derived(filterQuery(applied));
	const stats = $derived(dashboard?.currencies.find((c) => c.currency === currency));
	const days = $derived(calendar(applied.start, applied.end));
	const labels = $derived(days.map((d) => d.slice(8, 10) + '/' + d.slice(5, 7)));
	const sites = $derived([
		...new Set(dashboard?.daily.filter((p) => p.currency === currency).map((p) => p.site) || [])
	]);
	const priceSeries = $derived(
		sites.map((site) => ({
			label: siteName(site),
			values: days.map(
				(day) =>
					dashboard?.daily.find(
						(p) => p.site === site && p.currency === currency && p.date === day
					)?.[metric] ?? null
			)
		}))
	);
	const executionSeries = $derived(
		['completed', 'partial', 'failed', 'in_progress'].map((key, i) => ({
			label: ['Completed', 'Partial', 'Failures / blocks', 'In progress'][i],
			values: days.map(
				(day) => dashboard?.executions.find((p) => p.date === day)?.[key as 'completed'] ?? 0
			)
		}))
	);
	const siteRows = $derived(dashboard?.sites.filter((p) => p.currency === currency) || []);
	const payments = $derived(dashboard?.payments.filter((p) => p.currency === currency) || []);
	const paymentLabel = (p: {
		method: string;
		installments: number | null;
		interest_free: boolean | null;
	}) =>
		p.method === 'installment'
			? `${p.installments || '?'}× · ${p.interest_free === true ? 'interest-free' : p.interest_free === false ? 'with interest' : 'interest not specified'}`
			: paymentName(p.method);
	const paymentGroups = $derived([...new Set(payments.map(paymentLabel))]);
	const paymentSites = $derived([...new Set(payments.map((p) => p.site))]);
	const paymentSeries = $derived(
		paymentSites.map((site) => ({
			label: siteName(site),
			values: paymentGroups.map((label) =>
				payments
					.filter((p) => p.site === site && paymentLabel(p) === label)
					.reduce((sum, p) => sum + p.offers, 0)
			)
		}))
	);
	const criteria = $derived(terms.find((t) => t.public_id === applied.term_id)?.criteria);
	async function loadOptions() {
		const current = ++optionVersion;
		optionsController?.abort();
		optionsController = new AbortController();
		optionsLoading = true;
		try {
			const params = new SvelteURLSearchParams();
			if (filters.term_id) params.set('term_id', filters.term_id);
			if (filters.site) params.set('site', filters.site);
			if (productSearch.trim()) params.set('q', productSearch.trim());
			if (filters.product_id) params.set('selected', filters.product_id);
			const result = await request<ProductOption[]>(`/analytics/prices/products?${params}`, {
				signal: optionsController.signal
			});
			if (current === optionVersion) {
				products = result;
				if (filters.product_id && !result.some((p) => p.public_id === filters.product_id))
					filters.product_id = '';
			}
		} catch (cause) {
			if (current !== optionVersion || (cause instanceof Error && cause.name === 'AbortError'))
				return;
			throw cause;
		} finally {
			if (current === optionVersion) optionsLoading = false;
		}
	}
	async function searchProducts() {
		await tick();
		filters.q = productSearch.trim();
		filters.product_id = '';
		version++;
		clearTimeout(searchTimer);
		optionsLoading = true;
		optionVersion++;
		optionsController?.abort();
		searchTimer = setTimeout(() => {
			void apply();
			void loadOptions().catch((cause) => {
				if (cause instanceof Error && cause.name !== 'AbortError') message = cause.message;
			});
		}, 300);
	}
	async function changeScope() {
		await tick();
		clearTimeout(searchTimer);
		filters.product_id = '';
		void apply();
		try {
			await loadOptions();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Unable to load products.';
		}
	}
	async function load() {
		const current = ++version;
		loading = true;
		message = '';
		dashboard = undefined;
		captures = undefined;
		try {
			if (detail) {
				const result = await request<CapturePage>(
					`/analytics/detail?${query}&latest=true&limit=${limit}&offset=${offset}`
				);
				if (current === version) captures = result;
			} else {
				const result = await request<PriceDashboard>(`/analytics/prices/dashboard?${query}`);
				if (current === version) {
					dashboard = result;
					if (!result.currencies.some((c) => c.currency === currency))
						currency = result.currencies[0]?.currency || 'BRL';
				}
			}
		} catch (cause) {
			if (current === version)
				message = cause instanceof Error ? cause.message : 'Unable to load data.';
		} finally {
			if (current === version) loading = false;
		}
	}
	async function apply() {
		await tick();
		clearTimeout(searchTimer);
		if (
			!filters.start ||
			!filters.end ||
			filters.start > filters.end ||
			(new Date(filters.end).getTime() - new Date(filters.start).getTime()) / 86400000 > 365
		) {
			message = 'Enter a valid date range of up to 366 days.';
			return;
		}
		applied = { ...filters };
		offset = 0;
		const current = ++version;
		await goto(`${page.url.pathname}?${filterQuery(applied)}`, {
			replace: true,
			reset: false
		});
		if (current === version) await load();
	}
	async function preset(days: number) {
		const range = dateRange(days);
		filters = { ...filters, start: range.start, end: range.end };
		await apply();
	}
	onMount(() => {
		let active = true;
		for (const key of Object.keys(filters) as (keyof PriceFilters)[])
			filters[key] = page.url.searchParams.get(key) || filters[key];
		applied = { ...filters };
		productSearch = filters.q;
		void (async () => {
			try {
				const all: Term[] = [];
				let batch: Term[];
				do {
					batch = await request<Term[]>(`/search-terms?limit=100&offset=${all.length}`);
					all.push(...batch);
				} while (batch.length === 100 && active);
				if (!active) return;
				terms = all;
				const selected = terms.find((term) => term.public_id === filters.term_id);
				if (selected)
					filters.term_id =
						uniqueTerms.find(
							(term) => term.term.trim().toLowerCase() === selected.term.trim().toLowerCase()
						)?.public_id || '';
				applied = { ...filters };
				sources = await request<Source[]>('/sources');
				let canonicalBatch: { public_id: string; name: string }[];
				do {
					canonicalBatch = await request<{ public_id: string; name: string }[]>(
						`/catalog/canonical-products?limit=100&offset=${canonicalProducts.length}`
					);
					canonicalProducts = [...canonicalProducts, ...canonicalBatch];
				} while (canonicalBatch.length === 100 && active);
				if (!active) return;
				await loadOptions();
				if (active) await load();
			} catch (cause) {
				if (active) {
					message = cause instanceof Error ? cause.message : 'Unable to load filters.';
					loading = false;
				}
			}
		})();
		return () => {
			clearTimeout(searchTimer);
			optionsController?.abort();
			active = false;
			version++;
			optionVersion++;
		};
	});
</script>

<svelte:head
	><title
		>{detail ? 'Product details' : extractions ? 'Extractions' : 'Prices'} · Analytics · Panoptes</title
	></svelte:head
>
<div class="page-header">
	<div>
		<span class="eyebrow">{extractions ? 'DATA IN PERSPECTIVE' : 'THE MARKET IN PERSPECTIVE'}</span>
		<h1>
			{detail ? 'Product details' : extractions ? 'Extraction analytics' : 'Price analytics'}
		</h1>
	</div>
	<Button variant="secondary" onclick={load} disabled={loading}>Refresh</Button>
</div>
<form
	class="panel filter-panel"
	onsubmit={(event) => {
		event.preventDefault();
		void apply();
	}}
>
	<div class="filter-heading">
		<div>
			<h2>Explore your data</h2>
			<p>
				Date range {extractions ? 'by run start date' : 'by collection date'} · Brasília time
			</p>
		</div>
		<div class="presets">
			{#each [7, 30, 90] as n (n)}<button type="button" onclick={() => preset(n)} disabled={loading}
					>{n} days</button
				>{/each}
		</div>
	</div>
	<div class="filters">
		<Select
			id="analytics-canonical-product"
			label="Normalized product"
			bind:value={filters.canonical_product_id}
			onchange={changeScope}
			options={[
				{ value: '', label: 'All products' },
				...canonicalProducts.map((product) => ({ value: product.public_id, label: product.name }))
			]}
		/>
		<Input
			id="analytics-start"
			label="From"
			type="date"
			bind:value={filters.start}
			onchange={apply}
			required
		/>
		<Input
			id="analytics-end"
			label="To"
			type="date"
			bind:value={filters.end}
			onchange={apply}
			min={filters.start}
			required
		/>
		<Select
			id="analytics-term"
			label="Search term"
			bind:value={filters.term_id}
			onchange={changeScope}
			options={[
				{ value: '', label: 'All terms' },
				...uniqueTerms.map((t) => ({
					value: t.public_id,
					label: t.term
				}))
			]}
		/>
		<Select
			id="analytics-site"
			label="Extraction site"
			bind:value={filters.site}
			onchange={changeScope}
			options={[
				{ value: '', label: 'All sites' },
				...sources.map((s) => ({ value: s.id, label: s.name }))
			]}
		/>
		<div class="product-filter">
			<Input
				id="analytics-product-search"
				label="Search products"
				bind:value={productSearch}
				oninput={searchProducts}
				placeholder="Product name, category, or description"
				maxlength={300}
			/>
			<Select
				id="analytics-product"
				label="Product"
				bind:value={filters.product_id}
				onchange={apply}
				disabled={optionsLoading}
				options={[
					{ value: '', label: optionsLoading ? 'Loading products…' : 'All products' },
					...products.map((p) => ({
						value: p.public_id,
						label: `${p.title} · ${siteName(p.site)}`
					}))
				]}
			/>
			<span class="search-status" aria-live="polite">
				{optionsLoading
					? 'Searching products…'
					: productSearch.trim()
						? `${products.length} products sorted by relevance`
						: 'Search by name or describe the product you are looking for.'}
			</span>
		</div>
	</div>
	<div class="filter-actions">
		{#if detail}<span
				>View offers from the latest collection for each product in the selected period.</span
			>{/if}
		<Button
			variant="secondary"
			type="button"
			disabled={loading}
			onclick={async () => {
				productSearch = '';
				filters = dateRange();
				await changeScope();
			}}>Clear filters</Button
		>
	</div>
</form>
<Notice {message} retry={load} />
{#if criteria}<div class="panel criteria">
		<strong>Term criteria</strong>
		<p>
			{criteria.query || criteria.category_name || criteria.category || 'Product'}{criteria.brands
				?.length
				? ` · ${criteria.brands.join(', ')}`
				: ''}{criteria.authors?.length
				? ` · ${criteria.authors.join(', ')}`
				: ''}{criteria.reference_price
				? ` · Reference: ${money(criteria.reference_price, criteria.currency || 'BRL')}`
				: ''}
		</p>
		{#if criteria.description}<p>{criteria.description}</p>{/if}
		{#each criteria.characteristics || [] as c, i (i)}<p>
				{c.name}: {c.operator}
				{c.value}
				{c.unit}
			</p>{/each}{#if criteria.notes}<p>{criteria.notes}</p>{/if}
	</div>{/if}
{#if loading}<div class="panel loading-state" aria-live="polite">
		<span class="spinner"></span>Loading {detail ? 'details' : 'metrics'}…
	</div>
{:else if detail && captures}
	<section class="product-results" aria-label="Products and purchase terms">
		<div class="panel-header">
			<div>
				<h2>Products and purchase terms</h2>
				<p>
					{captures.total.toLocaleString('en-US')} offers · latest collection for each product in the
					period
				</p>
			</div>
		</div>
		{#if !captures.items.length}
			<div class="panel empty-state">
				<h2>No products found</h2>
				<p>Adjust the filters or expand the date range.</p>
			</div>
		{:else}
			{#each captures.items as capture, i (`${capture.capture_id}:${capture.public_id || i}`)}
				<ProductDetails value={capture} />
			{/each}
		{/if}
	</section>
	<div class="pagination">
		<span
			>{captures.total
				? `${offset + 1}–${Math.min(offset + limit, captures.total)} of ${captures.total}`
				: '0 records'}</span
		>
		<div>
			<Button
				variant="secondary"
				disabled={!offset}
				onclick={() => {
					offset -= limit;
					void load();
				}}>Previous</Button
			><Button
				variant="secondary"
				disabled={offset + limit >= captures.total}
				onclick={() => {
					offset += limit;
					void load();
				}}>Next</Button
			>
		</div>
	</div>
{:else if dashboard}
	{#if extractions}
		<div class="metric-grid">
			<div class="panel metric">
				<span>Tracked products</span><strong>{dashboard.totals.products}</strong><small
					>{dashboard.totals.offers} distinct offers</small
				>
			</div>
			<div class="panel metric">
				<span>Collections in this period</span><strong>{dashboard.totals.observations}</strong
				><small>Distinct captures per product</small>
			</div>
			<div class="panel metric">
				<span>Runs</span><strong>{dashboard.execution_totals.total}</strong><small
					>{dashboard.execution_totals.completed} completed · {dashboard.execution_totals.failed} failures
					/ blocks</small
				>
			</div>
			<div class="panel metric">
				<span>Completion rate</span><strong
					>{dashboard.execution_totals.total
						? `${((100 * dashboard.execution_totals.completed) / dashboard.execution_totals.total).toLocaleString('en-US', { maximumFractionDigits: 1 })}%`
						: '—'}</strong
				><small
					>{dashboard.execution_totals.partial} partial · {dashboard.execution_totals.in_progress} in
					progress</small
				>
			</div>
		</div>
		<section class="panel chart-panel">
			<div class="chart-heading">
				<div>
					<h2>Extractions over time</h2>
					<p>Status of runs started each day</p>
				</div>
			</div>
			<ComparisonChart title="Daily runs by status" kind="bar" {labels} series={executionSeries} />
		</section>
		<p class="analytics-note">
			The completion rate includes all runs in the period, including those still in progress.
		</p>
	{:else}
		{#if !dashboard.totals.observations && !dashboard.execution_totals.total}<section
				class="panel empty-state"
			>
				<h2>No data in this period</h2>
				<p>Try expanding the date range or changing the filters.</p>
				<a href="/extractions?new">Create extraction ↗</a>
			</section>{/if}
		<div class="currency-heading">
			<div>
				<h2>Price intelligence</h2>
			</div>
			<Select
				id="analytics-currency"
				label="Comparison currency"
				bind:value={currency}
				options={dashboard.currencies.length
					? dashboard.currencies.map((c) => ({ value: c.currency, label: c.currency }))
					: [{ value: 'BRL', label: 'BRL' }]}
			/>
		</div>
		<div class="metric-grid">
			<div class="panel metric">
				<span>Lowest price</span><strong>{money(stats?.minimum, currency)}</strong><small
					>{stats?.priced_offers || 0} offers with a reported price</small
				>
			</div>
			<div class="panel metric">
				<span>Average price</span><strong>{money(stats?.average, currency)}</strong><small
					>Highest price: {money(stats?.maximum, currency)}</small
				>
			</div>
			<div class="panel metric">
				<span>Price drops</span><strong>{stats?.drops || 0}</strong><small
					>{stats?.rises || 0} increases · compared with the previous collection in the period</small
				>
			</div>
			<div class="panel metric">
				<span>Interest-free installments</span><strong>{stats?.interest_free || 0}</strong><small
					>{stats?.promotions || 0} offers with promotions · {stats?.available || 0} available</small
				>
			</div>
		</div>
		<CommerceAnalytics
			rows={(dashboard.commerce || []).filter((row) => row.currency === currency)}
			coupons={(dashboard.coupon_terms || []).filter((row) => row.currency === currency)}
			{currency}
		/>
		<div class="chart-grid">
			<section class="panel chart-panel">
				<div class="chart-heading">
					<div>
						<h2>Price trends</h2>
						<p>Prices collected by day and site · {currency}</p>
					</div>
					<Select
						id="price-metric"
						label="Metric"
						bind:value={metric}
						options={[
							{ value: 'average', label: 'Average price' },
							{ value: 'minimum', label: 'Lowest price' },
							{ value: 'maximum', label: 'Highest price' }
						]}
					/>
				</div>
				<ComparisonChart
					title="Daily price trends by site"
					{labels}
					series={priceSeries}
					format={(v) => money(v, currency)}
				/>
			</section>
			<section class="panel chart-panel">
				<div class="chart-heading">
					<div>
						<h2>Site comparison</h2>
						<p>Latest offers in the period · {currency}</p>
					</div>
				</div>
				<ComparisonChart
					title="Minimum, average, and maximum prices by site"
					kind="bar"
					labels={siteRows.map((s) => siteName(s.site))}
					series={['minimum', 'average', 'maximum'].map((key, i) => ({
						label: ['Minimum', 'Average', 'Maximum'][i],
						values: siteRows.map((s) => s[key as 'average'])
					}))}
					format={(v) => money(v, currency)}
				/>
			</section>
			<section class="panel chart-panel">
				<div class="chart-heading">
					<div>
						<h2>Payment and installments</h2>
						<p>Offers by advertised terms and site · {currency}</p>
					</div>
				</div>
				<ComparisonChart
					title="Offers by payment method and installments"
					kind="bar"
					labels={paymentGroups}
					series={paymentSeries}
				/>
				<p class="small-note">An offer may appear under more than one payment option.</p>
			</section>
		</div>
		<section class="panel insight-panel">
			<div class="panel-header">
				<div>
					<h2>Detected opportunities</h2>
					<p>
						Largest drops compared with the previous collection for the same offer and currency in
						the period.
					</p>
				</div>
			</div>
			{#if dashboard.opportunities.filter((o) => o.currency === currency).length}<div
					class="opportunity-grid"
				>
					{#each dashboard.opportunities.filter((o) => o.currency === currency) as offer, i (i)}<article
							class="opportunity"
						>
							<span class="drop"
								>{offer.change.toLocaleString('en-US', { maximumFractionDigits: 1 })}%</span
							><strong>{offer.title}</strong><small
								>{siteName(offer.site)} · {date(offer.observed_at)}</small
							><b>{money(offer.price, currency)}</b><small
								>Previous: {money(offer.previous_price, currency)}</small
							>
						</article>{/each}
				</div>{:else}<p class="insight-empty">
					No comparable price drops found. At least two collections of the same offer are required
					in the period.
				</p>{/if}
		</section>
		<section class="panel detail-panel">
			<div class="panel-header">
				<div>
					<h2>Commercial terms in numbers</h2>
					<p>Advertised totals and installments from the latest offers.</p>
				</div>
			</div>
			{#if payments.length}<div class="table-scroll">
					<table>
						<thead
							><tr
								><th>Site</th><th>Payment</th><th>Installments</th><th>Interest</th><th>Offers</th
								><th>Average total</th><th>Average installment</th></tr
							></thead
						><tbody
							>{#each payments as p, i (i)}<tr
									><td>{siteName(p.site)}</td><td>{paymentName(p.method)}</td><td
										>{p.installments || '—'}</td
									><td
										>{p.interest_free === true
											? 'Interest-free'
											: p.interest_free === false
												? 'With interest'
												: 'Not specified'}</td
									><td>{p.offers}</td><td>{money(p.average_total, currency)}</td><td
										>{money(p.average_installment, currency)}</td
									></tr
								>{/each}</tbody
						>
					</table>
				</div>{:else}<p class="insight-empty">
					No payment options recorded for these filters.
				</p>{/if}
		</section>
		<p class="analytics-note">
			Site averages may include different products. Select a product or term for a specific
			comparison. Currencies are analyzed separately; coupon and shipping terms appear under Product
			details. Days without collections appear as gaps. The term filter uses products associated
			with the search, including their updates.
		</p>
	{/if}
{/if}

<style>
	.filter-panel,
	.criteria {
		padding: 22px;
		margin-bottom: 24px;
	}
	.filter-heading,
	.currency-heading,
	.chart-heading {
		display: flex;
		gap: 18px;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 20px;
	}
	h2 {
		font-size: 17px;
	}
	p,
	small {
		color: var(--muted);
	}
	.filter-heading p,
	.chart-heading p {
		font-size: 13px;
		margin-top: 6px;
		line-height: 1.5;
	}
	.presets {
		display: flex;
		gap: 8px;
	}
	.presets button {
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--blue-50);
		color: var(--blue-800);
		padding: 6px 12px;
		font-size: 12px;
	}
	.filters {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 16px;
	}
	.product-filter {
		grid-column: 1/-1;
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 16px;
	}
	.search-status {
		grid-column: 1/-1;
		font-size: 12px;
		color: var(--muted);
	}
	.filter-actions {
		display: flex;
		justify-content: flex-end;
		gap: 10px;
		align-items: center;
		margin-top: 20px;
	}
	.filter-actions span {
		margin-right: auto;
		color: var(--muted);
		font-size: 12px;
	}
	.criteria p {
		font-size: 13px;
		margin-top: 8px;
	}
	.metric-grid {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 16px;
		margin-bottom: 26px;
	}
	.metric {
		padding: 22px;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	.metric span {
		font-size: 13px;
		color: var(--muted);
	}
	.metric strong {
		font-size: 28px;
		letter-spacing: -1px;
		font-variant-numeric: tabular-nums;
	}
	.metric small {
		font-size: 12px;
		line-height: 1.5;
	}
	.currency-heading :global(.field),
	.chart-heading :global(.field) {
		width: 180px;
		flex-shrink: 0;
	}
	.chart-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 20px;
		margin-bottom: 24px;
	}
	.chart-grid > .chart-panel:last-child {
		grid-column: 1 / -1;
	}
	.chart-panel {
		padding: 22px;
		min-width: 0;
	}
	.chart-heading {
		min-height: 70px;
	}
	.detail-panel,
	.insight-panel {
		margin-bottom: 24px;
		overflow: hidden;
	}
	.detail-panel :global(.panel-header),
	.insight-panel :global(.panel-header) {
		padding: 22px;
	}
	.table-scroll {
		overflow-x: auto;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 13px;
		text-align: left;
	}
	th {
		background: var(--blue-50);
		color: var(--muted);
		font-size: 12px;
		font-weight: 600;
	}
	td,
	th {
		padding: 16px 20px;
		border-bottom: 1px solid var(--border);
		vertical-align: top;
	}
	.product-results {
		display: grid;
		gap: 20px;
		min-width: 0;
	}
	.product-results > .panel-header p {
		margin-top: 8px;
		font-size: 13px;
		line-height: 1.5;
	}

	.small-note {
		font-size: 12px;
		margin-top: 12px;
	}
	.opportunity-grid {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 14px;
		padding: 0 22px 22px;
	}
	.opportunity {
		display: flex;
		flex-direction: column;
		gap: 8px;
		border: 1px solid var(--border);
		border-radius: 10px;
		padding: 18px;
	}
	.opportunity strong {
		font-size: 14px;
		line-height: 1.5;
	}
	.opportunity small {
		font-size: 12px;
	}
	.opportunity b {
		font-size: 20px;
	}
	.drop {
		color: var(--success);
		background: #edf7f0;
		border-radius: 5px;
		padding: 4px 8px;
		align-self: flex-start;
		font-size: 13px;
		font-weight: 700;
	}
	.insight-empty {
		padding: 0 22px 24px;
		font-size: 14px;
		line-height: 1.6;
	}
	@media (max-width: 1200px) {
		.metric-grid,
		.opportunity-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
		.chart-grid {
			grid-template-columns: 1fr;
		}
	}
	@media (max-width: 600px) {
		.product-filter {
			grid-template-columns: 1fr;
		}
		.filters {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
		.filters :global(.field:nth-child(n + 3)) {
			grid-column: 1/-1;
		}
		.filter-heading,
		.currency-heading,
		.chart-heading {
			flex-direction: column;
			align-items: stretch;
		}
		.filter-actions {
			flex-wrap: wrap;
		}
		.filter-actions span {
			width: 100%;
		}
		.metric {
			padding: 16px;
		}
		.metric strong {
			font-size: 23px;
		}
		.opportunity-grid {
			grid-template-columns: 1fr;
		}
	}
</style>

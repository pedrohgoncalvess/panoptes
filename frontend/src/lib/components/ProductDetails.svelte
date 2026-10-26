<script lang="ts">
	import { date } from '#lib/api.ts';
	import { money, siteName, type Capture } from '#lib/price-analytics.ts';
	import CommercialDetails from './CommercialDetails.svelte';
	let { value }: { value: Capture } = $props();
	const url = $derived(value.url && /^https?:\/\//i.test(value.url) ? value.url : undefined);
	const discount = $derived(
		value.price != null &&
			value.list_price != null &&
			Number(value.list_price) > Number(value.price) &&
			Number(value.price) >= 0
			? Number(value.list_price) - Number(value.price)
			: null
	);
	const availability = $derived(
		value.availability_text ||
			{ in_stock: 'Available', out_of_stock: 'Unavailable' }[value.availability || ''] ||
			'Availability not specified'
	);
	const labels: Record<string, string> = {
		color: 'Color',
		size: 'Size',
		capacity: 'Capacity',
		voltage: 'Voltage',
		socket: 'Socket',
		cores: 'Cores',
		threads: 'Threads',
		description: 'Description',
		format: 'Format',
		screen_size_inches: 'Screen (inches)',
		storage_gb: 'Storage (GB)',
		memory_gb: 'Memory (GB)',
		page_count: 'Pages',
		language: 'Language',
		publisher: 'Publisher',
		author: 'Author',
		isbn: 'ISBN',
		isbn13: 'ISBN-13',
		ean: 'EAN',
		gtin: 'GTIN',
		mpn: 'Manufacturer code'
	};
	const categories: Record<string, string> = {
		book: 'Books',
		electronics: 'Electronics',
		appliances: 'Home appliances',
		hardware: 'Hardware',
		school_supplies: 'School supplies',
		television: 'Televisions',
		refrigerator: 'Refrigerators',
		other: 'Other'
	};
	const formatValue = (value: unknown): string =>
		value == null
			? 'Not specified'
			: typeof value === 'boolean'
				? value
					? 'Yes'
					: 'No'
				: Array.isArray(value)
					? value.map(formatValue).join(', ')
					: typeof value === 'object'
						? Object.entries(value)
								.map(
									([key, item]) =>
										`${labels[key] || key.replaceAll('_', ' ')}: ${formatValue(item)}`
								)
								.join(' · ')
						: String(value);
</script>

<article class="panel product-details">
	<header class="product-heading">
		<div class="product-identity">
			<span class="store">{siteName(value.site)}</span>
			<h2>{value.title}</h2>
			<p>Sold by {value.seller || 'seller not specified'}</p>
			<p class="availability" class:unavailable={value.availability === 'out_of_stock'}>
				{availability}
			</p>
			{#if url}<a class="product-link" href={url} target="_blank" rel="noopener noreferrer"
					>View product in store ↗</a
				>{/if}
		</div>
		<div class="price-summary">
			<span>Advertised price</span>
			{#if value.list_price != null}<p>
					Was <s>{money(value.list_price, value.currency || 'BRL')}</s>
				</p>{/if}
			<strong
				>{value.price != null
					? money(value.price, value.currency || 'BRL')
					: 'Price not specified'}</strong
			>
			{#if discount != null}<p class="discount">
					{money(discount, value.currency || 'BRL')} discount ({(
						(discount / Number(value.list_price)) *
						100
					).toLocaleString('en-US', { maximumFractionDigits: 1 })}%)
				</p>{/if}
			<small>Shipping and coupons shown separately.</small>
		</div>
	</header>
	<section class="product-specifications" aria-label="Product attributes">
		<h3>About this product</h3>
		<dl>
			<div>
				<dt>Category</dt>
				<dd>{categories[value.category || ''] || value.category || 'Not specified'}</dd>
			</div>
			<div>
				<dt>Brand</dt>
				<dd>{value.brand || 'Not specified'}</dd>
			</div>
			<div>
				<dt>Model</dt>
				<dd>{value.model || 'Not specified'}</dd>
			</div>
			<div>
				<dt>Condition</dt>
				<dd>
					{{ new: 'New', used: 'Used', refurbished: 'Refurbished' }[value.condition || ''] ||
						value.condition ||
						'Not specified'}
				</dd>
			</div>
			<div>
				<dt>Ships from / origin</dt>
				<dd>{value.ships_from || 'Not specified'}</dd>
			</div>
			{#each Object.entries({ ...value.attributes, ...value.identifiers }) as [name, item] (name)}
				<div>
					<dt>{labels[name] || name.replaceAll('_', ' ')}</dt>
					<dd>{formatValue(item)}</dd>
				</div>
			{/each}
		</dl>
	</section>
	<CommercialDetails {value} />
	<footer>
		<p>Updated at {date(value.observed_at)} · latest collection in the selected period</p>
		<details>
			<summary>Collection data</summary>
			<dl>
				<div>
					<dt>Product in store</dt>
					<dd>{value.source_key}</dd>
				</div>
				<div>
					<dt>Associated terms</dt>
					<dd>{value.terms || 'None'}</dd>
				</div>
				<div>
					<dt>Collection</dt>
					<dd>{value.capture_id}</dd>
				</div>
				<div>
					<dt>Offer</dt>
					<dd>{value.public_id || 'No offer extracted'}</dd>
				</div>
			</dl>
			{#if value.request_id}<a
					class="product-link"
					href={`/extraction/logs?request_id=${value.request_id}`}>View run ↗</a
				>{/if}
		</details>
	</footer>
</article>

<style>
	.product-details {
		padding: 24px;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.product-heading {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(220px, 0.45fr);
		gap: 24px;
		align-items: start;
	}
	.product-identity,
	.price-summary {
		min-width: 0;
	}
	.store {
		display: inline-block;
		color: var(--blue-700);
		font-size: 13px;
		font-weight: 650;
		margin-bottom: 10px;
	}
	h2 {
		font-size: 21px;
		line-height: 1.4;
	}
	h3 {
		font-size: 15px;
		margin-bottom: 16px;
	}
	p {
		margin-top: 8px;
		font-size: 14px;
		line-height: 1.6;
		color: var(--muted);
	}
	.availability {
		color: var(--success);
		font-weight: 600;
	}
	.unavailable {
		color: var(--muted);
	}
	.product-link {
		display: inline-block;
		color: var(--blue-700);
		font-size: 13px;
		margin-top: 12px;
		text-decoration: underline;
		text-underline-offset: 3px;
	}
	.price-summary {
		background: var(--blue-50);
		padding: 18px;
		border: 1px solid var(--border);
		border-radius: 10px;
	}
	.price-summary > span,
	small {
		font-size: 12px;
		color: var(--muted);
	}
	.price-summary strong {
		display: block;
		margin: 10px 0;
		font-size: 28px;
		line-height: 1.3;
		font-variant-numeric: tabular-nums;
	}
	.discount {
		color: var(--success);
		font-weight: 600;
	}
	.product-specifications {
		margin: 24px 0;
		padding: 24px 0;
		border-block: 1px solid var(--border);
	}
	dl {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 18px;
		margin: 0;
	}
	dl > div {
		min-width: 0;
	}
	dt {
		color: var(--muted);
		font-size: 12px;
	}
	dd {
		margin: 5px 0 0;
		font-size: 14px;
		line-height: 1.6;
	}
	footer {
		margin-top: 24px;
		padding-top: 16px;
		border-top: 1px solid var(--border);
	}
	footer p,
	summary {
		font-size: 12px;
		color: var(--muted);
	}
	summary {
		cursor: pointer;
		margin: 12px 0;
	}
	@media (max-width: 900px) {
		.product-heading {
			grid-template-columns: minmax(0, 1fr);
		}
		dl {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}
	@media (max-width: 480px) {
		.product-details {
			padding: 18px;
		}
		dl {
			grid-template-columns: minmax(0, 1fr);
		}
	}
</style>

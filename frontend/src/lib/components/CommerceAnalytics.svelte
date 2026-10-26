<script lang="ts">
	import { money, siteName, type CouponTerms, type CommerceStats } from '#lib/price-analytics.ts';
	import ComparisonChart from './ComparisonChart.svelte';
	let {
		rows,
		coupons,
		currency
	}: { rows: CommerceStats[]; coupons: CouponTerms[]; currency: string } = $props();
</script>

<section class="panel commerce-analytics" aria-label="Coupons and shipping analytics">
	<h2>Coupons and shipping</h2>
	<p>
		Latest observation per offer in the selected period · {currency}. Unknown shipping is not zero.
	</p>
	{#if rows.length}
		<div class="charts">
			<ComparisonChart
				title="Offers with advertised coupons"
				kind="bar"
				labels={rows.map((row) => siteName(row.site))}
				series={[
					{ label: 'With coupons', values: rows.map((row) => row.with_coupons) },
					{ label: 'All offers', values: rows.map((row) => row.offers) }
				]}
			/>
			<ComparisonChart
				title="Shipping coverage by site"
				kind="bar"
				labels={rows.map((row) => siteName(row.site))}
				series={[
					{ label: 'Reported free', values: rows.map((row) => row.free_shipping) },
					{ label: 'Paid', values: rows.map((row) => row.paid_shipping) },
					{ label: 'Unknown cost', values: rows.map((row) => row.unknown_shipping) }
				]}
			/>
		</div>
		<div class="table-scroll">
			<table>
				<caption>Coupon terms and delivery coverage</caption>
				<thead
					><tr
						><th>Site</th><th>Offers with coupons</th><th>Quantified / total coupons</th><th
							>Expired coupons</th
						><th>Average quoted shipping</th><th>Quotes with CEP</th><th
							>Multiple delivery options</th
						></tr
					></thead
				>
				<tbody
					>{#each rows as row (row.site)}<tr>
							<td>{siteName(row.site)}</td><td>{row.with_coupons} / {row.offers}</td><td
								>{row.quantified_coupons} / {row.coupons}</td
							><td>{row.expired_coupons}</td><td
								>{money(row.average_advertised_with_coupons, currency)} / {money(
									row.average_advertised_without_coupons,
									currency
								)}</td
							><td>{money(row.average_shipping, currency)}</td><td>{row.destination_specific}</td
							><td>{row.multiple_shipping_options}</td>
						</tr>{/each}</tbody
				>
			</table>
		</div>
	{:else}<p>No commercial observations for this currency and period.</p>{/if}
	{#if coupons.length}
		<details>
			<summary>Advertised coupon terms ({coupons.length})</summary>
			<div class="table-scroll">
				<table>
					<caption
						>Each coupon is conditional; discounts are not applied to the averages above.</caption
					>
					<thead
						><tr
							><th>Site / coupon</th><th>Discount</th><th>Minimum spend</th><th>Discount cap</th><th
								>Activation</th
							><th>Valid until</th><th>Offers</th></tr
						></thead
					>
					<tbody
						>{#each coupons as coupon, i (i)}<tr>
								<td
									>{siteName(coupon.site)} · {coupon.code || 'No code reported'}
									<p>{coupon.text}</p></td
								>
								<td
									>{coupon.discount_amount != null
										? money(coupon.discount_amount, currency)
										: coupon.discount_percent != null
											? `${coupon.discount_percent}%`
											: 'Unknown'}</td
								>
								<td>{money(coupon.minimum_spend, currency)}</td><td
									>{money(coupon.maximum_discount, currency)}</td
								>
								<td
									>{coupon.requires_activation === true
										? 'Required'
										: coupon.requires_activation === false
											? 'Not required'
											: 'Unknown'}</td
								>
								<td>{coupon.expires_at || 'Unknown'}</td><td>{coupon.offers}</td>
							</tr>{/each}</tbody
					>
				</table>
			</div>
		</details>
	{/if}
	<p class="note">
		Coupons are advertised terms, not verified eligibility or realized savings. Expiration is
		checked now. Shipping counts and averages use the primary quote, including known zero quotes and
		apply to captured destinations and conditions; delivery options are not combined. Advertised
		averages compare different offer groups, not the savings from applying a coupon. Open product
		details to see individual coupon simulations and payment prices.
	</p>
</section>

<style>
	.commerce-analytics {
		padding: 24px;
		margin: 24px 0;
		min-width: 0;
	}
	h2 {
		margin: 0 0 8px;
		font-size: 18px;
	}
	p {
		color: var(--muted);
		font-size: 14px;
	}
	.charts {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 24px;
	}
	.table-scroll {
		overflow-x: auto;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 14px;
	}
	caption {
		text-align: left;
		padding: 16px 0;
		font-weight: 600;
	}
	th,
	td {
		text-align: left;
		padding: 12px;
		border-bottom: 1px solid var(--border);
	}
	th {
		color: var(--muted);
		font-size: 12px;
	}
	.note {
		font-size: 13px;
		margin-top: 16px;
	}
	@media (max-width: 900px) {
		.charts {
			grid-template-columns: minmax(0, 1fr);
		}
	}
</style>

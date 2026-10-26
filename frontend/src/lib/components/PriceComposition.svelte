<script lang="ts">
	import type { PriceComposition } from '#lib/commercial.ts';
	import { money } from '#lib/price-analytics.ts';
	let { value, currency }: { value: PriceComposition; currency?: string | null } = $props();
	const format = (amount: string | null) => (currency ? money(amount, currency) : 'Not specified');
	const statuses: Record<string, string> = {
		simulated: 'Conditional simulation',
		expired: 'Expired',
		minimum_not_met: 'Minimum spend not met',
		unknown: 'Insufficient information'
	};
</script>

<section class="composition" aria-label="Price composition">
	<h3>Price composition</h3>
	<div class="summary">
		<div><span>Advertised price</span><strong>{format(value.advertised_price)}</strong></div>
		<div>
			<span>Confirmed price without coupon</span><strong
				>{format(value.price_without_coupon)}</strong
			>
		</div>
		<div><span>Captured shipping</span><strong>{format(value.shipping_price)}</strong></div>
		<div>
			<span>Without coupon + shipping</span><strong>{format(value.total_without_coupon)}</strong>
		</div>
	</div>
	<p>
		Coupon included in advertised price: {value.price_includes_coupon === true
			? 'Yes'
			: value.price_includes_coupon === false
				? 'No'
				: 'Unknown'}
	</p>
	{#each value.coupon_scenarios as scenario, i (i)}
		<article>
			<h4>
				{scenario.code ? `Coupon ${scenario.code}` : `Coupon ${scenario.promotion_index + 1}`} · {statuses[
					scenario.status
				] || scenario.status}
			</h4>
			<div class="summary">
				<div><span>Scenario base</span><strong>{format(scenario.base_price)}</strong></div>
				<div><span>Estimated savings</span><strong>{format(scenario.savings)}</strong></div>
				<div><span>With coupon</span><strong>{format(scenario.price_with_coupon)}</strong></div>
				<div>
					<span>With coupon + shipping</span><strong>{format(scenario.total_with_shipping)}</strong>
				</div>
			</div>
			{#each scenario.assumptions as assumption, index (index)}<p class="note">
					{assumption}
				</p>{/each}
		</article>
	{/each}
	<details>
		<summary>Calculation conditions</summary>{#each value.notes as note, index (index)}<p
				class="note"
			>
				{note}
			</p>{/each}
	</details>
</section>

<style>
	.composition {
		margin-bottom: 24px;
		padding-bottom: 20px;
		border-bottom: 1px solid var(--border);
	}
	h3,
	h4 {
		margin: 0 0 12px;
		font-size: 15px;
	}
	.summary {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 16px;
	}
	span,
	strong {
		display: block;
	}
	span,
	.note {
		color: var(--muted);
		font-size: 13px;
	}
	strong {
		margin-top: 4px;
		font-size: 18px;
		font-variant-numeric: tabular-nums;
	}
	article {
		padding: 16px;
		margin: 16px 0;
		border: 1px solid var(--border);
		border-radius: 8px;
	}
	summary {
		cursor: pointer;
	}
	@media (max-width: 760px) {
		.summary {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}
	@media (max-width: 400px) {
		.summary {
			grid-template-columns: minmax(0, 1fr);
		}
	}
</style>

<script lang="ts">
	import PriceComposition from './PriceComposition.svelte';
	import { date } from '#lib/api.ts';
	import type { CommercialSnapshot } from '#lib/commercial.ts';
	let { value, showPromotions = true }: { value: CommercialSnapshot; showPromotions?: boolean } =
		$props();
	const shippingOptions = $derived(
		value.shipping_options?.length ? value.shipping_options : value.shipping ? [value.shipping] : []
	);
	const money = (amount: string | null | undefined) =>
		amount != null && amount !== '' && Number.isFinite(Number(amount)) && value.currency
			? new Intl.NumberFormat('en-US', { style: 'currency', currency: value.currency }).format(
					Number(amount)
				)
			: 'Not specified';
	const methods: Record<string, string> = {
		pix: 'Pix',
		cash: 'Upfront payment / bank slip',
		card: 'Card',
		installment: 'Installments'
	};
</script>

<div class="commerce-details">
	{#if value.price_composition}<PriceComposition
			value={value.price_composition}
			currency={value.currency}
		/>{/if}
	<div class="commerce-grid">
		<section class="commerce-section" aria-label="Payment and installments">
			<h3>Payment and installments</h3>
			{#each value.payment_options || [] as payment, index (index)}
				<div class="condition-card">
					<strong>{methods[payment.method || ''] || payment.method || 'Payment'}</strong>
					<p class="payment-price">{money(payment.total_price)}</p>
					{#if payment.installment_count != null}
						<p>
							{payment.installment_count}× {money(payment.installment_price)} · {payment.interest_free ===
							true
								? 'interest-free'
								: payment.interest_free === false
									? 'with interest'
									: 'interest not specified'}
						</p>
					{/if}
					{#if payment.total_is_derived}<small>Total calculated from installments</small>{/if}
					{#if value.units_per_pack && payment.total_price != null}<small
							>{money(String(Number(payment.total_price) / value.units_per_pack))} per unit</small
						>{/if}
					<p>{payment.text}</p>
					{#each payment.conditions || [] as condition, i (i)}<p class="condition">
							{condition}
						</p>{/each}
				</div>
			{:else}<p class="unavailable">Payment options were not provided during collection.</p>{/each}
		</section>
		<section class="commerce-section" aria-label="Shipping and delivery">
			<h3>Shipping and delivery</h3>
			{#each shippingOptions as shipping, index (index)}
				<div class="condition-card">
					<strong
						>{shipping.is_free === true
							? 'Free shipping'
							: `Shipping: ${money(shipping.price)}`}</strong
					>
					<p>{shipping.text}</p>
					<p>Delivery: {shipping.delivery_text || 'Delivery time not specified'}</p>
					<p>
						Destination: {shipping.destination_postal_code
							? `Postal code ${shipping.destination_postal_code}`
							: 'Postal code not specified'}
					</p>
					{#each shipping.conditions || [] as condition, i (i)}<p class="condition">
							{condition}
						</p>{/each}
				</div>
			{:else}<p class="unavailable">
					Shipping, delivery time, and destination were not provided during collection.
				</p>{/each}
		</section>
		{#if showPromotions}
			<section class="commerce-section" aria-label="Coupons and promotions">
				<h3>Coupons and promotions</h3>
				{#each value.promotions || [] as promotion, index (index)}
					<div class="condition-card">
						<strong
							>{promotion.code
								? `Coupon ${promotion.code}`
								: promotion.kind === 'coupon'
									? 'Advertised coupon'
									: 'Promotion'}</strong
						>
						<p>{promotion.text}</p>
						{#if promotion.discount_amount != null}<p>
								Discount: {money(promotion.discount_amount)}
							</p>{/if}
						{#if promotion.discount_percent != null}<p>
								Discount: {promotion.discount_percent}%
							</p>{/if}
						{#if promotion.minimum_spend != null}<p>
								Minimum spend: {money(promotion.minimum_spend)}
							</p>{/if}
						{#if promotion.maximum_discount != null}<p>
								Maximum discount: {money(promotion.maximum_discount)}
							</p>{/if}
						<p>
							Activation: {promotion.requires_activation === true
								? 'required'
								: promotion.requires_activation === false
									? 'not required'
									: 'not specified'}
						</p>
						<p>
							Valid until: {promotion.expires_at ? date(promotion.expires_at) : 'not specified'}
						</p>
						{#each promotion.conditions || [] as condition, i (i)}<p class="condition">
								{condition}
							</p>{/each}
					</div>
				{:else}<p class="unavailable">
						No coupons or promotions were provided during collection.
					</p>{/each}
				<small
					>Coupon inclusion in the advertised price may be unknown. Calculated scenarios are
					conditional simulations.</small
				>
			</section>
		{/if}
		<section class="commerce-section" aria-label="Quantity and purchase limits">
			<h3>Quantity and purchase limits</h3>
			<dl class="quantity-grid">
				<div>
					<dt>Stock</dt>
					<dd>
						{value.stock_qt != null
							? `${value.stock_qt} units`
							: value.stock_lower_bound_qt != null
								? `At least ${value.stock_lower_bound_qt} units`
								: 'Not specified'}
					</dd>
				</div>
				<div>
					<dt>Units per pack</dt>
					<dd>{value.units_per_pack ?? 'Not specified'}</dd>
				</div>
				<div>
					<dt>Minimum purchase</dt>
					<dd>{value.minimum_purchase_qt ?? 'Not specified'}</dd>
				</div>
				<div>
					<dt>Purchase limit</dt>
					<dd>{value.maximum_purchase_qt ?? 'Not specified'}</dd>
				</div>
			</dl>
		</section>
	</div>
	{#if value.commercial_extraction}<details class="commerce-evidence">
			<summary>Collection sources and evidence</summary>
			{#if value.commercial_extraction.model}<p>Model: {value.commercial_extraction.model}</p>{/if}
			{#if value.commercial_extraction.fallback_status === 'failed'}<p>
					AI interpretation failed; parser data was preserved.
				</p>{/if}
			{#if value.commercial_extraction.fallback_status === 'disabled'}<p>
					AI is disabled or no key is configured.
				</p>{/if}
			{#if value.commercial_extraction.unresolved?.length}<p>
					{value.commercial_extraction.unresolved.length} excerpts could not be fully interpreted; unknown
					values remain unspecified.
				</p>{/if}
			{#each value.commercial_extraction.evidence || [] as evidence, index (index)}<blockquote>
					<small
						>{evidence.method === 'openrouter' ? 'AI with evidence' : 'Deterministic parser'}</small
					>{evidence.excerpt}
				</blockquote>{/each}
		</details>{/if}
</div>

<style>
	.commerce-details {
		min-width: 0;
		font-size: 14px;
		line-height: 1.6;
		overflow-wrap: anywhere;
	}
	.commerce-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 24px;
	}
	.commerce-section {
		min-width: 0;
	}
	h3 {
		font-size: 15px;
		margin: 0 0 12px;
	}
	p {
		margin: 6px 0;
	}
	.condition-card {
		min-width: 0;
		padding: 16px;
		border: 1px solid var(--border);
		border-radius: 8px;
		margin-bottom: 10px;
	}
	.payment-price {
		font-size: 20px;
		font-weight: 650;
		font-variant-numeric: tabular-nums;
	}
	small,
	.unavailable,
	dt {
		color: var(--muted);
		font-size: 13px;
	}
	small {
		display: block;
	}
	.condition {
		padding-left: 10px;
		border-left: 2px solid var(--border);
	}
	.quantity-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 16px;
		margin: 0;
	}
	.quantity-grid div {
		min-width: 0;
	}
	dd {
		margin: 4px 0 0;
	}
	summary {
		cursor: pointer;
	}
	blockquote {
		margin: 12px 0;
		padding-left: 12px;
		border-left: 2px solid var(--border);
	}
	.commerce-evidence {
		margin-top: 24px;
		padding-top: 16px;
		border-top: 1px solid var(--border);
		color: var(--muted);
	}
	@media (max-width: 760px) {
		.commerce-grid {
			grid-template-columns: minmax(0, 1fr);
		}
	}
	@media (max-width: 400px) {
		.quantity-grid {
			grid-template-columns: minmax(0, 1fr);
		}
	}
</style>

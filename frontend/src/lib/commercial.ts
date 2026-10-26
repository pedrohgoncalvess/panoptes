export type PriceComposition = {
	advertised_price: string | null;
	price_includes_coupon: boolean | null;
	price_without_coupon: string | null;
	shipping_price: string | null;
	total_without_coupon: string | null;
	notes: string[];
	coupon_scenarios: {
		promotion_index: number;
		code: string | null;
		status: string;
		base_price: string | null;
		savings: string | null;
		price_with_coupon: string | null;
		total_with_shipping: string | null;
		assumptions: string[];
	}[];
};
export type Payment = {
	method?: string;
	text: string;
	total_price?: string | null;
	installment_count?: number | null;
	installment_price?: string | null;
	interest_free?: boolean | null;
	total_is_derived?: boolean;
	extraction_method?: string;
	conditions?: string[];
};
export type Shipping = {
	text: string;
	price?: string | null;
	is_free?: boolean | null;
	destination_postal_code?: string | null;
	delivery_text?: string | null;
	conditions?: string[];
};
export type Promotion = {
	kind?: string;
	text: string;
	code?: string | null;
	discount_amount?: string | null;
	discount_percent?: string | null;
	minimum_spend?: string | null;
	maximum_discount?: string | null;
	expires_at?: string | null;
	requires_activation?: boolean | null;
	conditions?: string[];
};
export type CommercialSnapshot = {
	price_composition?: PriceComposition | null;
	currency?: string | null;
	stock_qt?: number | null;
	stock_lower_bound_qt?: number | null;
	units_per_pack?: number | null;
	minimum_purchase_qt?: number | null;
	maximum_purchase_qt?: number | null;
	payment_options?: Payment[];
	shipping?: Shipping | null;
	shipping_options?: Shipping[];
	promotions?: Promotion[];
	commercial_extraction?: {
		fallback_status?: string;
		model?: string | null;
		unresolved?: string[];
		evidence?: { field: string; excerpt: string; method: string }[];
	} | null;
};

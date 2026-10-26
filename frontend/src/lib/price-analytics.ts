import type { CommercialSnapshot } from './commercial.ts';

export type ProductOption = { public_id: string; title: string; site: string };
export type PriceFilters = {
	start: string;
	end: string;
	term_id: string;
	product_id: string;
	canonical_product_id: string;
	site: string;
	q: string;
};
export type PricePoint = {
	date: string;
	site: string;
	currency: string;
	minimum: number;
	average: number;
	maximum: number;
	observations: number;
};
export type ExecutionPoint = {
	date: string;
	total: number;
	completed: number;
	failed: number;
	partial: number;
	in_progress: number;
};
export type PaymentPoint = {
	site: string;
	currency: string;
	method: string;
	installments: number | null;
	interest_free: boolean | null;
	offers: number;
	average_total: number | null;
	average_installment: number | null;
};
export type CurrencyStats = {
	currency: string;
	priced_offers: number;
	minimum: number | null;
	average: number | null;
	maximum: number | null;
	drops: number;
	rises: number;
	available: number;
	interest_free: number;
	promotions: number;
};
export type CouponTerms = import('./commercial.ts').Promotion & {
	site: string;
	currency: string;
	offers: number;
};
export type CommerceStats = {
	average_advertised_with_coupons: number | null;
	average_advertised_without_coupons: number | null;
	site: string;
	currency: string;
	offers: number;
	with_coupons: number;
	coupons: number;
	quantified_coupons: number;
	expired_coupons: number;
	with_shipping: number;
	free_shipping: number;
	paid_shipping: number;
	unknown_shipping: number;
	average_shipping: number | null;
	destination_specific: number;
	multiple_shipping_options: number;
};
export type PriceDashboard = {
	commerce?: CommerceStats[];
	coupon_terms?: CouponTerms[];
	totals: { products: number; observations: number; offers: number };
	execution_totals: {
		total: number;
		completed: number;
		failed: number;
		partial: number;
		in_progress: number;
	};
	currencies: CurrencyStats[];
	daily: PricePoint[];
	executions: ExecutionPoint[];
	sites: {
		site: string;
		currency: string;
		minimum: number;
		average: number;
		maximum: number;
		offers: number;
	}[];
	payments: PaymentPoint[];
	opportunities: {
		product_id: string;
		title: string;
		site: string;
		currency: string;
		price: number;
		previous_price: number;
		change: number;
		observed_at: string;
	}[];
};
export type Capture = CommercialSnapshot & {
	public_id: string | null;
	capture_id: string;
	product_id: string;
	title: string;
	site: string;
	source_key: string;
	url: string | null;
	seller: string | null;
	terms: string | null;
	observed_at: string;
	price: string | null;
	list_price: string | null;
	currency: string | null;
	availability: string | null;
	availability_text: string | null;
	stock_qt: number | null;
	execution_status: string | null;
	request_id: string | null;
	job_id: string;
	brand?: string | null;
	model?: string | null;
	category?: string | null;
	attributes?: Record<string, unknown> | null;
	identifiers?: Record<string, unknown> | null;
	ships_from?: string | null;
	condition?: string | null;
};
export type CapturePage = { items: Capture[]; total: number; limit: number; offset: number };
export const siteName = (site: string) =>
	({
		amazon_br: 'Amazon',
		mercado_livre_br: 'Mercado Livre',
		kabum_br: 'KaBuM!',
		pichau_br: 'Pichau',
		terabyte_br: 'TerabyteShop'
	})[site] || site;
export const paymentName = (method: string) =>
	({ pix: 'Pix', cash: 'Upfront payment / bank slip', card: 'Card', installment: 'Installments' })[
		method
	] || method;
export const money = (value: number | string | null | undefined, currency = 'BRL') =>
	value == null
		? '—'
		: new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(Number(value));
export function dateRange(days = 30): PriceFilters {
	const today = new Intl.DateTimeFormat('en-CA', {
		timeZone: 'America/Sao_Paulo',
		year: 'numeric',
		month: '2-digit',
		day: '2-digit'
	}).format(new Date());
	const date = new Date(today + 'T12:00:00Z');
	date.setUTCDate(date.getUTCDate() - days + 1);
	return {
		start: date.toISOString().slice(0, 10),
		end: today,
		term_id: '',
		product_id: '',
		canonical_product_id: '',
		q: '',
		site: ''
	};
}
export function filterQuery(filters: PriceFilters) {
	return new URLSearchParams(Object.entries(filters).filter(([, value]) => value)).toString();
}
export function calendar(start: string, end: string) {
	const days: string[] = [];
	const current = new Date(start + 'T12:00:00Z');
	while (
		Number.isFinite(current.getTime()) &&
		current.toISOString().slice(0, 10) <= end &&
		days.length < 366
	) {
		days.push(current.toISOString().slice(0, 10));
		current.setUTCDate(current.getUTCDate() + 1);
	}
	return days;
}

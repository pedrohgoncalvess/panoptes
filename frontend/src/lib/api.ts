import { goto } from '$app/navigation';

export class ApiError extends Error {
	constructor(
		message: string,
		public status: number
	) {
		super(message);
	}
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
	const response = await fetch('/api' + path, {
		...init,
		headers: { 'Content-Type': 'application/json', ...init.headers }
	});
	if (response.status === 401 && path !== '/auth/login') {
		await goto('/', { invalidateAll: true });
		throw new Error('Your session has expired. Sign in again.');
	}
	if (!response.ok) {
		const value = await response.json().catch(() => ({}));
		throw new ApiError(
			typeof value.message === 'string'
				? value.message
				: typeof value.detail === 'string'
					? value.detail
					: 'Unable to complete the request. Check your details and try again.',
			response.status
		);
	}
	return response.status === 204 ? (undefined as T) : await response.json();
}
export const date = (value?: string | null) =>
	value
		? new Intl.DateTimeFormat('en-US', { dateStyle: 'short', timeStyle: 'short' }).format(
				new Date(value)
			)
		: '—';
export type Source = { id: string; name: string };
export type Category = {
	slug: string;
	name: string;
	keywords: string[];
	suggested_fields: string[];
	active: boolean;
};
export type Characteristic = {
	name: string;
	value: string;
	unit: string;
	operator: 'eq' | 'gte' | 'lte' | 'contains';
};
export type Term = {
	public_id: string;
	term: string;
	site?: string;
	criteria?: {
		match_mode?: 'profile' | 'exact_product' | 'category' | 'intent';
		query?: string;
		description?: string;
		category_keywords?: string[];
		isbn?: string[];
		excluded_title_terms?: string[];
		exclude_accessories?: boolean;
		required_attributes?: Record<string, string | number | boolean | null>;
		category?: string;
		category_name?: string;
		title?: string;
		authors?: string[];
		brands?: string[];
		reference_price?: string;
		currency?: string;
		characteristics?: Characteristic[];
		notes?: string;
	};
};
export type Qualification = {
	source_key: string;
	stage?: 'search' | 'detail';
	assessment: {
		candidate: { title: string; url: string };
		decision: string;
		reason: string;
		checks?: {
			name: string;
			expected: string;
			actual?: string;
			status: string;
			evidence?: string;
		}[];
	};
};
export type Schedule = {
	kind: 'fixed' | 'interval' | 'random_daily';
	timezone: string;
	times?: string[];
	interval_minutes?: number;
	times_per_day?: number;
};
export type Routine = {
	sites?: string[];
	term?: string;
	site?: string;
	public_id: string;
	name: string;
	search_term_id: string;
	mode: string;
	schedule: Schedule;
	enabled: boolean;
	next_run_at?: string;
};
export type Extraction = {
	max_pages_qt?: number | null;
	max_candidates_qt?: number | null;
	refresh_interval_seconds?: number | null;
	criteria?: Term['criteria'];
	site?: string;
	public_id: string;
	mode: string;
	status: string;
	term?: string;
	source_key?: string;
	search_term_id?: string;
	entity_id?: string;
	created_at: string;
	completed_at?: string;
	summary: Record<string, unknown>;
};
export type ExtractionPage = { items: Extraction[]; total: number; limit: number; offset: number };
export type Analytics = {
	period_days: number;
	totals: {
		products: number;
		active_routines: number;
		requests: number;
		completed: number;
		failed: number;
		in_progress: number;
	};
	daily: { date: string; total: number; completed: number; failed: number }[];
};

export type ExtractionGroup = Extraction & { group_key: string; execution_count: number };
export type ExtractionGroupPage = {
	items: ExtractionGroup[];
	total: number;
	limit: number;
	offset: number;
};

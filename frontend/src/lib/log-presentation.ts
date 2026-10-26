export type ExtractionLog = {
	id: number;
	request_id: string;
	correlation_id: string;
	site: string | null;
	level: string;
	event: string;
	message: string;
	details: Record<string, unknown>;
	created_at: string;
};

export const executionStatuses: Record<string, string> = {
	pending: 'Queued',
	running: 'In progress',
	completed: 'Completed',
	partial: 'Partially completed',
	failed: 'Failed',
	blocked: 'Blocked',
	accepted: 'Accepted',
	rejected: 'Rejected',
	uncertain: 'Needs review'
};

const stages: Record<string, string> = {
	extraction_started: 'Extraction started',
	context_ready: 'Search configuration',
	page_fetch_started: 'Accessing site',
	http_fallback: 'Access without a browser session',
	source_page_fetched: 'Page received',
	page_received: 'Page received',
	page_blocked: 'Access interrupted',
	page_retry: 'Retrying access',
	product_started: 'Extracting product',
	product_parse_started: 'Reading product data',
	product_parsed: 'Product identified',
	product_classified: 'Product classified from page',
	commercial_extracted: 'Commercial terms recorded',
	product_validation: 'Checking product criteria',
	tracking_paused: 'Tracking paused for incompatible product',
	image_failed: 'Image unavailable',
	product_saved: 'Product processed',
	search_page_started: 'Searching products',
	search_parse_started: 'Reading search results',
	search_parsed: 'Results identified',
	pagination_unavailable: 'Next page unavailable',
	extraction_interrupted: 'Extraction interrupted; results preserved',
	candidate_validation: 'Checking candidate',
	product_failed: 'Product extraction failed',
	extraction_blocked: 'Extraction blocked by site',
	extraction_unavailable: 'Site unavailable',
	lease_lost: 'Run interrupted',
	extraction_failed: 'Extraction failed',
	parser_failed: 'HTML preserved for parser analysis',
	extraction_finished: 'Extraction finished',
	historical_summary: 'Results from a previous run'
};

export function stageTitle(entry: ExtractionLog): string {
	return stages[entry.event] || entry.message;
}

export function isCaptcha(details: Record<string, unknown>): boolean {
	if (details.cause === 'captcha' || details.reason === 'captcha') return true;
	try {
		return /\/captcha(?:\/|$)/i.test(new URL(String(details.final_url || '')).pathname);
	} catch {
		return false;
	}
}

export function explainFailure(details: Record<string, unknown>): string | null {
	const code = isCaptcha(details) ? 'captcha' : String(details.cause || details.reason || '');
	const reasons: Record<string, string> = {
		awaiting_product_classification:
			'Classification will take place after the product page is read.',
		intent_rules: 'Product compared with the search using data extracted from the page.',
		intent_classified: 'Search and description compared with product evidence.',
		product_type_mismatch:
			'The product is a kit, computer, or accessory, but the search requires a standalone component.',
		classifier_unavailable:
			'Classification requires interpretation, but the classifier is unavailable. The product remains unconfirmed.',
		classifier_failed:
			'Classification could not be completed with valid evidence. The product remains unconfirmed.',
		classifier_rate_limited:
			'The AI provider limited requests (HTTP 429). Classification remained unavailable after retries. The product remains unconfirmed and tracking stays enabled.',
		classifier_provider_unavailable:
			'The AI provider remained temporarily unavailable after retries. The product remains unconfirmed and tracking stays enabled.',
		pagination_url_unavailable:
			'The next-page button did not provide a valid URL in the captured HTML. The extraction completed partially and preserved its results. JavaScript navigation still needs to be integrated.',
		search_layout_not_recognized:
			'Panoptes received the page but did not recognize the expected search results format. The parser for this page needs to be investigated and adjusted.',
		unexpected_content_type: 'The site returned content other than a product page.',
		captcha:
			'The site presented a security challenge. Complete verification in your browser and run again. If using Docker, enable “This browser” in the extension or send the session again.',
		local_browser_unavailable:
			'The local browser is unavailable. Open your browser, sign in to Panoptes, and enable collection in the extension.',
		local_browser_timeout:
			'The local browser did not return the page in time. Check the collection tab and make sure the extension and Panoptes are open.',
		local_browser_error:
			'Unable to capture the page in the local browser. Check the tab opened by the extension before running again.',
		verification_required:
			'The site requires security verification. Complete verification in the browser and send the session again through the extension.',
		access_denied: 'The site denied access to the page.',
		rate_limited: 'The site limited the number of requests. Wait before trying again.',
		authentication_required:
			'The site requested authentication. Check the connection and send an authenticated session again.',
		reconnect_required: 'The connection needs to be renewed. Send an authenticated session again.',
		connection_in_progress:
			'The site connection is still being prepared. Wait for it to complete before extracting products.',
		title_matches: 'The title matches the requested product.',
		profile_candidate: 'Candidate selected to confirm brand and attributes on the product page.',
		profile_matches: 'The product meets the criteria and can be tracked.',
		profile_mismatch: 'One or more product details do not meet the search criteria.',
		profile_missing_information:
			'The page did not provide enough information to confirm all criteria. Tracking was not enabled.',
		excluded_title: 'The title contains a term excluded by the search criteria.',
		title_mismatch: 'The title does not match the requested product.',
		author_mismatch: 'The author does not match the search criteria.',
		author_missing: 'The page did not provide the author; the product needs review.',
		isbn_missing: 'The page did not provide the ISBN; the product needs review.',
		isbn_mismatch: 'The ISBN does not match the requested book.',
		robot_check: 'The site requested security verification to continue.',
		login_required:
			'The site requested authentication. Check the connection and send an authenticated session again.',
		session_expired: 'The site session expired. Reconnect your account and send the session again.',
		context_missing: 'Unable to load the configuration required for this extraction.'
	};
	if (reasons[code]) return reasons[code];
	if (code.endsWith('_blocked'))
		return 'The site interrupted access or required verification. Check previous events and the connection status.';
	if (code.endsWith('_unavailable'))
		return 'The site remained unavailable after retries. Run the extraction again when access is restored.';
	if (/http_status_\d+/.test(code) || typeof details.http_status === 'number') {
		const status = Number(code.match(/http_status_(\d+)/)?.[1] || details.http_status);
		if (status === 403)
			return 'The site denied access to the page. Check the connection status before trying again.';
		if (status === 429) return 'The site limited the number of requests. Wait before trying again.';
		if (status >= 500) return 'The site returned an error. Check the retries in previous events.';
		if (status === 404) return 'The requested page was not found on the site.';
	}
	if (
		details.error === 'TimeoutError' ||
		details.error === 'ReadTimeout' ||
		details.error === 'ConnectTimeout'
	)
		return 'The request exceeded the time limit and was interrupted.';
	if (details.error === 'ConnectError') return 'Unable to establish a connection to the site.';
	return code || details.error
		? 'Unable to complete this step. The data below and the support reference can help investigate the issue.'
		: null;
}

const labels: Record<string, string> = {
	payment_count: 'Payment methods',
	promotion_count: 'Promotions',
	shipping_count: 'Shipping terms',
	fallback_status: 'Additional interpretation',
	unresolved_count: 'Excerpts not fully interpreted',
	model: 'Model used',
	mode: 'Extraction type',
	stage: 'Page analyzed',
	captured_at: 'Captured at',
	parser_version: 'Parser version',
	browser_configured: 'Browser service available',
	max_pages: 'Page limit',
	max_candidates: 'Product limit',
	source_url: 'Requested page',
	final_url: 'Page received',
	attempt: 'Attempt',
	http_status: 'Site response',
	capture_mode: 'Access method',
	bytes: 'Page size',
	media_type: 'Content received',
	delay_seconds: 'Retry delay',
	source_key: 'Product code',
	parser: 'Parser used',
	page: 'Search page',
	candidates: 'Products found',
	has_next_page: 'Has another page',
	decision: 'Decision',
	status: 'Result',
	assets: 'Stored files',
	image_errors: 'Image failures',
	duration_ms: 'Duration',
	products: 'Products processed',
	truncated: 'Product limit reached',
	recovered: 'Result recovered',
	title: 'Title',
	authors: 'Authors',
	term: 'Search term'
};
const technicalKeys = new Set([
	'reason',
	'cause',
	'error',
	'error_id',
	'stack',
	'sqlstate',
	'owner',
	'snapshot_id',
	'asset_id',
	'sha256'
]);
const humanize = (key: string) =>
	key
		.replace(/([a-z])([A-Z])/g, '$1 $2')
		.replaceAll('_', ' ')
		.replace(/^./, (value) => value.toUpperCase());
const number = (value: number) => value.toLocaleString('en-US', { maximumFractionDigits: 2 });

function formatValue(key: string, value: unknown): string {
	if (key === 'fallback_status' && typeof value === 'string')
		return (
			(
				{
					not_needed: 'Parser sufficient',
					disabled: 'AI disabled or no key',
					completed: 'Interpretation completed',
					failed: 'AI unavailable; parser data preserved'
				} as Record<string, string>
			)[value] || value
		);
	if (typeof value === 'boolean') return value ? 'Yes' : 'No';
	if (typeof value === 'number') {
		if (key === 'duration_ms')
			return value < 1000 ? `${number(value)} ms` : `${number(value / 1000)} seconds`;
		if (key === 'delay_seconds') return `${number(value)} seconds`;
		if (key === 'bytes')
			return value < 1024
				? `${number(value)} bytes`
				: value < 1024 * 1024
					? `${number(value / 1024)} KB`
					: `${number(value / 1024 / 1024)} MB`;
		if (key === 'http_status')
			return `${value}${value === 200 ? ' · Page received' : value === 403 ? ' · Access denied' : value === 429 ? ' · Request limit' : value >= 500 ? ' · Site error' : ''}`;
		return number(value);
	}
	const text = String(value);
	if (key === 'stage')
		return text === 'search' ? 'Search results' : text === 'product' ? 'Product' : humanize(text);
	if (key === 'captured_at') return new Date(text).toLocaleString('en-US');
	if (key === 'status' || key === 'decision') return executionStatuses[text] || humanize(text);
	if (key === 'mode')
		return text === 'discover'
			? 'Product search'
			: text === 'refresh'
				? 'Product update'
				: humanize(text);
	if (key === 'capture_mode')
		return text === 'browser_local'
			? 'Your browser through the extension'
			: text === 'browser'
				? 'Browser with session'
				: text === 'http'
					? 'HTTP access'
					: humanize(text);
	if (key === 'media_type')
		return text === 'text/html' || text === 'application/xhtml+xml' ? 'Web page' : text;
	return text;
}

export type LogField = { label: string; value: string };
export function detailFields(details: Record<string, unknown>): LogField[] {
	const fields: LogField[] = [];
	function visit(value: unknown, key: string, prefix: string, depth: number) {
		if (value === null || value === undefined || technicalKeys.has(key) || depth > 5) return;
		const label = prefix + (labels[key] || humanize(key));
		if (Array.isArray(value)) {
			if (value.every((item) => item === null || typeof item !== 'object')) {
				if (value.length)
					fields.push({
						label,
						value: value
							.filter((item) => item !== null)
							.map((item) => formatValue(key, item))
							.join(', ')
					});
			} else
				value.forEach((item, index) => visit(item, String(index + 1), label + ' · ', depth + 1));
		} else if (typeof value === 'object') {
			for (const [child, item] of Object.entries(value))
				visit(item, child, label + ' · ', depth + 1);
		} else fields.push({ label, value: formatValue(key, value) });
	}
	for (const [key, value] of Object.entries(details)) visit(value, key, '', 0);
	return fields;
}

export function supportFields(entry: ExtractionLog): LogField[] {
	const fields = [
		{ label: 'Run reference', value: entry.request_id },
		{ label: 'Tracking reference', value: entry.correlation_id },
		{ label: 'Recorded stage', value: entry.event }
	];
	for (const [key, label] of Object.entries({
		reason: 'Diagnostic code',
		cause: 'Recorded reason',
		error: 'Error type',
		error_id: 'Error reference',
		sqlstate: 'Database code',
		snapshot_id: 'Capture reference',
		asset_id: 'File reference',
		sha256: 'Content identifier (SHA-256)'
	})) {
		const value = entry.details[key];
		if (typeof value === 'string' || typeof value === 'number')
			fields.push({ label, value: String(value) });
	}
	return fields;
}

export function stackLocations(details: Record<string, unknown>): string[] {
	if (!Array.isArray(details.stack)) return [];
	return details.stack
		.filter((frame): frame is Record<string, unknown> => !!frame && typeof frame === 'object')
		.map(
			(frame) =>
				`${String(frame.file || 'File')} · line ${String(frame.line || '—')} · ${String(frame.function || 'Unknown stage')}`
		);
}

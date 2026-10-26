<script lang="ts">
	import { onMount } from 'svelte';
	import { request, date, type Routine } from '#lib/api.ts';
	import Button from '#lib/components/Button.svelte';
	import Input from '#lib/components/Input.svelte';
	import Select from '#lib/components/Select.svelte';
	import Notice from '#lib/components/Notice.svelte';
	import Icon from '#lib/components/Icon.svelte';

	type Event =
		| 'extraction_started'
		| 'extraction_finished'
		| 'extraction_error'
		| 'price_threshold'
		| 'price_drop'
		| 'price_increase';
	type Rule = {
		event: Event;
		routine_ids: string[];
		entity_id: string | null;
		currency: string;
		threshold: string | null;
		direction: 'below' | 'above';
		percent: string | null;
	};
	type Webhook = { public_id: string; name: string; url: string; enabled: boolean; rules: Rule[] };
	type Delivery = {
		public_id: string;
		event: Event;
		status: string;
		attempts: number;
		http_status: number | null;
		last_error: string | null;
		created_at: string;
		next_attempt_at: string;
	};
	const events: { value: Event; label: string }[] = [
		{ value: 'extraction_started', label: 'Extraction started' },
		{ value: 'extraction_finished', label: 'Extraction finished' },
		{ value: 'extraction_error', label: 'Extraction error' },
		{ value: 'price_threshold', label: 'Absolute price threshold' },
		{ value: 'price_drop', label: 'Price drop (%)' },
		{ value: 'price_increase', label: 'Price increase (%)' }
	];
	const statuses: Record<string, string> = {
		pending: 'Pending',
		delivered: 'Delivered',
		failed: 'Failed',
		cancelled: 'Canceled'
	};
	let modelEvent = $state<Event>('extraction_started');
	let items = $state<Webhook[]>([]);
	let routines = $state<Routine[]>([]);
	let routinesReady = $state(false);
	let loading = $state(true);
	let busy = $state(false);
	let message = $state('');
	let success = $state('');
	let offset = $state(0);
	const limit = 20;
	let showForm = $state(false);
	let editing = $state<string>();
	let name = $state('');
	let url = $state('');
	let enabled = $state(true);
	let rules = $state<Rule[]>([]);
	let deleting = $state<Webhook>();
	let history = $state<Webhook>();
	let deliveries = $state<Delivery[]>([]);
	let historyOffset = $state(0);
	let historyLoading = $state(false);
	let historyError = $state('');
	let historyRequest = 0;
	const label = (event: Event) => events.find((item) => item.value === event)?.label || event;
	const errorText = (cause: unknown) =>
		cause instanceof Error ? cause.message : 'Unable to complete the operation.';
	function newRule(): Rule {
		return {
			event: 'extraction_started',
			routine_ids: [],
			entity_id: null,
			currency: 'BRL',
			threshold: null,
			direction: 'below',
			percent: null
		};
	}
	async function load() {
		loading = true;
		message = '';
		try {
			items = await request<Webhook[]>(`/alerts/webhooks?limit=${limit}&offset=${offset}`);
		} catch (cause) {
			message = errorText(cause);
		} finally {
			loading = false;
		}
	}
	async function loadRoutines() {
		routinesReady = false;
		try {
			const result: Routine[] = [];
			let page: Routine[];
			do {
				page = await request<Routine[]>(`/routines?limit=100&offset=${result.length}`);
				result.push(...page);
			} while (page.length === 100);
			routines = result;
			routinesReady = true;
		} catch (cause) {
			message = errorText(cause);
		}
	}
	onMount(() => {
		void load();
		void loadRoutines();
	});
	function start(item?: Webhook) {
		editing = item?.public_id;
		name = item?.name || '';
		url = item?.url || '';
		enabled = item?.enabled ?? true;
		rules = item ? structuredClone($state.snapshot(item.rules)) : [newRule()];
		showForm = true;
		success = '';
		message = '';
	}
	async function save(event: SubmitEvent) {
		event.preventDefault();
		busy = true;
		message = '';
		success = '';
		try {
			const value = {
				name,
				url,
				enabled,
				rules: rules.map((rule) => ({
					...rule,
					entity_id: rule.event.startsWith('price_') ? rule.entity_id || null : null,
					threshold: rule.event === 'price_threshold' ? rule.threshold : null,
					direction: rule.event === 'price_threshold' ? rule.direction : 'below',
					percent: ['price_drop', 'price_increase'].includes(rule.event) ? rule.percent : null
				}))
			};
			await request(`/alerts/webhooks${editing ? `/${editing}` : ''}`, {
				method: editing ? 'PUT' : 'POST',
				body: JSON.stringify(value)
			});
			showForm = false;
			success = 'Webhook saved.';
			await load();
		} catch (cause) {
			message = errorText(cause);
		} finally {
			busy = false;
		}
	}
	async function toggle(item: Webhook) {
		busy = true;
		message = '';
		success = '';
		try {
			await request(`/alerts/webhooks/${item.public_id}`, {
				method: 'PUT',
				body: JSON.stringify({
					name: item.name,
					url: item.url,
					rules: item.rules,
					enabled: !item.enabled
				})
			});
			success = item.enabled ? 'Webhook paused. Pending deliveries canceled.' : 'Webhook enabled.';
			await load();
		} catch (cause) {
			message = errorText(cause);
		} finally {
			busy = false;
		}
	}
	async function remove() {
		if (!deleting) return;
		busy = true;
		message = '';
		success = '';
		try {
			await request(`/alerts/webhooks/${deleting.public_id}`, { method: 'DELETE' });
			if (history?.public_id === deleting.public_id) {
				history = undefined;
				historyRequest++;
			}
			if (editing === deleting.public_id) showForm = false;
			deleting = undefined;
			success = 'Webhook removed.';
			if (items.length === 1 && offset) offset -= limit;
			await load();
		} catch (cause) {
			message = errorText(cause);
		} finally {
			busy = false;
		}
	}
	async function loadHistory(item: Webhook, nextOffset = 0) {
		const current = ++historyRequest;
		history = item;
		historyOffset = nextOffset;
		historyLoading = true;
		historyError = '';
		deliveries = [];
		try {
			const result = await request<Delivery[]>(
				`/alerts/webhooks/${item.public_id}/deliveries?limit=${limit}&offset=${nextOffset}`
			);
			if (current === historyRequest) deliveries = result;
		} catch (cause) {
			if (current === historyRequest) historyError = errorText(cause);
		} finally {
			if (current === historyRequest) historyLoading = false;
		}
	}
	function scope(rule: Rule) {
		return rule.routine_ids.length
			? rule.routine_ids
					.map((id) => routines.find((r) => r.public_id === id)?.name || 'Routine removed')
					.join(', ')
			: 'All extractions, including manual runs';
	}
</script>

<svelte:head><title>Alerts · Panoptes</title></svelte:head>
<div class="page-header">
	<div>
		<span class="eyebrow">EVERY CHANGE, TO THE RIGHT DESTINATION</span>
		<h1>Alerts</h1>
		<p>Send extraction events and price changes to your webhooks.</p>
	</div>
	<Button onclick={() => start()} disabled={busy}><Icon name="plus" size={17} /> New webhook</Button
	>
</div>
<Notice
	{message}
	retry={async () => {
		await load();
		await loadRoutines();
	}}
/><Notice message={success} success />
<section class="panel models-panel" aria-label="Event templates">
	<div>
		<h2>Event templates</h2>
		<p>Download a sample JSON payload received by the webhook. The data is fictional.</p>
	</div>
	<div class="model-download">
		<Select
			id="webhook-model-event"
			label="Template event"
			bind:value={modelEvent}
			options={events}
		/>
		<a
			class="button button--secondary"
			href={`/webhook-models/${modelEvent}.json`}
			download={`panoptes-${modelEvent}.json`}>Download .json template</a
		>
	</div>
</section>
{#if showForm}
	<section class="panel form-panel">
		<h2>{editing ? 'Edit webhook' : 'New webhook'}</h2>
		<p>Each endpoint receives only the events and routines you choose.</p>
		<form onsubmit={save}>
			<fieldset disabled={busy} class="config-fields">
				<div class="form-grid">
					<Input
						id="webhook-name"
						label="Endpoint name"
						bind:value={name}
						required
						maxlength={200}
						placeholder="e.g. Price monitoring"
					/>
					<Input
						id="webhook-url"
						label="Webhook URL"
						type="url"
						bind:value={url}
						required
						placeholder="https://your-endpoint.com/events"
						hint="Receives POST requests with event data in JSON."
					/>
				</div>
				<label class="check"
					><input type="checkbox" bind:checked={enabled} /> Endpoint enabled</label
				>
				<div class="section-heading">
					<h3>Delivery rules</h3>
					<Button
						variant="secondary"
						onclick={() => rules.push(newRule())}
						disabled={rules.length >= 100}>Add rule</Button
					>
				</div>
				{#each rules as rule, index}
					<div class="rule">
						<div class="section-heading">
							<strong>Rule {index + 1}</strong><Button
								variant="ghost"
								onclick={() => rules.splice(index, 1)}
								disabled={rules.length === 1}>Remove rule {index + 1}</Button
							>
						</div>
						<Select
							id={`event-${index}`}
							label="When to send"
							bind:value={rule.event}
							options={events}
						/>
						<fieldset class="routine-scope">
							<legend>Routines for this rule</legend>
							<label class="check"
								><input
									type="checkbox"
									checked={rule.routine_ids.length === 0}
									onchange={() => {
										rule.routine_ids = rule.routine_ids.length
											? []
											: routines.slice(0, 1).map((r) => r.public_id);
									}}
									disabled={!routinesReady || !routines.length}
								/> All extractions, including manual runs</label
							>
							{#if !routinesReady}<p>
									Unable to load routines. <button
										type="button"
										class="text-action"
										onclick={loadRoutines}>Try again</button
									>
								</p>
							{:else if !routines.length}<p>
									No routines created. <a href="/routines">Create routine</a>
								</p>
							{:else}<div class="routine-list">
									{#each routines as routine}<label class="check"
											><input
												type="checkbox"
												checked={rule.routine_ids.includes(routine.public_id)}
												onchange={(event) => {
													rule.routine_ids = event.currentTarget.checked
														? [...rule.routine_ids, routine.public_id]
														: rule.routine_ids.filter((id) => id !== routine.public_id);
												}}
											/>
											{routine.name}</label
										>{/each}
								</div>{/if}
							<small
								>{scope(rule)}. With no routines selected, the rule applies to all extractions.</small
							>
						</fieldset>
						{#if rule.event.startsWith('price_')}
							<div class="form-grid">
								<Input
									id={`currency-${index}`}
									label="Currency"
									bind:value={rule.currency}
									required
									pattern={'[A-Z]{3}'}
									maxlength={3}
									hint="e.g. BRL. Only compares prices in the same currency."
								/>
								<Input
									id={`entity-${index}`}
									label="Product ID (optional)"
									bind:value={rule.entity_id}
									placeholder="Listing UUID"
									hint="Leave empty to track all products from the selected routines."
								/>
								{#if rule.event === 'price_threshold'}
									<Select
										id={`direction-${index}`}
										label="Price condition"
										bind:value={rule.direction}
										options={[
											{ value: 'below', label: 'At or below the threshold' },
											{ value: 'above', label: 'At or above the threshold' }
										]}
									/>
									<Input
										id={`threshold-${index}`}
										label="Price threshold"
										bind:value={rule.threshold}
										required
										inputmode="decimal"
										pattern={'[0-9]+([.][0-9]{1,4})?'}
										placeholder="2500.00"
										hint="Triggers when entering the range, including the first known price."
									/>
								{:else}
									<Input
										id={`percent-${index}`}
										label="Minimum change (%)"
										bind:value={rule.percent}
										required
										inputmode="decimal"
										pattern={'[0-9]+([.][0-9]{1,4})?'}
										placeholder="10"
										hint="Compared with the previous price of the same offer. e.g. 10 for 10%."
									/>
								{/if}
							</div>
						{:else if rule.event === 'extraction_finished'}<p>
								Sends on completion, including runs with errors or partial results.
							</p>
						{:else if rule.event === 'extraction_error'}<p>
								Sends on failures, blocks, and partial results.
							</p>{/if}
					</div>
				{/each}
			</fieldset>
			{#if editing}<p>Saving changes cancels pending deliveries to this endpoint.</p>{/if}
			<div class="form-actions">
				<Button type="submit" disabled={busy || !routinesReady}
					>{busy ? 'Saving…' : 'Save webhook'}</Button
				><Button variant="secondary" disabled={busy} onclick={() => (showForm = false)}
					>Cancel</Button
				>
			</div>
		</form>
	</section>
{/if}
{#if deleting}<div class="confirm-row" role="alert">
		<p>Remove <strong>{deleting.name}</strong> and its delivery history?</p>
		<Button variant="danger" disabled={busy} onclick={remove}>Remove webhook</Button><Button
			variant="secondary"
			disabled={busy}
			onclick={() => (deleting = undefined)}>Cancel</Button
		>
	</div>{/if}
<section class="panel">
	<div class="section-heading">
		<div>
			<h2>Registered endpoints</h2>
			<p>Independent rules for each endpoint.</p>
		</div>
	</div>
	{#if loading}<div class="empty-state">Loading webhooks…</div>
	{:else if !items.length}<div class="empty-state">
			<Icon name="alerts" size={28} />
			<h3>{offset ? 'No endpoints on this page' : 'Your events can go further'}</h3>
			<p>Add a webhook and choose which extractions and price changes you want to receive.</p>
			{#if !offset}<Button onclick={() => start()}>Add your first webhook</Button>{/if}
		</div>
	{:else}<div class="webhooks">
			{#each items as item (item.public_id)}<article class="webhook">
					<div class="destination">
						<div>
							<h3>{item.name}</h3>
							<span class:paused={!item.enabled} class="state"
								>{item.enabled ? 'Active' : 'Paused'}</span
							>
						</div>
						<p class="url">{item.url}</p>
						<div class="rule-tags">
							{#each item.rules as rule}<span
									>{label(rule.event)}{#if rule.threshold}
										· {rule.direction === 'above' ? '≥' : '≤'}
										{rule.currency}
										{rule.threshold}{/if}{#if rule.percent}
										· {rule.percent}%{/if}<small>{scope(rule)}</small></span
								>{/each}
						</div>
					</div>
					<div class="actions">
						<Button variant="secondary" disabled={busy || showForm} onclick={() => toggle(item)}
							>{item.enabled ? 'Pause' : 'Enable'}</Button
						><Button variant="ghost" disabled={busy} onclick={() => start(item)}>Edit</Button
						><Button variant="ghost" onclick={() => loadHistory(item)}>Deliveries</Button><Button
							variant="ghost"
							disabled={busy}
							onclick={() => (deleting = item)}>Remove</Button
						>
					</div>
				</article>{/each}
		</div>{/if}
	<div class="pagination">
		<Button
			variant="secondary"
			disabled={!offset || loading}
			onclick={() => {
				offset -= limit;
				void load();
			}}>Previous</Button
		><span>Page {offset / limit + 1}</span><Button
			variant="secondary"
			disabled={items.length < limit || loading}
			onclick={() => {
				offset += limit;
				void load();
			}}>Next</Button
		>
	</div>
</section>
{#if history}<section class="panel history">
		<div class="section-heading">
			<div>
				<h2>Deliveries · {history.name}</h2>
				<p>
					Up to five attempts. The endpoint must ignore events with an ID it has already received.
				</p>
			</div>
			<Button
				variant="ghost"
				onclick={() => {
					history = undefined;
					historyRequest++;
				}}>Close</Button
			>
		</div>
		<Notice message={historyError} retry={() => history && loadHistory(history, historyOffset)} />
		{#if historyLoading}<div class="empty-state">
				Loading deliveries…
			</div>{:else if !deliveries.length}<div class="empty-state">
				No deliveries recorded on this page.
			</div>{:else}<div class="table-scroll">
				<table>
					<thead
						><tr
							><th>Event</th><th>State</th><th>Attempts</th><th>Response</th><th>Recorded at</th
							></tr
						></thead
					><tbody
						>{#each deliveries as delivery}<tr
								><td
									>{label(delivery.event)}<small class="delivery-id">{delivery.public_id}</small
									></td
								><td
									>{statuses[delivery.status]}{#if delivery.status === 'pending'}<small
											class="delivery-id">Next attempt: {date(delivery.next_attempt_at)}</small
										>{/if}</td
								><td>{delivery.attempts}</td><td
									>{delivery.http_status ??
										(delivery.last_error ? 'Endpoint unavailable or not allowed' : '—')}</td
								><td>{date(delivery.created_at)}</td></tr
							>{/each}</tbody
					>
				</table>
			</div>{/if}
		<div class="pagination">
			<Button
				variant="secondary"
				disabled={!historyOffset || historyLoading}
				onclick={() => history && loadHistory(history, historyOffset - limit)}>Previous</Button
			><Button
				variant="secondary"
				disabled={historyLoading}
				onclick={() => history && loadHistory(history, historyOffset)}>Refresh</Button
			><Button
				variant="secondary"
				disabled={deliveries.length < limit || historyLoading}
				onclick={() => history && loadHistory(history, historyOffset + limit)}>Next</Button
			>
		</div>
	</section>{/if}

<style>
	.models-panel {
		padding: 24px;
		margin-bottom: 24px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 24px;
		flex-wrap: wrap;
	}
	.models-panel p {
		margin-top: 6px;
		font-size: 14px;
	}
	.model-download {
		display: flex;
		align-items: flex-end;
		gap: 12px;
		flex-wrap: wrap;
	}
	.model-download :global(.field) {
		min-width: 220px;
	}
	@media (max-width: 600px) {
		.model-download {
			width: 100%;
		}
		.model-download :global(.field),
		.model-download a {
			width: 100%;
			min-width: 0;
		}
	}
	.page-header p,
	.panel p {
		color: var(--muted);
	}
	.form-panel,
	.history {
		margin-bottom: 24px;
	}
	.history {
		margin-top: 24px;
	}
	.config-fields {
		border: 0;
		padding: 0;
		margin: 0;
		min-width: 0;
	}
	.form-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 20px;
		margin: 20px 0;
	}
	.section-heading {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 16px;
		margin-bottom: 18px;
	}
	.section-heading h2,
	.section-heading h3 {
		margin: 0;
	}
	.section-heading p {
		margin-bottom: 0;
	}
	.panel > .section-heading {
		padding: 23px 24px;
		margin-bottom: 0;
	}
	.rule {
		border: 1px solid var(--border);
		border-radius: 12px;
		padding: 20px;
		margin: 16px 0;
	}
	.routine-scope {
		margin: 20px 0;
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 16px;
	}
	.routine-scope legend {
		padding: 0 8px;
		font-size: 13px;
		font-weight: 600;
	}
	.routine-scope small {
		color: var(--muted);
	}
	.routine-list {
		display: flex;
		flex-wrap: wrap;
		gap: 10px 24px;
		padding: 12px 0;
	}
	.check {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 13px;
		margin: 8px 0;
	}
	.check input {
		accent-color: var(--blue-700);
	}
	.form-actions,
	.actions,
	.pagination,
	.confirm-row {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
	}
	.confirm-row {
		margin-bottom: 20px;
		padding: 16px;
		border: 1px solid var(--border);
		border-radius: 12px;
	}
	.webhook {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 24px;
		padding: 24px;
		border-top: 1px solid var(--border);
	}
	.destination {
		min-width: 0;
	}
	.destination > div:first-child {
		display: flex;
		align-items: center;
		gap: 12px;
	}
	.destination h3 {
		margin: 0;
		font-size: 16px;
	}
	.url {
		overflow-wrap: anywhere;
		font-size: 13px;
	}
	.state {
		color: var(--blue-700);
		font-size: 11px;
		font-weight: 600;
	}
	.state.paused {
		color: var(--muted);
	}
	.rule-tags {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	.rule-tags > span {
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 8px 10px;
		font-size: 12px;
	}
	.rule-tags small,
	.delivery-id {
		display: block;
		color: var(--muted);
		font-size: 11px;
		margin-top: 5px;
		overflow-wrap: anywhere;
	}
	.actions {
		flex-shrink: 0;
	}
	.pagination {
		justify-content: flex-end;
		padding-top: 20px;
		font-size: 12px;
		color: var(--muted);
	}
	.empty-state {
		padding: 40px 20px;
		text-align: center;
	}
	.text-action {
		background: none;
		border: none;
		color: var(--blue-700);
		cursor: pointer;
	}
	.table-scroll {
		overflow-x: auto;
	}
	@media (max-width: 900px) {
		.webhook {
			flex-direction: column;
		}
	}
	@media (max-width: 600px) {
		.form-grid {
			grid-template-columns: 1fr;
		}
		.section-heading {
			align-items: flex-start;
			flex-wrap: wrap;
		}
		.rule {
			padding: 14px;
		}
	}
</style>

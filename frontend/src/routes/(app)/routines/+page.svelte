<script lang="ts">
	import { onMount } from 'svelte';
	import { request, date, type Routine, type Term, type Schedule, type Source } from '#lib/api.ts';
	import { groupRoutineTerms, termKey, toggleRoutineSite } from '#lib/routine-terms.ts';
	import Button from '#lib/components/Button.svelte';
	import Input from '#lib/components/Input.svelte';
	import Select from '#lib/components/Select.svelte';
	import SourceSwitch from '#lib/components/SourceSwitch.svelte';
	import Status from '#lib/components/Status.svelte';
	import Notice from '#lib/components/Notice.svelte';
	import Icon from '#lib/components/Icon.svelte';
	let items = $state<Routine[]>([]);
	let terms = $state<Term[]>([]);
	let sources = $state<Source[]>([]);
	const termGroups = $derived(groupRoutineTerms(terms));
	let availableSites = $state<string[]>([]);
	let selectedSites = $state<string[]>([]);
	let loadingSources = $state(false);
	let sourcesError = $state('');
	let sourceRequest = 0;
	async function loadRoutineSources(id: string, selection?: string[]) {
		const current = ++sourceRequest;
		availableSites = [];
		selectedSites = [];
		sourcesError = '';
		loadingSources = true;
		try {
			const result = await request<{ site: string }[]>(`/search-terms/${id}/routine-sources`);
			if (current !== sourceRequest) return;
			availableSites = [...new Set(result.map((item) => item.site))];
			selectedSites = selection
				? availableSites.filter((site) => selection.includes(site))
				: [...availableSites];
		} catch (cause) {
			if (current === sourceRequest)
				sourcesError = cause instanceof Error ? cause.message : 'Unable to load marketplaces.';
		} finally {
			if (current === sourceRequest) loadingSources = false;
		}
	}
	function toggleSource(site: string, checked: boolean) {
		if (!availableSites.includes(site) || busy || loadingSources) return;
		selectedSites = toggleRoutineSite(selectedSites, availableSites, site, checked);
	}
	function selectedTermKey() {
		return termKey(terms.find((term) => term.public_id === termId)?.term || '');
	}
	function selectTerm(key: string) {
		termId = termGroups.find((group) => group.value === key)?.terms[0]?.public_id || '';
		if (termId) void loadRoutineSources(termId);
	}
	let loading = $state(true);
	let message = $state('');
	let success = $state('');
	let offset = $state(0);
	const limit = 20;
	let busy = $state(false);
	let activeAction = $state('');
	let showForm = $state(false);
	let editing = $state<string>();
	let deleting = $state<Routine>();
	let name = $state('');
	let termId = $state('');
	let mode = $state('discover');
	let kind = $state('interval');
	let interval = $state<number | undefined>(1440);
	let times = $state('08:00');
	let daily = $state<number | undefined>(3);
	let timezone = $state('America/Sao_Paulo');
	let enabled = $state(true);
	async function load() {
		loading = true;
		message = '';
		try {
			items = await request<Routine[]>(`/routines?limit=${limit}&offset=${offset}`);
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Unable to load routines.';
		} finally {
			loading = false;
		}
	}
	async function loadTerms() {
		try {
			let page: Term[];
			let index = 0;
			const result: Term[] = [];
			do {
				page = await request<Term[]>(`/search-terms?limit=100&offset=${index}`);
				result.push(...page);
				index += 100;
			} while (page.length === 100);
			terms = result;
			if (showForm && !termId && !editing && terms.length) selectTerm(termKey(terms[0].term));
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Unable to load terms.';
		}
	}
	onMount(() => {
		void load();
		void loadTerms();
		void request<Source[]>('/sources')
			.then((value) => {
				sources = value;
			})
			.catch(() => {
				message = 'Unable to load the marketplace list. Refresh the page to try again.';
			});
	});
	function start(item?: Routine) {
		editing = item?.public_id;
		name = item?.name || '';
		termId = item?.search_term_id || terms[0]?.public_id || '';
		if (termId)
			void loadRoutineSources(
				termId,
				item ? item.sites || (item.site ? [item.site] : []) : undefined
			);
		mode = item?.mode || 'discover';
		kind = item?.schedule.kind || 'interval';
		interval = item?.schedule.interval_minutes || 1440;
		times = item?.schedule.times?.join(', ') || '08:00';
		daily = item?.schedule.times_per_day || 3;
		timezone = item?.schedule.timezone || 'America/Sao_Paulo';
		enabled = item?.enabled ?? true;
		showForm = true;
		success = '';
		message = '';
	}
	function schedule(): Schedule {
		const fixedTimes = times.split(',').map((t) => t.trim());
		if (
			kind === 'fixed' &&
			(fixedTimes.some((t) => !/^([01]\d|2[0-3]):[0-5]\d$/.test(t)) ||
				new Set(fixedTimes).size !== fixedTimes.length)
		) {
			throw new Error('Enter unique times from 00:00 to 23:59, separated by commas.');
		}
		try {
			new Intl.DateTimeFormat('en-US', { timeZone: timezone });
		} catch {
			throw new Error('Enter a valid time zone, such as America/Sao_Paulo or UTC.');
		}
		return {
			kind: kind as Schedule['kind'],
			timezone,
			...(kind === 'fixed'
				? { times: fixedTimes }
				: kind === 'interval'
					? { interval_minutes: Number(interval) }
					: { times_per_day: Number(daily) })
		};
	}
	async function save(event: SubmitEvent) {
		event.preventDefault();
		if (loadingSources || !selectedSites.length) {
			message = 'Select at least one marketplace from the first extraction.';
			return;
		}
		busy = true;
		message = '';
		success = '';
		try {
			await request(editing ? `/routines/${editing}` : '/routines', {
				method: editing ? 'PUT' : 'POST',
				body: JSON.stringify({
					name: name.trim(),
					schedule: schedule(),
					enabled,
					sites: selectedSites,
					...(!editing ? { search_term_id: termId, mode } : {})
				})
			});
			showForm = false;
			success = editing ? 'Routine updated.' : 'Routine created.';
			offset = 0;
			await load();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Unable to save.';
		} finally {
			busy = false;
		}
	}
	async function toggle(item: Routine) {
		activeAction = item.public_id;
		message = '';
		success = '';
		try {
			await request(`/routines/${item.public_id}`, {
				method: 'PUT',
				body: JSON.stringify({ name: item.name, schedule: item.schedule, enabled: !item.enabled })
			});
			success = item.enabled ? 'Routine paused.' : 'Routine enabled.';
			await load();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Unable to update.';
		} finally {
			activeAction = '';
		}
	}
	async function remove() {
		if (!deleting) return;
		activeAction = deleting.public_id;
		message = '';
		success = '';
		try {
			await request(`/routines/${deleting.public_id}`, { method: 'DELETE' });
			deleting = undefined;
			success = 'Routine removed.';
			if (items.length === 1 && offset) offset -= limit;
			await load();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Unable to remove.';
		} finally {
			activeAction = '';
		}
	}
	function description(item: Routine) {
		const s = item.schedule;
		return s.kind === 'fixed'
			? s.times?.join(' · ')
			: s.kind === 'interval'
				? `Every ${s.interval_minutes} min`
				: `${s.times_per_day} times per day`;
	}
</script>

<svelte:head><title>Routines · Panoptes</title></svelte:head>
<div class="page-header">
	<div>
		<span class="eyebrow">CONSISTENCY IN EVERY OBSERVATION</span>
		<h1>Routines</h1>
	</div>
	<Button onclick={() => start()}><Icon name="plus" size={17} /> New routine</Button>
</div>
<Notice {message} retry={load} /><Notice message={success} success />
{#if showForm}<section class="panel form-panel">
		<h2>{editing ? 'Edit routine' : 'New routine'}</h2>
		<p>Set up a schedule to discover or update products for a search term.</p>
		{#if !terms.length && !editing}<div class="notice">
				Add a term on the extractions page to create your first routine. <a
					class="button button--secondary"
					href="/extractions?new=1">Add term</a
				>
			</div>{/if}
		<form onsubmit={save}>
			<div class="form-grid">
				<Input
					id="routine-name"
					label="Routine name"
					bind:value={name}
					required
					maxlength={200}
					placeholder="e.g. Track technology books"
				/><Select
					id="routine-term"
					label="Search term"
					bind:value={selectedTermKey, selectTerm}
					disabled={!!editing}
					required
					options={termGroups}
				/><Select
					id="routine-mode"
					label="Extraction type"
					bind:value={mode}
					disabled={!!editing}
					options={[
						{ value: 'discover', label: 'Discover products' },
						{ value: 'refresh', label: 'Update previously found products' }
					]}
				/><Select
					id="routine-kind"
					label="Frequency"
					bind:value={kind}
					options={[
						{ value: 'interval', label: 'Regular interval' },
						{ value: 'fixed', label: 'Fixed times' },
						{ value: 'random_daily', label: 'Spread throughout the day' }
					]}
				/>
				{#if kind === 'interval'}<Input
						id="routine-interval"
						label="Interval in minutes"
						type="number"
						min={1}
						max={525600}
						bind:value={interval}
						required
					/>{:else if kind === 'fixed'}<Input
						id="routine-times"
						label="Times"
						bind:value={times}
						required
						hint="Use times from 00:00 to 23:59, separated by commas. e.g. 08:00, 18:30"
					/>{:else}<Input
						id="routine-daily"
						label="Runs per day"
						type="number"
						min={1}
						max={1440}
						bind:value={daily}
						required
					/>{/if}<Input
					id="routine-timezone"
					label="Time zone"
					bind:value={timezone}
					required
					hint="IANA identifier, such as America/Sao_Paulo or UTC."
				/>
			</div>
			<fieldset class="routine-sources">
				<legend>Routine marketplaces</legend>
				<p>Available based on the term's first extraction. Keep at least one enabled.</p>
				{#if loadingSources}<p role="status">Loading marketplaces…</p>{/if}
				<div class="source-switches">
					{#each sources as source (source.id)}
						<SourceSwitch
							id={`routine-source-${source.id}`}
							label={source.name}
							checked={selectedSites.includes(source.id)}
							disabled={busy ||
								loadingSources ||
								!availableSites.includes(source.id) ||
								(selectedSites.includes(source.id) && selectedSites.length === 1)}
							onchange={(checked) => toggleSource(source.id, checked)}
						/>
					{/each}
				</div>
				{#if sourcesError}
					<p role="alert">Unable to retrieve the first extraction: {sourcesError}</p>
					<Button
						type="button"
						variant="secondary"
						onclick={() =>
							loadRoutineSources(
								termId,
								editing ? items.find((item) => item.public_id === editing)?.sites : undefined
							)}>Try again</Button
					>
				{:else if !loadingSources && !availableSites.length}<small
						>Run the first extraction for this term before setting up the routine.</small
					>{/if}
			</fieldset>
			<div class="form-actions">
				<label class="checkbox"
					><input type="checkbox" bind:checked={enabled} /> Enable routine</label
				><Button
					variant="secondary"
					type="button"
					disabled={busy}
					onclick={() => (showForm = false)}>Cancel</Button
				><Button
					type="submit"
					{busy}
					disabled={loadingSources ||
						!sources.length ||
						!selectedSites.length ||
						!name.trim() ||
						(!editing && !termId)}>Save routine</Button
				>
			</div>
		</form>
	</section>{/if}
<section class="panel">
	<div class="panel-header">
		<div>
			<h2>Your schedules</h2>
			<p>Control the frequency and keep tracking up to date.</p>
		</div>
		<Button variant="ghost" onclick={load} disabled={loading}>Refresh</Button>
	</div>
	{#if deleting}<div class="confirm-row" role="alert">
			<span>Remove routine “{deleting.name}”?</span>
			<div>
				<Button variant="secondary" onclick={() => (deleting = undefined)} disabled={!!activeAction}
					>Cancel</Button
				><Button variant="danger" onclick={remove} busy={!!activeAction}>Remove</Button>
			</div>
		</div>{/if}
	{#if loading}<div class="loading-state">
			<span class="spinner"></span>Loading routines…
		</div>{:else if items.length}<div class="table-scroll">
			<table>
				<thead
					><tr
						><th>Routine</th><th>Frequency</th><th>Next run</th><th>Status</th><th>Actions</th></tr
					></thead
				><tbody
					>{#each items as item (item.public_id)}<tr
							><td
								><div class="table-title">{item.name}</div>
								<div class="table-subtitle">
									{terms.find((t) => t.public_id === item.search_term_id)?.term || 'Search term'} ·
									{item.mode === 'discover' ? 'Discovery' : 'Update'}
								</div></td
							><td
								>{description(item)}
								<div class="table-subtitle">{item.schedule.timezone}</div></td
							><td class="muted">{item.enabled ? date(item.next_run_at) : '—'}</td><td
								><Status status={item.enabled ? 'active' : 'paused'} /></td
							><td
								><div class="row-actions">
									<Button variant="ghost" onclick={() => start(item)} disabled={!!activeAction}
										>Edit</Button
									><Button
										variant="ghost"
										onclick={() => toggle(item)}
										busy={activeAction === item.public_id}
										disabled={!!activeAction}>{item.enabled ? 'Pause' : 'Enable'}</Button
									><Button
										variant="ghost"
										onclick={() => (deleting = item)}
										disabled={!!activeAction}>Remove</Button
									>
								</div></td
							></tr
						>{/each}</tbody
				>
			</table>
		</div>{:else}<div class="empty-state">
			<Icon name="routines" size={30} />
			<h3>Your next observation starts here</h3>
			<p>Create a routine to discover or update products automatically.</p>
			<Button onclick={() => start()}>Create your first routine</Button>
		</div>{/if}
	<div class="pagination">
		<span
			>{items.length ? `${offset + 1}–${offset + items.length}` : '0'} routines on this page</span
		>
		<div>
			<Button
				variant="secondary"
				disabled={!offset || loading}
				onclick={() => {
					offset -= limit;
					void load();
				}}>Previous</Button
			><Button
				variant="secondary"
				disabled={items.length < limit || loading}
				onclick={() => {
					offset += limit;
					void load();
				}}>Next</Button
			>
		</div>
	</div>
</section>

<style>
	.routine-sources {
		border: 1px solid var(--border);
		border-radius: 10px;
		padding: 16px;
		margin: 20px 0;
	}
	.routine-sources p {
		margin: 0 0 12px;
	}
	.source-switches {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
		gap: 12px;
	}
</style>

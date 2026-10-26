<script lang="ts">
	import { onMount } from 'svelte';
	import { request, type Analytics, type ExtractionPage } from '#lib/api.ts';
	import Stats from '#lib/components/Stats.svelte';
	import ActivityChart from '#lib/components/ActivityChart.svelte';
	import ExtractionTable from '#lib/components/ExtractionTable.svelte';
	import Notice from '#lib/components/Notice.svelte';
	import Icon from '#lib/components/Icon.svelte';
	let analytics = $state<Analytics>();
	let extractions = $state<ExtractionPage>();
	let loading = $state(true);
	let message = $state('');
	async function load() {
		loading = true;
		message = '';
		try {
			[analytics, extractions] = await Promise.all([
				request<Analytics>('/analytics'),
				request<ExtractionPage>('/scrape-requests?limit=5')
			]);
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Unable to load data.';
		} finally {
			loading = false;
		}
	}
	onMount(() => {
		void load();
	});
</script>

<svelte:head><title>Overview · Panoptes</title></svelte:head>
<div class="page-header">
	<div>
		<span class="eyebrow">YOUR OBSERVATION CENTER</span>
		<h1>A view of everything.</h1>
		<p>Track your data, routines, and next steps.</p>
	</div>
	<a class="button button--primary" href="/extractions?new=1"
		><Icon name="plus" size={17} /> New extraction</a
	>
</div>
<Notice {message} retry={load} />
{#if loading}<div class="panel loading-state">
		<span class="spinner"></span>Preparing your overview…
	</div>{:else if analytics && extractions}<Stats value={analytics} />
	<div class="dashboard-columns">
		<section class="panel">
			<div class="panel-header">
				<div>
					<h2>Extraction activity</h2>
					<p>Your operation over the last 7 days</p>
				</div>
				<a href="/analytics">Explore <Icon name="arrow" size={15} /></a>
			</div>
			<ActivityChart value={analytics} />
		</section>
		<section class="panel guide-panel">
			<span class="guide-icon"><Icon name="routines" size={23} /></span>
			<h2>Your watch,<br />always on.</h2>
			<p>Organize routines to track your products at the right times.</p>
			<a href="/routines">Manage routines <Icon name="arrow" size={16} /></a>
		</section>
	</div>
	<section class="panel">
		<div class="panel-header">
			<div>
				<h2>Recent extractions</h2>
				<p>The latest platform activity</p>
			</div>
			<a href="/extractions">View all <Icon name="arrow" size={15} /></a>
		</div>
		<ExtractionTable items={extractions.items} />
	</section>{/if}

<script lang="ts">
	import type { Analytics } from '#lib/api.ts';
	import Icon from './Icon.svelte';
	let { value }: { value: Analytics } = $props();
	let success = $derived(
		value.totals.requests
			? Math.round((value.totals.completed / value.totals.requests) * 100) + '%'
			: '—'
	);
</script>

<div class="stats-grid">
	<div class="stat-card">
		<div class="stat-card-top">Observed products <Icon name="search" size={18} /></div>
		<div class="stat-value">{value.totals.products.toLocaleString('en-US')}</div>
		<div class="stat-caption">Total in catalog</div>
	</div>
	<div class="stat-card">
		<div class="stat-card-top">Active routines <Icon name="routines" size={18} /></div>
		<div class="stat-value">{value.totals.active_routines}</div>
		<div class="stat-caption">Enabled schedules</div>
	</div>
	<div class="stat-card">
		<div class="stat-card-top">Extractions <Icon name="extractions" size={18} /></div>
		<div class="stat-value">{value.totals.requests.toLocaleString('en-US')}</div>
		<div class="stat-caption">Over the last {value.period_days} days</div>
	</div>
	<div class="stat-card">
		<div class="stat-card-top">Completion rate <Icon name="check" size={18} /></div>
		<div class="stat-value">{success}</div>
		<div class="stat-caption">{value.totals.in_progress} queued or running</div>
	</div>
</div>

<script lang="ts">
	import { onMount } from 'svelte';
	import { request, type Source } from '#lib/api.ts';
	import ScheduledExtractions from '#lib/components/ScheduledExtractions.svelte';
	import Notice from '#lib/components/Notice.svelte';
	let sources = $state<Source[]>([]);
	let message = $state('');
	async function loadSources() {
		message = '';
		try {
			sources = await request<Source[]>('/sources');
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Unable to load sources.';
		}
	}
	onMount(() => {
		void loadSources();
	});
</script>

<svelte:head><title>Scheduled · Extractions · Panoptes</title></svelte:head>
<div class="page-header">
	<div>
		<span class="eyebrow">UPCOMING OBSERVATIONS</span>
		<h1>Scheduled extractions</h1>
		<p>Track upcoming extractions and move their runs forward.</p>
	</div>
	<a class="button button--secondary" href="/routines">Manage routines</a>
</div>
<Notice {message} retry={loadSources} />
<ScheduledExtractions {sources} />

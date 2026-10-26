<script lang="ts">
	import { page } from '$app/state';
	import Brand from '#lib/components/Brand.svelte';
</script>

<svelte:head><title>{page.status} · Panoptes</title></svelte:head>
<main class="error-page">
	<Brand /><span class="eyebrow">{page.status}</span>
	<h1>{page.status === 404 ? 'This page does not exist.' : 'Unable to continue.'}</h1>
	<p>{page.error?.message || 'Try again in a few moments.'}</p>
	<a href="/" class="button button--primary">Back to home</a>
</main>

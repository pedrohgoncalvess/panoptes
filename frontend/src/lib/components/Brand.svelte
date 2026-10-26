<script lang="ts">
	let { compact = false }: { compact?: boolean } = $props();
</script>

<span class="brand"
	><svg viewBox="0 0 40 40" width="36" height="36" fill="none" aria-hidden="true"
		><path
			d="M4 22C9 11 31 11 36 22C31 33 9 33 4 22Z"
			stroke="currentColor"
			stroke-width="2"
		/><circle cx="20" cy="22" r="5" fill="currentColor" /><path
			d="M10 9V6M20 7V3M30 9V6"
			stroke="currentColor"
			stroke-width="2"
			stroke-linecap="round"
		/></svg
	>{#if !compact}<span>panoptes<span class="brand-dot">.</span></span>{/if}</span
>

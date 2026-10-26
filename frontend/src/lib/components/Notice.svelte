<script lang="ts">
	import Button from './Button.svelte';
	let {
		message,
		retry,
		success = false
	}: { message: string; retry?: () => void; success?: boolean } = $props();
</script>

{#if message}<div class:notice-success={success} class="notice" role={success ? 'status' : 'alert'}>
		<span>{message}</span>{#if retry}<Button variant="secondary" onclick={retry}>Try again</Button
			>{/if}
	</div>{/if}

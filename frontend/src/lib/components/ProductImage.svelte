<script lang="ts">
	import Icon from './Icon.svelte';
	let { src, title }: { src?: string; title: string } = $props();
	let failed = $derived(!src);
</script>

{#if src && /^https?:\/\//i.test(src) && !failed}<img
		class="product-photo"
		{src}
		alt={title}
		loading="lazy"
		referrerpolicy="no-referrer"
		onerror={() => (failed = true)}
	/>{:else}<div class="product-photo photo-placeholder">
		<Icon name="extractions" /><span>No image</span>
	</div>{/if}

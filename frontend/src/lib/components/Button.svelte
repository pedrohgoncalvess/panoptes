<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLButtonAttributes } from 'svelte/elements';
	let {
		children,
		variant = 'primary',
		busy = false,
		disabled = false,
		type = 'button',
		...rest
	}: HTMLButtonAttributes & {
		children: Snippet;
		variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
		busy?: boolean;
	} = $props();
</script>

<button
	{...rest}
	{type}
	class={`button button--${variant} ${rest.class || ''}`}
	disabled={disabled || busy}
	aria-busy={busy}
>
	{#if busy}<span class="spinner" aria-hidden="true"></span>{/if}{@render children()}
</button>

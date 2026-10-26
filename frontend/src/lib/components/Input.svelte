<script lang="ts">
	import type { HTMLInputAttributes } from 'svelte/elements';
	let {
		label,
		id,
		type = 'text',
		value = $bindable(),
		hint,
		...rest
	}: HTMLInputAttributes & { label: string; id: string; hint?: string } = $props();
</script>

<label class="field" for={id}
	><span>{label}</span><input
		{...rest}
		{id}
		{type}
		bind:value
		aria-describedby={hint ? `${id}-hint` : undefined}
	/>{#if hint}<small id={`${id}-hint`}>{hint}</small>{/if}</label
>

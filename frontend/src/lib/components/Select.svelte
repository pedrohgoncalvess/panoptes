<script lang="ts">
	import type { HTMLSelectAttributes } from 'svelte/elements';
	let {
		label,
		id,
		value = $bindable(''),
		options,
		...rest
	}: HTMLSelectAttributes & {
		label: string;
		id: string;
		options: { value: string; label: string }[];
	} = $props();
</script>

<label class="field" for={id}
	><span>{label}</span><select {...rest} {id} bind:value
		>{#each options as option (option.value)}<option value={option.value}>{option.label}</option
			>{/each}</select
	></label
>

<script lang="ts">
	let {
		id,
		label,
		checked,
		disabled = false,
		onchange
	}: {
		id: string;
		label: string;
		checked: boolean;
		disabled?: boolean;
		onchange: (checked: boolean) => void;
	} = $props();
</script>

<label class="source-switch" class:enabled={checked} for={id}>
	<span>{label}</span>
	<span class="control">
		<input
			{id}
			type="checkbox"
			{checked}
			{disabled}
			onchange={(event) => onchange(event.currentTarget.checked)}
		/>
		<span class="track" aria-hidden="true"><span class="thumb"></span></span>
		<span class="state">{checked ? 'On' : 'Off'}</span>
	</span>
</label>

<style>
	.source-switch {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 14px;
		border: 1px solid var(--border, #d4d4d8);
		border-radius: 10px;
		cursor: pointer;
		font-size: 0.9rem;
	}
	.control {
		display: flex;
		align-items: center;
		position: relative;
		gap: 8px;
	}
	input {
		position: absolute;
		width: 38px;
		height: 24px;
		opacity: 0;
		margin: 0;
		cursor: pointer;
	}
	.track {
		width: 38px;
		height: 22px;
		border-radius: 20px;
		background: #71717a;
		padding: 3px;
		box-sizing: border-box;
		pointer-events: none;
	}
	.thumb {
		display: block;
		width: 16px;
		height: 16px;
		border-radius: 50%;
		background: white;
		transition: transform 0.15s ease;
	}
	input:checked + .track {
		background: var(--accent, #2563eb);
	}
	input:checked + .track .thumb {
		transform: translateX(16px);
	}
	input:focus-visible + .track {
		outline: 2px solid var(--accent, #2563eb);
		outline-offset: 3px;
	}
	input:disabled ~ span {
		opacity: 0.6;
	}
	.state {
		min-width: 62px;
		font-size: 0.8rem;
	}
	@media (prefers-reduced-motion: reduce) {
		.thumb {
			transition: none;
		}
	}
</style>

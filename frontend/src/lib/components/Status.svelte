<script lang="ts">
	let { status }: { status: string } = $props();
	const labels: Record<string, string> = {
		completed: 'Completed',
		pending: 'Queued',
		running: 'Running',
		failed: 'Failed',
		blocked: 'Blocked',
		partial: 'Partial',
		active: 'Active',
		paused: 'Paused'
	};
</script>

<span class={`status status--${status}`}><span></span>{labels[status] || status}</span>

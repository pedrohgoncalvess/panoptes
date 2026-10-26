<script lang="ts">
	import type { Analytics } from '#lib/api.ts';
	let { value }: { value: Analytics } = $props();
	let max = $derived(Math.max(1, ...value.daily.map((day) => day.total)));
	const label = (value: string) => value.slice(8, 10) + '/' + value.slice(5, 7);
</script>

<div class="chart">
	<div class="chart-top">
		<div class="chart-total">{value.totals.requests}<small>extractions in this period</small></div>
		<div class="legend"><span><i></i>Completed</span><span><i></i>Other</span></div>
	</div>
	{#if value.totals.requests}
		<div
			class="bar-chart"
			role="img"
			aria-label={`Daily extractions over the last ${value.period_days} days. ${value.totals.completed} completed out of ${value.totals.requests}.`}
		>
			{#each value.daily as day (day.date)}<div
					class="bar-column"
					title={`${label(day.date)}: ${day.total} extractions, ${day.completed} completed, ${day.failed} failures`}
				>
					<div class="bar-stack" style:height={`${(day.total / max) * 95}%`}>
						<div
							class="bar-completed"
							style:height={`${day.total ? (day.completed / day.total) * 100 : 0}%`}
						></div>
					</div>
				</div>{/each}
		</div>
		<div class="bar-labels" aria-hidden="true">
			{#each value.daily as day, i (day.date)}<span
					>{value.daily.length <= 14 || i % 5 === 0 ? label(day.date) : ''}</span
				>{/each}
		</div>
		<details class="chart-data">
			<summary>View daily values</summary>
			<div class="table-scroll">
				<table>
					<thead><tr><th>Date</th><th>Total</th><th>Completed</th><th>Failures</th></tr></thead
					><tbody
						>{#each value.daily as day (day.date)}<tr
								><td>{label(day.date)}</td><td>{day.total}</td><td>{day.completed}</td><td
									>{day.failed}</td
								></tr
							>{/each}</tbody
					>
				</table>
			</div>
		</details>
	{:else}<div class="chart-empty">Your first extractions will appear here.</div>{/if}
</div>

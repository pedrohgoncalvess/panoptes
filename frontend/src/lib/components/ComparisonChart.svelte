<script lang="ts">
	export type Series = { label: string; values: (number | null)[] };
	let {
		title,
		labels,
		series,
		kind = 'line',
		format = (v: number) => v.toLocaleString('en-US', { maximumFractionDigits: 2 })
	}: {
		title: string;
		labels: string[];
		series: Series[];
		kind?: 'line' | 'bar';
		format?: (v: number) => string;
	} = $props();
	let hovered = $state<number | null>(null);
	const colors = ['#326fac', '#35745b', '#ab4646', '#98662e', '#7556a4'];
	const width = 760,
		height = 260,
		left = 86,
		right = 18,
		top = 18,
		bottom = 38;
	const max = $derived(
		Math.max(1, ...series.flatMap((s) => s.values.filter((v): v is number => v != null))) * 1.12
	);
	const hasData = $derived(series.some((s) => s.values.some((v) => v != null)));
	const plotWidth = width - left - right;
	const plotHeight = height - top - bottom;
	const x = (i: number) => left + ((i + 0.5) * plotWidth) / Math.max(1, labels.length);
	const y = (v: number) => top + plotHeight * (1 - v / max);
	function path(values: (number | null)[]) {
		let connected = false;
		return values
			.map((v, i) => {
				if (v == null) {
					connected = false;
					return '';
				}
				const p = `${connected ? 'L' : 'M'}${x(i)},${y(v)}`;
				connected = true;
				return p;
			})
			.join(' ');
	}
</script>

<div class="comparison-chart">
	{#if hasData}
		<div class="legend">
			{#each series as s, i (s.label)}<span
					><i style:background={colors[i % colors.length]}></i>{s.label}</span
				>{/each}
		</div>
		<div class="plot-scroll">
			<div class="plot-surface">
				<svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
					<title>{title}</title>
					{#each [0, 0.25, 0.5, 0.75, 1] as ratio (ratio)}
						<line
							x1={left}
							x2={width - right}
							y1={y(max * ratio)}
							y2={y(max * ratio)}
							stroke="var(--border)"
						/>
						<text x={left - 10} y={y(max * ratio) + 4} text-anchor="end">{format(max * ratio)}</text
						>
					{/each}
					{#if hovered != null}
						<rect
							x={left + (hovered * plotWidth) / labels.length}
							y={top}
							width={plotWidth / labels.length}
							height={plotHeight}
							fill="var(--blue-50)"
						/>
						<line
							x1={x(hovered)}
							x2={x(hovered)}
							y1={top}
							y2={height - bottom}
							stroke="var(--muted)"
							stroke-dasharray="4 4"
						/>
					{/if}
					{#each series as s, si (s.label)}
						{#if kind === 'line'}<path
								d={path(s.values)}
								fill="none"
								stroke={colors[si % colors.length]}
								stroke-width="2.5"
							/>{/if}
						{#each s.values as value, i (i)}
							{#if value != null}
								{#if kind === 'line'}<circle
										cx={x(i)}
										cy={y(value)}
										r={hovered === i ? 6 : 3.5}
										fill={colors[si % colors.length]}
										><title>{labels[i]} · {s.label}: {format(value)}</title></circle
									>
								{:else}<rect
										x={left +
											(i * plotWidth) / labels.length +
											((si + 0.15) * plotWidth) / labels.length / series.length}
										y={y(value)}
										width={Math.max(1, (plotWidth / labels.length / series.length) * 0.7)}
										height={Math.max(0, y(0) - y(value))}
										rx="2"
										fill={colors[si % colors.length]}
										><title>{labels[i]} · {s.label}: {format(value)}</title></rect
									>{/if}
							{/if}
						{/each}
					{/each}
					{#each labels as label, i (i)}{#if labels.length <= 8 || i % Math.ceil(labels.length / 8) === 0 || i === labels.length - 1}<text
								x={x(i)}
								y={height - 10}
								text-anchor="middle">{label}</text
							>{/if}{/each}
					{#each labels as label, i (i)}
						<rect
							class="hover-target"
							x={left + (i * plotWidth) / labels.length}
							y={top}
							width={plotWidth / labels.length}
							height={plotHeight}
							fill="transparent"
							role="button"
							tabindex="0"
							aria-label={`${label}: ${series.map((s) => `${s.label}: ${s.values[i] == null ? 'No data' : format(s.values[i]!)}`).join('; ')}`}
							onpointerenter={() => (hovered = i)}
							onpointerleave={() => (hovered = null)}
							onfocus={() => (hovered = i)}
							onblur={() => (hovered = null)}
						/>
					{/each}
				</svg>
				{#if hovered != null}
					<div
						class="chart-tooltip"
						role="tooltip"
						style:left={`${Math.min(72, Math.max(12, (x(hovered) / width) * 100))}%`}
					>
						<strong>{labels[hovered]}</strong>
						{#each series as s, i (s.label)}
							<div>
								<i style:background={colors[i % colors.length]}></i><span>{s.label}</span>
								<b>{s.values[hovered] == null ? 'No data' : format(s.values[hovered]!)}</b>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>
		<details class="chart-data">
			<summary>View chart data</summary>
			<div class="table-scroll">
				<table>
					<thead
						><tr
							><th>Reference</th>{#each series as s (s.label)}<th>{s.label}</th>{/each}</tr
						></thead
					><tbody
						>{#each labels as label, i (i)}<tr
								><td>{label}</td>{#each series as s (s.label)}<td
										>{s.values[i] == null ? '—' : format(s.values[i]!)}</td
									>{/each}</tr
							>{/each}</tbody
					>
				</table>
			</div>
		</details>
	{:else}<div class="chart-empty">No data for this comparison in the selected period.</div>{/if}
</div>

<style>
	.plot-surface {
		position: relative;
		min-width: 480px;
	}
	.hover-target {
		cursor: crosshair;
	}
	.hover-target:focus-visible {
		outline: 2px solid var(--blue-700);
		outline-offset: -2px;
	}
	.chart-tooltip {
		position: absolute;
		top: 4px;
		z-index: 1;
		pointer-events: none;
		max-width: 280px;
		padding: 12px;
		border: 1px solid var(--border);
		border-radius: 8px;
		background: var(--surface, #fff);
		color: var(--text, #172b3a);
		font-size: 12px;
		box-shadow: 0 4px 16px #0002;
		transform: translateX(-50%);
	}
	.chart-tooltip strong {
		display: block;
		margin-bottom: 8px;
	}
	.chart-tooltip div {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-top: 6px;
	}
	.chart-tooltip i {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
	}
	.chart-tooltip b {
		margin-left: auto;
		padding-left: 12px;
		white-space: nowrap;
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: 14px;
		font-size: 12px;
		color: var(--muted);
		margin-bottom: 12px;
	}
	.legend span {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.legend i {
		width: 9px;
		height: 9px;
		border-radius: 50%;
	}
	.plot-scroll {
		overflow-x: auto;
	}
	svg {
		width: 100%;
		min-width: 480px;
		display: block;
	}
	text {
		font-size: 11px;
		fill: var(--muted);
	}
	.chart-empty {
		padding: 60px 16px;
		text-align: center;
		color: var(--muted);
	}
</style>

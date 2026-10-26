<script lang="ts">
	import {
		detailFields,
		explainFailure,
		isCaptcha,
		stageTitle,
		supportFields,
		stackLocations,
		type ExtractionLog
	} from '#lib/log-presentation.ts';
	let { entry }: { entry: ExtractionLog } = $props();
	const fields = $derived(detailFields(entry.details));
	const explanation = $derived(explainFailure(entry.details));
	const stack = $derived(stackLocations(entry.details));
	const searchLink = $derived.by(() => {
		if (
			entry.site !== 'mercado_livre_br' ||
			(!isCaptcha(entry.details) && entry.details.cause !== 'verification_required')
		)
			return null;
		try {
			const url = new URL(String(entry.details.source_url || ''));
			return url.protocol === 'https:' &&
				url.hostname === 'lista.mercadolivre.com.br' &&
				!url.username &&
				!url.password
				? url.href
				: null;
		} catch {
			return null;
		}
	});
	const sources: Record<string, string> = {
		mercado_livre_br: 'Mercado Livre',
		amazon_br: 'Amazon Brazil',
		kabum_br: 'KaBuM!',
		pichau_br: 'Pichau',
		terabyte_br: 'TerabyteShop'
	};
	const levels: Record<string, string> = {
		INFO: 'Information',
		WARNING: 'Warning',
		ERROR: 'Error'
	};
</script>

<article
	class="log-entry"
	class:error={entry.level === 'ERROR'}
	class:warning={entry.level === 'WARNING'}
>
	<header>
		<span class="level">{levels[entry.level] || entry.level}</span><span
			>{sources[entry.site || ''] || 'Processing'}</span
		><time datetime={entry.created_at}
			>{new Date(entry.created_at).toLocaleString('en-US', { hour12: false })}</time
		>
	</header>
	<h2>{stageTitle(entry)}</h2>
	{#if entry.message !== stageTitle(entry)}<p class="description">{entry.message}</p>{/if}
	{#if explanation}<p class="explanation">{explanation}</p>{/if}
	{#if fields.length}<dl class="event-fields">
			{#each fields as field, index (index)}<div>
					<dt>{field.label}</dt>
					<dd>{field.value}</dd>
				</div>{/each}
		</dl>{/if}
	<footer>
		{#if searchLink}<a href={searchLink} target="_blank" rel="noopener noreferrer"
				>Open the search in my browser</a
			>{/if}
		{#if typeof entry.details.asset_id === 'string'}
			<a
				class="capture-download"
				href={'/api/assets/' + entry.details.asset_id + '/download'}
				data-sveltekit-reload>Download HTML</a
			>
		{/if}
		<a href={'/extraction/logs?request_id=' + entry.request_id} data-sveltekit-reload
			>View this extraction · {entry.request_id.slice(0, 8)}</a
		>
	</footer>
	<details class="support">
		<summary>Support information</summary>
		<dl>
			{#each supportFields(entry) as field (field.label)}<div>
					<dt>{field.label}</dt>
					<dd>{field.value}</dd>
				</div>{/each}
		</dl>
		{#if stack.length}<h3>Where the failure occurred</h3>
			<ol>
				{#each stack as location, index (index)}<li>{location}</li>{/each}
			</ol>{/if}
	</details>
</article>

<style>
	.log-entry {
		background: white;
		padding: 22px;
		border: 1px solid #dce3ed;
		border-left: 4px solid #4778bc;
		border-radius: 12px;
		min-width: 0;
	}
	.log-entry.error {
		border-left-color: #c82f43;
	}
	.log-entry.warning {
		border-left-color: #c8860b;
	}
	header {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 12px;
		font-size: 12px;
		color: #61748f;
	}
	.level {
		font-weight: 700;
		background: #eef4fc;
		color: #275b96;
		padding: 4px 9px;
		border-radius: 20px;
	}
	.error .level {
		color: #aa2434;
		background: #fff0f2;
	}
	.warning .level {
		color: #946509;
		background: #fff6df;
	}
	time {
		margin-left: auto;
	}
	h2 {
		font-size: 17px;
		margin: 14px 0 8px;
		line-height: 1.4;
	}
	.description {
		margin: 0;
		color: #61748f;
		font-size: 14px;
	}
	.explanation {
		background: #f3f6fa;
		border-radius: 8px;
		padding: 14px 16px;
		margin: 14px 0;
		font-size: 14px;
		line-height: 1.65;
	}
	.error .explanation {
		background: #fff4f5;
		color: #862635;
	}
	dl {
		margin: 14px 0 0;
	}
	.event-fields {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 16px 24px;
		border-top: 1px solid #edf1f6;
		padding-top: 16px;
	}
	dt {
		color: #61748f;
		font-size: 12px;
		margin-bottom: 5px;
	}
	dd {
		margin: 0;
		font-size: 14px;
		font-weight: 600;
		overflow-wrap: anywhere;
		line-height: 1.5;
	}
	footer {
		display: flex;
		flex-wrap: wrap;
		gap: 16px;
		margin-top: 18px;
		font-size: 13px;
	}
	.capture-download {
		font-weight: 700;
	}
	.support {
		margin-top: 16px;
		border-top: 1px solid #edf1f6;
		padding-top: 14px;
		font-size: 12px;
	}
	summary {
		cursor: pointer;
		color: #61748f;
	}
	.support dl {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 14px;
	}
	.support dd,
	li {
		font-size: 12px;
		font-weight: 400;
		overflow-wrap: anywhere;
	}
	h3 {
		font-size: 13px;
		margin: 18px 0 8px;
	}
	ol {
		padding-left: 22px;
		line-height: 1.8;
	}
	@media (max-width: 800px) {
		.event-fields {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
		time {
			width: 100%;
			margin-left: 0;
		}
	}
	@media (max-width: 480px) {
		.log-entry {
			padding: 18px;
		}
		.event-fields,
		.support dl {
			grid-template-columns: 1fr;
		}
	}
</style>

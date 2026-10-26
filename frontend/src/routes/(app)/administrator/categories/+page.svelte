<script lang="ts">
	import { onMount } from 'svelte';
	import { request, type Category } from '#lib/api.ts';
	import Input from '#lib/components/Input.svelte';
	import Button from '#lib/components/Button.svelte';
	import Notice from '#lib/components/Notice.svelte';
	let categories = $state<Category[]>([]);
	let slug = $state('');
	let name = $state('');
	let keywords = $state('');
	let fields = $state('');
	let editing = $state(false);
	let active = $state(true);
	let busy = $state(false);
	let message = $state('');
	let success = $state('');
	async function load() {
		try {
			categories = await request<Category[]>('/admin/categories');
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Unable to load categories.';
		}
	}
	onMount(() => {
		void load();
	});
	function edit(c?: Category) {
		slug = c?.slug || '';
		name = c?.name || '';
		keywords = c?.keywords.join(', ') || '';
		fields = c?.suggested_fields.join(', ') || '';
		active = c?.active ?? true;
		editing = Boolean(c);
	}
	const split = (s: string) =>
		s
			.split(',')
			.map((v) => v.trim())
			.filter(Boolean);
	async function save(event: SubmitEvent) {
		event.preventDefault();
		busy = true;
		message = success = '';
		try {
			await request(`/admin/categories/${slug}`, {
				method: 'PUT',
				body: JSON.stringify({
					slug,
					name: name.trim(),
					keywords: split(keywords),
					suggested_fields: split(fields),
					active
				})
			});
			success = 'Category saved. Existing searches retain their original criteria.';
			edit();
			await load();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Unable to save.';
		} finally {
			busy = false;
		}
	}
</script>

<svelte:head><title>Categories · Administrator · Panoptes</title></svelte:head>
<div class="page-header">
	<div>
		<span class="eyebrow">CATALOG CONFIGURATION</span>
		<h1>Categories</h1>
		<p>Manage categories and suggestions for new extractions.</p>
	</div>
</div>
<Notice {message} /><Notice message={success} success />
<section class="panel form-panel">
	<h2>{editing ? 'Edit category' : 'New category'}</h2>
	<form onsubmit={save}>
		<div class="form-grid">
			<Input
				id="category-slug"
				label="Identifier"
				bind:value={slug}
				readonly={editing}
				required
				pattern={'[a-z][a-z0-9_]{0,59}'}
				maxlength={60}
				placeholder="sports"
				hint="Lowercase letters, numbers, and underscores. Remains stable across searches."
			/>
			<Input
				id="category-name"
				label="Name"
				bind:value={name}
				required
				maxlength={100}
				placeholder="Sports"
			/>
			<Input
				id="category-keywords"
				label="Product recognition keywords"
				bind:value={keywords}
				placeholder="bicycle, ball, racket"
				hint="Separate with commas. Selection looks for these words in the title or the category provided by the site."
			/>
			<Input
				id="category-fields"
				label="Suggested attributes"
				bind:value={fields}
				placeholder="Material, Weight, Size"
				hint="Separate with commas. Users can also create their own attributes."
			/>
		</div>
		<label><input type="checkbox" bind:checked={active} /> Available for new searches</label>
		<div class="form-actions">
			<Button type="button" variant="secondary" onclick={() => edit()} disabled={busy}>Clear</Button
			><Button type="submit" {busy}>Save category</Button>
		</div>
	</form>
</section>
<section class="panel form-panel">
	<h2>Categories</h2>
	<p>
		Deactivate a category to remove it from the selector for new searches. Its history remains
		available.
	</p>
	{#each categories as c (c.slug)}<div class="category-item">
			<div>
				<strong>{c.name}</strong>
				<p>{c.slug} · {c.active ? 'Active' : 'Inactive'}</p>
				<small>{c.keywords.join(', ') || 'No recognition keywords'}</small>
			</div>
			<Button variant="secondary" onclick={() => edit(c)}>Edit</Button>
		</div>{/each}
</section>

<style>
	.category-item {
		display: flex;
		justify-content: space-between;
		gap: 16px;
		padding: 16px 0;
		border-bottom: 1px solid var(--border, #ddd);
	}
	.category-item p {
		margin: 4px 0;
	}
</style>

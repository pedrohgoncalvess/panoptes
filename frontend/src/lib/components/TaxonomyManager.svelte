<script lang="ts">
	import { onMount } from 'svelte';
	import { request } from '#lib/api.ts';
	import Button from './Button.svelte';
	import Input from './Input.svelte';
	import Select from './Select.svelte';
	import Notice from './Notice.svelte';

	type Taxon = {
		id: string;
		parent_id: string | null;
		name: string;
		description: string;
		active: boolean;
		products: number;
		parent_name?: string;
	};
	type Policy = { category_target: number; subcategory_target: number; allow_creation: boolean };
	type Product = {
		public_id: string;
		name: string;
		status: string | null;
		taxon_ids: string[];
		result?: {
			reason?: string;
			review_reason?: string;
			categories?: { name: string; subcategories: { name: string }[] }[];
		};
	};
	let nodes = $state<Taxon[]>([]);
	let policy = $state<Policy>({
		category_target: 20,
		subcategory_target: 200,
		allow_creation: true
	});
	let products = $state<Product[]>([]);
	let selectedProduct = $state<Product>();
	let selected = $state<string[]>([]);
	let editing = $state('');
	let name = $state('');
	let parent = $state('');
	let description = $state('');
	let active = $state(true);
	let query = $state('');
	let offset = $state(0);
	let busy = $state(false);
	let message = $state('');
	let success = $state('');
	const roots = $derived(nodes.filter((n) => !n.parent_id));
	const label = (n: Taxon) => (n.parent_name ? `${n.parent_name} › ${n.name}` : n.name);
	const status = (value: string | null) =>
		({
			pending: 'Waiting for agent',
			processing: 'Classifying',
			completed: 'Classified',
			needs_review: 'Needs review',
			failed: 'Failure',
			manual: 'Protected manual adjustment'
		})[value || ''] || 'Waiting for agent';

	async function loadTaxonomy() {
		const data = await request<{ nodes: Taxon[]; policy: Policy }>('/catalog/taxonomy');
		nodes = data.nodes;
		policy = data.policy;
	}
	async function loadProducts() {
		products = await request<Product[]>(
			`/admin/taxonomy/products?q=${encodeURIComponent(query)}&limit=50&offset=${offset}`
		);
	}
	async function action(work: () => Promise<void>) {
		busy = true;
		message = success = '';
		try {
			await work();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Unable to save.';
		} finally {
			busy = false;
		}
	}
	onMount(() => {
		void action(async () => {
			await Promise.all([loadTaxonomy(), loadProducts()]);
		});
	});
	function edit(node?: Taxon) {
		editing = node?.id || '';
		name = node?.name || '';
		parent = node?.parent_id || '';
		description = node?.description || '';
		active = node?.active ?? true;
	}
	async function saveNode(event: SubmitEvent) {
		event.preventDefault();
		await action(async () => {
			await request(`/admin/taxonomy${editing ? `/${editing}` : ''}`, {
				method: editing ? 'PUT' : 'POST',
				body: JSON.stringify({ name, parent_id: parent || null, description, active })
			});
			await loadTaxonomy();
			edit();
			success = 'Classification saved. Products remain linked by their identifier.';
		});
	}
	function choose(product: Product) {
		selectedProduct = product;
		selected = [...product.taxon_ids];
	}
	function toggle(node: Taxon, checked: boolean) {
		if (checked)
			selected = [...new Set([...selected, node.id, ...(node.parent_id ? [node.parent_id] : [])])];
		else
			selected = selected.filter(
				(id) => id !== node.id && nodes.find((n) => n.id === id)?.parent_id !== node.id
			);
	}
	async function saveAssignment() {
		if (!selectedProduct) return;
		const productId = selectedProduct.public_id;
		await action(async () => {
			await request(`/admin/taxonomy/products/${productId}`, {
				method: 'PUT',
				body: JSON.stringify({ taxon_ids: selected })
			});
			await loadProducts();
			const updated = products.find((p) => p.public_id === productId);
			if (updated) choose(updated);
			success = 'Assignments saved. The agent will not overwrite this manual adjustment.';
		});
	}
	async function reclassify() {
		if (!selectedProduct) return;
		const productId = selectedProduct.public_id;
		await action(async () => {
			await request(`/admin/taxonomy/products/${productId}/reclassify`, { method: 'POST' });
			await loadProducts();
			selectedProduct = products.find((p) => p.public_id === productId);
			success = 'Product resubmitted to the agent. Manual protection has been removed.';
		});
	}
</script>

<section class="panel taxonomy-manager">
	<h2>Product categories and subcategories</h2>
	<p>
		Automatic classification with multiple assignments. Manual adjustments are protected until you
		resubmit the product to the agent.
	</p>
	<Notice {message} /><Notice message={success} success />
	<form
		class="form-grid"
		onsubmit={(event) => {
			event.preventDefault();
			void action(async () => {
				await request('/admin/taxonomy/policy', { method: 'PUT', body: JSON.stringify(policy) });
				success = 'Growth targets saved.';
			});
		}}
	>
		<Input
			id="taxonomy-category-target"
			label="Category target"
			type="number"
			bind:value={policy.category_target}
			min={1}
			max={1000}
			required
		/>
		<Input
			id="taxonomy-subcategory-target"
			label="Subcategory target"
			type="number"
			bind:value={policy.subcategory_target}
			min={1}
			max={10000}
			required
		/>
		<label
			><input type="checkbox" bind:checked={policy.allow_creation} /> Allow the agent to create categories</label
		>
		<Button type="submit" disabled={busy}>Save targets</Button>
	</form>
	<p>
		<small
			>{roots.length} categories · {nodes.length - roots.length} subcategories. Once targets are reached,
			creation requires a justified exception; manual creation remains available.</small
		>
	</p>
	<div class="taxonomy-columns">
		<div>
			<h3>{editing ? 'Edit classification' : 'New classification'}</h3>
			<form onsubmit={saveNode}>
				<Input id="taxon-name" label="Name" bind:value={name} maxlength={100} required />
				<Select
					id="taxon-parent"
					label="Parent category"
					bind:value={parent}
					disabled={Boolean(editing)}
					options={[
						{ value: '', label: 'Top-level category (no parent)' },
						...roots.map((n) => ({ value: n.id, label: n.name }))
					]}
				/>
				<Input
					id="taxon-description"
					label="Description"
					bind:value={description}
					maxlength={1000}
				/>
				<label><input type="checkbox" bind:checked={active} /> Active</label>
				<div class="actions">
					<Button type="submit" disabled={busy}>Save classification</Button>
					<Button variant="secondary" onclick={() => edit()} disabled={busy}>Clear</Button>
				</div>
			</form>
			<div class="taxon-list">
				{#each roots as root (root.id)}
					<div class="taxon-row">
						<strong>{root.name}</strong><small
							>{root.products} products · {root.active ? 'Active' : 'Inactive'}</small
						>
						<Button variant="secondary" onclick={() => edit(root)} disabled={busy}>Edit</Button>
					</div>
					{#each nodes.filter((n) => n.parent_id === root.id) as child (child.id)}
						<div class="taxon-row child">
							<span>↳ {child.name}</span><small
								>{child.products} products · {child.active ? 'Active' : 'Inactive'}</small
							>
							<Button variant="secondary" onclick={() => edit(child)} disabled={busy}>Edit</Button>
						</div>
					{/each}
				{/each}
			</div>
		</div>
		<div>
			<h3>Adjust products</h3>
			<form
				class="actions"
				onsubmit={(event) => {
					event.preventDefault();
					offset = 0;
					void action(loadProducts);
				}}
			>
				<Input
					id="taxonomy-product-search"
					label="Search product"
					bind:value={query}
					maxlength={200}
				/>
				<Button type="submit" disabled={busy}>Search</Button>
			</form>
			<div class="product-list">
				{#each products as product (product.public_id)}
					<button
						class:selected={selectedProduct?.public_id === product.public_id}
						type="button"
						onclick={() => choose(product)}
						disabled={busy}
					>
						<strong>{product.name}</strong><small>{status(product.status)}</small>
					</button>
				{:else}<p>No normalized products found.</p>{/each}
			</div>
			<div class="actions">
				<Button
					variant="secondary"
					disabled={busy || offset === 0}
					onclick={() => {
						offset -= 50;
						void action(loadProducts);
					}}>Previous</Button
				>
				<Button
					variant="secondary"
					disabled={busy || products.length < 50}
					onclick={() => {
						offset += 50;
						void action(loadProducts);
					}}>Next</Button
				>
			</div>
			{#if selectedProduct}
				<h3>{selectedProduct.name}</h3>
				<p>{status(selectedProduct.status)}</p>
				{#if selectedProduct.status === 'needs_review' && selectedProduct.result?.categories?.length}
					<p>
						Agent suggestion: {selectedProduct.result.categories
							.map((category) =>
								[
									category.name,
									...category.subcategories.map((child) => `${category.name} › ${child.name}`)
								].join(', ')
							)
							.join('; ')}
					</p>
				{/if}
				{#if selectedProduct.result?.review_reason || selectedProduct.result?.reason}<p>
						{selectedProduct.result?.review_reason || selectedProduct.result?.reason}
					</p>{/if}
				<div class="assignment-list">
					{#each nodes.filter((n) => selected.includes(n.id) || (n.active && (!n.parent_id || nodes.find((p) => p.id === n.parent_id)?.active))) as node (node.id)}
						<label
							><input
								type="checkbox"
								checked={selected.includes(node.id)}
								onchange={(event) => toggle(node, event.currentTarget.checked)}
							/>{label(node)}{!node.active ||
							(node.parent_id && !nodes.find((p) => p.id === node.parent_id)?.active)
								? '(inactive; deselect to save)'
								: ''}</label
						>
					{/each}
				</div>
				<div class="actions">
					<Button onclick={saveAssignment} disabled={busy}>Save manual assignments</Button>
					<Button variant="secondary" onclick={reclassify} disabled={busy}>Resubmit to agent</Button
					>
				</div>
			{/if}
		</div>
	</div>
</section>

<style>
	.taxonomy-manager {
		padding: 24px;
		margin-top: 24px;
	}
	.taxonomy-columns {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 32px;
	}
	.actions {
		display: flex;
		gap: 8px;
		align-items: end;
		flex-wrap: wrap;
		margin: 12px 0;
	}
	.taxon-row {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
		padding: 10px 0;
		border-bottom: 1px solid var(--border, #ddd);
	}
	.taxon-row > :first-child {
		flex: 1;
	}
	.child {
		padding-left: 20px;
	}
	.taxon-list,
	.product-list,
	.assignment-list {
		max-height: 420px;
		overflow-y: auto;
		margin: 16px 0;
	}
	.product-list button {
		width: 100%;
		text-align: left;
		padding: 12px;
		color: inherit;
		background: transparent;
		border: 1px solid var(--border, #ddd);
		cursor: pointer;
	}
	.product-list button.selected {
		border-color: currentColor;
	}
	.product-list small {
		display: block;
		margin-top: 4px;
	}
	.assignment-list label {
		display: flex;
		gap: 8px;
		padding: 6px 0;
	}
	@media (max-width: 850px) {
		.taxonomy-columns {
			grid-template-columns: 1fr;
		}
	}
</style>

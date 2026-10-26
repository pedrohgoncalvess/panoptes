<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { request } from '#lib/api.ts';
	import Brand from '#lib/components/Brand.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import Button from '#lib/components/Button.svelte';
	import type { LayoutProps } from './$types';
	let { data, children }: LayoutProps = $props();
	let open = $state(false);
	let mobile = $state(false);
	let analyticsOpen = $state(page.url.pathname.startsWith('/analytics'));
	let administratorOpen = $state(page.url.pathname.startsWith('/administrator'));
	const administratorMenus = $derived([
		...(data.user.role === 'admin'
			? [
					{ href: '/administrator/categories', label: 'Categories' },
					{ href: '/administrator/taxonomy', label: 'Product classification' }
				]
			: []),
		{ href: '/administrator/mcp-keys', label: 'MCP keys' }
	]);
	let extractionsOpen = $state(
		page.url.pathname.startsWith('/extractions') || page.url.pathname === '/extraction/logs'
	);
	const extractionMenus = [
		{ href: '/extractions', label: 'Runs' },
		{ href: '/extractions/scheduled', label: 'Scheduled' },
		{ href: '/extraction/logs', label: 'Now' }
	];
	const analyticsMenus = [
		{ href: '/analytics/extractions', label: 'Extractions' },
		{ href: '/analytics/prices', label: 'Prices' },
		{ href: '/analytics/detail', label: 'Product details' }
	];
	onMount(() => {
		const query = window.matchMedia('(max-width: 800px)');
		const update = () => {
			mobile = query.matches;
			if (!mobile) open = false;
		};
		update();
		query.addEventListener('change', update);
		return () => query.removeEventListener('change', update);
	});
	let leaving = $state(false);
	let logoutError = $state('');
	const menus = $derived([
		{ href: '/dashboard', label: 'Overview', icon: 'dashboard' },
		{ href: '/analytics', label: 'Analytics', icon: 'analytics' },
		{ href: '/routines', label: 'Routines', icon: 'routines' },
		{ href: '/alerts', label: 'Alerts', icon: 'alerts' },
		{ href: '/connections', label: 'Connections', icon: 'connections' },
		{ href: '/extractions', label: 'Extractions', icon: 'extractions' },
		{ href: '/data', label: 'Data', icon: 'table' },
		{ href: '/administrator', label: 'Administrator', icon: 'shield' }
	]);
	async function logout() {
		leaving = true;
		logoutError = '';
		try {
			await request('/auth/logout', { method: 'POST' });
			await goto('/', { invalidateAll: true });
		} catch {
			logoutError = 'Unable to sign out. Try again.';
		} finally {
			leaving = false;
		}
	}
</script>

<svelte:window
	onkeydown={(event) => {
		if (event.key === 'Escape') open = false;
	}}
/>
<div class="app-shell">
	{#if open}<button
			class="sidebar-backdrop"
			aria-label="Close navigation"
			onclick={() => (open = false)}
		></button>{/if}
	<aside class:sidebar-open={open} class="sidebar" inert={mobile && !open}>
		<a href="/dashboard" class="brand-link" aria-label="Panoptes home"><Brand /></a>
		<div class="workspace">
			<span class="workspace-icon">P</span>
			<div><strong>Main workspace</strong><small>Data monitoring</small></div>
		</div>
		<div class="nav-label">PLATFORM</div>
		<nav aria-label="Main navigation">
			{#each menus as menu (menu.href)}{#if menu.href === '/analytics' || menu.href === '/extractions' || menu.href === '/administrator'}
					{@const analytics = menu.href === '/analytics'}
					{@const administrator = menu.href === '/administrator'}
					{@const expanded = analytics
						? analyticsOpen
						: administrator
							? administratorOpen
							: extractionsOpen}
					{@const submenus = analytics
						? analyticsMenus
						: administrator
							? administratorMenus
							: extractionMenus}
					{@const submenuId = `${menu.href.slice(1)}-submenu`}
					<button
						class="nav-dropdown"
						class:active={submenus.some((child) => child.href === page.url.pathname)}
						aria-expanded={expanded}
						aria-controls={submenuId}
						onclick={() => {
							if (analytics) analyticsOpen = !analyticsOpen;
							else if (administrator) administratorOpen = !administratorOpen;
							else extractionsOpen = !extractionsOpen;
						}}
					>
						<Icon name={menu.icon} /><span>{menu.label}</span>
						<span class="dropdown-chevron" class:expanded><Icon name="chevron" size={15} /></span>
					</button>
					{#if expanded}<div id={submenuId} class="nav-submenu">
							{#each submenus as child (child.href)}<a
									href={analytics && page.url.pathname.startsWith('/analytics')
										? child.href + page.url.search
										: child.href}
									class:active={page.url.pathname === child.href}
									aria-current={page.url.pathname === child.href ? 'page' : undefined}
									onclick={() => (open = false)}>{child.label}</a
								>{/each}
						</div>{/if}
				{:else}<a
						href={menu.href}
						class:active={page.url.pathname === menu.href}
						aria-current={page.url.pathname === menu.href ? 'page' : undefined}
						onclick={() => (open = false)}
						><Icon name={menu.icon} /><span>{menu.label}</span
						>{#if page.url.pathname === menu.href}<span class="nav-indicator"></span>{/if}</a
					>{/if}{/each}
		</nav>
		<div class="sidebar-bottom">
			<div class="user-row">
				<span class="avatar">{data.user.name.slice(0, 1).toUpperCase()}</span>
				<div><strong>{data.user.name}</strong><small>{data.user.email}</small></div>
				<button class="icon-button" onclick={logout} disabled={leaving} aria-label="Sign out"
					><Icon name="logout" size={18} /></button
				>
			</div>
			{#if logoutError}<p role="alert" class="logout-error">{logoutError}</p>{/if}
		</div>
	</aside>
	<div class="main-shell">
		<header class="topbar">
			<div>
				<Button
					variant="ghost"
					class="mobile-menu"
					onclick={() => (open = !open)}
					aria-label="Open navigation"
					aria-expanded={open}><Icon name="menu" /></Button
				><span class="topbar-label">Workspace</span><Icon name="chevron" size={13} /><strong
					>{[...analyticsMenus, ...extractionMenus, ...administratorMenus].find(
						(m) => m.href === page.url.pathname
					)?.label ||
						menus.find((m) => m.href === page.url.pathname)?.label ||
						'Platform'}</strong
				>
			</div>
		</header>
		<main class="page-content">{@render children()}</main>
		<footer class="app-footer">Panoptes <span>A watchful eye on your data.</span></footer>
	</div>
</div>

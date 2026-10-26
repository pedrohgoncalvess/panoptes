<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { request, date, ApiError } from '#lib/api.ts';
	import Button from '#lib/components/Button.svelte';
	type Connection = {
		site: string;
		name: string;
		status: string;
		interactive: boolean;
		saved_at?: string;
		connection_method?: string;
		requires_login?: boolean;
	};
	type Frame = {
		image?: string;
		authenticated?: boolean;
		session_saved?: boolean;
		access_verified?: boolean;
		status?: string;
		notice?: string;
	};
	let items = $state<Connection[]>([]);
	let selected = $state('');
	let image = $state('');
	let message = $state('');
	let importedSite = $state('');
	let notice = $state('');
	let busy = $state(false);
	let browserOpen = $state(false);
	let modal: HTMLDialogElement;
	let screen = $state<HTMLDivElement>();
	let frameBusy = false;
	let alive = true;
	let queue: Promise<void> = Promise.resolve();
	let pending = 0;
	let lastMove = 0;
	let lastDown = { time: 0, x: 0, y: 0, button: -1 };
	let clickCount = 1;
	const labels: Record<string, string> = {
		disconnected: 'Disconnected',
		connecting: 'Connecting',
		connected: 'Connected',
		reconnect_required: 'Reconnection required',
		verification_required: 'Verification required',
		rate_limited: 'Request limit reached',
		local_browser_unavailable: 'Local browser unavailable'
	};
	async function load() {
		try {
			items = await request<Connection[]>('/browser-connections');
		} catch (error) {
			message = (error as Error).message;
		}
	}
	function closeOverlay() {
		browserOpen = false;
		modal?.close();
		selected = '';
		image = '';
		notice = '';
	}
	async function frame() {
		if (!selected || !browserOpen || frameBusy || pending || busy) return;
		const site = selected;
		frameBusy = true;
		try {
			const value = await request<Frame>(`/browser-connections/${site}/frame`);
			if (!alive || selected !== site) return;
			if (value.status === 'connected' && (value.authenticated || value.session_saved)) {
				closeOverlay();
				message = value.authenticated ? 'Sign-in confirmed. Session saved.' : 'Session saved.';
				await load();
			} else if (value.image) {
				image = 'data:image/jpeg;base64,' + value.image;
				notice = value.notice || '';
			}
		} catch (error) {
			if (selected === site) {
				notice = (error as Error).message;
				if (error instanceof ApiError && error.status === 409) browserOpen = false;
				// Failed screenshots and navigation do not prove successful login.
				await load();
			}
		} finally {
			frameBusy = false;
		}
	}
	async function action(site: string, operation: string) {
		busy = true;
		message = '';
		notice = '';
		try {
			await queue;
			if (operation === 'connect') {
				browserOpen = false;
				selected = site;
				image = '';
				await tick();
				modal.showModal();
			}
			const result = await request<Connection>(
				`/browser-connections/${site}${operation === 'disconnect' ? '' : '/' + operation}`,
				{ method: operation === 'disconnect' ? 'DELETE' : 'POST' }
			);
			if (operation === 'save' && result.status !== 'connected')
				throw new Error('The session has not been saved yet. Try again.');
			if (operation === 'connect') browserOpen = true;
			if (operation !== 'connect') closeOverlay();
			if (operation === 'save') message = 'Session saved.';
			await load();
		} catch (error) {
			notice = message = (error as Error).message;
		} finally {
			busy = false;
			if (selected) {
				await frame();
				await tick();
				screen?.focus();
			}
		}
	}
	function input(value: Record<string, unknown>) {
		const site = selected;
		if (!site || !browserOpen || busy) return;
		pending++;
		queue = queue
			.then(async () => {
				if (!alive || selected !== site || !browserOpen) return;
				try {
					await request(`/browser-connections/${site}/input`, {
						method: 'POST',
						body: JSON.stringify(value)
					});
				} catch (error) {
					if (selected === site) {
						notice = (error as Error).message;
						if (error instanceof ApiError && error.status === 409) browserOpen = false;
					}
				}
			})
			.finally(() => {
				pending--;
			});
	}
	function coordinates(event: MouseEvent) {
		const bounds = screen!.getBoundingClientRect();
		return {
			x: Math.max(
				0,
				Math.min(1279, Math.floor(((event.clientX - bounds.left) * 1280) / bounds.width))
			),
			y: Math.max(
				0,
				Math.min(799, Math.floor(((event.clientY - bounds.top) * 800) / bounds.height))
			)
		};
	}
	function pointer(event: PointerEvent, action: string) {
		event.preventDefault();
		const position = coordinates(event);
		if (action === 'down') {
			clickCount =
				performance.now() - lastDown.time < 400 &&
				lastDown.button === event.button &&
				Math.abs(lastDown.x - position.x) < 5 &&
				Math.abs(lastDown.y - position.y) < 5
					? Math.min(3, clickCount + 1)
					: 1;
			lastDown = { time: performance.now(), ...position, button: event.button };
			screen!.focus();
			screen!.setPointerCapture(event.pointerId);
		}
		if (action === 'move') {
			if (performance.now() - lastMove < 60) return;
			lastMove = performance.now();
		}
		input({
			action,
			...position,
			click_count: clickCount,
			modifiers: [
				event.shiftKey && 'Shift',
				event.ctrlKey && 'Control',
				event.altKey && 'Alt',
				event.metaKey && 'Meta'
			].filter(Boolean),
			button: event.button === 2 ? 'right' : event.button === 1 ? 'middle' : 'left'
		});
	}
	function keyboard(event: KeyboardEvent) {
		if (event.isComposing || event.key === 'Dead' || event.key === 'Process') return;
		if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'v') return;
		event.preventDefault();
		if (['Shift', 'Control', 'Alt', 'Meta', 'CapsLock', 'Unidentified'].includes(event.key)) return;
		const modifiers = [
			event.shiftKey && 'Shift',
			event.ctrlKey && 'Control',
			event.altKey && 'Alt',
			event.metaKey && 'Meta'
		].filter(Boolean);
		if (
			event.key.length === 1 &&
			!event.ctrlKey &&
			!event.metaKey &&
			!event.altKey &&
			event.key.charCodeAt(0) > 126
		)
			input({ action: 'text', text: event.key });
		else input({ action: 'key', key: event.key === ' ' ? 'Space' : event.key, modifiers });
	}
	function paste(event: ClipboardEvent) {
		event.preventDefault();
		input({
			action: 'text',
			text: event.clipboardData?.getData('text/plain').slice(0, 4096) || ''
		});
	}
	function beforeInput(event: InputEvent) {
		event.preventDefault();
		if (!event.isComposing && event.data && event.inputType === 'insertText')
			input({ action: 'text', text: event.data });
	}
	function mirror(node: HTMLDivElement) {
		const wheel = (event: WheelEvent) => {
			event.preventDefault();
			const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 800 : 1;
			input({
				action: 'scroll',
				delta: Math.max(-1600, Math.min(1600, Math.round(event.deltaY * unit))),
				delta_x: Math.max(-1600, Math.min(1600, Math.round(event.deltaX * unit)))
			});
		};
		node.addEventListener('wheel', wheel, { passive: false });
		return {
			destroy() {
				node.removeEventListener('wheel', wheel);
			}
		};
	}
	onMount(() => {
		alive = true;
		importedSite = new URL(window.location.href).searchParams.get('imported') || '';
		void load().then(() => {
			const imported = items.find(
				(item) =>
					item.site === importedSite &&
					item.status === 'connected' &&
					['extension', 'local_extension'].includes(item.connection_method || '')
			);
			if (imported)
				message =
					imported.connection_method === 'local_extension'
						? `Collection for ${imported.name} enabled in your browser. Keep this browser and a Panoptes tab open.`
						: `Session for ${imported.name} sent through the extension and confirmed. Ready for collection.`;
		});
		const timer = setInterval(() => {
			if (selected) void frame();
			else void load();
		}, 700);
		return () => {
			alive = false;
			clearInterval(timer);
			modal?.close();
			image = '';
		};
	});
</script>

<svelte:head><title>Connections · Panoptes</title></svelte:head>
<div class="page-heading">
	<div>
		<h1>Connections</h1>
		<p>Connect your accounts to use browser sessions for collection.</p>
	</div>
</div>
<p>
	Connections are shared by this workspace's routines and managed by the administrator. Your
	password is not saved. In Docker mode, the session is encrypted on the server. In local mode, it
	stays in your browser.
</p>
{#if message}<p role="status">{message}</p>{/if}
<div class="connection-list">
	{#each items as item (item.site)}
		<section
			class="connection-card"
			class:imported-session={item.site === importedSite &&
				item.status === 'connected' &&
				['extension', 'local_extension'].includes(item.connection_method || '')}
		>
			<h2>{item.name}</h2>
			<p>{labels[item.status] || item.status}</p>
			{#if item.status === 'verification_required'}<p>
					{item.connection_method === 'local_extension'
						? 'Complete the challenge in the collection tab opened by the extension and run the extraction again. Your session stays in this browser.'
						: 'Open the failed search in your browser, complete the challenge, and enable “This browser” in the extension, or send the session again. Then run the extraction again.'}
				</p>{/if}
			{#if item.connection_method === 'local_extension'}
				<p class="session-method">Collection in your browser through the extension</p>
				<p>
					Keep the browser and an authenticated Panoptes tab open. Cookies, IndexedDB, and other
					account data stay in this profile.
				</p>
				{#if item.status === 'local_browser_unavailable'}<p>
						Open the extension on a page from the site and enable collection in this browser again.
					</p>{/if}
			{:else}<p>
					To use the browser where you are already signed in, choose “This browser” in the Panoptes
					extension.
				</p>{/if}
			{#if item.connection_method === 'extension' && item.status === 'connected'}<p
					class="session-method"
				>
					Session imported through the extension
				</p>{/if}
			<small
				>{item.connection_method === 'local_extension'
					? 'Connection enabled at'
					: 'Session saved at'}: {date(item.saved_at)}</small
			>
			<div class="connection-actions">
				<Button disabled={busy || !!selected} onclick={() => action(item.site, 'connect')}
					>{item.connection_method === 'local_extension'
						? 'Use Docker browser'
						: item.status === 'disconnected'
							? 'Connect'
							: 'Open browser'}</Button
				>
				{#if item.status !== 'disconnected'}<Button
						variant="danger"
						disabled={busy || !!selected}
						onclick={() => action(item.site, 'disconnect')}>Disconnect</Button
					>{/if}
			</div>
		</section>
	{/each}
</div>
<dialog
	bind:this={modal}
	class="browser-overlay"
	aria-labelledby="browser-title"
	oncancel={(event) => event.preventDefault()}
>
	<header class="browser-toolbar">
		<div>
			<h2 id="browser-title">
				{items.find((item) => item.site === selected)?.name || 'Browser'}
			</h2>
			<p>
				{#if items.find((item) => item.site === selected)?.requires_login === false}
					Once sign-in is confirmed, the session will be saved and this window will close
					automatically. To use access without signing in, complete verification and click Use this
					session.
				{:else}
					Click the page and use your keyboard and mouse. The window closes once sign-in is
					confirmed.
				{/if}
			</p>
		</div>
		<div class="connection-actions">
			{#if items.find((item) => item.site === selected)?.requires_login === false}
				<Button disabled={busy || !browserOpen} onclick={() => action(selected, 'save')}
					>Use this session</Button
				>
			{/if}
			{#if !browserOpen}<Button disabled={busy} onclick={() => action(selected, 'connect')}
					>Try again</Button
				>{/if}
			<Button
				disabled={busy || !browserOpen}
				variant="secondary"
				onclick={() => {
					input({ action: 'login' });
					screen?.focus();
				}}>Open sign-in</Button
			><Button
				disabled={busy || !browserOpen}
				variant="secondary"
				onclick={() => {
					input({ action: 'home' });
					screen?.focus();
				}}>Home page</Button
			><Button disabled={busy} variant="ghost" onclick={() => action(selected, 'cancel')}
				>Close</Button
			>
		</div>
	</header>
	{#if notice}<p role="alert" class="browser-notice">{notice}</p>{/if}
	{#if image && browserOpen}
		<div
			bind:this={screen}
			use:mirror
			class="browser-screen"
			role="textbox"
			aria-label="Mirrored browser: use keyboard and mouse"
			tabindex="0"
			contenteditable="true"
			spellcheck="false"
			onpointerdown={(event) => pointer(event, 'down')}
			onpointerup={(event) => pointer(event, 'up')}
			onpointermove={(event) => pointer(event, 'move')}
			onpointercancel={() => input({ action: 'release' })}
			oncontextmenu={(event) => event.preventDefault()}
			onkeydown={keyboard}
			onpaste={paste}
			onbeforeinput={beforeInput}
			onblur={() => input({ action: 'release' })}
			oncompositionend={(event) => {
				input({ action: 'text', text: event.data });
			}}
		>
			<img
				src={image}
				alt="Page from the connected site"
				draggable="false"
				contenteditable="false"
			/>
		</div>
	{:else}<div class="browser-loading" role="status">
			{busy
				? 'Opening browser…'
				: browserOpen
					? 'Loading browser…'
					: 'The connection is not open. Use “Try again”.'}
		</div>{/if}
</dialog>

<style>
	.imported-session {
		outline: 2px solid #23835b;
		outline-offset: 3px;
	}
	.session-method {
		color: #23835b;
		font-weight: 600;
	}
	.connection-list {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
		gap: 20px;
		margin: 24px 0;
	}
	.connection-card {
		border: 1px solid var(--border);
		border-radius: 12px;
		padding: 24px;
		background: var(--surface);
	}
	.connection-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		align-items: center;
		margin: 12px 0;
	}
	.browser-overlay {
		margin: auto;
		padding: 0;
		border: 1px solid var(--border);
		border-radius: 12px;
		width: min(1320px, 96vw);
		max-width: 96vw;
		max-height: 94dvh;
		overflow: auto;
		background: var(--surface);
		color: var(--ink);
	}
	.browser-overlay::backdrop {
		background: rgb(10 20 32 / 75%);
	}
	.browser-toolbar {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		gap: 12px;
		padding: 16px 20px;
		border-bottom: 1px solid var(--border);
	}
	.browser-toolbar h2 {
		margin: 0;
		font-size: 20px;
	}
	.browser-toolbar p {
		font-size: 14px;
		color: var(--muted);
		margin: 4px 0;
	}
	.browser-screen {
		display: block;
		line-height: 0;
		background: #fff;
		cursor: default;
		outline-offset: -3px;
		touch-action: none;
		caret-color: transparent;
	}
	.browser-screen:focus {
		outline: 2px solid var(--blue-600);
	}
	.browser-screen img {
		width: 100%;
		display: block;
		user-select: none;
	}
	.browser-notice {
		padding: 12px 20px;
		color: var(--danger);
		background: #fff5f3;
		margin: 0;
	}
	.browser-loading {
		display: grid;
		place-items: center;
		min-height: 300px;
	}
	small {
		color: var(--muted);
	}
</style>

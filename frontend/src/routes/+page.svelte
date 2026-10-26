<script lang="ts">
	import { goto } from '$app/navigation';
	import { request } from '#lib/api.ts';
	import Brand from '#lib/components/Brand.svelte';
	import Button from '#lib/components/Button.svelte';
	import Input from '#lib/components/Input.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import Notice from '#lib/components/Notice.svelte';
	import type { PageProps } from './$types';
	let { form }: PageProps = $props();
	let email = $state('');
	let password = $state('');
	let busy = $state(false);
	let message = $state('');
	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (busy) return;
		busy = true;
		message = '';
		try {
			await request('/auth/login', {
				method: 'POST',
				body: JSON.stringify({ email: email.trim(), password })
			});
			await goto('/dashboard', { invalidateAll: true });
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Unable to sign in.';
		} finally {
			busy = false;
		}
	}
</script>

<svelte:head
	><title>Sign in · Panoptes</title><meta
		name="description"
		content="Sign in to Panoptes to track your extractions and routines."
	/></svelte:head
>
<main class="login-layout">
	<section class="login-form" aria-label="Sign in to Panoptes">
		<a class="login-brand" href="/" aria-label="Panoptes"><Brand /></a>
		<div class="login-inner">
			<h1>Sign in</h1>
			<form method="POST" onsubmit={submit}>
				<Input
					id="email"
					name="email"
					label="Email"
					type="email"
					autocomplete="username"
					autocapitalize="none"
					spellcheck={false}
					placeholder="you@company.com"
					bind:value={email}
					required
				/>
				<Input
					id="password"
					name="password"
					label="Password"
					type="password"
					autocomplete="current-password"
					placeholder="Your password"
					bind:value={password}
					required
				/>
				<Notice message={message || form?.message || ''} />
				<Button type="submit" {busy}>Sign in <Icon name="arrow" size={20} /></Button>
			</form>
		</div>
	</section>
	<section class="login-story" aria-label="A broader view">
		<div class="orbital" aria-hidden="true">
			<div class="orbit orbit-one"></div>
			<div class="orbit orbit-two"></div>
			<div class="orbit orbit-three"></div>
			<svg viewBox="0 0 400 300"
				><path d="M40 155Q200 -20 360 155Q200 330 40 155Z" /><circle
					cx="200"
					cy="155"
					r="55"
				/><circle cx="200" cy="155" r="15" /></svg
			>
		</div>
		<h2>A broader view.</h2>
	</section>
</main>

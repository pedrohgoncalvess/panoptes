<script lang="ts">
	let { name, size = 20 }: { name: string; size?: number } = $props();
	const paths: Record<string, string> = {
		table: 'M3 3h18v18H3z M3 9h18 M3 15h18 M9 3v18',
		dashboard: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
		analytics: 'M4 20V10 M12 20V4 M20 20v-7',
		routines: 'M20 7a9 9 0 1 0 1 8 M20 3v5h-5 M12 7v5l3 2',
		connections:
			'M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2 M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2',
		extractions: 'M12 3v12 m-5-5 5 5 5-5 M4 16v5h16v-5',
		alerts: 'M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9 M10 21h4',
		arrow: 'M5 12h14 m-5-5 5 5-5 5',
		play: 'm8 5 11 7-11 7z',
		plus: 'M12 5v14 M5 12h14',
		logout: 'M9 3H4v18h5 M9 12h12 m-5-5 5 5-5 5',
		chevron: 'm9 5 7 7-7 7',
		menu: 'M4 6h16 M4 12h16 M4 18h16',
		check: 'm5 12 4 4 10-10',
		close: 'm6 6 12 12 M18 6 6 18',
		search: 'M21 21l-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
		shield: 'M12 3 3 7v5c0 5 9 9 9 9s9-4 9-9V7z m-5 9 3 3 6-6'
	};
</script>

<svg
	width={size}
	height={size}
	viewBox="0 0 24 24"
	fill="none"
	stroke="currentColor"
	stroke-width="1.65"
	stroke-linecap="round"
	stroke-linejoin="round"
	aria-hidden="true"><path d={paths[name] || paths.dashboard} /></svg
>

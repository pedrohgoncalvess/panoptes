import type { Term } from './api.ts';

export function toggleRoutineSite(
	selected: string[],
	available: string[],
	site: string,
	checked: boolean
): string[] {
	if (!available.includes(site)) return selected;
	if (checked) return selected.includes(site) ? selected : [...selected, site];
	return selected.length > 1 ? selected.filter((value) => value !== site) : selected;
}

export function termKey(term: string): string {
	return term.normalize('NFKC').trim().replace(/\s+/gu, ' ').toLocaleLowerCase('pt-BR');
}

export function groupRoutineTerms(terms: Term[]) {
	const groups = new Map<string, { value: string; label: string; terms: Term[] }>();
	for (const term of terms) {
		const key = termKey(term.term);
		let group = groups.get(key);
		if (!group) {
			group = { value: key, label: term.term.trim(), terms: [] };
			groups.set(key, group);
		}
		if (!group.terms.some((item) => item.public_id === term.public_id)) group.terms.push(term);
	}
	return [...groups.values()];
}

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { groupRoutineTerms, toggleRoutineSite } from '../src/lib/routine-terms.ts';

test('keeps the sole marketplace on and refuses unavailable marketplaces', () => {
	assert.deepEqual(toggleRoutineSite(['terabyte'], ['terabyte'], 'terabyte', false), ['terabyte']);
	assert.deepEqual(toggleRoutineSite(['terabyte'], ['terabyte'], 'amazon', true), ['terabyte']);
});

test('allows multiple marketplaces to be toggled but always keeps one selected', () => {
	const available = ['terabyte', 'amazon'];
	let selected = toggleRoutineSite(['terabyte'], available, 'amazon', true);
	assert.deepEqual(selected, available);
	selected = toggleRoutineSite(selected, available, 'terabyte', false);
	assert.deepEqual(selected, ['amazon']);
	assert.deepEqual(toggleRoutineSite(selected, available, 'amazon', false), ['amazon']);
	assert.deepEqual(toggleRoutineSite(selected, available, 'amazon', true), ['amazon']);
});

test('shows one term across marketplaces while preserving every configuration ID', () => {
	const terms = [
		{ public_id: 'amazon', term: 'Câmera digital', site: 'amazon' },
		{ public_id: 'ml', term: '  CÂMERA   digital ', site: 'mercado_livre' },
		{
			public_id: 'profile',
			term: 'Câmera digital',
			site: 'amazon',
			criteria: { description: 'Outro perfil' }
		},
		{ public_id: 'other', term: 'Notebook', site: 'amazon' }
	];
	const groups = groupRoutineTerms([...terms, terms[0]]);
	assert.deepEqual(
		groups.map(({ label }) => label),
		['Câmera digital', 'Notebook']
	);
	assert.deepEqual(
		groups[0].terms.map(({ public_id }) => public_id),
		['amazon', 'ml', 'profile']
	);
	assert.deepEqual(groups[1].terms, [terms[3]]);
});

test('handles an empty list and equivalent Unicode spellings', () => {
	assert.deepEqual(groupRoutineTerms([]), []);
	assert.equal(
		groupRoutineTerms([
			{ public_id: 'a', term: 'Câmera' },
			{ public_id: 'b', term: 'Ca\u0302mera' }
		]).length,
		1
	);
});

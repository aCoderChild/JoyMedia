import { referenceLabel } from '../src/utils/rioPresentation.js';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { assetCategory, assetDisplayName, groupAssets } from '../src/utils/assetPresentation.js';

test('groups references by their semantic role rather than raw file type', () => {
	const groups = groupAssets([
		{ asset_name: 'Room', reference_role: 'Environment', asset_category: 'Background' },
		{ asset_name: 'Pack', reference_role: 'Product', asset_category: 'Other' },
		{ asset_name: 'Actor', reference_role: 'Person', asset_category: 'Character' },
	]);
	assert.deepEqual(groups.map(group => group.category), ['Product', 'Character', 'Environment']);
	assert.equal(assetCategory({ asset_category: 'Background' }), 'Environment');
});

test('uses descriptive generated pose names instead of technical reference identifiers', () => {
	const asset = {
		reference_role: 'Character', reference_key: 'pose_123456789abc',
		label: 'pose_123456789abc', asset_name: 'actor_front Standing with one hand raised beside the face. front',
	};
	assert.equal(assetDisplayName(asset), 'Standing with one hand raised beside the face');
});

test('keeps product views distinct and disambiguates repeated display names', () => {
	const groups = groupAssets([
		{ asset_name: 'Package', reference_role: 'Product', product_view: 'front_left' },
		{ asset_name: 'Package', reference_role: 'Product', product_view: 'front_right' },
		{ asset_name: 'Room', reference_role: 'Environment' },
		{ asset_name: 'Room', reference_role: 'Environment' },
	]);
	assert.deepEqual(groups[0].items.map(item => item.display_name), ['Package · Front Left', 'Package · Front Right']);
	assert.deepEqual(groups[1].items.map(item => item.display_name), ['Room (1)', 'Room (2)']);
});

test('scene reference lines never show technical media keys', () => {
	assert.equal(referenceLabel({ reference_key: 'product_cutout_266d190359', label: 'product_cutout_266d190359', reference_role: 'Product' }), 'product cutout');
	assert.equal(referenceLabel({ reference_key: 'mascot_front', label: 'mascot_front', reference_role: 'Character' }), 'mascot front');
	assert.equal(referenceLabel({ reference_key: 'room' }, [{ reference_key: 'room', display_name: 'Living room' }]), 'Living room');
});

test('derived references are told apart from the customer uploads', async () => {
	const { derivedReference } = await import('../src/utils/rioPresentation.js');
	assert.equal(derivedReference({ reference_key: 'mascot_front', label: 'mascot front' }), null);
	assert.equal(derivedReference({ reference_key: 'product' }), null);
	assert.equal(derivedReference({ reference_key: 'pose_c836448df484' }), 'generated');
	assert.equal(derivedReference({ reference_key: 'product_view_b005066f2c4a' }), 'generated');
	assert.equal(derivedReference({ reference_key: 'mascot_front', label: 'mascot seated (verified)' }), 'generated');
	assert.equal(derivedReference({ reference_key: 'mascot_sheet_view3' }), 'sheet');
});

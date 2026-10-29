const CATEGORY_ORDER = ['Product', 'Character', 'Environment', 'Brand', 'Style', 'Motion', 'Audio', 'Other'];

export function assetCategory(asset) {
	const role = String(asset?.reference_role || '').trim();
	const category = String(asset?.asset_category || '').trim();
	const value = role && role !== 'General' ? role : category;
	if (['Character', 'Person'].includes(value)) return 'Character';
	if (['Environment', 'Background'].includes(value)) return 'Environment';
	if (['Product', 'Brand', 'Style', 'Motion', 'Audio'].includes(value)) return value;
	if (value === 'Logo') return 'Brand';
	if (asset?.media_type === 'Audio') return 'Audio';
	return 'Other';
}

function compactName(value) {
	return String(value || '')
		.replace(/\.[a-z0-9]{2,5}$/i, '')
		// A generated media key ends in a hash, e.g. product_cutout_266d190359.
		.replace(/[_-](?=[a-f0-9]*\d)[a-f0-9]{8,}$/i, '')
		.replace(/[_-]+/g, ' ')
		.replace(/\s+/g, ' ')
		.trim();
}

function shortPhrase(value, limit = 52) {
	const phrase = compactName(value).split(/\s*[.;\n]\s*/)[0].trim();
	if (phrase.length <= limit) return phrase;
	const cut = phrase.slice(0, limit + 1);
	return `${cut.slice(0, cut.lastIndexOf(' ') > limit / 2 ? cut.lastIndexOf(' ') : limit).trim()}…`;
}

export function assetDisplayName(asset) {
	const category = assetCategory(asset);
	const view = String(asset?.product_view || '').trim();
	const label = String(asset?.label || '').trim();
	const referenceKey = String(asset?.reference_key || '').trim();
	const raw = label && !referenceKey.startsWith(label) && !label.startsWith(referenceKey) && !/^[a-z]+_[a-f0-9]{8,}/i.test(label)
		? label : asset?.asset_name || label;
	let name = String(raw);
	if (category === 'Character') name = name.replace(/^[a-z][a-z0-9]*_[a-z0-9_]+\s+(?=[a-z])/i, '');
	name = compactName(name);
	const key = compactName(asset?.reference_key);
	if (key && name.toLowerCase().startsWith(`${key.toLowerCase()} `)) name = name.slice(key.length).trim();
	name = name.replace(/^[\s:—–-]+/, '');
	if (category === 'Product' && view && view !== 'source') {
		const viewLabel = compactName(view).replace(/\b\w/g, letter => letter.toUpperCase());
		if (!name.toLowerCase().includes(view.replace(/_/g, ' ').toLowerCase())) name = `${shortPhrase(name, 38)} · ${viewLabel}`;
	}
	return shortPhrase(name) || category;
}

export function groupAssets(assets) {
	const buckets = new Map();
	for (const asset of assets || []) {
		const category = assetCategory(asset);
		if (!buckets.has(category)) buckets.set(category, []);
		buckets.get(category).push({ ...asset, display_name: assetDisplayName(asset), display_category: category });
	}
	for (const items of buckets.values()) {
		const counts = new Map();
		for (const item of items) counts.set(item.display_name, (counts.get(item.display_name) || 0) + 1);
		const seen = new Map();
		for (const item of items) {
			const name = item.display_name;
			if (counts.get(name) > 1) {
				const index = (seen.get(name) || 0) + 1;
				seen.set(name, index);
				item.display_name = `${name} (${index})`;
			}
		}
	}
	return [...buckets.entries()]
		.sort(([a], [b]) => CATEGORY_ORDER.indexOf(a) - CATEGORY_ORDER.indexOf(b))
		.map(([category, items]) => ({ category, items }));
}

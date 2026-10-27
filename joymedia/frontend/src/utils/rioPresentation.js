const categoryNames = {
	Product: 'Sản phẩm', Character: 'Nhân vật', Environment: 'Bối cảnh',
	Brand: 'Thương hiệu', Logo: 'Thương hiệu', Style: 'Phong cách',
	Motion: 'Chuyển động', Audio: 'Âm thanh', Other: 'Khác',
};

const categoryIcons = {
	Product: '▣', Character: '♟', Environment: '▧', Brand: '◆',
	Logo: '◆', Style: '✦', Motion: '▶', Audio: '♫', Other: '◇',
};

export function categoryLabel(category, language = 'en') {
	return language === 'vi' ? categoryNames[category] || category : category;
}

export function categoryIcon(category) {
	return categoryIcons[category] || '◇';
}

export function referenceLabel(reference, assets = []) {
	const asset = assets.find(item => item.reference_key === reference.reference_key);
	return asset?.display_name || asset?.label || reference.label
		|| String(reference.reference_key || '').replace(/[_-]+/g, ' ');
}

export function referenceCategory(reference, assets = []) {
	const asset = assets.find(item => item.reference_key === reference.reference_key);
	return asset?.display_category || asset?.reference_role || reference.reference_role || 'Other';
}

export function categoryOptions(asset) {
	if (asset.media_type === 'Audio') return ['Audio'];
	return asset.media_type === 'Video'
		? ['Motion', 'Environment', 'Style']
		: ['Product', 'Character', 'Environment', 'Logo', 'Style'];
}

export function formatDuration(seconds) {
	const value = Number(seconds);
	return Number.isFinite(value) && value >= 0 ? `${Number(value.toFixed(1))}s` : '—';
}

export function aspectRatio(width, height) {
	const w = Number(width), h = Number(height);
	if (!Number.isInteger(w) || !Number.isInteger(h) || w <= 0 || h <= 0) return '—';
	let a = w, b = h;
	while (b) [a, b] = [b, a % b];
	return `${w / a}:${h / a}`;
}

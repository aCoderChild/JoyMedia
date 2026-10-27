<template>
	<div class="rio-studio" data-test="rio-studio">
		<header class="rio-header">
			<div class="rio-brand" aria-label="RIO Studio">
				<span class="rio-brand-mark" aria-hidden="true">◇</span>
				<strong>RIO <span>STUDIO</span></strong>
				<span class="rio-status" :class="{ 'is-busy': busy }"><i />{{ statusLabel }}</span>
			</div>
			<div class="rio-project-name" :title="projectTitle">{{ projectTitle }}</div>
			<div class="rio-header-actions">
				<router-link class="rio-header-link" to="/projects">{{ t('Projects', 'Dự án') }}</router-link>
				<button type="button" data-test="rio-versions-toggle" :aria-expanded="versionsOpen" @click="versionsOpen = !versionsOpen">{{ t('Video versions', 'Các phiên bản') }}</button>
				<button v-if="canWork && nextActionLabel" type="button" class="rio-next-action" :disabled="busy || (nextAction === 'brief' && !idea?.trim())" @click="emit('continue')">{{ nextActionLabel }}</button>
				<button v-if="canWork" type="button" :title="t('Project settings', 'Cài đặt dự án')" :aria-label="t('Project settings', 'Cài đặt dự án')" @click="emit('settings')">⚙</button>
				<button v-if="canEdit" type="button" :title="t('Add scene', 'Thêm cảnh')" :aria-label="t('Add scene', 'Thêm cảnh')" @click="emit('add-scene')">＋</button>
				<button type="button" :title="t('Project media', 'Tư liệu dự án')" :aria-label="t('Show or hide project media', 'Hiện hoặc ẩn tư liệu dự án')" :aria-expanded="assetsOpen" @click="assetsOpen = !assetsOpen">▧</button>
				<button type="button" :title="t('Toggle minimap', 'Bật/tắt sơ đồ nhỏ')" :aria-label="t('Toggle minimap', 'Bật/tắt sơ đồ nhỏ')" :aria-pressed="showMinimap" @click="showMinimap = !showMinimap">▦</button>
				<button type="button" :title="t('Fit canvas', 'Toàn cảnh')" :aria-label="t('Fit all scenes on screen', 'Hiện tất cả cảnh trên màn hình')" @click="fitCanvas">⛶</button>
				<button v-if="canEdit" type="button" class="rio-classic" @click="emit('classic')">{{ t('Classic editor', 'Trình biên tập cũ') }}</button>
				<button type="button" class="rio-classic" @click="emit('video')">{{ t('Guided view', 'Xem theo bước') }}</button>
			</div>
		</header>
		<div v-if="versionsOpen" class="rio-versions" data-test="rio-versions"><header><strong>{{ t('Videos in this project', 'Video trong dự án') }}</strong><button type="button" :aria-label="t('Close versions', 'Đóng phiên bản')" @click="versionsOpen = false">×</button></header><VideoShelf :project="projectName" :readonly="!canWork" /></div>
		<p v-if="nextActionHint && !error" class="rio-guidance" role="status">{{ nextActionHint }}</p>
		<div v-if="error" class="rio-alert" role="alert">{{ error }} <button type="button" @click="emit('retry')">{{ t('Retry', 'Thử lại') }}</button></div>
		<div class="rio-work-area">
			<aside v-if="assetsOpen" class="rio-assets" :aria-label="t('Project media', 'Tư liệu dự án')">
				<div class="rio-assets-head"><strong>◇ {{ t('ASSETS', 'TƯ LIỆU') }}</strong><div class="rio-asset-tools"><div class="rio-asset-size" :aria-label="t('Thumbnail size', 'Cỡ ảnh')"><button v-for="size in ['s', 'm', 'l']" :key="size" type="button" :class="{ active: assetSize === size }" :aria-pressed="assetSize === size" @click="assetSize = size">{{ size.toUpperCase() }}</button></div><button v-if="canWork" type="button" class="rio-asset-plus" :title="t('Add media', 'Thêm tư liệu')" @click="emit('open-media')">＋</button></div></div>
				<div class="rio-assets-list" :class="`size-${assetSize}`">
					<div v-for="asset in displayedAssets" :key="asset.asset_version || asset.name" class="rio-asset-card" :class="{ selected: selectedAsset?.asset_version === asset.asset_version }" :draggable="canEdit && Boolean(asset.reference_key)" @dragstart="startAssetDrag($event, asset)" @dragend="draggedAsset = null">
						<div class="rio-asset-thumb"><button type="button" class="rio-asset-image" :title="asset.asset_name || asset.label || asset.display_name" @click="emit('select-asset', asset)"><MediaThumbnail :src="asset.file" :media-type="asset.media_type" :alt="asset.display_name" aspect="aspect-square" /></button><button type="button" class="rio-asset-badge" :class="asset.display_category.toLowerCase()" :title="t('Change category', 'Đổi danh mục')" :disabled="!canEdit" @click="categoryAsset = categoryAsset === asset.asset_version ? null : asset.asset_version">{{ categoryIcon(asset.display_category) }} <span>{{ categoryLabel(asset.display_category) }}</span></button></div>
						<div v-if="editingAsset === asset.asset_version" class="rio-asset-name-edit"><input v-model="editedAssetName" :aria-label="t('Asset name', 'Tên tư liệu')" maxlength="140" @keydown.enter.prevent="saveAssetName(asset)" @keydown.esc="editingAsset = null" @blur="saveAssetName(asset)" /></div>
						<button v-else type="button" class="rio-asset-name" :title="t('Rename asset', 'Đổi tên tư liệu')" :disabled="!canEdit" @click="beginAssetName(asset)">{{ asset.display_name }}</button>
						<div v-if="canEdit && categoryAsset === asset.asset_version" class="rio-category-menu"><button v-for="role in categoryOptions(asset)" :key="role" type="button" @click="emit('update-asset', asset, { reference_role: role }); categoryAsset = null">{{ categoryIcon(role) }} {{ categoryLabel(role) }}</button></div>
						<button v-if="canEdit && asset.reference_key && selectedShot" type="button" class="rio-asset-assign" :disabled="shotReferenceKeys(selectedShot).includes(asset.reference_key)" :title="t('Add reference to selected scene', 'Thêm tư liệu vào cảnh đã chọn')" @click="emit('assign-asset', asset)">{{ shotReferenceKeys(selectedShot).includes(asset.reference_key) ? '✓' : '↗' }}</button>
						<button v-if="canEdit" type="button" class="rio-asset-remove" :title="t('Remove from project', 'Gỡ khỏi dự án')" @click="emit('remove-asset', asset)">×</button>
					</div>
					<p v-if="!assets.length" class="rio-empty-assets">{{ t('Add product, character, and location references.', 'Thêm ảnh sản phẩm, nhân vật và bối cảnh.') }}</p>
				</div>
				<button v-if="canWork" type="button" class="rio-add-media" @click="emit('open-media')">＋ {{ t('Add reference', 'Thêm tư liệu') }}</button>
			</aside>
			<section class="rio-canvas" ref="canvasRef" :aria-label="t('Scene canvas', 'Sơ đồ cảnh')" @pointerdown="startPan" @pointermove="movePan" @pointerup="endPan" @pointercancel="endPan">
				<div class="rio-canvas-inner" :style="{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }">
					<svg class="rio-connections" :width="canvasWidth" :height="canvasHeight" aria-hidden="true">
						<path v-for="(edge, index) in edges" :key="index" :d="edge" />
					</svg>
					<article v-for="(shot, index) in shots" :key="shot.name" class="rio-node" :class="{ active: index === selectedShotIndex }" :style="nodeStyle(shot, index)" @pointerdown.stop="startNodeDrag($event, shot, index)" @pointermove.stop="moveNodeDrag" @pointerup.stop="endNodeDrag" @pointercancel.stop="endNodeDrag" @dragover.prevent @drop.prevent.stop="dropAssetOnShot($event, shot)">
						<div class="rio-node-head"><span>🎬 <strong>{{ t('Shot', 'Cảnh') }} {{ String(shot.shot_number || index + 1).padStart(2, '0') }}</strong></span><span class="rio-node-ratio">{{ ratioLabel }}</span><button type="button" :title="t('Scene details', 'Chi tiết cảnh')" :aria-label="t('Scene details', 'Chi tiết cảnh')" @click.stop="openShotDetails(shot, index)">⋯</button></div>
						<button type="button" class="rio-node-preview" @click.stop="selectShot(shot, index)">
							<img v-if="frameFor(shot)" :src="frameFor(shot)" :alt="shot.shot_name || `Shot ${index + 1}`" />
							<span v-else><b>▧</b>{{ t('No scene image yet', 'Chưa có ảnh đầu cảnh') }}</span>
						</button>
						<div class="rio-node-body">
							<label :for="`rio-prompt-${shot.name}`">{{ t('Prompt', 'Mô tả cảnh') }}</label>
							<textarea :id="`rio-prompt-${shot.name}`" :value="draftFor(shot)" :disabled="!canEdit || busy || isShotBusy(shot)" rows="3" @input="setDraft(shot, $event.target.value)" @keydown.ctrl.enter.prevent="saveDraft(shot)" @keydown.meta.enter.prevent="saveDraft(shot)" />
							<div v-if="shotReferenceKeys(shot).length" class="rio-reference-line" :title="shot.references.map(reference => referenceLabel(reference)).join(' · ')">{{ shot.references.map(reference => referenceLabel(reference)).join(' · ') }}</div>
						</div>
							<div class="rio-node-actions">
								<button v-if="canWork && frameNeedsApproval(shot)" type="button" :disabled="busy || isShotBusy(shot)" :title="t('Approve this first frame', 'Duyệt ảnh đầu cảnh')" @click.stop="emit('approve-frame', shot.name, true)">{{ t('Approve image', 'Duyệt ảnh') }}</button>
								<button v-if="canEdit && promptDirty(shot)" type="button" :disabled="busy || isShotBusy(shot)" @click.stop="saveDraft(shot)">{{ t('Save', 'Lưu') }}</button>
								<button v-if="canWork" type="button" :disabled="busy || isShotBusy(shot) || !storyboardApproved || promptDirty(shot)" :title="!storyboardApproved ? t('Approve storyboard first', 'Duyệt bảng phân cảnh trước') : promptDirty(shot) ? t('Save the scene description first', 'Lưu mô tả cảnh trước') : t('Generate or redraw this scene’s first image', 'Tạo hoặc vẽ lại ảnh đầu cảnh')" @click.stop="emit('draw-shot', shot)">{{ t('Create image', 'Tạo ảnh') }}</button>
								<button v-if="canEdit" type="button" :disabled="busy || isShotBusy(shot) || !frameFor(shot) || frameNeedsApproval(shot)" :title="frameNeedsApproval(shot) ? t('Approve the scene image first', 'Duyệt ảnh cảnh trước') : t('Generate this scene’s video', 'Tạo video cho cảnh này')" @click.stop="emit('render-shot', shot)">{{ t('Create clip', 'Tạo đoạn phim') }}</button>
							<button v-if="canEdit" type="button" @click.stop="openShotDetails(shot, index)">{{ t('Details', 'Chi tiết') }}</button>
						</div>
						<i class="rio-port rio-port-in" /><i class="rio-port rio-port-out" />
					</article>
					<div v-if="!shots.length" class="rio-empty-canvas">
						<strong>{{ t('Your storyboard will appear here', 'Bảng phân cảnh sẽ xuất hiện ở đây') }}</strong>
						<p>{{ t('Plan the video from your references to create scene nodes.', 'Lập kịch bản từ tư liệu để tạo các cảnh.') }}</p>
						<textarea :value="idea" :disabled="!canWork" :aria-label="t('Video idea', 'Ý tưởng video')" :placeholder="t('Describe the product and what should happen in the video', 'Mô tả sản phẩm và nội dung video')" rows="4" @input="emit('update:idea', $event.target.value)" />
						<button v-if="canWork" type="button" :disabled="busy || !idea?.trim()" @click="emit('continue')">{{ t('Generate storyboard', 'Tạo phân cảnh') }}</button>
					</div>
				</div>
				<div class="rio-canvas-controls"><button type="button" :aria-label="t('Zoom out', 'Thu nhỏ')" @click="zoom = Math.max(0.45, zoom - 0.1)">−</button><span>{{ Math.round(zoom * 100) }}%</span><button type="button" :aria-label="t('Zoom in', 'Phóng to')" @click="zoom = Math.min(1.6, zoom + 0.1)">＋</button><button type="button" :aria-label="t('Fit all scenes on screen', 'Hiện tất cả cảnh trên màn hình')" @click="fitCanvas">⛶</button></div>
				<div v-if="showMinimap" class="rio-minimap" aria-hidden="true"><span>{{ t('OVERVIEW', 'TỔNG QUAN') }}</span><div v-for="(shot, index) in shots" :key="shot.name" :style="miniStyle(shot, index)" /></div>
			</section>
			<aside v-if="selectedAsset || detailsShot" class="rio-details" :aria-label="t('Details', 'Chi tiết')">
					<header><strong>{{ detailsShot ? `${t('Shot', 'Cảnh')} ${detailsShot.shot_number || selectedShotIndex + 1}` : t('Asset', 'Tư liệu') }}</strong><button type="button" :title="t('Close', 'Đóng')" :aria-label="t('Close details', 'Đóng chi tiết')" @click="closeDetails">×</button></header>
					<template v-if="detailsShot">
						<div class="rio-details-summary"><strong>{{ detailsShot.shot_name || detailsShot.title || `${t('Shot', 'Cảnh')} ${detailsShot.shot_number}` }}</strong><span>{{ formatDuration(detailsShot.duration_seconds) }}</span></div>
						<div class="rio-details-frame"><img v-if="frameFor(detailsShot)" class="rio-details-preview" :src="frameFor(detailsShot)" :alt="detailsShot.shot_name || t('Scene frame', 'Khung cảnh')" /><p v-else>{{ t('No first frame yet', 'Chưa có ảnh đầu cảnh') }}</p></div>
						<p class="rio-details-status">{{ frameStatusLabel(detailsShot) }}</p>
						<h4>{{ t('What happens', 'Nội dung cảnh') }}</h4><p class="rio-details-action-text">{{ detailsShot.storyboard_action || detailsShot.generation_prompt || t('No scene description yet.', 'Chưa có mô tả cảnh.') }}</p>
						<h4>{{ t('References used', 'Tư liệu dùng trong cảnh') }}</h4>
						<div class="rio-details-references"><div v-for="reference in detailsShot.references || []" :key="reference.reference_key" class="rio-details-reference"><span class="rio-details-reference-icon" aria-hidden="true">{{ categoryIcon(referenceCategory(reference)) }}</span><span class="rio-details-reference-copy"><small>{{ categoryLabel(referenceCategory(reference)) }}</small><strong :title="referenceLabel(reference)">{{ referenceLabel(reference) }}</strong></span><button v-if="canEdit" type="button" :title="t('Remove from scene', 'Gỡ khỏi cảnh')" :aria-label="`${t('Remove from scene', 'Gỡ khỏi cảnh')}: ${referenceLabel(reference)}`" @click="removeShotReference(detailsShot, reference.reference_key)">×</button></div><small v-if="!detailsShot.references?.length">{{ t('Drag an asset onto this scene to add it.', 'Kéo tư liệu vào cảnh để thêm.') }}</small></div>
						<button v-if="canEdit" type="button" class="rio-details-action" @click="emit('edit-shot', detailsShot, selectedShotIndex)">{{ t('Edit scene settings', 'Chỉnh sửa cảnh') }}</button>
					</template>
					<template v-else-if="selectedAsset"><MediaThumbnail :src="selectedAsset.file" :media-type="selectedAsset.media_type" :alt="selectedAsset.asset_name || selectedAsset.label" aspect="aspect-square" /><p>{{ selectedAsset.label || selectedAsset.asset_name }}</p><p>{{ categoryLabel(selectedAsset.reference_role || selectedAsset.asset_category) }}</p><p v-if="selectedAsset.product_view && selectedAsset.product_view !== 'source'">{{ t('View', 'Góc nhìn') }}: {{ selectedAsset.product_view.replaceAll('_', ' ') }}</p><button v-if="canEdit && selectedAsset.reference_key && selectedShot" type="button" class="rio-details-action" :disabled="shotReferenceKeys(selectedShot).includes(selectedAsset.reference_key)" @click="emit('assign-asset', selectedAsset)">{{ t('Add to selected scene', 'Thêm vào cảnh đang chọn') }}</button></template>
				</aside>
		</div>
		<section class="rio-bottom" :style="{ height: `${Math.min(420, 220 + Math.max(0, audioLanes.length - 1) * 57 + (selectedAudio ? 42 : 0))}px` }">
			<div class="rio-timeline">
				<div class="rio-timeline-head"><button type="button" :disabled="!previewVideo" :aria-label="playing ? t('Pause preview', 'Tạm dừng xem trước') : t('Play preview', 'Phát xem trước')" @click="togglePlayback">{{ playing ? 'Ⅱ' : '▶' }}</button><strong>{{ t('TIMELINE', 'DÒNG THỜI GIAN') }}</strong><span>{{ clips.length }} {{ t('clips', 'đoạn') }}</span><div v-if="canWork" class="rio-audio-add"><button type="button" data-test="rio-add-audio" :aria-expanded="audioAddOpen" @click="audioAddOpen = !audioAddOpen">＋ {{ t('Add audio', 'Thêm âm thanh') }}</button><div v-if="audioAddOpen" class="rio-audio-add-menu"><button v-for="role in ['BGM', 'Voiceover', 'SFX']" :key="role" type="button" @click="chooseAudioRole(role)">{{ audioRoleLabel(role) }}</button></div></div><button v-if="canWork" type="button" @click="emit('open-timeline')">{{ t('Edit tracks', 'Biên tập') }}</button><button v-if="canEdit" type="button" class="rio-export" :disabled="!canExport || exporting" @click="emit('export')">{{ exporting ? '…' : t('Export video', 'Xuất video') }}</button></div>
				<div class="rio-ruler"><span v-for="tick in ticks" :key="tick" :style="{ left: `${tick / totalSeconds * 100}%` }">{{ tick }}s</span><input v-if="clips.length" type="range" min="0" :max="totalSeconds" step="0.1" :value="playheadSeconds" :aria-label="t('Preview position', 'Vị trí xem trước')" @input="seekTimeline(Number($event.target.value))" /></div>
				<div class="rio-track"><b :title="t('Video track', 'Đường hình')">{{ t('VIDEO', 'HÌNH') }}</b><div class="rio-track-content"><button v-for="(clip, index) in orderedClips" :key="clip.name || index" type="button" class="rio-video-clip" :class="{ selected: clip.name === activeClip?.name }" :style="clipStyle(clip, index)" :title="clipDescription(clip, index)" @click="selectClip(clip)">{{ clipTitle(clip, index) }}</button><span v-if="!clips.length" class="rio-track-empty">{{ t('Generated clips appear here', 'Video sau khi dựng sẽ xuất hiện ở đây') }}</span></div></div>
				<div v-for="(lane, laneIndex) in audioLanes" :key="`audio-${laneIndex}`" class="rio-track rio-audio-row"><b :title="audioRoleLabel(lane.role)">{{ audioRoleLabel(lane.role) }}</b><div class="rio-track-content"><button v-for="clip in lane.clips" :key="clip.name" type="button" class="rio-audio-clip" :class="{ 'is-selected': selectedAudioName === clip.name, 'is-disabled': !clip.enabled }" :style="audioStyle(clip)" :title="`${audioTitle(clip)}${clip.enabled ? '' : ` · ${t('Disabled', 'Đã tắt')}`}`" @click="selectedAudioName = clip.name" @dblclick="emit('open-timeline', clip)">{{ audioTitle(clip) }}</button></div></div>
				<div v-if="!audioLanes.length" class="rio-track rio-audio-row"><b :title="t('Audio track', 'Đường âm thanh')">{{ t('AUDIO', 'ÂM THANH') }}</b><div class="rio-track-content"><span class="rio-track-empty">{{ t('No audio yet. Add music, voice, or effects.', 'Chưa có âm thanh. Thêm nhạc, lời thoại hoặc hiệu ứng.') }}</span></div></div>
				<div v-if="selectedAudio" class="rio-audio-actions"><strong :title="audioTitle(selectedAudio)">{{ audioTitle(selectedAudio) }}</strong><button v-if="canWork" type="button" :disabled="busy" @click="emit('toggle-audio', selectedAudio, !selectedAudio.enabled)">{{ selectedAudio.enabled ? t('Disable', 'Tắt') : t('Enable', 'Bật') }}</button><button v-if="canWork && selectedAudio.audio_role !== 'Source'" type="button" :disabled="busy" @click="removeSelectedAudio">{{ t('Remove', 'Xóa khỏi dòng thời gian') }}</button><button type="button" @click="emit('open-timeline', selectedAudio)">{{ t('More controls', 'Điều chỉnh thêm') }}</button></div>
			</div>
			<div class="rio-monitor"><div class="rio-monitor-head"><span>▣ {{ t('PREVIEW', 'XEM TRƯỚC') }}</span><time>{{ timecode }}</time></div><video v-if="previewVideo" ref="videoRef" :src="previewVideo" controls playsinline @loadedmetadata="applyPendingSeek" @play="playing = true" @pause="playing = false" @timeupdate="onTimeUpdate" @ended="playing = false" /><img v-else-if="previewImage" :src="previewImage" :alt="t('Selected first frame', 'Ảnh đầu cảnh đã chọn')" /><div v-else class="rio-monitor-empty">🎬<span>{{ t('Select a scene to preview', 'Chọn cảnh để xem trước') }}</span></div></div>
		</section>
	</div>
</template>

<script setup>
import { computed, nextTick, reactive, ref, watch } from 'vue';
import MediaThumbnail from '../MediaThumbnail.vue';
import VideoShelf from './VideoShelf.vue';
import { groupAssets } from '../../utils/assetPresentation.js';
import { clipAtSeconds, layoutAudioLanes, orderTimelineClips, shotIndexForClip, sourceSecondsForTimeline } from '../../utils/rioTimeline.js';
import { aspectRatio, categoryIcon, categoryLabel as getCategoryLabel, categoryOptions, formatDuration, referenceCategory as getReferenceCategory, referenceLabel as getReferenceLabel } from '../../utils/rioPresentation.js';

const props = defineProps({
	projectName: String, projectTitle: String, projectStatus: String, currentLang: String, idea: String,
	canEdit: Boolean, canWork: Boolean,
	assets: { type: Array, default: () => [] }, selectedAsset: Object,
	shots: { type: Array, default: () => [] }, selectedShotIndex: { type: Number, default: 0 },
	clips: { type: Array, default: () => [] }, audioClips: { type: Array, default: () => [] },
	finalVideo: Object, timeline: Object, fps: { type: Number, default: 24 },
	width: Number, height: Number, busy: Boolean, exporting: Boolean, canExport: Boolean,
	storyboardApproved: Boolean, busyShots: { type: Array, default: () => [] },
	frames: { type: Array, default: () => [] }, nextAction: String, error: String,
});
const emit = defineEmits(['classic', 'video', 'update:idea', 'settings', 'add-scene', 'open-media', 'select-asset', 'assign-asset', 'update-asset', 'remove-asset', 'update-shot-references', 'select-shot', 'edit-shot', 'draw-shot', 'approve-frame', 'render-shot', 'save-prompt', 'open-timeline', 'add-audio', 'toggle-audio', 'remove-audio', 'export', 'retry', 'continue']);
const t = (en, vi) => props.currentLang === 'vi' ? vi : en;
const assetsOpen = ref(typeof window === 'undefined' || window.innerWidth > 640), assetSize = ref('m'), draggedAsset = ref(null), editingAsset = ref(null), editingAssetName = ref(''), detailsShotName = ref(null), canvasRef = ref(null), videoRef = ref(null), playing = ref(false), elapsed = ref(0), zoom = ref(1), showMinimap = ref(false), versionsOpen = ref(false), selectedAudioName = ref(null), audioAddOpen = ref(false);
const pan = reactive({ x: 0, y: 0 });
const positions = reactive({});
const drafts = reactive({});
const nodeWidth = 380, nodeHeight = 430, nodeGap = 100;
const canvasWidth = computed(() => Math.max(1100, props.shots.length * (nodeWidth + nodeGap) + 180));
const canvasHeight = 830;
const statusLabel = computed(() => {
	if (props.busy) return t('Working', 'Đang xử lý');
	const labels = {
		Draft: t('Draft', 'Bản nháp'), Planning: t('Planning', 'Đang lập kế hoạch'),
		Queued: t('Waiting', 'Đang chờ'), Running: t('Working', 'Đang xử lý'),
		Completed: t('Complete', 'Hoàn tất'), Failed: t('Needs attention', 'Cần xử lý'),
		Archived: t('Archived', 'Đã lưu trữ'),
	};
	return labels[props.projectStatus] || props.projectStatus || t('Ready', 'Sẵn sàng');
});
const nextActionLabel = computed(() => ({
	brief: t('Plan video', 'Lập kịch bản'), plan: t('Generate storyboard', 'Tạo phân cảnh'),
	approve: t('Approve storyboard', 'Duyệt phân cảnh'), previews: t('Generate first frames', 'Tạo ảnh đầu cảnh'),
	retry: t('Retry previews', 'Thử lại ảnh'), review: t('Review scene images', 'Xem lại ảnh các cảnh'),
	render: t('Generate video', 'Tạo video'), watch: t('Watch video', 'Xem video'),
})[props.nextAction] || '');
const nextActionHint = computed(() => ({
	brief: t('Start with a short idea for your video and add your product photos.', 'Bắt đầu bằng ý tưởng ngắn và thêm ảnh sản phẩm.'),
	plan: t('Your idea is ready. Generate scenes to review the story.', 'Ý tưởng đã sẵn sàng. Tạo các cảnh để xem câu chuyện.'),
	approve: t('Read the scene descriptions, then approve the storyboard when they match your idea.', 'Đọc mô tả từng cảnh, rồi duyệt phân cảnh khi đúng ý tưởng.'),
	previews: t('Create the first image for each scene, then check the product and character.', 'Tạo ảnh đầu cho từng cảnh, rồi kiểm tra sản phẩm và nhân vật.'),
	review: t('Select each scene image, check it, and approve it before making the video.', 'Chọn từng ảnh cảnh, kiểm tra và duyệt trước khi tạo video.'),
	render: t('The scene images are ready. Generate the video to see the motion.', 'Ảnh các cảnh đã sẵn sàng. Tạo video để xem chuyển động.'),
	watch: t('Your video is ready to preview below.', 'Video đã sẵn sàng để xem ở khung bên dưới.'),
	retry: t('Some images could not be checked. Retry their preparation.', 'Một số ảnh chưa kiểm tra được. Hãy thử chuẩn bị lại.'),
	working: t('The system is working. Finished scenes appear here as they are ready.', 'Hệ thống đang xử lý. Cảnh hoàn thành sẽ hiện tại đây.'),
	loading: t('Loading scene images…', 'Đang tải ảnh các cảnh…'),
})[props.nextAction] || '');
const assetGroups = computed(() => groupAssets(props.assets));
const displayedAssets = computed(() => assetGroups.value.flatMap(group => group.items));
const detailsShot = computed(() => props.shots.find(shot => shot.name === detailsShotName.value) || null);
watch(() => props.selectedAsset?.asset_version, value => { if (value) detailsShotName.value = null; });
function categoryLabel(category) { return getCategoryLabel(category, props.currentLang); }
function referenceLabel(reference) { return getReferenceLabel(reference, props.assets); }
function referenceCategory(reference) { return getReferenceCategory(reference, props.assets); }
function frameStatusLabel(shot) { const frame = props.frames.find(row => row.shot === shot?.name); if (frame?.stale) return t('Image needs updating', 'Ảnh cần cập nhật'); if (!frameFor(shot)) return t('Image has not been created', 'Ảnh chưa được tạo'); if (frame?.status === 'Approved') return t('Image approved', 'Ảnh đã duyệt'); if (frame?.needs_keyframe) return t('Image needs review', 'Ảnh cần xem lại'); return t('Image available', 'Đã có ảnh'); }
function beginAssetName(asset) { categoryAsset.value = null; editingAsset.value = asset.asset_version; editedAssetName.value = asset.display_name; }
function saveAssetName(asset) { if (editingAsset.value !== asset.asset_version) return; editingAsset.value = null; const label = editedAssetName.value.trim(); if (label && label !== asset.display_name) emit('update-asset', asset, { label }); }
function startAssetDrag(event, asset) { draggedAsset.value = asset; event.dataTransfer.effectAllowed = 'copy'; event.dataTransfer.setData('text/plain', asset.reference_key || ''); }
function dropAssetOnShot(event, shot) { if (!props.canEdit) return; const asset = draggedAsset.value || props.assets.find(item => item.reference_key === event.dataTransfer.getData('text/plain')); draggedAsset.value = null; if (asset?.reference_key && !shotReferenceKeys(shot).includes(asset.reference_key)) emit('assign-asset', asset, shot); }
function openShotDetails(shot, index) { detailsShotName.value = shot.name; emit('select-shot', shot, index); }
function closeDetails() { detailsShotName.value = null; emit('select-asset', null); }
function removeShotReference(shot, referenceKey) { if (props.canEdit) emit('update-shot-references', shot, shotReferenceKeys(shot).filter(key => key !== referenceKey)); }
const ratioLabel = computed(() => aspectRatio(props.width, props.height));
const storyboardApproved = computed(() => props.storyboardApproved);
const orderedClips = computed(() => orderTimelineClips(props.clips));
const audioLanes = computed(() => layoutAudioLanes(props.audioClips));
const selectedAudio = computed(() => props.audioClips.find(clip => clip.name === selectedAudioName.value) || null);
function removeSelectedAudio() { if (!selectedAudio.value || !props.canWork) return; const clip = selectedAudio.value; selectedAudioName.value = null; emit('remove-audio', clip); }
function audioRoleLabel(role) { return { BGM: t('Music', 'Nhạc nền'), Music: t('Music', 'Nhạc nền'), Voiceover: t('Voiceover', 'Lời thoại'), SFX: t('Sound effect', 'Hiệu ứng âm thanh'), Source: t('Scene audio', 'Âm thanh cảnh') }[role] || t('Audio', 'Âm thanh'); }
function chooseAudioRole(role) { audioAddOpen.value = false; emit('add-audio', role); }
const totalSeconds = computed(() => Math.max(1, Number(props.timeline?.total_seconds || 0), ...[...props.clips, ...props.audioClips].map(clip => (Number(clip.timeline_start_frame || 0) + Number(clip.duration_frames || 0)) / Math.max(1, props.fps)), Number(props.shots.reduce((sum, shot) => sum + Number(shot.duration_seconds || 0), 0) || 0)));
const ticks = computed(() => { const step = totalSeconds.value > 30 ? 10 : totalSeconds.value > 12 ? 5 : 2; return Array.from({ length: Math.floor(totalSeconds.value / step) + 1 }, (_, i) => i * step); });
const previewShot = computed(() => props.shots[props.selectedShotIndex] || props.shots[0]);
const selectedShot = previewShot;
const activeClipName = ref(null);
const activeClip = computed(() => props.clips.find(clip => clip.name === activeClipName.value && clip.shot === previewShot.value?.name) || props.clips.find(clip => clip.shot === previewShot.value?.name) || null);
const previewVideo = computed(() => props.finalVideo?.file || activeClip.value?.source_file || previewShot.value?.selected_output_file || previewShot.value?.output_video || '');
const previewImage = computed(() => frameFor(previewShot.value));
const playheadSeconds = computed(() => props.finalVideo?.file ? elapsed.value : activeClip.value ? Number(activeClip.value.timeline_start_frame || 0) / Math.max(1, props.fps) + Math.max(0, elapsed.value - Number(activeClip.value.source_in_frame || 0) / Math.max(1, props.fps)) : elapsed.value);
const timecode = computed(() => { const s = Math.max(0, playheadSeconds.value); return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}.${Math.floor((s % 1) * 10)}`; });
const edges = computed(() => props.shots.slice(0, -1).map((shot, index) => { const a = positionFor(shot, index), b = positionFor(props.shots[index + 1], index + 1); const x1 = a.x + nodeWidth, y1 = a.y + 215, x2 = b.x, y2 = b.y + 215; return `M ${x1} ${y1} C ${x1 + 52} ${y1}, ${x2 - 52} ${y2}, ${x2} ${y2}`; }));
function frameFor(shot) {
	const frame = props.frames.find(row => row.shot === shot?.name);
	if (frame?.stale) return '';
	return frame?.url || shot?.first_frame_image || '';
}
function frameNeedsApproval(shot) { const frame = props.frames.find(row => row.shot === shot?.name); return Boolean(frame?.needs_keyframe && frame?.url && !frame?.stale && frame?.status !== 'Approved'); }
function shotReferenceKeys(shot) { return Array.isArray(shot?.references) ? shot.references.map(reference => reference.reference_key).filter(Boolean) : []; }
function isShotBusy(shot) { return props.busyShots.some(item => (typeof item === 'string' ? item : item?.name || item?.shot) === shot?.name); }
function defaultPosition(index) { return { x: 100 + index * (nodeWidth + nodeGap), y: 135 + (index % 2) * 110 }; }
function positionFor(shot, index) { return positions[shot.name] || defaultPosition(index); }
function nodeStyle(shot, index) { const p = positionFor(shot, index); return { left: `${p.x}px`, top: `${p.y}px` }; }
function miniStyle(shot, index) { const p = positionFor(shot, index); return { left: `${Math.min(92, p.x / canvasWidth.value * 100)}%`, top: `${p.y / canvasHeight * 100}%` }; }
function layoutKey() { return `joymedia:rio-layout:${props.projectName}`; }
watch(() => props.projectName, () => { for (const key of Object.keys(positions)) delete positions[key]; try { const saved = JSON.parse(localStorage.getItem(layoutKey()) || '{}'); for (const [key, value] of Object.entries(saved)) if (Number.isFinite(value?.x) && Number.isFinite(value?.y)) positions[key] = value; } catch { /* Layout is optional. */ } nextTick(focusCanvas); }, { immediate: true });
function persistLayout() { try { localStorage.setItem(layoutKey(), JSON.stringify(positions)); } catch { /* Browsers can disable storage. */ } }
function focusCanvas() { zoom.value = 0.82; pan.x = 0; pan.y = 0; }
function fitCanvas() { const w = canvasRef.value?.clientWidth || 900; zoom.value = Math.max(0.45, Math.min(1, (w - 80) / Math.max(700, canvasWidth.value))); pan.x = 0; pan.y = 0; }
watch(() => props.shots.length, () => nextTick(focusCanvas));
let drag = null;
function startPan(event) { if (event.button !== 0 || event.target.closest('button,textarea,input')) return; drag = { kind: 'pan', x: event.clientX, y: event.clientY, originalX: pan.x, originalY: pan.y }; event.currentTarget.setPointerCapture(event.pointerId); }
function movePan(event) { if (drag?.kind !== 'pan') return; pan.x = drag.originalX + event.clientX - drag.x; pan.y = drag.originalY + event.clientY - drag.y; }
function endPan(event) { if (drag?.kind === 'pan') { drag = null; if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); } }
function startNodeDrag(event, shot, index) { if (event.button !== 0 || event.target.closest('button,textarea,input')) return; const p = positionFor(shot, index); drag = { kind: 'node', key: shot.name, x: event.clientX, y: event.clientY, originalX: p.x, originalY: p.y }; event.currentTarget.setPointerCapture(event.pointerId); }
function moveNodeDrag(event) { if (drag?.kind !== 'node') return; positions[drag.key] = { x: Math.max(0, drag.originalX + (event.clientX - drag.x) / zoom.value), y: Math.max(0, drag.originalY + (event.clientY - drag.y) / zoom.value) }; }
function endNodeDrag(event) { if (drag?.kind === 'node') { persistLayout(); drag = null; if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); } }
function selectShot(shot, index) { activeClipName.value = props.clips.find(clip => clip.shot === shot.name)?.name || null; emit('select-shot', shot, index); elapsed.value = 0; }
function draftFor(shot) { return shot.name in drafts ? drafts[shot.name] : shot.generation_prompt || shot.storyboard_action || ''; }
function promptDirty(shot) { return String(draftFor(shot)).trim() !== String(shot.generation_prompt || shot.storyboard_action || '').trim(); }
function setDraft(shot, value) { drafts[shot.name] = value; }
function saveDraft(shot) { if (!props.canEdit) return; const value = String(drafts[shot.name] ?? '').trim(); if (value && value !== String(shot.generation_prompt || '').trim()) emit('save-prompt', shot, value); }
function togglePlayback() { const player = videoRef.value; if (!player) return; if (player.paused) player.play().catch(() => { playing.value = false; }); else player.pause(); }
function onTimeUpdate(event) { elapsed.value = event.target.currentTime || 0; }
function clipTitle(_clip, index) { return `${t('Clip', 'Đoạn')} ${index + 1}`; }
function clipDescription(clip, index) { const shot = props.shots.find(row => row.name === clip.shot); const number = shot?.shot_number || clip.shot_number; const source = number ? `${t('Shot', 'Cảnh')} ${number}` : t('Unlinked scene', 'Chưa gắn cảnh'); return `${clipTitle(clip, index)} · ${source} · ${formatDuration(clip.duration_seconds)}`; }
function audioTitle(clip) { return clip.audio_role === 'Voiceover' ? t('Voiceover', 'Lời thoại') : clip.audio_role === 'Source' ? t('Scene audio', 'Âm thanh cảnh') : clip.audio_role === 'Music' ? t('Music', 'Nhạc') : clip.source_asset_name || t('Audio', 'Âm thanh'); }
function clipStyle(clip, index = 0) { const start = Number(clip.timeline_start_frame || 0) / Math.max(1, props.fps); const duration = Number(clip.duration_frames || 0) / Math.max(1, props.fps) || totalSeconds.value / Math.max(1, props.clips.length); return { left: `${Math.max(0, start / totalSeconds.value * 100)}%`, width: `${Math.max(3, Math.min(100, duration / totalSeconds.value * 100))}%`, zIndex: index + 1 }; }
function audioStyle(clip) { return clipStyle(clip); }
let pendingSeekSeconds = null;
function applyPendingSeek() { const player = videoRef.value; if (player && pendingSeekSeconds !== null && player.readyState >= 1) { player.currentTime = Math.max(0, Math.min(pendingSeekSeconds, Number.isFinite(player.duration) ? player.duration : pendingSeekSeconds)); pendingSeekSeconds = null; } }
function selectClip(clip, timelineSeconds = Number(clip.timeline_start_frame || 0) / Math.max(1, props.fps)) {
	const index = shotIndexForClip(props.shots, clip);
	if (index < 0) { emit('open-timeline', clip); return; }
	activeClipName.value = clip.name;
	emit('select-shot', props.shots[index], index);
	pendingSeekSeconds = props.finalVideo?.file ? timelineSeconds : sourceSecondsForTimeline(clip, timelineSeconds, props.fps);
	elapsed.value = pendingSeekSeconds;
	nextTick(applyPendingSeek);
}
function seekTimeline(seconds) {
	const target = Math.max(0, Math.min(totalSeconds.value, seconds));
	const clip = clipAtSeconds(orderedClips.value, target, props.fps);
	if (clip) selectClip(clip, target);
}
</script>

<style scoped>
.rio-studio{--rio-cyan:var(--primary-accent);--rio-line:var(--outline-border);--rio-muted:var(--ink-muted);display:flex;flex-direction:column;min-height:0;height:100%;width:100%;background:#070b10;color:#ecf7fb;font:13px Inter,system-ui,sans-serif}.rio-studio button{cursor:pointer}.rio-studio button:disabled{opacity:.4;cursor:not-allowed}.rio-header{height:52px;flex:none;display:flex;align-items:center;gap:18px;padding:0 16px;border-bottom:1px solid var(--rio-line);background:#080d13}.rio-brand{display:flex;align-items:center;gap:8px;white-space:nowrap}.rio-brand-mark{font-size:29px;line-height:1;color:var(--rio-cyan);text-shadow:0 0 14px var(--rio-cyan)}.rio-brand strong{font-size:17px;letter-spacing:1px}.rio-brand strong span{color:var(--rio-cyan)}.rio-status{display:inline-flex;align-items:center;gap:6px;border:1px solid #166b61;border-radius:30px;background:#08352d;color:#47dfb8;padding:3px 9px;font-size:10px;font-weight:700}.rio-status.is-busy{border-color:#8e6918;background:#3b2c0e;color:#ffd063}.rio-status i{width:6px;height:6px;border-radius:50%;background:currentColor}.rio-project-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#b7c9d2;font-weight:600;flex:1}.rio-header-actions{display:flex;gap:7px}.rio-header-actions button,.rio-canvas-controls button{min-width:29px;height:29px;border:1px solid #293e4b;border-radius:7px;background:#111a26;color:#d4f8fa}.rio-header-actions button:hover,.rio-canvas-controls button:hover{border-color:var(--rio-cyan);color:var(--rio-cyan)}.rio-header-actions .rio-classic{font-size:11px;padding:0 9px}.rio-alert{padding:8px 14px;color:#ffb8be;background:#36131b;border-bottom:1px solid #8c3545}.rio-alert button{margin-left:10px;text-decoration:underline}.rio-work-area{display:flex;flex:1;min-height:160px}.rio-assets{width:290px;flex:none;display:flex;flex-direction:column;background:#0b111a;border-right:1px solid var(--rio-line);min-height:0}.rio-assets-head{display:flex;justify-content:space-between;align-items:center;padding:12px;color:var(--rio-cyan);letter-spacing:1px;border-bottom:1px solid var(--rio-line)}.rio-assets-head button,.rio-add-media{border:1px solid #137888;border-radius:7px;background:#0a2833;color:var(--rio-cyan);padding:4px 9px}.rio-assets-list{overflow:auto;flex:1;padding:9px}.rio-asset{display:flex;gap:9px;width:100%;align-items:center;text-align:left;padding:7px;border:1px solid transparent;border-radius:8px;background:transparent;color:#e8f3f8}.rio-asset:hover,.rio-asset.selected{border-color:#1c8ba0;background:#122533}.rio-asset :deep(img),.rio-asset :deep(video){width:50px;height:50px;object-fit:cover;border-radius:5px}.rio-asset span{min-width:0;display:flex;flex-direction:column}.rio-asset strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px}.rio-asset small{color:var(--rio-muted);font-size:10px}.rio-empty-assets{padding:16px 6px;color:var(--rio-muted)}.rio-add-media{margin:9px;text-align:center}.rio-canvas{position:relative;overflow:hidden;flex:1;min-width:0;background-color:#050a10;background-image:linear-gradient(#0b273177 1px,transparent 1px),linear-gradient(90deg,#0b273177 1px,transparent 1px);background-size:24px 24px;touch-action:none}.rio-canvas-inner{position:absolute;inset:0;transform-origin:0 0}.rio-connections{position:absolute;left:0;top:0;overflow:visible;pointer-events:none}.rio-connections path{fill:none;stroke:#087e9c;stroke-width:2.5;filter:drop-shadow(0 0 4px #00e5f288)}.rio-node{position:absolute;width:380px;min-height:430px;border:1px solid #344755;border-radius:13px;background:#171e2a;box-shadow:0 12px 35px #000b;touch-action:none}.rio-node.active{border-color:var(--rio-cyan);box-shadow:0 0 0 1px #00e5f255,0 16px 40px #000c}.rio-node-head{height:39px;display:flex;align-items:center;gap:8px;padding:0 11px;border-bottom:1px solid #2c3746}.rio-node-head>span:first-child{flex:1}.rio-node-ratio{color:#57dcb9;background:#103e39;border:1px solid #236b65;border-radius:4px;font-size:9px;padding:2px 5px}.rio-node-head button{font-size:20px;color:#9cb0bc;padding:0 3px}.rio-node-preview{display:flex;width:calc(100% - 22px);height:190px;margin:10px 11px;align-items:center;justify-content:center;overflow:hidden;border:1px solid #0a202a;border-radius:9px;background:#070b11;color:var(--rio-muted)}.rio-node-preview img{width:100%;height:100%;object-fit:contain}.rio-node-preview span{display:flex;flex-direction:column;align-items:center;font-size:11px}.rio-node-preview b{font-size:26px;color:var(--rio-cyan)}.rio-node-body{padding:4px 11px 8px}.rio-node-body label{display:block;margin-bottom:5px;font-size:11px;color:#b5c5d3}.rio-node-body textarea{width:100%;min-height:70px;resize:vertical;padding:8px;border:1px solid #243445;border-radius:6px;background:#0a1019;color:#eef7fb;font:11px/1.45 inherit}.rio-node-body textarea:focus{outline:1px solid var(--rio-cyan)}.rio-reference-line{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--rio-muted);font-size:10px}.rio-node-actions{display:flex;gap:6px;padding:0 11px 11px}.rio-node-actions button{flex:1;padding:6px 5px;border:1px solid #245e70;border-radius:6px;background:#102634;color:#84eafb;font-size:11px;font-weight:700}.rio-node-actions button:nth-child(2){border-color:#5d408a;color:#d5afff;background:#2d213d}.rio-node-actions button:nth-child(3){border-color:#2d4656;color:#d7e6ec;background:#172533}.rio-node-actions button:hover{filter:brightness(1.35)}.rio-port{position:absolute;top:205px;width:20px;height:20px;border-radius:50%;border:2px solid #07131a;box-shadow:0 0 12px currentColor}.rio-port-in{left:-11px;background:#a855f7;color:#a855f7}.rio-port-out{right:-11px;background:var(--rio-cyan);color:var(--rio-cyan)}.rio-canvas-controls{position:absolute;left:12px;bottom:12px;display:flex;align-items:center;gap:4px;padding:4px;border:1px solid var(--rio-line);border-radius:9px;background:#0b1520e8}.rio-canvas-controls span{min-width:40px;text-align:center;color:var(--rio-cyan);font-size:11px}.rio-minimap{position:absolute;right:12px;top:12px;width:130px;height:85px;border:1px solid #166a7b;border-radius:7px;background:#091a26eb;pointer-events:none;overflow:hidden}.rio-minimap span{position:absolute;left:7px;top:4px;color:var(--rio-muted);font-size:9px}.rio-minimap div{position:absolute;width:15px;height:10px;border:1px solid var(--rio-cyan);border-radius:2px;background:#14546999}.rio-empty-canvas{position:absolute;top:22%;left:50%;transform:translateX(-50%);text-align:center;color:#d9e6e8}.rio-empty-canvas p{margin:8px;color:var(--rio-muted)}.rio-empty-canvas button{margin-top:10px;border:1px solid var(--rio-cyan);border-radius:7px;padding:7px 11px;color:var(--rio-cyan)}.rio-bottom{height:220px;display:flex;gap:5px;flex:none;padding:5px;border-top:1px solid #113a49;background:#05080d}.rio-timeline{flex:1;min-width:0;border:1px solid var(--rio-line);border-radius:8px;overflow:hidden;background:#070d14}.rio-timeline-head{height:37px;display:flex;align-items:center;gap:9px;padding:0 9px;border-bottom:1px solid var(--rio-line)}.rio-timeline-head>button:first-child{background:var(--rio-cyan);color:#041018;border-radius:7px;width:27px;height:25px;font-weight:900}.rio-timeline-head strong{color:#d9f7fa;font-size:10px;letter-spacing:1px}.rio-timeline-head span{flex:1;color:var(--rio-muted);font-size:10px}.rio-timeline-head button:not(:first-child){border:1px solid #2c5263;border-radius:6px;padding:4px 8px;color:#aeeaf1;font-size:10px}.rio-timeline-head .rio-export{background:linear-gradient(90deg,#074d61,#503281);color:white!important;font-weight:700}.rio-ruler{position:relative;height:25px;margin-left:34px;border-bottom:1px solid var(--rio-line)}.rio-ruler span{position:absolute;top:6px;color:#6e8597;font-size:9px}.rio-track{display:flex;height:57px;border-bottom:1px solid var(--rio-line)}.rio-track>b{width:34px;display:grid;place-items:center;border-right:1px solid var(--rio-line);color:#90c1cb}.rio-track-content{position:relative;flex:1;min-width:0}.rio-video-clip,.rio-audio-clip{position:absolute;top:8px;height:38px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left;padding:8px;border:1px solid #15a7bb;border-radius:5px;background:#103b4c;color:#ddfbff;font-size:10px}.rio-audio-clip{border-color:#7942a5;background:#382348;color:#eed1ff}.rio-track-empty{display:block;margin:16px;color:#536675;font-size:10px}.rio-monitor{width:30%;min-width:220px;display:flex;flex-direction:column;border:1px solid #087c91;border-radius:8px;overflow:hidden;background:#010306}.rio-monitor-head{display:flex;justify-content:space-between;padding:5px 9px;color:#85bac4;font-size:9px;letter-spacing:.8px}.rio-monitor-head time{color:var(--rio-cyan)}.rio-monitor video,.rio-monitor img{width:100%;height:calc(100% - 23px);object-fit:contain}.rio-monitor-empty{display:flex;flex:1;flex-direction:column;align-items:center;justify-content:center;color:#8294a2;font-size:23px}.rio-monitor-empty span{font-size:10px}@media(max-width:900px){.rio-project-name{display:none}.rio-assets{width:210px}.rio-bottom{height:185px}.rio-monitor{min-width:180px}}@media(max-width:640px){.rio-assets{position:absolute;left:0;top:0;bottom:0;z-index:5;box-shadow:10px 0 30px #0009}.rio-header-actions .rio-classic{display:none}.rio-monitor{display:none}.rio-node{width:380px}}
.rio-studio{flex:1;height:auto}
.rio-header-actions .rio-next-action{padding:0 12px;border-color:#087f91;background:#06313e;color:#a9f3fb;font-weight:700;white-space:nowrap}
.rio-empty-canvas textarea{display:block;width:min(460px,80vw);margin:14px auto 0;padding:10px;border:1px solid #2b5867;border-radius:7px;background:#0d1923;color:#eef7fb;font:inherit;resize:vertical}
.rio-empty-canvas textarea:focus{outline:1px solid var(--rio-cyan)}
.rio-work-area{position:relative}
.rio-asset-main{display:flex;align-items:center;gap:9px;flex:1;min-width:0;text-align:left}
.rio-asset-main span{min-width:0}
.rio-asset-assign{flex:none;border:1px solid #245e70;border-radius:6px;padding:5px 7px;background:#102634;color:var(--rio-cyan);font-size:14px}
.rio-asset-assign:hover{border-color:var(--rio-cyan)}
.rio-assets{margin:8px 0 8px 8px;border:1px solid #166a7b;border-radius:11px;box-shadow:0 0 18px #06b6d426,0 10px 30px #0009;overflow:hidden}.rio-assets-head{height:46px;padding:0 10px;background:#ffffff05}.rio-asset-tools{display:flex;align-items:center;gap:6px}.rio-asset-size{display:flex;border:1px solid var(--rio-line);border-radius:5px;overflow:hidden;background:#090c13}.rio-asset-size button{padding:2px 6px;color:var(--rio-muted);font-size:10px;font-weight:800}.rio-asset-size button.active{background:var(--rio-cyan);color:#061018}.rio-assets-head .rio-asset-plus{height:25px;width:25px;display:grid;place-items:center;padding:0}.rio-assets-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));align-content:start;gap:8px;padding:10px;overflow:auto}.rio-assets-list.size-s{grid-template-columns:repeat(3,minmax(0,1fr))}.rio-assets-list.size-l{grid-template-columns:1fr}.rio-asset-card{position:relative;min-width:0;padding:5px;border:1px solid #1f273b;border-radius:8px;background:#121622;color:#e8f3f8;cursor:grab}.rio-asset-card:hover,.rio-asset-card.selected{border-color:var(--rio-cyan);background:#171d2c;box-shadow:0 0 10px #00f0ff30}.rio-asset-card:active{cursor:grabbing}.rio-asset-card .rio-asset-main{width:100%;display:flex;flex-direction:column;gap:5px;text-align:center}.rio-asset-thumb{position:relative;display:block;width:100%;aspect-ratio:1;background:#0006;border:1px solid #ffffff12;border-radius:6px;overflow:hidden}.rio-assets-list.size-l .rio-asset-thumb{aspect-ratio:16/9}.rio-asset-thumb :deep(img),.rio-asset-thumb :deep(video){width:100%;height:100%;object-fit:cover}.rio-asset-main strong{display:block;width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;font-weight:600}.rio-asset-badge{position:absolute;top:4px;left:4px;display:flex;align-items:center;gap:3px;padding:2px 5px;border:1px solid #fde68a;border-radius:5px;background:#b45309;color:#fff;font-size:8px;font-weight:800;box-shadow:0 2px 7px #000a}.rio-asset-badge.character{background:#7e22ce;border-color:#d8b4fe}.rio-asset-badge.environment{background:#047857;border-color:#a7f3d0}.rio-asset-badge.audio{background:#4338ca;border-color:#c7d2fe}.rio-asset-badge.motion{background:#0284c7;border-color:#bae6fd}.rio-assets-list.size-s .rio-asset-badge span{display:none}.rio-asset-card .rio-asset-assign{position:absolute;right:8px;top:8px;padding:2px 5px;background:#102634d9}.rio-empty-assets{grid-column:1/-1}
.rio-asset-card{overflow:visible}.rio-asset-image{display:block;width:100%;height:100%;padding:0}.rio-asset-name{display:block;width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:3px 2px;color:#e8f3f8;text-align:center;font-size:11px;font-weight:600}.rio-asset-name:hover{color:var(--rio-cyan);background:#00f0ff12}.rio-asset-name-edit input{width:100%;padding:3px;border:1px solid var(--rio-cyan);border-radius:4px;background:#090c14;color:white;text-align:center;font-size:11px}.rio-asset-badge{cursor:pointer}.rio-category-menu{position:absolute;z-index:30;top:28px;left:5px;min-width:132px;padding:4px;border:1px solid var(--rio-line);border-radius:6px;background:#111a26;box-shadow:0 6px 16px #000b}.rio-category-menu button{display:block;width:100%;padding:5px;text-align:left;color:#dcecf2;font-size:11px}.rio-category-menu button:hover{background:#164555}.rio-asset-remove{position:absolute;top:5px;right:5px;display:none;width:19px;height:19px;border:1px solid #fda4af;border-radius:50%;background:#be123c;color:white;font-weight:800;line-height:15px}.rio-asset-card:hover .rio-asset-remove,.rio-asset-remove:focus{display:block}.rio-asset-card:has(.rio-category-menu) .rio-asset-remove{display:none}.rio-asset-card .rio-asset-assign{top:auto;bottom:26px;right:7px}
.rio-details{position:absolute;right:12px;top:108px;z-index:15;width:270px;max-height:calc(100% - 168px);overflow:auto;padding:12px;border:1px solid #176d80;border-radius:9px;background:#0d1722f5;box-shadow:0 12px 28px #000b;color:#e8f3f8}.rio-details header{display:flex;align-items:center;justify-content:space-between;margin:-3px 0 10px}.rio-details header button{font-size:20px;color:#9cb0bc}.rio-details p{margin:8px 0;overflow-wrap:anywhere;font-size:12px}.rio-details h4{margin:12px 0 7px;color:var(--rio-cyan);font-size:11px}.rio-details-preview{max-height:160px;max-width:100%;margin:auto;object-fit:contain}.rio-details :deep(img),.rio-details :deep(video){max-height:160px;object-fit:contain}.rio-details-references{display:flex;flex-wrap:wrap;gap:5px}.rio-details-references span{padding:4px 6px;border:1px solid #275668;border-radius:5px;background:#132936;font-size:10px}.rio-details-references span button{margin-left:3px;color:#ffb4bd}.rio-details-references small{color:var(--rio-muted)}.rio-details-action{width:100%;margin-top:12px;padding:7px;border:1px solid #247f91;border-radius:6px;background:#103440;color:var(--rio-cyan);font-weight:700;font-size:11px}
.rio-work-area>.rio-details{position:relative;right:auto;top:auto;z-index:auto;flex:0 0 280px;width:280px;max-height:none;min-height:0;border-width:0 0 0 1px;border-radius:0;box-shadow:none;background:#0d1722;overflow:auto}
.rio-studio{position:relative}.rio-header-link{display:grid;place-items:center;min-height:29px;padding:0 9px;border:1px solid #293e4b;border-radius:7px;background:#111a26;color:#d4f8fa;font-size:11px;white-space:nowrap}.rio-header-link:hover{border-color:var(--rio-cyan);color:var(--rio-cyan)}
.rio-versions{position:absolute;top:52px;right:12px;z-index:30;width:min(700px,calc(100vw - 24px));max-height:min(480px,70vh);overflow:auto;padding:12px;border:1px solid #176d80;border-radius:0 0 10px 10px;background:#0d1722;box-shadow:0 18px 45px #000d}.rio-versions>header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}.rio-versions>header button{font-size:20px;color:#c6dbe4}.rio-versions :deep([data-test="video-shelf"]){border-color:#275668;background:#101d29}.rio-versions :deep([data-test="video-shelf"] li){background:#12202d}
.rio-header-actions button[aria-pressed="true"]{border-color:var(--rio-cyan);color:var(--rio-cyan)}
.rio-guidance{flex:none;margin:0;padding:9px 16px;border-bottom:1px solid #21475a;background:#0d1b27;color:#c4e8f0;font-size:12px;line-height:1.45}
.rio-studio :is(button,a,textarea,input):focus-visible{outline:2px solid var(--rio-cyan);outline-offset:2px}
.rio-node-actions{flex-wrap:wrap}.rio-node-actions button{min-height:34px;min-width:calc(50% - 4px);font-size:12px}
.rio-header-actions button,.rio-canvas-controls button,.rio-header-link{min-height:34px}
.rio-ruler input[type="range"]{position:absolute;inset:0;width:100%;height:100%;margin:0;background:transparent;appearance:none;cursor:pointer}
.rio-ruler input[type="range"]::-webkit-slider-runnable-track{height:2px;background:#306073}
.rio-ruler input[type="range"]::-moz-range-track{height:2px;background:#306073}
.rio-ruler input[type="range"]::-webkit-slider-thumb{width:12px;height:12px;margin-top:-5px;border:2px solid #061018;border-radius:50%;background:#22d3ee;appearance:none;box-shadow:0 0 0 2px #22d3ee66}
.rio-ruler input[type="range"]::-moz-range-thumb{width:10px;height:10px;border:2px solid #061018;border-radius:50%;background:#22d3ee}
.rio-timeline{overflow-y:auto;overflow-x:hidden}
.rio-ruler{margin-left:88px}
.rio-track>b{width:88px;flex:none;padding:0 5px;text-align:center;font-size:10px;line-height:1.2;overflow:hidden;text-overflow:ellipsis}
.rio-timeline-head{position:sticky;top:0;z-index:10;background:#070d14}
.rio-audio-add{position:relative}
.rio-timeline-head .rio-audio-add>button,.rio-audio-add-menu button{border:1px solid #2c5263;border-radius:6px;padding:4px 8px;color:#aeeaf1;font-size:11px}
.rio-audio-add-menu{position:fixed;z-index:50;display:flex;flex-direction:column;gap:3px;padding:5px;border:1px solid #267d8f;border-radius:7px;background:#111c29;box-shadow:0 10px 20px #000a}
.rio-audio-add-menu button{text-align:left;white-space:nowrap}
.rio-audio-add-menu button:hover{background:#123747}
.rio-audio-row{flex:none}
.rio-audio-clip.is-selected{border-color:#dfb6ff;box-shadow:inset 0 0 0 1px #dfb6ff}
.rio-audio-clip.is-disabled{opacity:.48;text-decoration:line-through}
.rio-audio-actions{display:flex;align-items:center;gap:7px;min-height:40px;padding:5px 10px;color:#e9d5ff;border-top:1px solid #51336d}
.rio-audio-actions strong{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px}
.rio-audio-actions button{border:1px solid #6d5090;border-radius:5px;padding:4px 8px;color:#efd8ff;font-size:11px}
.rio-audio-actions button:hover{background:#382348}
.rio-work-area>.rio-details{flex-basis:330px;width:330px;padding:16px}
.rio-details header{margin:0 0 14px;padding-bottom:10px;border-bottom:1px solid #234457}
.rio-details header strong{font-size:15px}
.rio-details-summary{display:flex;align-items:flex-start;gap:8px;justify-content:space-between}
.rio-details-summary strong{min-width:0;font-size:14px;line-height:1.4}
.rio-details-summary span{flex:none;padding:3px 6px;border:1px solid #315a69;border-radius:5px;color:#b8d6e1;font-size:11px}
.rio-details-frame{display:grid;place-items:center;min-height:110px;margin-top:12px;border:1px solid #263e4b;border-radius:7px;background:#070d14}
.rio-details-frame p{color:#8da9b6}
.rio-details-preview{max-height:190px}
.rio-details-status{margin:8px 0 0!important;color:#9fcdd3;font-size:11px!important}
.rio-details h4{margin:18px 0 7px;font-size:11px;text-transform:uppercase;letter-spacing:.5px}
.rio-details-action-text{margin:0!important;color:#d5e7ee;line-height:1.5;white-space:pre-wrap}
.rio-details-references{display:flex;flex-direction:column;gap:7px}
.rio-details-references .rio-details-reference{display:flex;align-items:center;gap:8px;min-width:0;padding:7px;border:1px solid #275668;border-radius:6px;background:#132936}
.rio-details-reference-icon{flex:none;color:#6ee7f0}
.rio-details-reference-copy{display:flex;flex:1;min-width:0;flex-direction:column;gap:2px}
.rio-details-reference-copy small{color:#9bb7c4;font-size:10px}
.rio-details-reference-copy strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;font-weight:600}
.rio-details-references .rio-details-reference button{flex:none;min-width:26px;min-height:26px;margin:0;border-radius:5px;color:#ffbec5;font-size:17px}
.rio-details-references .rio-details-reference button:hover{background:#63313c}
.rio-video-clip.selected{border-color:#67e8f9;background:#10536a;box-shadow:inset 0 0 0 1px #67e8f9}
.rio-node-body textarea{font-size:13px;line-height:1.5}
.rio-node-body label,.rio-reference-line,.rio-asset-name,.rio-details-action{font-size:12px}
.rio-node-preview span,.rio-track-empty,.rio-monitor-empty span{font-size:12px}
.rio-timeline-head strong,.rio-timeline-head span,.rio-timeline-head button:not(:first-child),.rio-monitor-head{font-size:11px}
.rio-studio button:disabled{cursor:not-allowed;opacity:.48}
@media(max-width:1100px){.rio-header{gap:9px;padding:0 10px}.rio-header-actions{max-width:60%;overflow-x:auto;flex:none}.rio-project-name{min-width:80px}}
@media(max-width:900px){.rio-work-area>.rio-details{flex-basis:220px;width:220px}}
@media(max-width:640px){.rio-work-area>.rio-details{position:absolute;right:0;top:0;bottom:0;z-index:20;width:min(300px,85vw);box-shadow:-10px 0 30px #0009}}
@media(max-width:640px){.rio-bottom{height:255px;flex-direction:column;overflow:auto}.rio-timeline{flex:none;min-height:120px}.rio-monitor{display:flex;flex:none;width:100%;min-width:0;height:125px}.rio-monitor video,.rio-monitor img{max-height:100px}.rio-header-actions{max-width:70%}.rio-guidance{font-size:11px}}
</style>

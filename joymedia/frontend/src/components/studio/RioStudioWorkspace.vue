<template>
	<div v-if="missing" class="rio-studio rio-missing" data-test="rio-missing">
		<div class="rio-missing-box" role="alert">
			<span class="rio-missing-icon" aria-hidden="true">⚠</span>
			<h2>{{ t('This project is no longer available', 'Dự án này không còn nữa') }}</h2>
			<p>{{ t('It may have been removed, or the link is out of date. Go back to your videos to continue.', 'Dự án có thể đã bị xoá hoặc đường dẫn đã cũ. Hãy quay lại danh sách video để tiếp tục.') }}</p>
			<a class="rio-missing-link" href="/joymedia/projects">{{ t('Back to my videos', 'Về danh sách video') }}</a>
		</div>
	</div>
	<div v-else class="rio-studio" data-test="rio-studio">
		<header class="rio-header">
			<div class="rio-brand" aria-label="JoyMedia">
				<span class="rio-brand-mark" aria-hidden="true">◇</span>
				<strong>JOY<span>MEDIA</span></strong>
				<button type="button" class="rio-status" :aria-expanded="statusOpen" :title="t('Show production status', 'Xem tiến độ sản xuất')" @click="statusOpen = !statusOpen" :class="{ 'is-busy': busy, 'is-attention': automaticVariant?.status === 'Needs Attention' || ['Failed', 'Needs Attention'].includes(projectStatus) }"><i />{{ statusLabel }} <small aria-hidden="true">⌄</small></button>
			</div>
			<div class="rio-project-name" :title="projectTitle">{{ projectTitle }}</div>
			<div class="rio-header-actions">
				<div class="rio-template-anchor">
					<button type="button" class="rio-template-trigger" data-test="rio-templates-toggle" :aria-expanded="templatesOpen" aria-controls="rio-template-library" @click="toggleTemplates">🎬 {{ t('Templates', 'Mẫu kịch bản') }} <span aria-hidden="true">⌄</span></button>
					<div v-if="templatesOpen" id="rio-template-library" class="rio-template-menu" data-test="rio-template-library">
						<header><strong>🎬 {{ t('VIDEO TEMPLATE LIBRARY', 'THƯ VIỆN MẪU VIDEO') }}<small v-if="templateTargetShot"> · {{ t('Shot', 'Cảnh') }} {{ templateTargetShot.shot_number }}</small></strong><span>{{ templates.length }} {{ t('templates', 'mẫu') }}</span></header>
						<p v-if="templatesLoading" role="status">{{ t('Loading templates…', 'Đang tải mẫu…') }}</p>
						<p v-else-if="templatesError" role="alert">{{ templatesError }} <button type="button" @click="loadTemplates">{{ t('Retry', 'Thử lại') }}</button></p>
						<p v-else-if="!templates.length">{{ t('No templates available.', 'Chưa có mẫu.') }}</p>
						<div v-for="template in templates" :key="template.id" class="rio-template-item">
							<strong>{{ props.currentLang === 'vi' ? template.title : template.title_en }}</strong>
							<p>{{ props.currentLang === 'vi' ? template.description : template.description_en }}</p>
							<p v-if="template.duration_seconds" class="rio-template-meta">{{ t(`${template.duration_seconds} seconds`, `${template.duration_seconds} giây`) }}<template v-if="template.source_label"> · {{ t('from', 'từ') }} {{ template.source_label }}</template></p>
							<!-- Watching the original is the only way to judge a reproduction. -->
							<button v-if="template.source_video" type="button" class="rio-template-preview-btn" @click="previewTemplate = previewTemplate === template.id ? null : template.id">{{ previewTemplate === template.id ? t('Hide the original', 'Ẩn video gốc') : t('Watch the original', 'Xem video gốc') }}</button>
							<video v-if="previewTemplate === template.id" class="rio-template-video" :src="template.source_video" controls playsinline preload="metadata" />
							<div><button v-if="!shots.length" type="button" :disabled="!canWork || busy" @click="useIdeaTemplate(template)">{{ t('Use for video idea', 'Dùng cho ý tưởng') }}</button><button v-if="shots.length" type="button" :disabled="!canEdit || busy" @click="useSceneTemplate(template)">{{ t('Add to selected scene', 'Thêm vào cảnh chọn') }}</button></div>
						</div>
					</div>
				</div>
				<router-link class="rio-header-link" to="/projects">{{ t('Projects', 'Dự án') }}</router-link>
				<button type="button" data-test="rio-versions-toggle" :aria-expanded="versionsOpen" @click="versionsOpen = !versionsOpen">{{ t('Video versions', 'Các phiên bản') }}</button>
				<button v-if="canRestore" type="button" @click="emit('restore')">{{ t('Restore project', 'Khôi phục dự án') }}</button>
				<button type="button" @click="emit('open-history')">{{ t('History', 'Lịch sử') }}</button>
				<button v-if="canWork && reviewableBatch" type="button" class="rio-next-action" @click="scriptReviewOpen = true">{{ t('Review script & scenes', 'Duyệt kịch bản & cảnh') }}</button>
				<button v-if="canWork && nextActionLabel && !automaticInProgress" type="button" class="rio-next-action" :disabled="busy || (nextAction === 'brief' && !idea?.trim())" @click="emit('continue')">{{ nextActionLabel }}</button>
				<button v-if="canWork" type="button" :title="t('Project settings', 'Cài đặt dự án')" :aria-label="t('Project settings', 'Cài đặt dự án')" @click="emit('settings')">⚙</button>
				<button v-if="canWork" type="button" :disabled="busy" :title="t('Add blank scene', 'Thêm cảnh trống')" :aria-label="t('Add blank scene', 'Thêm cảnh trống')" @click="emit('add-scene')">＋</button>
				<button type="button" :title="t('Character references and identity', 'Tư liệu và nhận dạng nhân vật')" :aria-label="t('Character references and identity', 'Tư liệu và nhận dạng nhân vật')" @click="openCharacters">🎭</button>
				<button type="button" :title="t('Project media', 'Tư liệu dự án')" :aria-label="t('Show or hide project media', 'Hiện hoặc ẩn tư liệu dự án')" :aria-expanded="assetsOpen" @click="assetsOpen = !assetsOpen">▧</button>
				<button type="button" :title="t('Toggle minimap', 'Bật/tắt sơ đồ nhỏ')" :aria-label="t('Toggle minimap', 'Bật/tắt sơ đồ nhỏ')" :aria-pressed="showMinimap" @click="showMinimap = !showMinimap">▦</button>
				<button type="button" :title="t('View and edit the current storyboard', 'Xem và chỉnh sửa phân cảnh hiện tại')" :aria-label="t('Storyboard editor', 'Bảng phân cảnh')" @click="emit('slice-storyboard')">▦▦</button>
				<button type="button" :title="t('Fit canvas', 'Toàn cảnh')" :aria-label="t('Fit all scenes on screen', 'Hiện tất cả cảnh trên màn hình')" @click="fitCanvas">⛶</button>
				<button type="button" :title="t('Fullscreen', 'Toàn màn hình')" :aria-label="t('Fullscreen', 'Toàn màn hình')" @click="toggleFullscreen">⛶+</button>
			</div>
		</header>
		<div v-if="versionsOpen" class="rio-versions" data-test="rio-versions"><header><strong>{{ t('Versions & comparison', 'Phiên bản & so sánh') }}</strong><button type="button" :aria-label="t('Close versions', 'Đóng phiên bản')" @click="versionsOpen = false">×</button></header><VideoShelf :project="projectName" :readonly="!canWork" embedded /></div>
		<div v-if="statusOpen" class="rio-status-panel">
		<p v-if="automaticInProgress" class="rio-guidance" role="status">{{ automaticMessage }} <span v-if="shots.length && automaticVariant.status === 'Needs Attention'">{{ automaticFailureReason }}</span></p>
		<p v-else-if="nextActionHint && !error" class="rio-guidance" role="status">{{ nextActionHint }}</p>
		<ProjectStages :project="project" :production="production" :automatic="automaticVariant" :shots="shots" :assets="assets" :frames="frames" :current-lang="currentLang" />
		</div>
		<div v-if="error" class="rio-alert" role="alert">{{ error }} <button type="button" @click="emit('retry')">{{ t('Retry', 'Thử lại') }}</button></div>
		<div class="rio-work-area">
			<aside v-if="assetsOpen" class="rio-assets" :class="{ 'is-drop-target': fileDragDepth > 0 }" :style="{ width: `${drawerWidth}px` }" :aria-label="t('Project media', 'Tư liệu dự án')" @dragenter="onFileDragEnter" @dragover="onFileDragOver" @dragleave="onFileDragLeave" @drop="onFileDrop">
				<div class="rio-drawer-resize" :title="t('Drag to change the panel width', 'Kéo để đổi độ rộng')" @pointerdown="startDrawerResize" @pointermove="moveDrawerResize" @pointerup="endDrawerResize" @pointercancel="endDrawerResize" />
				<div class="rio-assets-head"><strong>◇ {{ t('ASSETS', 'TƯ LIỆU') }}</strong><div class="rio-asset-tools"><div class="rio-asset-size" :aria-label="t('Thumbnail size', 'Cỡ ảnh')"><button v-for="size in ['s', 'm', 'l']" :key="size" type="button" :class="{ active: assetSize === size }" :aria-pressed="assetSize === size" @click="assetSize = size">{{ size.toUpperCase() }}</button></div><button v-if="canWork" type="button" class="rio-asset-plus" :title="t('Add media', 'Thêm tư liệu')" @click="emit('open-media')">＋</button></div></div>
				<div ref="assetListRef" class="rio-assets-list" :class="`size-${assetSize}`" @pointerdown="startMarquee">
					<div v-for="asset in displayedAssets" :key="asset.asset_version || asset.name" class="rio-asset-card" :class="{ selected: selectedAsset?.asset_version === asset.asset_version, 'is-multi-selected': selectedAssetKeys.includes(assetKey(asset)) }" :data-asset-key="assetKey(asset)" :draggable="canEdit && Boolean(asset.reference_key)" @dragstart="startAssetDrag($event, asset)" @dragend="draggedAsset = null">
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
				<div v-if="marquee.visible" class="rio-marquee" :style="marqueeStyle" aria-hidden="true" />
				<div v-if="selectedAssetKeys.length" class="rio-batch-bar" role="status">
					<span>📌 {{ t('Selected', 'Đã chọn') }} <b>{{ selectedAssetKeys.length }}</b></span>
					<div class="rio-batch-actions">
						<button v-if="canEdit" type="button" class="rio-batch-remove" :disabled="busy" :title="t('Remove the selected media from this project (Delete)', 'Gỡ các tư liệu đã chọn khỏi dự án (Delete)')" @click="removeSelectedAssets">🗑 {{ t('Remove', 'Gỡ') }} ({{ selectedAssetKeys.length }})</button>
						<button type="button" class="rio-batch-cancel" :title="t('Clear selection (Esc)', 'Bỏ chọn (Esc)')" :aria-label="t('Clear selection', 'Bỏ chọn')" @click="clearAssetSelection">✖</button>
					</div>
				</div>
				<p v-if="fileDragDepth > 0" class="rio-drop-hint" role="status">{{ t('Drop files to add them to your media library', 'Thả tệp để thêm vào thư viện tư liệu') }}</p>
			</aside>
			<section class="rio-canvas" ref="canvasRef" :aria-label="t('Scene canvas', 'Sơ đồ cảnh')" @pointerdown="startPan" @pointermove="movePan" @pointerup="endPan" @pointercancel="endPan">
				<div class="rio-canvas-inner" :style="{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }">
					<svg class="rio-connections" :width="canvasWidth" :height="canvasHeight" aria-hidden="true">
						<path v-for="link in links" :key="link.key" :d="link.d" :class="{ continues: link.continues }" />
					</svg>
					<!-- Plain-language control for continuity_mode, which decides whether a scene reuses the previous scene's ending. -->
					<button v-for="link in links" :key="`link-${link.key}`" type="button" class="rio-link-toggle" :class="{ continues: link.continues }" :style="{ left: `${link.midX}px`, top: `${link.midY}px` }" :disabled="!canEdit || busy || link.busy" :title="link.hint" :aria-label="link.hint" @pointerdown.stop @click.stop="toggleContinuity(link)">{{ link.continues ? t('Continues', 'Tiếp nối') : t('New scene', 'Cảnh mới') }}</button>
					<article v-for="(shot, index) in shots" :key="shot.name" class="rio-node" :class="{ active: index === selectedShotIndex, compact: compactShots.has(shot.name) }" :style="nodeStyle(shot, index)" @pointerdown.stop="startNodeDrag($event, shot, index)" @pointermove.stop="moveNodeDrag" @pointerup.stop="endNodeDrag" @pointercancel.stop="endNodeDrag" @dragover.prevent @drop.prevent.stop="dropAssetOnShot($event, shot)">
						<div class="rio-node-head"><span>🎬 <strong>{{ t('Shot', 'Cảnh') }} {{ String(shot.shot_number || index + 1).padStart(2, '0') }}</strong></span><span class="rio-node-ratio" :class="{ working: isShotBusy(shot) }">{{ isShotBusy(shot) ? t('WORKING…', 'ĐANG TẠO…') : ratioLabel }}</span><button type="button" class="rio-node-collapse" :title="compactShots.has(shot.name) ? t('Expand scene', 'Mở rộng cảnh') : t('Collapse scene', 'Thu gọn cảnh')" :aria-expanded="!compactShots.has(shot.name)" @click.stop="toggleCompact(shot)">{{ compactShots.has(shot.name) ? '+' : '−' }}</button><button type="button" :title="t('Scene details', 'Chi tiết cảnh')" :aria-label="t('Scene details', 'Chi tiết cảnh')" @click.stop="openShotDetails(shot, index)">⋯</button></div>
						<button v-show="!compactShots.has(shot.name)" type="button" class="rio-node-preview" @click.stop="selectShot(shot, index)">
							<img v-if="frameFor(shot)" :src="frameFor(shot)" :alt="shot.shot_name || `Shot ${index + 1}`" />
							<span v-else><b>🖼️</b>{{ t('No first frame / video yet', 'Chưa có ảnh đầu cảnh / video') }}</span>
						</button>
						<div v-show="!compactShots.has(shot.name)" class="rio-node-body">
							<div class="rio-prompt-heading"><label :for="`rio-prompt-${shot.name}`">{{ t('Prompt', 'Mô tả cảnh') }}</label><button type="button" :title="t('Inspect this scene', 'Xem chi tiết cảnh')" :aria-label="t('Inspect this scene', 'Xem chi tiết cảnh')" @click.stop="openShotDetails(shot, index)">👁</button><button type="button" class="rio-dictate" :class="{ listening: dictatingShot === shot.name }" :disabled="!canEdit || !speechSupported || busy || isShotBusy(shot)" :title="dictatingShot === shot.name ? t('Stop dictating', 'Dừng đọc') : t('Dictate this scene description', 'Đọc mô tả cảnh')" :aria-label="dictatingShot === shot.name ? t('Stop dictating', 'Dừng đọc') : t('Dictate this scene description', 'Đọc mô tả cảnh')" :aria-pressed="dictatingShot === shot.name" @click.stop="toggleDictation(shot)">🎙</button><button type="button" :disabled="!canEdit || busy || isShotBusy(shot)" :title="t('Prompt library', 'Thư viện gợi ý')" :aria-label="t('Open prompt library for this scene', 'Mở thư viện gợi ý cho cảnh này')" @click.stop="openSceneTemplates(shot)">▤</button></div>
							<textarea :placeholder="t('Describe this scene…', 'Mô tả cảnh bạn muốn tạo…')" :id="`rio-prompt-${shot.name}`" :value="draftFor(shot)" :disabled="!canEdit || busy || isShotBusy(shot)" rows="3" @input="setDraft(shot, $event.target.value)" @keydown.ctrl.enter.prevent="saveDraft(shot)" @keydown.meta.enter.prevent="saveDraft(shot)" />
							<div v-if="shotReferenceKeys(shot).length" class="rio-reference-line" :title="shot.references.map(reference => referenceLabel(reference)).join(' · ')">{{ shot.references.map(reference => referenceLabel(reference)).join(' · ') }}</div>
						</div>
							<div v-show="!compactShots.has(shot.name)" class="rio-node-actions">
								<button v-if="canWork && frameNeedsApproval(shot)" type="button" :disabled="busy || isShotBusy(shot)" :title="t('Approve this first frame', 'Duyệt ảnh đầu cảnh')" @click.stop="emit('approve-frame', shot.name, true)">{{ t('Approve image', 'Duyệt ảnh') }}</button>
								<button v-if="canEdit && promptDirty(shot)" type="button" :disabled="busy || isShotBusy(shot)" @click.stop="saveDraft(shot)">{{ t('Save', 'Lưu') }}</button>
								<button v-if="canWork" type="button" class="rio-action-f0" :disabled="busy || isShotBusy(shot) || !storyboardApproved || promptDirty(shot)" :title="!storyboardApproved ? t('Approve storyboard first', 'Duyệt bảng phân cảnh trước') : promptDirty(shot) ? t('Save the scene description first', 'Lưu mô tả cảnh trước') : t('Generate or redraw this scene’s first image', 'Tạo hoặc vẽ lại ảnh đầu cảnh')" @click.stop="emit('draw-shot', shot)">✨ F0</button>
								<button type="button" class="rio-action-settings" :title="t('Scene and video settings', 'Cài đặt cảnh và video')" @click.stop="openShotDetails(shot, index)">🎬 {{ t('Clip', 'Clip') }}</button>
								<button v-if="canWork" type="button" class="rio-action-render" :disabled="!canEdit || busy || isShotBusy(shot) || !frameFor(shot) || frameNeedsApproval(shot)" :title="!canEdit ? t('Scene rendering requires a production role', 'Dựng từng cảnh cần quyền sản xuất') : frameNeedsApproval(shot) ? t('Approve the scene image first', 'Duyệt ảnh cảnh trước') : t('Generate this scene’s video', 'Tạo video cho cảnh này')" @click.stop="emit('render-shot', shot)">ϟ Render</button>
								<button type="button" class="rio-action-timeline" :disabled="timelineBusy || (!clips.some(clip => clip.shot === shot.name) && (!canWork || !shot.selected_output_asset_version))" :title="t('Open this scene in the timeline editor', 'Mở cảnh này trong trình biên tập dòng thời gian')" @click.stop="openSceneTimeline(shot)">＋ Timeline</button>
						</div>
						<button type="button" class="rio-port rio-port-reference" :title="t('Scene references', 'Tư liệu của cảnh')" :aria-label="t('Scene references', 'Tư liệu của cảnh')" @click.stop="openShotDetails(shot, index)" />
						<button type="button" class="rio-port rio-port-in" :title="t('First frame', 'Ảnh đầu cảnh')" :aria-label="t('First frame', 'Ảnh đầu cảnh')" @click.stop="selectShot(shot, index)" />
						<button type="button" class="rio-port rio-port-ending" :title="t('Scene frame settings', 'Cài đặt khung hình cảnh')" :aria-label="t('Scene frame settings', 'Cài đặt khung hình cảnh')" @click.stop="openShotDetails(shot, index)" />
						<button type="button" class="rio-port rio-port-out" :title="t('Preview scene output', 'Xem đầu ra của cảnh')" :aria-label="t('Preview scene output', 'Xem đầu ra của cảnh')" @click.stop="selectShot(shot, index)" />
					</article>
				</div>
				<div v-if="!shots.length && automaticVariant" class="rio-empty-canvas" data-test="rio-automatic-status" role="status">
					<span class="rio-empty-step">{{ t('AUTOMATIC VIDEO', 'VIDEO TỰ ĐỘNG') }}</span>
					<h2>{{ automaticStatusTitle }}</h2>
					<p>{{ automaticMessage }}</p>
					<p v-if="automaticVariant.error && automaticVariant.status === 'Needs Attention'" class="rio-auto-reason">{{ automaticFailureReason }}</p>
					<details v-if="automaticVariant.error && automaticFailureReason !== automaticVariant.error" class="rio-auto-reason"><summary>{{ t('Technical details', 'Chi tiết kỹ thuật') }}</summary><p>{{ automaticVariant.error }}</p></details>
					<p v-if="automaticStatusError" role="alert">{{ automaticStatusError }}</p>
					<button v-if="canWork && automaticVariant.status === 'Needs Attention'" type="button" :disabled="automaticRetrying" @click="retryAutomatic">{{ automaticRetrying ? t('Resuming…', 'Đang tiếp tục…') : t('Retry video', 'Thử lại video') }}</button>
				</div>
				<div v-else-if="!shots.length" class="rio-empty-canvas" data-test="rio-empty-storyboard">
					<span class="rio-empty-step">{{ t('START HERE', 'BẮT ĐẦU TẠI ĐÂY') }}</span>
					<h2>{{ t('Create your storyboard', 'Tạo bảng phân cảnh') }}</h2>
					<p>{{ t('Describe the story you want to tell. We will turn your idea and references into scenes.', 'Mô tả câu chuyện bạn muốn kể. JoyMedia sẽ dùng ý tưởng và tư liệu bên trái để tạo các cảnh.') }}</p>
					<label for="rio-video-idea">{{ t('Video idea', 'Ý tưởng video') }}</label>
					<textarea id="rio-video-idea" :value="idea" :disabled="!canWork" :placeholder="t('Describe the product and what should happen in the video', 'Mô tả sản phẩm và nội dung video')" rows="7" @input="emit('update:idea', $event.target.value)" />
					<div class="rio-empty-actions"><span>{{ t('You can review and edit the scenes after generation.', 'Bạn có thể xem và chỉnh sửa các cảnh sau khi tạo.') }}</span><button v-if="canWork" type="button" :disabled="busy || !idea?.trim()" @click="emit('continue')">{{ t('Generate storyboard', 'Tạo phân cảnh') }} →</button></div>
				</div>
				<div v-if="shots.length" class="rio-canvas-controls"><button type="button" :aria-label="t('Zoom out', 'Thu nhỏ')" @click="zoom = Math.max(0.45, zoom - 0.1)">−</button><span>{{ Math.round(zoom * 100) }}%</span><button type="button" :aria-label="t('Zoom in', 'Phóng to')" @click="zoom = Math.min(1.6, zoom + 0.1)">＋</button><button type="button" :aria-label="t('Fit all scenes on screen', 'Hiện tất cả cảnh trên màn hình')" @click="fitCanvas">⛶</button></div>
				<!-- A pointer shortcut for panning. The zoom and fit buttons above cover the same ground for keyboards, so this stays hidden from screen readers. -->
				<div v-if="showMinimap && shots.length" ref="minimapRef" class="rio-minimap is-interactive" :style="minimapPosition.x === null ? {} : { left: `${minimapPosition.x}px`, top: `${minimapPosition.y}px`, right: 'auto' }" :aria-label="t('Canvas minimap', 'Sơ đồ nhỏ')" @pointerdown.stop="startMinimapDrag" @pointermove.stop="moveMinimapDrag" @pointerup.stop="endMinimapDrag" @pointercancel.stop="endMinimapDrag"><span>MINIMAP</span><div class="rio-minimap-content"><div v-for="(shot, index) in shots" :key="shot.name" :class="{ active: index === selectedShotIndex }" :style="miniStyle(shot, index)" /><b class="rio-minimap-viewport" :style="minimapViewport" /></div></div>
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
					<template v-else-if="selectedAsset"><MediaThumbnail :src="selectedAsset.file" :media-type="selectedAsset.media_type" :alt="selectedAsset.asset_name || selectedAsset.label" aspect="aspect-square" /><p>{{ selectedAsset.label || selectedAsset.asset_name }}</p><p>{{ categoryLabel(selectedAsset.reference_role || selectedAsset.asset_category) }}</p><p v-if="selectedAsset.product_view && selectedAsset.product_view !== 'source'">{{ t('View', 'Góc nhìn') }}: {{ selectedAsset.product_view.replaceAll('_', ' ') }}</p><div v-if="canEdit && selectedAsset.reference_key" class="rio-identity">
							<label :for="`rio-identity-${selectedAsset.asset_version}`">@{{ t('tag', 'thẻ') }}</label>
							<input :id="`rio-identity-${selectedAsset.asset_version}`" v-model="identityDraft" :placeholder="t('e.g. BearShera', 'ví dụ: GauShera')" maxlength="60" @keydown.enter.prevent="saveIdentity" @blur="saveIdentity" />
							<small>{{ t('Give the same tag to every picture of one character or product, so they stay the same across scenes.', 'Đặt cùng một thẻ cho mọi ảnh của một nhân vật hoặc sản phẩm, để chúng giống nhau giữa các cảnh.') }}</small>
						</div>
						<button v-if="canEdit && selectedAsset.reference_key && selectedShot" type="button" class="rio-details-action" :disabled="shotReferenceKeys(selectedShot).includes(selectedAsset.reference_key)" @click="emit('assign-asset', selectedAsset)">{{ t('Add to selected scene', 'Thêm vào cảnh đang chọn') }}</button></template>
				</aside>
		</div>
		<p v-if="toolError" class="rio-alert" role="alert">{{ toolError }} <button @click="toolError = ''">×</button></p>
		<div v-if="scriptReviewOpen && canWork" class="rio-tool-overlay" @click.self="scriptReviewOpen = false">
			<section class="rio-tool-dialog" style="width:min(1000px,100%)" role="dialog" aria-modal="true" :aria-label="t('Review new video', 'Duyệt video mới')">
				<header><strong>{{ t('Review script & scenes', 'Duyệt kịch bản & cảnh') }}</strong><button type="button" :aria-label="t('Close', 'Đóng')" @click="scriptReviewOpen = false">×</button></header>
				<CreativeBatchPanel :project="projectName" :focus="automaticVariant?.project || projectName" @loaded="refreshAutomaticBatch" @show-video="scriptReviewOpen = false" />
			</section>
		</div>
		<StudioEffectsDialog v-if="effectsOpen" :project-name="projectName" :shot="selectedShot" :current-lang="currentLang" @close="effectsOpen = false" @upload="emit('add-audio', 'SFX')" @done="emit('timeline-refresh')" />
		<div v-if="charactersOpen" class="rio-tool-overlay" @click.self="charactersOpen = false">
			<section class="rio-tool-dialog" role="dialog" aria-modal="true" :aria-label="t('Character identity', 'Nhận dạng nhân vật')">
				<header><strong>🎭 {{ t('CHARACTER REFERENCES & IDENTITY', 'TƯ LIỆU & NHẬN DẠNG NHÂN VẬT') }}</strong><button :aria-label="t('Close', 'Đóng')" @click="charactersOpen = false">×</button></header>
				<p>{{ t('Give pictures of the same character the same identity tag. Assign a reference to a scene before generating its images.', 'Đặt cùng thẻ nhận dạng cho các ảnh của một nhân vật. Gán tư liệu cho cảnh trước khi tạo ảnh.') }}</p>
				<p v-if="!characterAssets.length">{{ t('Add a character picture to the project, then set its category to Character.', 'Thêm ảnh nhân vật vào dự án, rồi chọn danh mục Nhân vật.') }}</p>
				<div v-for="asset in characterAssets" :key="asset.asset_version" class="rio-character-row">
					<MediaThumbnail :src="asset.file" media-type="Image" :alt="asset.display_name" aspect="aspect-square" :contain="true" />
					<div><strong>{{ asset.display_name }}</strong><label>{{ t('Identity tag', 'Thẻ nhận dạng') }}<input v-model="characterTags[asset.asset_version]" :disabled="!canWork" maxlength="60" placeholder="@character" /></label></div>
					<button :disabled="!canWork || busy || (characterTags[asset.asset_version] || '').trim() === (asset.identity_key || '')" @click="emit('set-identity', asset, (characterTags[asset.asset_version] || '').trim())">{{ t('Save tag', 'Lưu thẻ') }}</button>
					<button v-if="selectedShot" :disabled="!canWork || busy || !asset.reference_key || shotReferenceKeys(selectedShot).includes(asset.reference_key)" @click="emit('assign-asset', asset)">{{ t('Use in selected scene', 'Dùng trong cảnh chọn') }}</button>
				</div>
				<footer><button @click="emit('open-media'); charactersOpen = false">＋ {{ t('Add reference pictures', 'Thêm ảnh tham chiếu') }}</button></footer>
			</section>
		</div>
		<div v-if="exportOptionsOpen" class="rio-tool-overlay" @click.self="exportOptionsOpen = false">
			<section class="rio-tool-dialog rio-export-options" role="dialog" aria-modal="true" :aria-label="t('Export video', 'Xuất video')">
				<header><strong>🎬 {{ t('EXPORT VIDEO', 'XUẤT VIDEO') }}</strong><button :aria-label="t('Close', 'Đóng')" @click="exportOptionsOpen = false">×</button></header>
				<label>{{ t('Output preset', 'Chất lượng xuất') }}<select v-model="exportPreset"><option value="Draft 720p">720p · {{ t('Draft', 'Bản nháp') }}</option><option value="Studio 1440p60">Cinema · 1440p / 60 fps</option></select></label>
				<p>{{ t('The export uses the timeline cuts, transitions, audio mix and project aspect ratio. Higher resolution does not restore details absent from the source.', 'Video xuất dùng bản dựng, chuyển cảnh, âm thanh và tỉ lệ của dự án. Độ phân giải cao hơn không khôi phục chi tiết thiếu trong nguồn.') }}</p>
				<footer><button @click="emit('settings'); exportOptionsOpen = false">{{ t('Project settings', 'Cài đặt dự án') }}</button><button :disabled="!canWork || !canExport || exporting || timelineBusy" @click="emit('export-preset', exportPreset); exportOptionsOpen = false">{{ t('Export', 'Xuất video') }}</button></footer>
			</section>
		</div>

		<section class="rio-bottom" :style="{ height: `${Math.min(420, 240 + Math.max(0, audioLanes.length - 2) * 57 + (selectedAudio ? 42 : 0))}px` }">
			<div class="rio-timeline">
				<div class="rio-timeline-head"><button type="button" class="rio-tl-play" :disabled="!previewVideo" :aria-label="playing ? t('Pause preview', 'Tạm dừng xem trước') : t('Play preview', 'Phát xem trước')" @click="togglePlayback">{{ playing ? 'Ⅱ' : '▶' }}</button><span class="rio-timeline-description" :title="t('Timeline', 'Dòng thời gian')">{{ clips.length }} {{ t('clips', 'đoạn') }}</span>

					<div v-if="canWork" class="rio-audio-add"><button type="button" data-test="rio-add-audio" :aria-expanded="audioAddOpen" @click="effectsOpen = true">🎙 SFX</button><div v-if="audioAddOpen" class="rio-audio-add-menu"><button v-for="role in ['BGM', 'Voiceover', 'SFX']" :key="role" type="button" @click="chooseAudioRole(role)">{{ audioRoleLabel(role) }}</button></div></div><button v-if="canWork" type="button" class="rio-tl-clear" :disabled="timelineBusy || exporting || !clips.length && !audioClips.length" :title="t('Clear the timeline', 'Xóa dòng thời gian')" :aria-label="t('Clear the timeline', 'Xóa dòng thời gian')" @click="pausePreview(); emit('clear-timeline')">🧹</button>
					<button v-for="action in ['left', 'split', 'right']" :key="action" v-show="canWork" type="button" class="rio-tl-cut" :disabled="timelineBusy || exporting || !cutPayload(action)" :title="cutLabel(action)" :aria-label="cutLabel(action)" @click="cutAtPlayhead(action)">{{ action === 'left' ? '✂‹' : action === 'right' ? '›✂' : '✂' }}</button>
					<button v-if="canWork" type="button" :disabled="!canUndo || timelineBusy" :aria-label="t('Undo timeline edit', 'Hoàn tác chỉnh sửa')" @click="pausePreview(); emit('undo-timeline')">↶</button>
					<button v-if="canWork" type="button" :disabled="!canRedo || timelineBusy" :aria-label="t('Redo timeline edit', 'Làm lại chỉnh sửa')" @click="pausePreview(); emit('redo-timeline')">↷</button>
					<button v-if="canWork" type="button" @click="emit('open-timeline')">✂ {{ t('Edit tracks', 'Biên tập') }}</button><div class="rio-tl-zoom" :title="t('Zoom the timeline', 'Co giãn dòng thời gian')"><button type="button" :aria-label="t('Zoom out', 'Thu nhỏ')" @click="timelineZoom = Math.max(1, timelineZoom - 0.25)">－</button><input type="range" min="1" max="4" step="0.25" :value="timelineZoom" :aria-label="t('Timeline zoom', 'Mức co giãn')" @input="timelineZoom = Number($event.target.value)" /><button type="button" :aria-label="t('Zoom in', 'Phóng to')" @click="timelineZoom = Math.min(4, timelineZoom + 0.25)">＋</button></div><span class="rio-timeline-spacer" /><button v-if="canWork" type="button" class="rio-export" :disabled="!canExport || exporting || timelineBusy" @click="exportPreset = exportQuality; exportOptionsOpen = true">{{ exporting ? '…' : '🎬 ' + (exportQuality === 'Studio 1440p60' ? 'Cinema · 1440p60' : '720p') }}</button></div>
				<div class="rio-tl-scroll"><div class="rio-tl-inner" :style="{ width: `${timelineZoom * 100}%` }">
					<div class="rio-ruler"><span v-for="tick in ticks" :key="tick" :style="{ left: `${tick / totalSeconds * 100}%` }">{{ tick }}s</span><input v-if="clips.length" type="range" min="0" :max="totalSeconds" :step="1 / Math.max(1, fps)" :value="playheadSeconds" :aria-label="t('Preview position', 'Vị trí xem trước')" @input="seekTimeline(Number($event.target.value))" /></div>
					<div v-if="clips.length" class="rio-tl-needle" :style="{ left: `calc(${Math.max(0, Math.min(1, playheadSeconds / totalSeconds)) * 100}% + ${48 * (1 - Math.max(0, Math.min(1, playheadSeconds / totalSeconds)))}px)` }" aria-hidden="true" />
					<div class="rio-track"><b class="rio-track-icon" :title="t('Video track', 'Đường hình')" aria-hidden="true">📹</b><div class="rio-track-content"><button v-for="(clip, index) in orderedClips" :key="clip.name || index" type="button" class="rio-video-clip" :class="{ selected: clip.name === activeClip?.name }" :style="clipStyle(clip, index)" :title="clipDescription(clip, index)" @click="selectClip(clip)">{{ clipTitle(clip, index) }}</button><span v-if="!clips.length" class="rio-track-empty">{{ t('Generated clips appear here', 'Video sau khi dựng sẽ xuất hiện ở đây') }}</span></div></div>
					<div v-for="(lane, laneIndex) in audioLanes" :key="`audio-${laneIndex}`" class="rio-track rio-audio-row"><b class="rio-track-icon" :title="audioRoleLabel(lane.role)" aria-hidden="true">{{ lane.role === 'SFX' ? '〰️' : lane.role === 'Voiceover' ? '🎙️' : '🔊' }}</b><div class="rio-track-content"><button v-for="clip in lane.clips" :key="clip.name" type="button" class="rio-audio-clip" :class="{ 'is-selected': selectedAudioName === clip.name, 'is-disabled': !clip.enabled }" :style="audioStyle(clip)" :title="`${audioTitle(clip)}${clip.enabled ? '' : ` · ${t('Disabled', 'Đã tắt')}`}`" @click="selectedAudioName = clip.name" @dblclick="emit('open-timeline', clip)">{{ audioTitle(clip) }}</button></div></div>
					<div v-if="!audioLanes.some(lane => lane.role === 'SFX')" class="rio-track rio-sfx-row"><b class="rio-track-icon" :title="t('Sound effects', 'Hiệu ứng âm thanh')" aria-hidden="true">〰</b><div class="rio-track-content" /></div>
					<div v-if="!audioLanes.length" class="rio-track rio-audio-row"><b class="rio-track-icon" :title="t('Audio track', 'Đường âm thanh')" aria-hidden="true">🔊</b><div class="rio-track-content"><span class="rio-track-empty">{{ t('No audio yet. Add music, voice, or effects.', 'Chưa có âm thanh. Thêm nhạc, lời thoại hoặc hiệu ứng.') }}</span></div></div>
				</div></div>
				<div v-if="selectedAudio" class="rio-audio-actions"><strong :title="audioTitle(selectedAudio)">{{ audioTitle(selectedAudio) }}</strong><button v-if="canWork" type="button" :disabled="busy" @click="emit('toggle-audio', selectedAudio, !selectedAudio.enabled)">{{ selectedAudio.enabled ? t('Disable', 'Tắt') : t('Enable', 'Bật') }}</button><button v-if="canWork && selectedAudio.audio_role !== 'Source'" type="button" :disabled="busy" @click="removeSelectedAudio">{{ t('Remove', 'Xóa khỏi dòng thời gian') }}</button><button type="button" @click="emit('open-timeline', selectedAudio)">{{ t('More controls', 'Điều chỉnh thêm') }}</button></div>
			</div>
			<div class="rio-monitor"><div class="rio-monitor-head"><span>▣ {{ t('PREVIEW', 'XEM TRƯỚC') }}</span><time>{{ timecode }}</time></div>
				<div v-if="previewVideo" class="rio-monitor-stage">
					<!-- Two players: one shows the current clip while the other preloads the next, so playback crosses a cut without stalling. -->
					<video v-show="activePlayer === 'a'" ref="videoRefA" :src="sources.a" :muted="muteSourceVideo" controls playsinline @loadedmetadata="applyPendingSeek" @play="onPlayerPlay('a')" @pause="onPlayerPause('a')" @timeupdate="onPlayerTimeUpdate('a', $event)" @ended="onPlayerEnded('a')" />
					<video v-show="activePlayer === 'b'" ref="videoRefB" :src="sources.b" :muted="muteSourceVideo" controls playsinline @loadedmetadata="applyPendingSeek" @play="onPlayerPlay('b')" @pause="onPlayerPause('b')" @timeupdate="onPlayerTimeUpdate('b', $event)" @ended="onPlayerEnded('b')" />
					<span class="rio-monitor-timecode" aria-hidden="true">{{ timecode }}</span>
				</div>
				<img v-else-if="previewImage" :src="previewImage" :alt="t('Selected first frame', 'Ảnh đầu cảnh đã chọn')" /><div v-else class="rio-monitor-empty">🎬<span>{{ t('Select a scene to preview', 'Chọn cảnh để xem trước') }}</span></div></div>
		</section>
	</div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { call } from 'frappe-ui';
import MediaThumbnail from '../MediaThumbnail.vue';
import VideoShelf from './VideoShelf.vue';
import ProjectStages from './ProjectStages.vue';
import StudioEffectsDialog from './StudioEffectsDialog.vue';
import CreativeBatchPanel from './CreativeBatchPanel.vue';
import { useTimelinePreviewEngine } from '../../composables/useTimelinePreviewEngine.js';
import { groupAssets } from '../../utils/assetPresentation.js';
import { clipAtSeconds, layoutAudioLanes, orderTimelineClips, shotIndexForClip, sourceSecondsForTimeline, timelineCut } from '../../utils/rioTimeline.js';
import { aspectRatio, categoryIcon, categoryLabel as getCategoryLabel, categoryOptions, formatDuration, referenceCategory as getReferenceCategory, referenceLabel as getReferenceLabel } from '../../utils/rioPresentation.js';

const props = defineProps({
	projectName: String, projectTitle: String, projectStatus: String, currentLang: String, idea: String,
	canEdit: Boolean, canWork: Boolean, canRestore: Boolean,
	assets: { type: Array, default: () => [] }, selectedAsset: Object,
	shots: { type: Array, default: () => [] }, selectedShotIndex: { type: Number, default: 0 },
	clips: { type: Array, default: () => [] }, audioClips: { type: Array, default: () => [] },
	finalVideo: Object, timeline: Object, fps: { type: Number, default: 24 },
	width: Number, height: Number, busy: Boolean, exporting: Boolean, canExport: Boolean,
	storyboardApproved: Boolean, busyShots: { type: Array, default: () => [] },
	frames: { type: Array, default: () => [] }, nextAction: String, error: String,
	project: { type: Object, default: () => ({}) }, production: { type: Object, default: null },
	missing: Boolean, timelineBusy: Boolean, canUndo: Boolean, canRedo: Boolean, exportQuality: { type: String, default: 'Studio 1440p60' },
});
const emit = defineEmits(['restore', 'open-history', 'update:idea', 'settings', 'add-scene', 'open-media', 'select-asset', 'assign-asset', 'update-asset', 'remove-asset', 'update-shot-references', 'select-shot', 'edit-shot', 'draw-shot', 'approve-frame', 'render-shot', 'save-prompt', 'open-timeline', 'add-audio', 'toggle-audio', 'remove-audio', 'export', 'retry', 'continue', 'set-continuity', 'upload-files', 'slice-storyboard', 'dictation-error', 'set-identity', 'apply-template-duration', 'rebuild-timeline', 'clear-timeline', 'trim-timeline', 'split-timeline', 'undo-timeline', 'redo-timeline', 'add-to-timeline', 'seek-timeline', 'timeline-refresh', 'export-preset']);
const t = (en, vi) => props.currentLang === 'vi' ? vi : en;
const automaticBatch = ref(null), automaticVariant = ref(null), automaticStatusError = ref(''), automaticRetrying = ref(false);
const scriptReviewOpen = ref(false);
const reviewableBatch = computed(() => automaticBatch.value?.delivery_mode === 'assisted' && ['Script Ready', 'Pictures Ready'].includes(automaticVariant.value?.status));
watch(reviewableBatch, ready => { if (ready && props.canWork) scriptReviewOpen.value = true; });
const automaticInProgress = computed(() => Boolean(automaticVariant.value && !['Completed', 'Cancelled'].includes(automaticVariant.value.status)));
let batchTimer, batchEpoch = 0;
async function refreshAutomaticBatch() {
	clearTimeout(batchTimer);
	const epoch = ++batchEpoch, project = props.projectName;
	try {
		const batches = await call('joymedia.api.creative.get_project_batches', { project_name: project }) || [];
		if (epoch !== batchEpoch || project !== props.projectName) return;
		const found = batches.map(batch => ({ batch, variant: (batch.variants || []).find(v => v.project === project) || (batch.source_project === project && batch.variants?.length === 1 ? batch.variants[0] : null) })).find(item => item.variant);
		automaticBatch.value = found?.batch || null;
		automaticVariant.value = found?.variant ? (found.batch.status === 'Cancelled' && found.variant.status !== 'Completed' ? { ...found.variant, status: 'Cancelled' } : found.variant) : null;
		automaticStatusError.value = '';
	} catch (error) { if (epoch === batchEpoch) automaticStatusError.value = t('Could not refresh video status.', 'Không thể cập nhật trạng thái video.'); }
	if (epoch === batchEpoch) batchTimer = window.setTimeout(refreshAutomaticBatch, 10000);
}
watch(() => props.projectName, () => { clearTimeout(batchTimer); scriptReviewOpen.value = false; automaticBatch.value = null; automaticVariant.value = null; void refreshAutomaticBatch(); }, { immediate: true });
onUnmounted(() => { ++batchEpoch; clearTimeout(batchTimer); });
const automaticStatusTitle = computed(() => reviewableBatch.value ? t('Review this video before continuing', 'Duyệt video này trước khi tiếp tục') : automaticVariant.value?.status === 'Needs Attention' ? t('Video needs attention', 'Video cần xử lý') : automaticVariant.value?.status === 'Cancelled' ? t('Video stopped', 'Video đã dừng') : automaticVariant.value?.status === 'Completed' ? t('Video complete', 'Video đã hoàn tất') : t('Creating your video', 'Đang tạo video'));
const automaticFailureReason = computed(() => {
	const error = automaticVariant.value?.error || '';
	if (/reference analysis is missing/i.test(error)) return t('The product or character image could not be analyzed. Try again later.', 'Chưa phân tích được ảnh sản phẩm hoặc nhân vật. Hãy thử lại sau.');
	if (/required character pose references could not be verified/i.test(error)) return t('The character poses could not be verified, so image generation stopped. Add suitable reference images or adjust the idea before retrying.', 'Chưa xác minh được tư thế nhân vật nên hệ thống đã dừng tạo ảnh. Hãy thêm ảnh tham chiếu phù hợp hoặc điều chỉnh ý tưởng trước khi thử lại.');
	if (/disappeared from its queue|Unable to upload to ComfyUI|Connection reset|GPU connection failure/i.test(error)) return t('The image server was interrupted. Nothing was lost; retry when ready.', 'Máy tạo hình bị gián đoạn. Không mất dữ liệu; hãy bấm thử lại.');
	return error;
});
const automaticMessage = computed(() => {
	const status = automaticVariant.value?.status;
	if (reviewableBatch.value) return t('Review the script or scene images, then choose whether to continue generation.', 'Hãy duyệt kịch bản hoặc ảnh cảnh, rồi chọn có tiếp tục tạo video hay không.');
	if (status === 'Needs Attention') return t('The automatic process stopped before it could finish.', 'Quá trình tự động đã dừng trước khi hoàn thành.');
	if (status === 'Cancelled') return t('This video was stopped.', 'Video này đã được dừng.');
	if (status === 'Completed') return t('Your video is ready to preview.', 'Video đã sẵn sàng để xem.');
	if (status === 'Queued') return t('Waiting for the next available worker.', 'Đang chờ hệ thống xử lý.');
	return t('JoyMedia is preparing this video automatically. Scenes will appear here when ready.', 'JoyMedia đang tự động chuẩn bị video. Các cảnh sẽ xuất hiện khi hoàn tất.');
});
async function retryAutomatic() {
	if (!automaticBatch.value || !automaticVariant.value || automaticRetrying.value) return;
	try {
		automaticRetrying.value = true; automaticStatusError.value = '';
		await call('joymedia.api.creative.retry_product_variant', { batch_name: automaticBatch.value.name, index: automaticVariant.value.index });
		clearTimeout(batchTimer); await refreshAutomaticBatch();
	} catch (error) { automaticStatusError.value = error?.messages?.[0] || error?.message || t('Could not resume the video.', 'Không thể tiếp tục video.'); }
	finally { automaticRetrying.value = false; }
}
const previewTemplate = ref(null);
const templatesOpen = ref(false), templatesLoading = ref(false), templatesError = ref(''), templates = ref([]), templateTargetShot = ref(null);
async function loadTemplates() {
	templatesLoading.value = true; templatesError.value = '';
	try { templates.value = await call('joymedia.api.prompt_templates.list_prompt_templates') || []; }
	catch (error) { templatesError.value = error?.messages?.[0] || error?.message || t('Could not load templates.', 'Không tải được mẫu.'); }
	finally { templatesLoading.value = false; }
}
function toggleTemplates() { templateTargetShot.value = null; templatesOpen.value = !templatesOpen.value; if (templatesOpen.value && !templates.value.length) loadTemplates(); }
function openSceneTemplates(shot) { templateTargetShot.value = shot; templatesOpen.value = true; if (!templates.value.length) loadTemplates(); }
function useIdeaTemplate(template) {
	const current = String(props.idea || '').trim();
	emit('update:idea', [current, template.idea].filter(Boolean).join('\n\n'));
	// The beats in the idea are written for a specific length, so carry it across;
	// leaving the project on another length silently produces a different film.
	if (Number(template.duration_seconds) > 0) emit('apply-template-duration', Number(template.duration_seconds), template);
	templatesOpen.value = false;
}
function useSceneTemplate(template) {
	const shot = templateTargetShot.value || props.shots[props.selectedShotIndex] || props.shots[0];
	if (!shot) return;
	setDraft(shot, [draftFor(shot).trim(), template.scene].filter(Boolean).join('\n\n'));
	templatesOpen.value = false;
	templateTargetShot.value = null;
}
const assetsOpen = ref(typeof window === 'undefined' || window.innerWidth > 640), assetSize = ref('m'), draggedAsset = ref(null), editingAsset = ref(null), editingAssetName = ref(''), detailsShotName = ref(null), canvasRef = ref(null), minimapRef = ref(null), videoRefA = ref(null), videoRefB = ref(null), playing = ref(false), elapsed = ref(0), zoom = ref(1), showMinimap = ref(true), versionsOpen = ref(false), timelineZoom = ref(1), selectedAudioName = ref(null), audioAddOpen = ref(false);
const statusOpen = ref(false), charactersOpen = ref(false), effectsOpen = ref(false), exportOptionsOpen = ref(false), exportPreset = ref(props.exportQuality), toolError = ref('');
const characterTags = reactive({});
const characterAssets = computed(() => displayedAssets.value.filter(asset => asset.display_category === 'Character'));
const compactShots = reactive(new Set());
function toggleCompact(shot) { if (compactShots.has(shot.name)) compactShots.delete(shot.name); else compactShots.add(shot.name); }
const minimapPosition = reactive({ x: null, y: null });
const pan = reactive({ x: 0, y: 0 });
const positions = reactive({});
const drafts = reactive({});
const nodeWidth = 380, nodeHeight = 440, nodeGap = 110;
const canvasWidth = computed(() => Math.max(1100, props.shots.length * (nodeWidth + nodeGap) + 180));
const canvasHeight = 830;
const statusLabel = computed(() => {
	if (automaticVariant.value?.status === 'Needs Attention') return t('Needs attention', 'Cần xử lý');
	if (automaticVariant.value && ['Queued', 'Planning', 'Locations', 'Keyframes', 'Rendering', 'Finishing', 'Exporting'].includes(automaticVariant.value.status)) return t('Working', 'Đang xử lý');
	if (props.busy) return t('Working', 'Đang xử lý');
	const labels = {
		Draft: t('Draft', 'Bản nháp'), Planning: t('Planning', 'Đang lập kế hoạch'),
		Queued: t('Waiting', 'Đang chờ'), Running: t('Working', 'Đang xử lý'),
		Completed: t('Complete', 'Hoàn tất'), 'Needs Attention': t('Needs attention', 'Cần xử lý'), Failed: t('Needs attention', 'Cần xử lý'),
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
const totalSeconds = computed(() => Math.max(props.clips.length ? 1 : 24, Number(props.timeline?.total_seconds || 0), ...[...props.clips, ...props.audioClips].map(clip => (Number(clip.timeline_start_frame || 0) + Number(clip.duration_frames || 0)) / Math.max(1, props.fps)), Number(props.shots.reduce((sum, shot) => sum + Number(shot.duration_seconds || 0), 0) || 0)));
const ticks = computed(() => { const step = totalSeconds.value > 60 ? 10 : totalSeconds.value > 30 ? 5 : 2; return Array.from({ length: Math.floor(totalSeconds.value / step) + 1 }, (_, i) => i * step); });
const previewShot = computed(() => props.shots[props.selectedShotIndex] || props.shots[0]);
const selectedShot = previewShot;
const activeClipName = ref(null);
const activeClip = computed(() => props.clips.find(clip => clip.name === activeClipName.value && clip.shot === previewShot.value?.name) || props.clips.find(clip => clip.shot === previewShot.value?.name) || null);
const previewVideo = computed(() => props.finalVideo?.file || activeClip.value?.source_file || previewShot.value?.selected_output_file || previewShot.value?.output_video || '');
const previewImage = computed(() => frameFor(previewShot.value));
const playheadSeconds = computed(() => props.finalVideo?.file ? elapsed.value : activeClip.value ? Number(activeClip.value.timeline_start_frame || 0) / Math.max(1, props.fps) + Math.max(0, elapsed.value - Number(activeClip.value.source_in_frame || 0) / Math.max(1, props.fps)) : elapsed.value);
const muteSourceVideo = computed(() => !props.finalVideo?.file && props.audioClips.some(clip => clip.audio_role === 'Source'));
const previewAudio = useTimelinePreviewEngine({
	videoClips: computed(() => []), audioClips: computed(() => props.finalVideo?.file ? [] : props.audioClips),
	fps: computed(() => props.fps), isPlaying: playing, isMuted: computed(() => Boolean(props.finalVideo?.file)),
	studioMode: computed(() => 'edit'), playheadFrame: computed(() => Math.round(playheadSeconds.value * Math.max(1, props.fps))),
	timelineTotalFrames: computed(() => totalSeconds.value * Math.max(1, props.fps)),
	renderTotalFrames: computed(() => totalSeconds.value * Math.max(1, props.fps)), getVideo: () => null, driveClock: false,
});
watch([playheadSeconds, playing, () => props.audioClips], () => previewAudio.syncAtFrame(Math.round(playheadSeconds.value * Math.max(1, props.fps))), { deep: true });
const timecode = computed(() => { const s = Math.max(0, playheadSeconds.value); return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}.${Math.floor((s % 1) * 10)}`; });
// One link per gap between scenes. `continues` mirrors the next scene's
// continuity_mode, so the line and its label always show what will be rendered.
const links = computed(() => props.shots.slice(0, -1).map((shot, index) => {
	const next = props.shots[index + 1];
	const a = positionFor(shot, index), b = positionFor(next, index + 1);
	const x1 = a.x + nodeWidth, y1 = a.y + (compactShots.has(shot.name) ? 20 : nodeHeight / 2), x2 = b.x, y2 = b.y + (compactShots.has(next.name) ? 20 : nodeHeight / 2);
	const continues = next.continuity_mode === 'Continue';
	return {
		key: next.name, shot: next, continues, busy: isShotBusy(next),
		d: `M ${x1} ${y1} C ${x1 + 52} ${y1}, ${x2 - 52} ${y2}, ${x2} ${y2}`,
		midX: (x1 + x2) / 2, midY: (y1 + y2) / 2,
		hint: continues
			? t('This scene carries on from the one before it. Choose to start it fresh instead.', 'Cảnh này tiếp nối cảnh trước. Bấm để bắt đầu một cảnh mới.')
			: t('This scene starts fresh. Choose to carry on from the scene before it.', 'Cảnh này bắt đầu mới. Bấm để tiếp nối cảnh trước.'),
	};
}));
function toggleContinuity(link) {
	if (!props.canEdit || props.busy || link.busy) return;
	emit('set-continuity', link.shot, link.continues ? 'New Scene' : 'Continue');
}
function frameFor(shot) {
	const frame = props.frames.find(row => row.shot === shot?.name);
	if (frame?.stale) return '';
	return frame?.url || shot?.first_frame_image || '';
}
function frameNeedsApproval(shot) { const frame = props.frames.find(row => row.shot === shot?.name); return Boolean(frame?.needs_keyframe && frame?.url && !frame?.stale && frame?.status !== 'Approved'); }
function shotReferenceKeys(shot) { return Array.isArray(shot?.references) ? shot.references.map(reference => reference.reference_key).filter(Boolean) : []; }
function isShotBusy(shot) { return props.busyShots.some(item => (typeof item === 'string' ? item : item?.name || item?.shot) === shot?.name); }
function defaultPosition(index) { return { x: 70 + index * (nodeWidth + nodeGap), y: 64 }; }
function positionFor(shot, index) { return positions[shot.name] || defaultPosition(index); }
function nodeStyle(shot, index) { const p = positionFor(shot, index); return { left: `${p.x}px`, top: `${p.y}px` }; }
function miniStyle(shot, index) { const p = positionFor(shot, index); return { left: `${Math.min(92, p.x / canvasWidth.value * 100)}%`, top: `${p.y / canvasHeight * 100}%` }; }
// The canvas is translated then scaled from its top-left, so the visible region
// starts at -pan/zoom and spans the viewport divided by zoom.
const minimapViewport = computed(() => {
	const scale = zoom.value || 1;
	const view = canvasRef.value;
	const w = (view?.clientWidth || 900) / scale, h = (view?.clientHeight || 600) / scale;
	return {
		left: `${Math.max(0, Math.min(100, -pan.x / scale / canvasWidth.value * 100))}%`,
		top: `${Math.max(0, Math.min(100, -pan.y / scale / canvasHeight * 100))}%`,
		width: `${Math.max(4, Math.min(100, w / canvasWidth.value * 100))}%`,
		height: `${Math.max(4, Math.min(100, h / canvasHeight * 100))}%`,
	};
});
/** Centres the canvas on the point the pointer picked in the minimap. */
function panToMinimap(event) {
	const box = minimapRef.value?.querySelector('.rio-minimap-content')?.getBoundingClientRect();
	const view = canvasRef.value;
	if (!box?.width || !view) return;
	const scale = zoom.value || 1;
	const targetX = (event.clientX - box.left) / box.width * canvasWidth.value;
	const targetY = (event.clientY - box.top) / box.height * canvasHeight;
	// Keep the canvas from drifting entirely out of view.
	const minX = Math.min(0, view.clientWidth - canvasWidth.value * scale);
	const minY = Math.min(0, view.clientHeight - canvasHeight * scale);
	pan.x = Math.max(minX, Math.min(0, view.clientWidth / 2 - targetX * scale));
	pan.y = Math.max(minY, Math.min(0, view.clientHeight / 2 - targetY * scale));
}
function startMinimapDrag(event) {
	if (event.button !== 0) return;
	const box = minimapRef.value.getBoundingClientRect(), canvas = canvasRef.value.getBoundingClientRect();
	minimapDragging = event.target.closest('span')
		? { x: event.clientX, y: event.clientY, left: box.left - canvas.left, top: box.top - canvas.top }
		: { navigate: true };
	event.currentTarget.setPointerCapture(event.pointerId);
	if (minimapDragging.navigate) panToMinimap(event);
}
function moveMinimapDrag(event) {
	if (!minimapDragging) return;
	if (minimapDragging.navigate) { panToMinimap(event); return; }
	const view = canvasRef.value, map = minimapRef.value;
	minimapPosition.x = Math.max(0, Math.min(view.clientWidth - map.offsetWidth, minimapDragging.left + event.clientX - minimapDragging.x));
	minimapPosition.y = Math.max(0, Math.min(view.clientHeight - map.offsetHeight, minimapDragging.top + event.clientY - minimapDragging.y));
}
function endMinimapDrag(event) { if (!minimapDragging) return; minimapDragging = false; if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }
function layoutKey() { return `joymedia:rio-layout:${props.projectName}`; }
watch(() => props.projectName, () => { for (const key of Object.keys(positions)) delete positions[key]; try { const saved = JSON.parse(localStorage.getItem(layoutKey()) || '{}'); for (const [key, value] of Object.entries(saved)) if (Number.isFinite(value?.x) && Number.isFinite(value?.y)) positions[key] = value; } catch { /* Layout is optional. */ } nextTick(focusCanvas); }, { immediate: true });
function persistLayout() { try { localStorage.setItem(layoutKey(), JSON.stringify(positions)); } catch { /* Browsers can disable storage. */ } }
function focusCanvas() { zoom.value = 1; pan.x = 0; pan.y = 0; }
function fitCanvas() { const w = canvasRef.value?.clientWidth || 900; zoom.value = Math.max(0.45, Math.min(1, (w - 80) / Math.max(700, canvasWidth.value))); pan.x = 0; pan.y = 0; }
watch(() => props.shots.length, () => nextTick(focusCanvas));
let drag = null;
let minimapDragging = false;

// ---- Dictation: the browser's own speech recognition, where it exists ----
const SpeechRecognition = typeof window !== 'undefined' ? (window.SpeechRecognition || window.webkitSpeechRecognition) : null;
const speechSupported = Boolean(SpeechRecognition);
const dictatingShot = ref(null);

// The @tag is the project's identity_key: pictures sharing it are one character or prop.
const identityDraft = ref('');
watch(() => props.selectedAsset?.asset_version, () => {
	identityDraft.value = props.selectedAsset?.identity_key || '';
}, { immediate: true });
function saveIdentity() {
	const next = identityDraft.value.trim();
	if (!props.selectedAsset || next === (props.selectedAsset.identity_key || '').trim()) return;
	emit('set-identity', props.selectedAsset, next);
}
let recognition = null;

function stopDictation() {
	if (recognition) { recognition.onend = null; recognition.stop(); recognition = null; }
	dictatingShot.value = null;
}
function toggleDictation(shot) {
	if (dictatingShot.value === shot.name) { stopDictation(); return; }
	stopDictation();
	recognition = new SpeechRecognition();
	recognition.lang = props.currentLang === 'vi' ? 'vi-VN' : 'en-US';
	recognition.continuous = true;
	recognition.interimResults = false;
	// Only settled phrases are appended, so the textarea never churns mid-sentence.
	recognition.onresult = (event) => {
		let heard = '';
		for (let i = event.resultIndex; i < event.results.length; i += 1) {
			if (event.results[i].isFinal) heard += event.results[i][0].transcript;
		}
		if (!heard.trim()) return;
		const existing = draftFor(shot);
		setDraft(shot, existing ? `${existing.trimEnd()} ${heard.trim()}` : heard.trim());
	};
	recognition.onerror = (event) => {
		stopDictation();
		if (event.error === 'aborted' || event.error === 'no-speech') return;
		emit('dictation-error', event.error);
	};
	recognition.onend = () => { dictatingShot.value = null; recognition = null; };
	dictatingShot.value = shot.name;
	try { recognition.start(); } catch { stopDictation(); }
}
onUnmounted(stopDictation);

// ---- Media panel: resize, rubber-band selection, OS file drops, shortcuts ----
const DRAWER_WIDTH_KEY = 'joymedia:rio-drawer-width';
const storedWidth = Number(typeof localStorage !== 'undefined' ? localStorage.getItem(DRAWER_WIDTH_KEY) : 0);
const drawerWidth = ref(Number.isFinite(storedWidth) && storedWidth >= 220 ? Math.min(650, storedWidth) : 290);
let drawerResizing = false;
function startDrawerResize(event) {
	if (event.button !== 0) return;
	drawerResizing = true;
	event.currentTarget.setPointerCapture(event.pointerId);
	event.preventDefault();
}
function moveDrawerResize(event) {
	if (!drawerResizing) return;
	// The panel is flush with the left edge, so the pointer's x is the width.
	drawerWidth.value = Math.max(220, Math.min(650, event.clientX));
}
function endDrawerResize(event) {
	if (!drawerResizing) return;
	drawerResizing = false;
	if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
	try { localStorage.setItem(DRAWER_WIDTH_KEY, String(Math.round(drawerWidth.value))); } catch { /* Browsers can disable storage. */ }
}

const assetListRef = ref(null);
const selectedAssetKeys = ref([]);
const marquee = reactive({ active: false, visible: false, startX: 0, startY: 0, left: 0, top: 0, width: 0, height: 0 });
const marqueeStyle = computed(() => ({ left: `${marquee.left}px`, top: `${marquee.top}px`, width: `${marquee.width}px`, height: `${marquee.height}px` }));
function assetKey(asset) { return asset.asset_version || asset.name; }
function clearAssetSelection() { selectedAssetKeys.value = []; }
watch(() => props.projectName, clearAssetSelection);
// Media removed elsewhere must not linger in the selection.
watch(() => props.assets, (list) => {
	if (event.code === 'Space' && previewVideo.value) { event.preventDefault(); togglePlayback(); return; }
	if (!selectedAssetKeys.value.length) return;
	const live = new Set((list || []).map(assetKey));
	selectedAssetKeys.value = selectedAssetKeys.value.filter((key) => live.has(key));
});

function startMarquee(event) {
	if (event.button !== 0 || !props.canEdit) return;
	const card = event.target.closest('.rio-asset-card');
	if (card) {
		// Ctrl/Cmd/Shift picks cards out; a plain press still starts a drag to the canvas.
		if (event.ctrlKey || event.metaKey || event.shiftKey) {
			event.preventDefault();
			const key = card.dataset.assetKey;
			selectedAssetKeys.value = selectedAssetKeys.value.includes(key)
				? selectedAssetKeys.value.filter((item) => item !== key)
				: [...selectedAssetKeys.value, key];
		}
		return;
	}
	if (event.target.closest('button, input')) return;
	marquee.active = true;
	marquee.visible = false;
	marquee.startX = event.clientX;
	marquee.startY = event.clientY;
	if (!event.ctrlKey && !event.metaKey && !event.shiftKey) clearAssetSelection();
	window.addEventListener('pointermove', moveMarquee);
	window.addEventListener('pointerup', endMarquee);
}
function moveMarquee(event) {
	if (!marquee.active) return;
	const dx = Math.abs(event.clientX - marquee.startX), dy = Math.abs(event.clientY - marquee.startY);
	if (dx <= 4 && dy <= 4) return;
	marquee.visible = true;
	const left = Math.min(marquee.startX, event.clientX), top = Math.min(marquee.startY, event.clientY);
	Object.assign(marquee, { left, top, width: dx, height: dy });
	const band = { left, top, right: left + dx, bottom: top + dy };
	const additive = event.ctrlKey || event.metaKey || event.shiftKey;
	const next = new Set(additive ? selectedAssetKeys.value : []);
	for (const card of assetListRef.value?.querySelectorAll('.rio-asset-card') || []) {
		const box = card.getBoundingClientRect();
		const hit = !(box.right < band.left || box.left > band.right || box.bottom < band.top || box.top > band.bottom);
		if (hit) next.add(card.dataset.assetKey);
		else if (!additive) next.delete(card.dataset.assetKey);
	}
	selectedAssetKeys.value = [...next];
}
function endMarquee() {
	marquee.active = false;
	marquee.visible = false;
	window.removeEventListener('pointermove', moveMarquee);
	window.removeEventListener('pointerup', endMarquee);
}

function removeSelectedAssets() {
	if (!props.canEdit || props.busy || !selectedAssetKeys.value.length) return;
	const chosen = new Set(selectedAssetKeys.value);
	const assets = (props.assets || []).filter((asset) => chosen.has(assetKey(asset)));
	clearAssetSelection();
	for (const asset of assets) emit('remove-asset', asset);
}

// Files dragged in from the desktop. dragenter/dragleave fire per child element,
// so a depth counter keeps the highlight steady while moving across the panel.
const fileDragDepth = ref(0);
const hasFiles = (event) => Array.from(event.dataTransfer?.types || []).includes('Files');
function onFileDragEnter(event) { if (props.canWork && hasFiles(event)) { event.preventDefault(); fileDragDepth.value += 1; } }
function onFileDragOver(event) { if (props.canWork && hasFiles(event)) { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; } }
function onFileDragLeave(event) { if (fileDragDepth.value > 0 && hasFiles(event)) fileDragDepth.value -= 1; }
function onFileDrop(event) {
	if (!props.canWork || !hasFiles(event)) return;
	event.preventDefault();
	fileDragDepth.value = 0;
	const files = Array.from(event.dataTransfer.files || []);
	if (files.length) emit('upload-files', files);
}

function openCharacters() {
	for (const asset of characterAssets.value) characterTags[asset.asset_version] = asset.identity_key || '';
	charactersOpen.value = true;
}
async function toggleFullscreen() {
	try {
		if (document.fullscreenElement) await document.exitFullscreen();
		else await canvasRef.value?.closest('[data-test="rio-studio"]')?.requestFullscreen();
	} catch { toolError.value = t('Fullscreen is not available in this browser.', 'Trình duyệt chưa hỗ trợ toàn màn hình.'); }
}
function openSceneTimeline(shot) {
	const clip = props.clips.find(item => item.shot === shot.name);
	if (clip) emit('open-timeline', clip); else if (props.canWork && shot.selected_output_asset_version) emit('add-to-timeline', shot);
}
function pausePreview() { activeVideo()?.pause(); playing.value = false; }
function cutLabel(action) { return action === 'left' ? t('Trim left of playhead', 'Bỏ phần trước đầu phát') : action === 'right' ? t('Trim right of playhead', 'Bỏ phần sau đầu phát') : t('Split at playhead', 'Tách tại đầu phát'); }
function cutPayload(action) { return timelineCut(activeClip.value, playheadSeconds.value, props.fps, action); }
function cutAtPlayhead(action) {
	if (!props.canWork || props.timelineBusy) return;
	const payload = cutPayload(action); if (!payload) return;
	pausePreview(); emit(action === 'split' ? 'split-timeline' : 'trim-timeline', payload);
}

function onWorkspaceKeydown(event) {
	if (event.key === 'Escape' && (scriptReviewOpen.value || charactersOpen.value || effectsOpen.value || exportOptionsOpen.value)) { scriptReviewOpen.value = charactersOpen.value = effectsOpen.value = exportOptionsOpen.value = false; return; }
	if (scriptReviewOpen.value || charactersOpen.value || effectsOpen.value || exportOptionsOpen.value) return;
	const el = document.activeElement;
	if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return;
	if (!selectedAssetKeys.value.length) return;
	if (event.key === 'Delete' || event.key === 'Backspace') { event.preventDefault(); removeSelectedAssets(); }
	else if (event.key === 'Escape') { event.preventDefault(); clearAssetSelection(); }
}
onMounted(() => window.addEventListener('keydown', onWorkspaceKeydown));
onUnmounted(() => {
	window.removeEventListener('keydown', onWorkspaceKeydown);
	endMarquee();
});
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
function togglePlayback() { const player = activeVideo(); if (!player) return; if (player.paused) player.play().catch(() => { playing.value = false; }); else player.pause(); }
function onTimeUpdate(event) { elapsed.value = event.target.currentTime || 0; }
function clipTitle(_clip, index) { return `${t('Clip', 'Đoạn')} ${index + 1}`; }
function clipDescription(clip, index) { const shot = props.shots.find(row => row.name === clip.shot); const number = shot?.shot_number || clip.shot_number; const source = number ? `${t('Shot', 'Cảnh')} ${number}` : t('Unlinked scene', 'Chưa gắn cảnh'); return `${clipTitle(clip, index)} · ${source} · ${formatDuration(clip.duration_seconds)}`; }
function audioTitle(clip) { return clip.audio_role === 'Voiceover' ? t('Voiceover', 'Lời thoại') : clip.audio_role === 'Source' ? t('Scene audio', 'Âm thanh cảnh') : clip.audio_role === 'Music' ? t('Music', 'Nhạc') : clip.source_asset_name || t('Audio', 'Âm thanh'); }
function clipStyle(clip, index = 0) { const start = Number(clip.timeline_start_frame || 0) / Math.max(1, props.fps); const duration = Number(clip.duration_frames || 0) / Math.max(1, props.fps) || totalSeconds.value / Math.max(1, props.clips.length); return { left: `${Math.max(0, start / totalSeconds.value * 100)}%`, width: `${Math.max(3, Math.min(100, duration / totalSeconds.value * 100))}%`, zIndex: index + 1 }; }
function audioStyle(clip) { return clipStyle(clip); }
// ---- Preview monitor: two players so a cut does not stall on a fresh load ----
const activePlayer = ref('a');
const sources = reactive({ a: '', b: '' });
const activeVideo = () => (activePlayer.value === 'a' ? videoRefA.value : videoRefB.value);
const idleVideo = () => (activePlayer.value === 'a' ? videoRefB.value : videoRefA.value);
const idleSlot = () => (activePlayer.value === 'a' ? 'b' : 'a');
// Only the visible player drives state; the idle one is mid-preload and must stay quiet.
const isActive = (slot) => slot === activePlayer.value;
function onPlayerPlay(slot) { if (isActive(slot)) playing.value = true; else idleVideo()?.pause(); }
function onPlayerPause(slot) { if (isActive(slot)) playing.value = false; }
function onPlayerTimeUpdate(slot, event) { if (isActive(slot)) elapsed.value = event.target.currentTime || 0; }

const nextClip = computed(() => {
	if (props.finalVideo?.file || !activeClip.value) return null;
	const ordered = orderedClips.value;
	const index = ordered.findIndex((clip) => clip.name === activeClip.value.name);
	return index >= 0 ? ordered[index + 1] || null : null;
});

// Keep the visible player on the current source and park the next one in the idle player.
watch([previewVideo, () => nextClip.value?.source_file], ([current, upcoming]) => {
	if (!current) { sources.a = ''; sources.b = ''; return; }
	if (sources[activePlayer.value] !== current) {
		// If the idle player already holds it (we preloaded it), just swap instead of reloading.
		if (sources[idleSlot()] === current) {
			const wasPlaying = playing.value;
			activeVideo()?.pause();
			activePlayer.value = idleSlot();
			if (wasPlaying) nextTick(() => activeVideo()?.play().catch(() => { playing.value = false; }));
		} else {
			sources[activePlayer.value] = current;
		}
	}
	const idle = idleSlot();
	if (sources[idle] !== (upcoming || '')) sources[idle] = upcoming || '';
}, { immediate: true });

// At the end of a clip, roll straight into the next one instead of stopping.
function onPlayerEnded(slot) {
	if (!isActive(slot)) return;
	const upcoming = nextClip.value;
	if (!upcoming) { playing.value = false; return; }
	const startSeconds = Number(upcoming.timeline_start_frame || 0) / Math.max(1, props.fps);
	selectClip(upcoming, startSeconds);
	nextTick(() => activeVideo()?.play().catch(() => { playing.value = false; }));
}

let pendingSeekSeconds = null;
function applyPendingSeek() { const player = activeVideo(); if (player && pendingSeekSeconds !== null && player.readyState >= 1) { player.currentTime = Math.max(0, Math.min(pendingSeekSeconds, Number.isFinite(player.duration) ? player.duration : pendingSeekSeconds)); pendingSeekSeconds = null; } }
function selectClip(clip, timelineSeconds = Number(clip.timeline_start_frame || 0) / Math.max(1, props.fps)) {
	const index = shotIndexForClip(props.shots, clip);
	if (index < 0) { emit('open-timeline', clip); return; }
	activeClipName.value = clip.name;
	emit('seek-timeline', Math.round(timelineSeconds * Math.max(1, props.fps)));
	emit('select-shot', props.shots[index], index);
	pendingSeekSeconds = props.finalVideo?.file ? timelineSeconds : sourceSecondsForTimeline(clip, timelineSeconds, props.fps);
	elapsed.value = pendingSeekSeconds;
	nextTick(applyPendingSeek);
}
function seekTimeline(seconds) {
	emit('seek-timeline', Math.round(seconds * Math.max(1, props.fps)));
	const target = Math.max(0, Math.min(totalSeconds.value, seconds));
	const clip = clipAtSeconds(orderedClips.value, target, props.fps);
	if (clip) selectClip(clip, target);
}
</script>

<style scoped>
.rio-status.is-attention { border-color: #a43e50; background: #3a1822; color: #ffb4c0; }
.rio-studio{--rio-cyan:var(--primary-accent);--rio-line:var(--outline-border);--rio-muted:var(--ink-muted);display:flex;flex-direction:column;min-height:0;height:100%;width:100%;background:#070b10;color:#ecf7fb;font:13px Inter,system-ui,sans-serif}.rio-studio button{cursor:pointer}.rio-studio button:disabled{opacity:.4;cursor:not-allowed}.rio-header{height:52px;flex:none;display:flex;align-items:center;gap:18px;padding:0 16px;border-bottom:1px solid var(--rio-line);background:#080d13}.rio-brand{display:flex;align-items:center;gap:8px;white-space:nowrap}.rio-brand-mark{font-size:29px;line-height:1;color:var(--rio-cyan);text-shadow:0 0 14px var(--rio-cyan)}.rio-brand strong{font-size:17px;letter-spacing:1px}.rio-brand strong span{color:var(--rio-cyan)}.rio-status{display:inline-flex;align-items:center;gap:6px;border:1px solid #166b61;border-radius:30px;background:#08352d;color:#47dfb8;padding:3px 9px;font-size:10px;font-weight:700}.rio-status.is-busy{border-color:#8e6918;background:#3b2c0e;color:#ffd063}.rio-status i{width:6px;height:6px;border-radius:50%;background:currentColor}.rio-project-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#b7c9d2;font-weight:600;flex:1}.rio-header-actions{display:flex;gap:7px}.rio-header-actions button,.rio-canvas-controls button{min-width:29px;height:29px;border:1px solid #293e4b;border-radius:7px;background:#111a26;color:#d4f8fa}.rio-header-actions button:hover,.rio-canvas-controls button:hover{border-color:var(--rio-cyan);color:var(--rio-cyan)}.rio-header-actions .rio-classic{font-size:11px;padding:0 9px}.rio-alert{padding:8px 14px;color:#ffb8be;background:#36131b;border-bottom:1px solid #8c3545}.rio-alert button{margin-left:10px;text-decoration:underline}.rio-work-area{display:flex;flex:1;min-height:160px}.rio-assets{width:290px;flex:none;display:flex;flex-direction:column;background:#0b111a;border-right:1px solid var(--rio-line);min-height:0}.rio-assets-head{display:flex;justify-content:space-between;align-items:center;padding:12px;color:var(--rio-cyan);letter-spacing:1px;border-bottom:1px solid var(--rio-line)}.rio-assets-head button,.rio-add-media{border:1px solid #137888;border-radius:7px;background:#0a2833;color:var(--rio-cyan);padding:4px 9px}.rio-assets-list{overflow:auto;flex:1;padding:9px}.rio-asset{display:flex;gap:9px;width:100%;align-items:center;text-align:left;padding:7px;border:1px solid transparent;border-radius:8px;background:transparent;color:#e8f3f8}.rio-asset:hover,.rio-asset.selected{border-color:#1c8ba0;background:#122533}.rio-asset :deep(img),.rio-asset :deep(video){width:50px;height:50px;object-fit:cover;border-radius:5px}.rio-asset span{min-width:0;display:flex;flex-direction:column}.rio-asset strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px}.rio-asset small{color:var(--rio-muted);font-size:10px}.rio-empty-assets{padding:16px 6px;color:var(--rio-muted)}.rio-add-media{margin:9px;text-align:center}.rio-canvas{position:relative;overflow:hidden;flex:1;min-width:0;background-color:#050a10;background-image:linear-gradient(#0b273177 1px,transparent 1px),linear-gradient(90deg,#0b273177 1px,transparent 1px);background-size:24px 24px;touch-action:none}.rio-canvas-inner{position:absolute;inset:0;transform-origin:0 0}.rio-connections{position:absolute;left:0;top:0;overflow:visible;pointer-events:none}.rio-connections path{fill:none;stroke:#087e9c;stroke-width:2.5;filter:drop-shadow(0 0 4px #00e5f288)}.rio-node{position:absolute;width:380px;min-height:430px;border:1px solid #344755;border-radius:13px;background:#171e2a;box-shadow:0 12px 35px #000b;touch-action:none}.rio-node.active{border-color:var(--rio-cyan);box-shadow:0 0 0 1px #00e5f255,0 16px 40px #000c}.rio-node-head{height:39px;display:flex;align-items:center;gap:8px;padding:0 11px;border-bottom:1px solid #2c3746}.rio-node-head>span:first-child{flex:1}.rio-node-ratio{color:#57dcb9;background:#103e39;border:1px solid #236b65;border-radius:4px;font-size:9px;padding:2px 5px}.rio-node-head button{font-size:20px;color:#9cb0bc;padding:0 3px}.rio-node-preview{display:flex;width:calc(100% - 22px);height:190px;margin:10px 11px;align-items:center;justify-content:center;overflow:hidden;border:1px solid #0a202a;border-radius:9px;background:#070b11;color:var(--rio-muted)}.rio-node-preview img{width:100%;height:100%;object-fit:contain}.rio-node-preview span{display:flex;flex-direction:column;align-items:center;font-size:11px}.rio-node-preview b{font-size:26px;color:var(--rio-cyan)}.rio-node-body{padding:4px 11px 8px}.rio-node-body label{display:block;margin-bottom:5px;font-size:11px;color:#b5c5d3}.rio-node-body textarea{width:100%;min-height:70px;resize:vertical;padding:8px;border:1px solid #243445;border-radius:6px;background:#0a1019;color:#eef7fb;font:11px/1.45 inherit}.rio-node-body textarea:focus{outline:1px solid var(--rio-cyan)}.rio-reference-line{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--rio-muted);font-size:10px}.rio-node-actions{display:flex;gap:6px;padding:0 11px 11px}.rio-node-actions button{flex:1;padding:6px 5px;border:1px solid #245e70;border-radius:6px;background:#102634;color:#84eafb;font-size:11px;font-weight:700}.rio-node-actions button:nth-child(2){border-color:#5d408a;color:#d5afff;background:#2d213d}.rio-node-actions button:nth-child(3){border-color:#2d4656;color:#d7e6ec;background:#172533}.rio-node-actions button:hover{filter:brightness(1.35)}.rio-port{position:absolute;top:205px;width:20px;height:20px;border-radius:50%;border:2px solid #07131a;box-shadow:0 0 12px currentColor}.rio-port-in{left:-11px;background:#a855f7;color:#a855f7}.rio-port-out{right:-11px;background:var(--rio-cyan);color:var(--rio-cyan)}.rio-canvas-controls{position:absolute;left:12px;bottom:12px;display:flex;align-items:center;gap:4px;padding:4px;border:1px solid var(--rio-line);border-radius:9px;background:#0b1520e8}.rio-canvas-controls span{min-width:40px;text-align:center;color:var(--rio-cyan);font-size:11px}.rio-minimap{position:absolute;right:12px;top:12px;width:130px;height:85px;border:1px solid #166a7b;border-radius:7px;background:#091a26eb;pointer-events:none;overflow:hidden}.rio-minimap span{position:absolute;left:7px;top:4px;color:var(--rio-muted);font-size:9px}.rio-minimap div{position:absolute;width:15px;height:10px;border:1px solid var(--rio-cyan);border-radius:2px;background:#14546999}.rio-empty-canvas{position:absolute;top:22%;left:50%;transform:translateX(-50%);text-align:center;color:#d9e6e8}.rio-empty-canvas p{margin:8px;color:var(--rio-muted)}.rio-empty-canvas button{margin-top:10px;border:1px solid var(--rio-cyan);border-radius:7px;padding:7px 11px;color:var(--rio-cyan)}.rio-bottom{height:220px;display:flex;gap:5px;flex:none;padding:5px;border-top:1px solid #113a49;background:#05080d}.rio-timeline{flex:1;min-width:0;border:1px solid var(--rio-line);border-radius:8px;overflow:hidden;background:#070d14}.rio-timeline-head{height:37px;display:flex;align-items:center;gap:9px;padding:0 9px;border-bottom:1px solid var(--rio-line)}.rio-timeline-head>button:first-child{background:var(--rio-cyan);color:#041018;border-radius:7px;width:27px;height:25px;font-weight:900}.rio-timeline-head strong{color:#d9f7fa;font-size:10px;letter-spacing:1px}.rio-timeline-head span{flex:1;color:var(--rio-muted);font-size:10px}.rio-timeline-head button:not(:first-child){border:1px solid #2c5263;border-radius:6px;padding:4px 8px;color:#aeeaf1;font-size:10px}.rio-timeline-head .rio-export{background:linear-gradient(90deg,#074d61,#503281);color:white!important;font-weight:700}
.rio-tl-play{background:var(--rio-cyan);color:#041018;border-radius:7px;width:27px;height:25px;font-weight:900}
.rio-tl-zoom{display:flex;align-items:center;gap:5px;padding:2px 7px;border:1px solid #2c5263;border-radius:30px;background:#0a1a24}
.rio-tl-zoom button{border:0;background:none;color:#8be9fb;font-size:13px;line-height:1;padding:0 2px}
.rio-tl-zoom input[type=range]{width:80px;accent-color:var(--rio-cyan)}
.rio-tl-clear{border:1px solid #2c5263;border-radius:6px;background:#102634;padding:4px 7px}
.rio-tl-clear:hover{border-color:var(--rio-cyan)}
.rio-tl-scroll{flex:1;min-height:0;overflow-x:auto;overflow-y:hidden}
.rio-tl-inner{position:relative;min-width:100%}
.rio-tl-needle{position:absolute;top:0;bottom:0;width:2px;margin-left:34px;background:var(--rio-cyan);box-shadow:0 0 7px var(--rio-cyan);pointer-events:none;z-index:3}
.rio-track-icon{font-size:15px}
.rio-ruler{position:relative;height:25px;margin-left:34px;border-bottom:1px solid var(--rio-line)}.rio-ruler span{position:absolute;top:6px;color:#6e8597;font-size:9px}.rio-track{display:flex;height:57px;border-bottom:1px solid var(--rio-line)}.rio-track>b{width:34px;display:grid;place-items:center;border-right:1px solid var(--rio-line);color:#90c1cb}.rio-track-content{position:relative;flex:1;min-width:0}.rio-video-clip,.rio-audio-clip{position:absolute;top:8px;height:38px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left;padding:8px;border:1px solid #15a7bb;border-radius:5px;background:#103b4c;color:#ddfbff;font-size:10px}.rio-audio-clip{border-color:#7942a5;background:#382348;color:#eed1ff}.rio-track-empty{display:block;margin:16px;color:#536675;font-size:10px}.rio-monitor{width:30%;min-width:220px;display:flex;flex-direction:column;border:1px solid #087c91;border-radius:8px;overflow:hidden;background:#010306}.rio-monitor-head{display:flex;justify-content:space-between;padding:5px 9px;color:#85bac4;font-size:9px;letter-spacing:.8px}.rio-monitor-head time{color:var(--rio-cyan)}.rio-monitor video,.rio-monitor img{width:100%;height:calc(100% - 23px);object-fit:contain}.rio-monitor-empty{display:flex;flex:1;flex-direction:column;align-items:center;justify-content:center;color:#8294a2;font-size:23px}.rio-monitor-empty span{font-size:10px}@media(max-width:900px){.rio-project-name{display:none}.rio-assets{width:210px}.rio-bottom{height:185px}.rio-monitor{min-width:180px}}@media(max-width:640px){.rio-assets{position:absolute;left:0;top:0;bottom:0;z-index:5;box-shadow:10px 0 30px #0009}.rio-header-actions .rio-classic{display:none}.rio-monitor{display:none}.rio-node{width:380px}}
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
.rio-ruler input[type="range"]{position:absolute;inset:0 auto 0 -6px;width:calc(100% + 12px);height:100%;margin:0;padding:0;background:transparent;appearance:none;cursor:pointer}
.rio-ruler input[type="range"]::-webkit-slider-runnable-track{height:2px;background:#306073}
.rio-ruler input[type="range"]::-moz-range-track{height:2px;background:#306073}
.rio-ruler input[type="range"]::-webkit-slider-thumb{box-sizing:border-box;width:12px;height:12px;margin-top:-5px;border:2px solid #061018;border-radius:50%;background:#22d3ee;appearance:none;box-shadow:0 0 0 2px #22d3ee66}
.rio-ruler input[type="range"]::-moz-range-thumb{box-sizing:border-box;width:12px;height:12px;border:2px solid #061018;border-radius:50%;background:#22d3ee}
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
.rio-assets{width:340px}
.rio-assets-list{gap:10px;padding:12px}
.rio-asset-card{padding:7px}
.rio-asset-thumb :deep(img),.rio-asset-thumb :deep(video){object-fit:contain}
.rio-asset-name{height:44px;max-height:44px;overflow:hidden;padding:6px 3px 4px;text-align:left;font-size:12px;line-height:17px;white-space:normal;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2}
.rio-empty-canvas{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:min(700px,calc(100% - 48px));max-height:calc(100% - 36px);overflow:auto;padding:28px 32px;text-align:left;border:1px solid #236778;border-radius:14px;background:#0d1722f5;box-shadow:0 20px 50px #000a;color:#e7f5f8;touch-action:auto}
.rio-empty-step{display:inline-block;margin-bottom:10px;color:var(--rio-cyan);font-size:11px;font-weight:800;letter-spacing:1.4px}
.rio-empty-canvas h2{margin:0;font-size:25px;line-height:1.2;font-weight:700}
.rio-empty-canvas p{margin:10px 0 24px;color:#a9c3cf;font-size:14px;line-height:1.5}
.rio-empty-canvas label{display:block;margin-bottom:8px;color:#d9edf2;font-size:13px;font-weight:700}
.rio-empty-canvas textarea{width:100%;min-height:150px;max-height:35vh;margin:0;padding:14px 16px;border-color:#3a6879;border-radius:9px;background:#09121c;color:#f2fafb;font-size:14px;line-height:1.55}
.rio-empty-actions{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-top:18px}
.rio-empty-actions span{color:#97b5c2;font-size:12px;line-height:1.4}
.rio-empty-actions button{flex:none;min-height:42px;margin:0;padding:9px 17px;border-color:#11a6bb;border-radius:8px;background:#07566a;color:#f0fcff;font-size:13px;font-weight:700}
.rio-empty-actions button:hover:not(:disabled){background:#08748c}
@media(max-width:1000px){.rio-assets{width:285px}.rio-assets-list{gap:7px;padding:8px}}
@media(max-width:640px){.rio-assets{width:min(340px,85vw)}.rio-empty-canvas{width:calc(100% - 24px);padding:22px 18px}.rio-empty-canvas h2{font-size:21px}.rio-empty-actions{align-items:stretch;flex-direction:column}.rio-empty-actions button{width:100%}}
.rio-template-anchor{position:relative;flex:none}
.rio-template-trigger{border-color:#0c8497!important;background:#063744!important;color:#d8fbff!important;font-weight:700}
.rio-template-menu{position:fixed;top:62px;right:16px;z-index:45;width:min(440px,calc(100vw - 24px));max-height:min(68vh,650px);overflow:auto;border:1px solid #168ca4;border-radius:12px;background:#0d1924;box-shadow:0 18px 48px #000a;color:#ecf7fb}
.rio-template-menu header{position:sticky;top:0;display:flex;justify-content:space-between;align-items:center;gap:10px;padding:13px 15px;border-bottom:1px solid #285063;background:#102330;color:#56daf0;font-size:12px;letter-spacing:.5px}
.rio-template-menu header span{border:1px solid #168ca4;border-radius:99px;padding:3px 9px;white-space:nowrap}
.rio-template-menu>p{padding:12px 15px;color:#b0c9d2}
.rio-template-item{padding:13px 15px;border-bottom:1px solid #244352}
.rio-template-item:last-child{border-bottom:0}
.rio-template-meta{color:var(--rio-cyan);font-size:10px;margin:2px 0 0}
.rio-template-preview-btn{margin-top:6px;border:1px solid #245e70;border-radius:6px;background:#102634;color:#84eafb;padding:3px 8px;font-size:10px}
.rio-template-preview-btn:hover{border-color:var(--rio-cyan)}
.rio-template-video{display:block;width:100%;margin-top:7px;border-radius:7px;background:#000}
.rio-template-item strong{font-size:13px}
.rio-template-item p{margin:5px 0 10px;color:#aec5cf;font-size:12px;line-height:1.45}
.rio-template-item div{display:flex;gap:7px;flex-wrap:wrap}
.rio-template-item button{min-height:31px;padding:5px 9px;border:1px solid #147f94;border-radius:6px;background:#093441;color:#d8faff;font-size:11px}
.rio-template-item button:hover:not(:disabled){background:#0d5263}
.rio-prompt-heading{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:5px}
.rio-prompt-heading label{margin:0}
.rio-dictate.listening{border-color:#f43f5e;color:#ffb8be;background:#36131b;animation:rio-dictate-pulse 1.4s ease-in-out infinite}
@keyframes rio-dictate-pulse{50%{opacity:.5}}
@media(prefers-reduced-motion:reduce){.rio-dictate.listening{animation:none}}
.rio-prompt-heading button{border:1px solid #245e70;border-radius:5px;background:#102634;color:#84eafb;padding:3px 7px;font-size:10px}
.rio-prompt-heading button:hover:not(:disabled){border-color:var(--rio-cyan)}
/* A scene that starts fresh gets a dashed, dimmer line; one that carries on gets the lit line. */
.rio-connections path{stroke:#2b4654;stroke-dasharray:7 6;filter:none}
.rio-connections path.continues{stroke:#087e9c;stroke-dasharray:none;filter:drop-shadow(0 0 4px #00e5f288)}
.rio-link-toggle{position:absolute;transform:translate(-50%,-50%);white-space:nowrap;border:1px solid #2b4654;border-radius:30px;background:#0b1520f2;color:#8aa6b4;padding:3px 10px;font-size:10px;font-weight:700;letter-spacing:.3px}
.rio-link-toggle.continues{border-color:#0e7f97;background:#072934f2;color:#8be9fb}
.rio-link-toggle:hover:not(:disabled){border-color:var(--rio-cyan);color:var(--rio-cyan)}
.rio-link-toggle:focus-visible{outline:2px solid var(--rio-cyan);outline-offset:2px}
/* Bottom-right keeps the overview clear of the toast stack, which owns the top-right. */
.rio-minimap{top:auto;bottom:12px}
.rio-minimap.is-interactive{pointer-events:auto;cursor:crosshair}
.rio-minimap div.active{border-color:#fff;background:#2b7f98cc}
.rio-missing{align-items:center;justify-content:center}
.rio-missing-box{max-width:460px;text-align:center;padding:30px;border:1px solid var(--rio-line);border-radius:14px;background:#0b1520}
.rio-missing-icon{font-size:40px;color:#f59e0b}
.rio-missing-box h2{margin:12px 0 8px;font-size:17px;color:#f6d79a}
.rio-missing-box p{margin:0 0 16px;color:var(--rio-muted);font-size:13px;line-height:1.6}
.rio-missing-link{display:inline-block;border:1px solid var(--rio-cyan);border-radius:8px;padding:8px 16px;color:var(--rio-cyan);text-decoration:none;font-weight:700}
.rio-missing-link:hover{background:#06313e}
.rio-identity{display:flex;flex-direction:column;gap:4px;margin:8px 0}
.rio-identity label{color:var(--rio-cyan);font-size:11px;font-weight:700}
.rio-identity input{padding:6px 8px;border:1px solid #243445;border-radius:6px;background:#0a1019;color:#eef7fb;font:12px inherit}
.rio-identity input:focus{outline:1px solid var(--rio-cyan)}
.rio-identity small{color:var(--rio-muted);font-size:10px;line-height:1.45}
.rio-minimap-viewport{position:absolute;border:1px solid #7fe9ff;border-radius:2px;background:#7fe9ff1f;pointer-events:none}
/* Media panel: width handle, drop target, rubber band and the batch bar. */
.rio-assets{position:relative}
.rio-drawer-resize{position:absolute;right:-3px;top:0;bottom:0;width:7px;z-index:4;cursor:col-resize;touch-action:none}
.rio-drawer-resize:hover{background:linear-gradient(90deg,transparent,#00f0ff55,transparent)}
.rio-assets.is-drop-target{outline:2px dashed var(--rio-cyan);outline-offset:-4px;background:#0d1a24}
.rio-drop-hint{margin:0;padding:8px 10px;border-top:1px solid var(--rio-line);color:var(--rio-cyan);font-size:11px;text-align:center}
.rio-asset-card.is-multi-selected{outline:2px solid var(--rio-cyan);outline-offset:-1px;box-shadow:0 0 14px #00e5f24d}
.rio-marquee{position:fixed;z-index:50;border:1px solid var(--rio-cyan);border-radius:3px;background:#00f0ff22;pointer-events:none}
.rio-batch-bar{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 10px;border-top:1px solid #0e7f97;background:#07222cf5;color:#cdeef6;font-size:11px}
.rio-batch-actions{display:flex;gap:6px}
.rio-batch-bar b{color:var(--rio-cyan)}
.rio-batch-remove{border:1px solid #8c3545;border-radius:6px;background:#36131b;color:#ffb8be;padding:4px 9px;font-weight:700}
.rio-batch-remove:hover:not(:disabled){border-color:#f43f5e;color:#fff}
.rio-batch-cancel{border:1px solid #2b4654;border-radius:6px;background:transparent;color:#8aa6b4;padding:4px 8px}
.rio-batch-cancel:hover{border-color:var(--rio-cyan);color:var(--rio-cyan)}
/* Preview stage holds both players stacked, plus the floating timecode. */
.rio-monitor-stage{position:relative;flex:1;min-height:0}
.rio-monitor-stage video{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#000}
.rio-monitor-timecode{position:absolute;right:8px;top:8px;z-index:2;padding:2px 7px;border-radius:5px;background:#030a0ecc;color:var(--rio-cyan);font-size:11px;font-variant-numeric:tabular-nums;letter-spacing:.5px;pointer-events:none;text-shadow:0 0 8px #00e5f2aa}

/* Workspace proportions follow the standalone editor; workflow feedback is in
   the status popover so it does not take space from the canvas. */
.rio-header{height:52px;min-height:52px;background:#070a10}
.rio-brand .rio-status{display:inline-flex;align-items:center;gap:6px;cursor:pointer;font:inherit;font-size:10px}
.rio-status small{font-size:11px;color:inherit}
.rio-status-panel{position:absolute;top:52px;left:16px;z-index:40;width:min(680px,calc(100vw - 32px));max-height:60vh;overflow:auto;border:1px solid #1c6273;border-radius:0 0 10px 10px;background:#0d1722;box-shadow:0 14px 35px #000a}
.rio-status-panel .rio-guidance{font-size:12px}
.rio-canvas{background-color:#070a10;background-image:linear-gradient(#0b273155 1px,transparent 1px),linear-gradient(90deg,#0b273155 1px,transparent 1px);background-size:20px 20px}
.rio-assets{margin:10px 0 10px 10px;background:#0e121a}
.rio-assets-head{height:46px;flex-shrink:0}
.rio-add-media{font-size:11px;padding:5px;min-height:28px}
.rio-node{display:flex;flex-direction:column;min-height:430px;background:#141824;border:1.5px solid #232d42;border-radius:12px}
.rio-node.active{border-color:#00e5f2;box-shadow:0 0 0 1px #00e5f2,0 0 18px #00e5f244,0 16px 40px #000b}
.rio-node-head{flex:none;height:39px;background:#ffffff03;border-color:#ffffff0f;cursor:move}
.rio-node-head .rio-node-collapse{height:22px;min-width:22px;padding:0;border:1px solid #2a4059;border-radius:5px;font-size:14px;line-height:1}
.rio-node-ratio.working{color:#fbbf24;border-color:#845d22;background:#f59e0b15}
.rio-node-preview{flex:none;height:200px;margin:10px 12px 8px;width:calc(100% - 24px);border:1px solid #ffffff0d;background:#05070c;box-shadow:inset 0 0 20px #000b}
.rio-node-preview b{font-size:23px;margin-bottom:8px}
.rio-node-body{flex:1;padding:6px 12px 8px;min-height:0}
.rio-node-body textarea{height:82px;min-height:82px;resize:vertical;background:#080c14;font-size:12px;line-height:1.5}
.rio-prompt-heading{gap:5px;min-height:23px}
.rio-prompt-heading label{flex:1;margin:0;font-weight:600}
.rio-prompt-heading button{max-width:130px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rio-node-actions{flex:none;gap:5px;padding:0 12px 11px;align-items:center;flex-wrap:wrap}
.rio-node-actions button{min-width:0;min-height:28px;flex:1;white-space:nowrap;font-size:10px;padding:5px 6px}
.rio-node-actions .rio-action-f0{background:#112a3a;color:#38bdf8;border-color:#265576}
.rio-node-actions .rio-action-settings{background:#473054;color:#f2ddff;border-color:#ba5ce7}
.rio-node-actions .rio-action-render{background:#10b981;color:#041911;border-color:#10b981}
.rio-node-actions .rio-action-timeline{background:#0c1b29;color:#38bdf8;border-color:#265576}
.rio-node.compact{min-height:39px;height:39px}
.rio-port{top:50%;transform:translateY(-50%);width:24px;height:24px;border:3px solid #07090e;padding:0;z-index:3;cursor:pointer}
.rio-port-in{left:-13px}.rio-port-out{right:-13px}
.rio-port-reference{left:-13px;top:22%;color:#10b981;background:#10b981}
.rio-port-ending{left:-13px;top:78%;color:#f59e0b;background:#f59e0b}
.rio-node.compact .rio-port-reference,.rio-node.compact .rio-port-ending{display:none}
.rio-minimap{top:16px;bottom:auto;right:16px;width:170px;height:110px;border-radius:9px;background:#0d1420eb;box-shadow:0 0 18px #00e5f21a}
.rio-minimap .rio-minimap-content{position:absolute;inset:23px 8px 8px;width:auto;height:auto;background:none;border:0;overflow:hidden}
.rio-minimap>span{left:0;right:0;top:0;padding:6px 9px;cursor:move;touch-action:none;font-size:10px;font-weight:700;letter-spacing:1px}
.rio-minimap-viewport{border-color:#00e5f2;box-shadow:0 0 10px #00e5f255}
.rio-canvas-controls{opacity:.65;padding:3px}
.rio-canvas-controls:hover,.rio-canvas-controls:focus-within{opacity:1}
.rio-bottom{gap:6px;padding:5px;background:#070a10}
.rio-timeline{display:flex;flex-direction:column;background:#070b11}
.rio-timeline-head{flex:none;min-height:40px;height:40px;gap:7px;padding:0 9px;background:#10131f}
.rio-timeline-head .rio-tl-play{border-radius:20px;width:31px;height:27px;box-shadow:0 0 12px #00e5f233}
.rio-timeline-head .rio-timeline-description{display:none}
.rio-timeline-head .rio-timeline-spacer{flex:1;min-width:3px}
.rio-timeline-head .rio-export{margin-left:auto;background:linear-gradient(100deg,#06b6d4,#8b5cf6);color:#080d17!important;min-height:28px;font-size:11px;border:0;box-shadow:0 0 12px #06b6d433}
.rio-tl-zoom{flex:none;gap:4px;padding:3px 5px}
.rio-tl-zoom input[type=range]{width:65px}
.rio-ruler{height:23px;margin-left:48px}
.rio-track>b{width:48px;flex-shrink:0}.rio-tl-needle{margin-left:0;transform:translateX(-50%)}
.rio-track{height:61px}.rio-track-empty{font-size:11px;color:#637887}
.rio-monitor{width:26%;min-width:220px;border-color:#00dcea;border-radius:9px;position:relative}
.rio-monitor-head{position:absolute;top:5px;right:5px;z-index:3;padding:2px 5px;border:1px solid #135969;border-radius:4px;background:#030a0ecc;box-shadow:0 0 8px #00e5f244}
.rio-monitor-head>span{display:none}
.rio-monitor>img{height:100%;width:100%}
.rio-monitor-timecode{display:none}
@media(max-width:900px){.rio-timeline-head{overflow-x:auto}.rio-monitor{min-width:180px}.rio-tl-zoom input[type=range]{width:45px}.rio-minimap{width:140px;height:90px}}
@media(max-width:640px){.rio-header-actions{max-width:62%}.rio-bottom{height:auto!important;max-height:40vh}.rio-monitor{min-height:120px;width:100%}.rio-minimap{width:110px;height:75px;right:8px;top:8px}}

.rio-tool-overlay{position:fixed;inset:0;z-index:70;display:grid;place-items:center;padding:20px;background:#03060bc9;backdrop-filter:blur(4px)}
.rio-tool-dialog{width:min(760px,100%);max-height:90vh;overflow:auto;padding:20px;border:1px solid #24576c;border-radius:13px;background:#101722;color:#e7f2f7;font:13px/1.6 Inter,system-ui,sans-serif;box-shadow:0 20px 60px #000a}
.rio-tool-dialog header,.rio-tool-dialog footer{display:flex;align-items:center;justify-content:space-between;gap:12px}.rio-tool-dialog header{color:#55e5f0}.rio-tool-dialog header button{font-size:24px}.rio-tool-dialog p{margin:14px 0;color:#a9bfcc}.rio-tool-dialog footer{margin-top:16px}.rio-tool-dialog button{padding:6px 10px;border:1px solid #23657c;border-radius:7px;background:#11313e;color:#86eff7}.rio-tool-dialog label{display:block;color:#a9bfcc;font-size:11px}.rio-tool-dialog input,.rio-tool-dialog select{display:block;width:100%;padding:8px;border:1px solid #2a4054;border-radius:6px;background:#090e17;color:#eff8ff}
.rio-character-row{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid #243645}.rio-character-row>:first-child{width:72px;min-width:72px;flex:0 0 72px}.rio-character-row>div{flex:1;min-width:100px}.rio-character-row strong{display:block;font-size:12px}.rio-export-options{max-width:480px}.rio-timeline-head{overflow-x:auto}.rio-timeline-head>button,.rio-tl-zoom,.rio-audio-add{flex-shrink:0}
@media(max-width:640px){.rio-character-row{flex-wrap:wrap}.rio-tool-dialog{padding:14px}}

.rio-versions{display:flex;flex-direction:column;overflow:hidden}.rio-versions>header{flex:none}.rio-versions :deep([data-test="video-shelf"]){display:flex;flex-direction:column;min-height:0;overflow:hidden}.rio-versions :deep(.video-shelf-grid){min-height:0;max-height:none;overflow-y:auto;flex:1}
</style>

<template>
  <div class="jm-workspace h-full overflow-y-auto" data-test="client-workspace">
    <header class="jm-workspace-header">
      <span class="jm-project-brand" aria-label="RIO Studio"><span aria-hidden="true">◇</span><strong>RIO</strong></span>
      <button class="text-sm text-ink-secondary shrink-0" @click="emit('back')">← {{ t('Your videos','Video của bạn') }}</button>
      <h1 class="font-semibold truncate flex-1">{{ title }}</h1>
      <button v-if="!archived" type="button" class="text-sm text-rio-500 shrink-0" data-test="open-rio-studio" @click="emit('advanced')">RIO Studio</button>
      <details ref="moreMenu" class="relative text-sm"><summary class="cursor-pointer px-2">{{ t('More','Thêm') }}</summary>
        <div class="absolute right-0 top-8 w-52 rounded-xl border border-outline-border bg-surface-card p-2 shadow-xl flex flex-col items-stretch">
          <button class="text-left p-2" data-test="open-project-history" @click="emit('history')">{{ t('Version history','Lịch sử phiên bản') }}</button>
          <button v-if="access.can_use_advanced_editor" class="text-left p-2" data-test="open-advanced-editor" @click="emit('advanced')">{{ t('Advanced editor','Trình chỉnh sửa nâng cao') }}</button>
          <button v-if="!archived" type="button" class="text-left p-2" data-test="open-video-settings" @click.stop="openSettings">{{ t('Video settings','Cài đặt video') }}</button>
        </div>
      </details>
    </header>
    <main class="jm-workspace-body">
      <p v-if="loading" role="status">{{ t('Loading your video…','Đang tải video…') }}</p>
      <template v-else-if="workspace">
        <VideoShelf :project="project" :readonly="access.reviewer || archived" style="order:-2" />
        <CreativeBatchPanel v-if="!access.reviewer" :project="project" :focus="workspace.family && workspace.family.root !== project ? project : ''" @loaded="(state) => { aiBatches = state.count; aiVideo = state.focused; }" @show-video="finished?.scrollIntoView({ block: 'start', behavior: 'smooth' })" />
        <div v-if="!aiVideo && !aiContainer && workspace.family && !workspace.family.is_working_edit" class="rounded-xl border border-outline-border p-4 flex flex-wrap items-center justify-between gap-3" data-test="alternate-edit-notice">
          <p class="text-sm">{{ t('Saved version','Phiên bản đã lưu') }} · {{ workspace.family.edit_label }}</p>
          <button class="jm-button-primary" data-test="open-working-edit" @click="emit('working-edit',workspace.family.current_edit)">{{ t('Open current version','Mở phiên bản hiện tại') }}</button>
        </div>
        <div v-if="archived" class="rounded-xl border border-outline-border p-4 flex flex-wrap items-center justify-between gap-3" data-test="archived-notice">
          <p class="text-sm">{{ t('This video is in the trash and will be deleted for good 30 days after it was removed. You can watch it or restore it.','Video này đang trong thùng rác và sẽ tự xóa vĩnh viễn 30 ngày sau khi bị xóa. Bạn có thể xem hoặc khôi phục.') }}</p>
          <button class="jm-btn-primary px-3 py-2" :disabled="busy" @click="emit('restore')">{{ t('Restore video','Khôi phục video') }}</button>
        </div>
        <p v-if="error" role="alert" class="text-sm text-rose-500">{{ error }}</p>
        <ol v-if="!aiContainer && !aiVideo" class="flex flex-wrap gap-5 text-xs text-ink-muted" :aria-label="t('Video steps','Các bước tạo video')">
          <li :class="{'text-rio-500 font-bold':step===1}">1. {{ t('Your idea','Ý tưởng') }}</li>
          <li :class="{'text-rio-500 font-bold':step===2}">2. {{ t('Review scenes','Duyệt cảnh') }}</li>
          <li :class="{'text-rio-500 font-bold':step===3}">3. {{ t('Your video','Video của bạn') }}</li>
        </ol>
        <button v-if="shots.length && !aiVideo" class="text-sm text-rio-500 underline justify-self-start" data-test="open-storyboard" @click="scenes?.scrollIntoView({block:'start',behavior:'smooth'})">{{ t('Review storyboard','Duyệt bảng phân cảnh') }} ↓</button>
        <!-- A finished AI video leads the page; how it was made follows below. -->
        <section v-if="video?.file || (shots.length && !aiVideo)" ref="finished" class="jm-stage-section" data-test="client-video" :style="aiVideo && video?.file ? 'order:-1' : ''">
          <div class="jm-stage-toolbar"><div><span v-if="!aiVideo" class="jm-eyebrow">{{ t('PREVIEW','XEM TRƯỚC') }}</span><p v-if="!aiVideo && workspace.family?.edit_label && (!reviewVersion || reviewVersion===currentVersion)" class="text-xs text-ink-muted" data-test="preview-edit-label">{{ workspace.family.edit_label }}</p><h2>{{ selectedScene ? t('Scene','Cảnh')+' '+(shots.indexOf(selectedScene)+1) : t('Your complete video','Video hoàn chỉnh') }}</h2></div><button v-if="reviewVersion && reviewVersion!==currentVersion" class="jm-button-secondary" @click="emit('review-close')">{{ t('Back to current video','Về video hiện tại') }}</button><button v-if="selectedScene && video?.file" class="jm-button-secondary" @click="selectMedia('master')">{{ t('Back to full video','Về video hoàn chỉnh') }}</button></div>
          <VideoReviewDialog v-if="inlineVersion" :key="project+inlineVersion+reviewFocused+reviewStartFrame" ref="inlineReview" embedded :project="project" :asset-version="inlineVersion" :focused-name="reviewFocused" :initial-frame="reviewStartFrame" @saved="emit('feedback-saved')" />
          <div v-else class="jm-canvas" tabindex="0" :aria-label="t('Video preview','Xem trước video')" @keydown.space.self.prevent="togglePlayback">
            <video v-if="mediaIsVideo" :key="mediaUrl" ref="stageVideo" :src="mediaUrl" controls playsinline preload="metadata" @loadedmetadata="mediaReady=true" @timeupdate="previewTime=$event.target.currentTime" @play="playback.play" @error="previewError=true" />
            <img v-else-if="mediaUrl" :key="mediaUrl+previewRetry" :src="mediaUrl" @error="previewError=true" :alt="t('Scene preview','Ảnh xem trước cảnh')" />
            <div v-else class="jm-canvas-empty"><span class="jm-canvas-symbol">▧</span><h3>{{ t('Your scene will appear here','Cảnh của bạn sẽ xuất hiện ở đây') }}</h3><p>{{ t('Review the scene plan below, then create your preview images.','Duyệt kịch bản bên dưới, rồi tạo ảnh xem trước.') }}</p></div>
            <div v-if="previewError" class="jm-playback-error" role="alert"><p>{{ t('This preview could not be played.','Không phát được bản xem trước này.') }}</p><button class="jm-button-secondary" @click="retryPreview">{{ t('Retry preview','Thử phát lại') }}</button></div>
          </div>
		  <div v-if="selectedScene" class="jm-scene-caption"><strong>{{ selectedScene.shot_name || selectedScene.title }}</strong><p>{{ shortCaption(sceneAction(selectedScene)) }}</p>
			<div v-if="aiVideo && video?.file && !archived" class="flex flex-wrap gap-2 mt-2">
			  <span class="text-xs text-ink-muted">{{ t('This take stays in the full video until you choose another one.', 'Cảnh này được giữ trong video đầy đủ cho đến khi bạn chọn bản khác.') }}</span>
			  <button class="jm-button-secondary" :disabled="busy" @click="emit('retry-scene', selectedScene)">{{ t('Retry clip', 'Tạo lại clip') }}</button>
			  <button class="jm-button-secondary" :disabled="busy" @click="emit('redraw', selectedScene.name)">{{ t('Retry first frame', 'Vẽ lại ảnh đầu') }}</button>
			  <button class="jm-button-secondary" :disabled="busy" @click="emit('history', selectedScene.name)">{{ t('Choose another take', 'Chọn bản khác') }}</button>
			</div>
		  </div>
          <p v-if="!selectedScene && video?.is_outdated" class="jm-timeline-note px-4 py-2" data-test="outdated-preview">{{ hasOutdatedScenes?t('Some scenes still use earlier footage.','Một số cảnh vẫn dùng footage cũ.'):t('The preview needs refreshing.','Cần làm mới bản xem trước.') }} <button v-if="!archived" class="underline" :disabled="busy" :data-test="hasOutdatedScenes?'update-client-scenes':'refresh-client-preview'" @click="hasOutdatedScenes?emit('continue'):emit('assemble')">{{ hasOutdatedScenes?t('Update scenes','Cập nhật cảnh'):t('Refresh preview','Làm mới bản xem trước') }}</button></p>
          <div class="jm-stage-actions">
            <p>{{ aiVideo ? '' : t('Preview · check your product, logo and character before publishing.','Bản xem trước · kiểm tra sản phẩm, logo và nhân vật trước khi đăng.') }}</p>
            <div><a v-if="mediaIsVideo && (!reviewVersion || reviewVersion===currentVersion)" :href="mediaUrl" download class="jm-button-primary">{{ aiVideo ? t('Download video','Tải video') : t('Download preview','Tải bản xem trước') }}</a></div>
          </div>
		  <div v-if="shots.length && !aiVideo" class="jm-scene-strip" role="group" :aria-label="t('Scene navigator','Chọn cảnh')" @keydown="navigateScenes">
            <button v-if="video?.file" type="button" class="jm-scene-tile jm-master-tile" :aria-pressed="!selectedScene" data-media-key="master" @click="selectMedia('master')"><span>▶</span><strong>{{ t('Full video','Cả video') }}</strong><small>{{ shots.length }} {{ t('scenes','cảnh') }}</small></button>
            <button v-for="(shot,index) in shots" :key="shot.name" type="button" class="jm-scene-tile" :aria-pressed="selectedScene?.name===shot.name" :data-media-key="shot.name" :data-test="'select-scene-'+index" :aria-label="t('Preview scene','Xem cảnh')+' '+(index+1)" @click="selectMedia(shot.name)"><img v-if="frame(shot)?.url" :src="frame(shot).url" alt="" loading="lazy" /><span v-else class="jm-scene-placeholder">{{ String(index+1).padStart(2,'0') }}</span><span class="jm-scene-tile-label">{{ t('Scene','Cảnh') }} {{ index+1 }} <small>{{ Number(shot.duration_seconds || 0).toFixed(0) }}s</small></span></button>
          </div>
        </section>
        <section v-if="!archived && !aiContainer && !aiVideo && (action!=='watch' || !video?.file)" class="jm-creation-panel" data-test="client-next-step">
          <h2 class="text-lg font-semibold">{{ instruction[0] }}</h2>
          <p class="text-sm text-ink-secondary">{{ instruction[1] }}</p>
          <textarea v-if="['brief','plan'].includes(action)" :value="prompt" :aria-label="t('Video idea','Ý tưởng video')" :placeholder="t('What product are you promoting, and what should happen in the video?','Bạn quảng cáo sản phẩm nào và muốn video có nội dung gì?')" rows="4" class="jm-prompt-input" @input="emit('update:prompt',$event.target.value)" />
          <button v-if="!['working','loading','review'].includes(action)" class="jm-button-primary jm-generate-button" :disabled="busy || (action==='brief'&&!prompt.trim())" @click="action==='watch'?emit('assemble'):emit('continue')">{{ instruction[2] }}</button>
          <p v-else-if="['working','loading'].includes(action)" role="status" class="text-sm text-rio-500">{{ t('You can leave this page and return later.','Bạn có thể rời trang và quay lại sau.') }}</p>
        </section>
        <div v-if="shots.length && !aiVideo" ref="scenes" class="scroll-mt-4"><ClientStoryboard :shots="shots" :frames="frames" :current-lang="currentLang" :archived="archived" :action="action" :busy="busy" :script-download-url="workspace?.project?.storyboard_download_url" @approve="(name,value)=>emit('approve',name,value)" @redraw="name=>emit('redraw',name)" @review="version=>emit('review',version)" @history="name=>emit('history',name)" /></div>
        <details class="text-sm border-t border-outline-border pt-4"><summary class="cursor-pointer text-ink-muted">{{ t('Your brief & images','Ý tưởng và hình ảnh') }}</summary>
          <p class="my-3 whitespace-pre-wrap text-ink-secondary">{{ prompt }}</p>
          <p v-if="productImages.length===1" class="my-3 text-amber-700" data-test="single-product-view-notice">{{ t('Only one product photo is supplied. Side and back packaging cannot be verified from it; add real photos from those angles for accurate multi-angle scenes.', 'Chỉ có một ảnh sản phẩm. Không thể xác minh mặt bên và mặt sau từ ảnh này; hãy thêm ảnh thật ở các góc đó để tạo cảnh nhiều góc chính xác.') }}</p>
          <p v-if="productImages.length>1 && !productImages.some(asset=>asset.product_view==='back')" class="my-3 text-amber-700">{{ t('No rear product view is supplied. Rear packaging remains unverified.', 'Chưa có ảnh mặt sau sản phẩm. Bao bì mặt sau vẫn chưa được xác minh.') }}</p>
          <div class="flex flex-wrap gap-3"><figure v-for="asset in images" :key="asset.asset_version || asset.name" class="w-28"><img :src="asset.file || asset.file_url" :alt="asset.label || asset.asset_name || ''" class="w-28 h-28 object-contain rounded border border-outline-border bg-white" /><figcaption class="mt-1 text-xs text-ink-muted break-words">{{ asset.reference_role==='Product' ? (asset.product_view || 'source').replaceAll('_',' ') : (asset.label || asset.asset_name || '') }}</figcaption></figure></div>
          <button v-if="!archived && access.can_use_advanced_editor" class="underline mt-3" @click="emit('advanced')">{{ t('Edit brief and images','Chỉnh sửa ý tưởng và hình ảnh') }}</button>
        </details>
      </template>
      <div v-else-if="missing" role="alert" class="space-y-3 py-10 text-center" data-test="video-missing">
        <p class="text-base font-semibold">{{ t('This video could not be found.','Không tìm thấy video này.') }}</p>
        <p class="text-sm text-ink-secondary">{{ t('It may have been deleted for good, or it belongs to another account.','Có thể video đã bị xóa vĩnh viễn hoặc thuộc tài khoản khác.') }}</p>
        <button class="jm-button-primary" @click="emit('back')">← {{ t('Back to your videos','Về trang Video của bạn') }}</button>
      </div>
      <p v-else role="alert">{{ t('Could not load this video.','Không tải được video.') }} <button class="underline" @click="emit('refresh')">{{ t('Try again','Thử lại') }}</button></p>
    </main>
  </div>
</template>
<script setup>
import ClientStoryboard from './ClientStoryboard.vue';
import VideoReviewDialog from './VideoReviewDialog.vue';
import {shortCaption,sceneAction} from '../../utils/storyboard';
import CreativeBatchPanel from './CreativeBatchPanel.vue';
import VideoShelf from './VideoShelf.vue';
import {useSession} from "../../stores/session";
import { computed, ref, watch } from 'vue';
import {usePreviewPlayback} from '../../composables/usePreviewPlayback';
const props=defineProps({project:String,title:String,currentLang:String,workspace:Object,loading:Boolean,prompt:{type:String,default:''},shots:{type:Array,default:()=>[]},frames:{type:Array,default:()=>[]},video:Object,reviewVersion:{type:String,default:''},reviewFocused:{type:String,default:''},reviewStartFrame:{type:Number,default:null},reviewRevision:{type:Number,default:0},action:String,busy:Boolean,error:String,missing:Boolean});
const emit=defineEmits(['back','history','working-edit','advanced','settings','continue','assemble','update:prompt','approve','redraw','retry-scene','restore','refresh','review','feedback-saved','review-close']);
const t=(en,vi)=>props.currentLang==='vi'?vi:en;
const {access}=useSession();
const scenes=ref(null),inlineReview=ref(null),finished=ref(null),moreMenu=ref(null);
const hasOutdatedScenes=computed(()=>props.shots.some(shot=>shot.is_outdated));
const inlineVersion=computed(()=>props.reviewVersion||currentVersion.value);
const stageVideo=ref(null), selectedMedia=ref('master'),previewError=ref(false),previewRetry=ref(0);
const previewTime=ref(0),mediaReady=ref(false);
const playback=usePreviewPlayback();
const selectedScene=computed(()=>selectedMedia.value==='master' ? (props.video?.file?null:props.shots[0] || null) : props.shots.find(s=>s.name===selectedMedia.value) || null);
const mediaIsVideo=computed(()=>selectedScene.value ? Boolean(selectedScene.value.selected_output_file || selectedScene.value.output_video) : Boolean(props.video?.file));
const mediaUrl=computed(()=>selectedScene.value ? selectedScene.value.selected_output_file || selectedScene.value.output_video || frame(selectedScene.value)?.url || '' : props.video?.file || '');
const currentVersion=computed(()=>selectedScene.value?.selected_output_asset_version || (!selectedScene.value?props.video?.asset_version:''));
function selectMedia(key){emit('review-close');playback.pauseAll();selectedMedia.value=key;previewError.value=false;}
// A native <details> menu remains above nearby content until it is explicitly
// closed. Close it before emitting so the settings overlay always receives the
// click and keyboard focus on both desktop and touch browsers.
function openSettings(){
  if(moreMenu.value) moreMenu.value.open=false;
  emit('settings');
}
function togglePlayback(){const element=stageVideo.value;if(element)element.paused?element.play().catch(()=>previewError.value=true):element.pause();}
function retryPreview(){previewError.value=false;previewRetry.value++;stageVideo.value?.load();}
watch(mediaUrl,()=>{previewError.value=false;previewTime.value=0;mediaReady.value=false;playback.pauseAll();});
watch(()=>props.reviewVersion,version=>{if(!version)return;const shot=props.shots.find(row=>row.selected_output_asset_version===version);if(shot)selectedMedia.value=shot.name;inlineReview.value?.$el?.scrollIntoView({block:'start'});});
function navigateScenes(event){
 if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
 const buttons=[...event.currentTarget.querySelectorAll('button[data-media-key]')];
 const index=buttons.indexOf(document.activeElement);if(index<0)return;
 event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:Math.max(0,Math.min(buttons.length-1,index+(event.key==='ArrowRight'?1:-1)));
 buttons[next]?.focus();selectMedia(buttons[next]?.dataset.mediaKey || 'master');
}
const archived=computed(()=>props.workspace?.family?.archived || props.workspace?.project?.status==='Archived');
const images=computed(()=>(props.workspace?.assets||[]).filter(a=>/\.(png|jpe?g|webp)(\?|$)/i.test(a.file||a.file_url||'')));
const productImages=computed(()=>images.value.filter(asset=>asset.reference_role==='Product'));
const frame=shot=>props.frames.find(f=>f.shot===shot.name);
// A project that only holds the product inputs of its AI-written videos is not itself a video:
// its manual idea → storyboard steps would start a stray second storyboard.
const aiBatches=ref(0);
// An AI-written video is followed entirely in its own panel (script → pictures → video);
// the manual step bar, storyboard grid and second player would repeat it.
const aiVideo=ref(false);
const aiContainer=computed(()=>aiBatches.value>0 && !props.shots.length && !props.video?.file);
const step=computed(()=>props.video?.file||props.action==='watch'?3:['brief','plan'].includes(props.action)?1:2);
const instruction=computed(()=>({
 brief:[t('Tell us your idea','Mô tả ý tưởng của bạn'),t('Describe your product and the video you want.','Mô tả sản phẩm và video bạn muốn.'),t('Create scene plan','Lên kịch bản')],
 plan:[t('Your idea is ready','Ý tưởng đã sẵn sàng'),t('We will turn your brief into scenes for you to review.','Hệ thống sẽ chuyển ý tưởng thành các cảnh để bạn duyệt.'),t('Create scene plan','Lên kịch bản')],
 approve:[t('Review your scene plan','Duyệt kịch bản'),t('Check the story before continuing.','Duyệt nội dung trước khi tiếp tục.'),t('Continue to preview images','Tiếp tục xem ảnh')],
 previews:[t('Prepare scene previews','Tạo ảnh xem trước'),t('See each scene before making the video.','Xem trước từng cảnh trước khi tạo video.'),t('Create preview images','Tạo ảnh xem trước')],
 review:[t('Choose the images for your video','Chọn ảnh cho video'),t('Check images, then approve.','Kiểm tra ảnh rồi duyệt.')],
 render:[t('Your scenes are ready','Các cảnh đã sẵn sàng'),t('The approved images will be used to make your video.','Video sẽ được tạo từ các ảnh bạn đã duyệt.'),t('Generate video','Tạo video')],
 watch:[t('Your scenes are ready to assemble','Các cảnh đã sẵn sàng để ghép'),t('Create a preview of the complete film.','Tạo bản xem trước của toàn bộ phim.'),t('Create full video preview','Tạo bản xem trước hoàn chỉnh')],
 working:[t('Creating your video','Đang tạo video'),t('Your progress is saved automatically.','Tiến trình được lưu tự động.')],
 loading:[t('Checking your scenes','Đang kiểm tra các cảnh'),t('Loading the latest previews.','Đang tải ảnh xem trước mới nhất.')],
 retry:[t('Previews could not be loaded','Không tải được ảnh xem trước'),t('Try loading your scene previews again.','Thử tải lại ảnh xem trước các cảnh.'),t('Try again','Thử lại')]
}[props.action]||[]));
</script>

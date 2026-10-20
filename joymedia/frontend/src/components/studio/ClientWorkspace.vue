<template>
  <div class="jm-workspace h-full overflow-y-auto" data-test="client-workspace">
    <header class="jm-workspace-header">
      <button class="text-sm text-ink-secondary shrink-0" @click="emit('back')">← {{ t('Your videos','Video của bạn') }}</button>
      <RoleBadge compact />
      <h1 class="font-semibold truncate flex-1">{{ title }}</h1>
      <button class="jm-button-secondary jm-history-shortcut" data-test="client-version-history" @click="emit('history')">{{ t('Version history','Lịch sử phiên bản') }}</button>
      <details class="relative text-sm"><summary class="cursor-pointer px-2">{{ t('More','Thêm') }}</summary>
        <div class="absolute right-0 top-8 w-52 rounded-xl border border-outline-border bg-surface-card p-2 shadow-xl flex flex-col items-stretch">
          <button class="text-left p-2" data-test="open-project-history" @click="emit('history')">{{ t('Version history','Lịch sử phiên bản') }}</button>
          <button v-if="access.can_use_advanced_editor" class="text-left p-2" data-test="open-advanced-editor" @click="emit('advanced')">{{ t('Advanced editor','Trình chỉnh sửa nâng cao') }}</button>
          <button v-if="!archived" class="text-left p-2" @click="emit('settings')">{{ t('Video settings','Cài đặt video') }}</button>
        </div>
      </details>
    </header>
    <main class="jm-workspace-body">
      <p v-if="loading" role="status">{{ t('Loading your video…','Đang tải video…') }}</p>
      <template v-else-if="workspace">
        <div v-if="workspace.family && !workspace.family.is_working_edit" class="rounded-xl border border-outline-border p-4 flex flex-wrap items-center justify-between gap-3" data-test="alternate-edit-notice">
          <p class="text-sm">{{ t('Saved version','Phiên bản đã lưu') }} · {{ workspace.family.edit_label }}</p>
          <button class="jm-button-primary" data-test="open-working-edit" @click="emit('working-edit',workspace.family.current_edit)">{{ t('Open current version','Mở phiên bản hiện tại') }}</button>
        </div>
        <div v-if="archived" class="rounded-xl border border-outline-border p-4 flex flex-wrap items-center justify-between gap-3" data-test="archived-notice">
          <p class="text-sm">{{ t('This video is archived. You can watch it or restore it to make changes.','Video này đã lưu trữ. Bạn có thể xem hoặc khôi phục để chỉnh sửa.') }}</p>
          <button class="jm-btn-primary px-3 py-2" :disabled="busy" @click="emit('restore')">{{ t('Restore video','Khôi phục video') }}</button>
        </div>
        <p v-if="error" role="alert" class="text-sm text-rose-500">{{ error }}</p>
        <ol class="flex flex-wrap gap-5 text-xs text-ink-muted" :aria-label="t('Video steps','Các bước tạo video')">
          <li :class="{'text-indigo-500 font-bold':step===1}">1. {{ t('Your idea','Ý tưởng') }}</li>
          <li :class="{'text-indigo-500 font-bold':step===2}">2. {{ t('Review scenes','Duyệt cảnh') }}</li>
          <li :class="{'text-indigo-500 font-bold':step===3}">3. {{ t('Your video','Video của bạn') }}</li>
        </ol>
        <button v-if="shots.length" class="text-sm text-indigo-500 underline justify-self-start" data-test="open-storyboard" @click="scenes?.scrollIntoView({block:'start',behavior:'smooth'})">{{ t('Review storyboard','Duyệt bảng phân cảnh') }} ↓</button>
        <section v-if="video?.file || shots.length" class="jm-stage-section" data-test="client-video">
          <div class="jm-stage-toolbar"><div><span class="jm-eyebrow">{{ t('PREVIEW','XEM TRƯỚC') }}</span><p v-if="workspace.family?.edit_label && (!reviewVersion || reviewVersion===currentVersion)" class="text-xs text-ink-muted" data-test="preview-edit-label">{{ workspace.family.edit_label }}</p><h2>{{ selectedScene ? t('Scene','Cảnh')+' '+(shots.indexOf(selectedScene)+1) : t('Your complete video','Video hoàn chỉnh') }}</h2></div><button v-if="reviewVersion && reviewVersion!==currentVersion" class="jm-button-secondary" @click="emit('review-close')">{{ t('Back to current video','Về video hiện tại') }}</button><button v-if="selectedScene && video?.file" class="jm-button-secondary" @click="selectMedia('master')">{{ t('Back to full video','Về video hoàn chỉnh') }}</button></div>
          <VideoReviewDialog v-if="inlineVersion" :key="project+inlineVersion+reviewFocused+reviewStartFrame" ref="inlineReview" embedded :project="project" :asset-version="inlineVersion" :focused-name="reviewFocused" :initial-frame="reviewStartFrame" @saved="emit('feedback-saved')" />
          <div v-else class="jm-canvas" tabindex="0" :aria-label="t('Video preview','Xem trước video')" @keydown.space.self.prevent="togglePlayback">
            <video v-if="mediaIsVideo" :key="mediaUrl" ref="stageVideo" :src="mediaUrl" controls playsinline preload="metadata" @loadedmetadata="mediaReady=true" @timeupdate="previewTime=$event.target.currentTime" @play="playback.play" @error="previewError=true" />
            <img v-else-if="mediaUrl" :key="mediaUrl+previewRetry" :src="mediaUrl" @error="previewError=true" :alt="t('Scene preview','Ảnh xem trước cảnh')" />
            <div v-else class="jm-canvas-empty"><span class="jm-canvas-symbol">▧</span><h3>{{ t('Your scene will appear here','Cảnh của bạn sẽ xuất hiện ở đây') }}</h3><p>{{ t('Review the scene plan below, then create your preview images.','Duyệt kịch bản bên dưới, rồi tạo ảnh xem trước.') }}</p></div>
            <div v-if="previewError" class="jm-playback-error" role="alert"><p>{{ t('This preview could not be played.','Không phát được bản xem trước này.') }}</p><button class="jm-button-secondary" @click="retryPreview">{{ t('Retry preview','Thử phát lại') }}</button></div>
          </div>
          <div v-if="selectedScene" class="jm-scene-caption"><strong>{{ selectedScene.shot_name || selectedScene.title }}</strong><p>{{ shortCaption(sceneAction(selectedScene)) }}</p></div>
          <p v-if="!selectedScene && video?.is_outdated" class="jm-timeline-note px-4 py-2" data-test="outdated-preview">{{ hasOutdatedScenes?t('Some scenes still use earlier footage.','Một số cảnh vẫn dùng footage cũ.'):t('The preview needs refreshing.','Cần làm mới bản xem trước.') }} <button v-if="!archived" class="underline" :disabled="busy" :data-test="hasOutdatedScenes?'update-client-scenes':'refresh-client-preview'" @click="hasOutdatedScenes?emit('continue'):emit('assemble')">{{ hasOutdatedScenes?t('Update scenes','Cập nhật cảnh'):t('Refresh preview','Làm mới bản xem trước') }}</button></p>
          <div class="jm-stage-actions">
            <p>{{ t('Preview · check your product, logo and character before publishing.','Bản xem trước · kiểm tra sản phẩm, logo và nhân vật trước khi đăng.') }}</p>
            <div><a v-if="mediaIsVideo && (!reviewVersion || reviewVersion===currentVersion)" :href="mediaUrl" download class="jm-button-primary">{{ t('Download preview','Tải bản xem trước') }}</a></div>
          </div>
          <div v-if="shots.length" class="jm-scene-strip" role="group" :aria-label="t('Scene navigator','Chọn cảnh')" @keydown="navigateScenes">
            <button v-if="video?.file" type="button" class="jm-scene-tile jm-master-tile" :aria-pressed="!selectedScene" data-media-key="master" @click="selectMedia('master')"><span>▶</span><strong>{{ t('Full video','Cả video') }}</strong><small>{{ shots.length }} {{ t('scenes','cảnh') }}</small></button>
            <button v-for="(shot,index) in shots" :key="shot.name" type="button" class="jm-scene-tile" :aria-pressed="selectedScene?.name===shot.name" :data-media-key="shot.name" :data-test="'select-scene-'+index" :aria-label="t('Preview scene','Xem cảnh')+' '+(index+1)" @click="selectMedia(shot.name)"><img v-if="frame(shot)?.url" :src="frame(shot).url" alt="" loading="lazy" /><span v-else class="jm-scene-placeholder">{{ String(index+1).padStart(2,'0') }}</span><span class="jm-scene-tile-label">{{ t('Scene','Cảnh') }} {{ index+1 }} <small>{{ Number(shot.duration_seconds || 0).toFixed(0) }}s</small></span></button>
          </div>
        </section>
        <section v-if="!archived && (action!=='watch' || !video?.file)" class="jm-creation-panel" data-test="client-next-step">
          <h2 class="text-lg font-semibold">{{ instruction[0] }}</h2>
          <p class="text-sm text-ink-secondary">{{ instruction[1] }}</p>
          <textarea v-if="['brief','plan'].includes(action)" :value="prompt" :aria-label="t('Video idea','Ý tưởng video')" :placeholder="t('What product are you promoting, and what should happen in the video?','Bạn quảng cáo sản phẩm nào và muốn video có nội dung gì?')" rows="4" class="jm-prompt-input" @input="emit('update:prompt',$event.target.value)" />
          <button v-if="!['working','loading','review'].includes(action)" class="jm-button-primary jm-generate-button" :disabled="busy || (action==='brief'&&!prompt.trim())" @click="action==='watch'?emit('assemble'):emit('continue')">{{ instruction[2] }}</button>
          <p v-else-if="['working','loading'].includes(action)" role="status" class="text-sm text-indigo-500">{{ t('You can leave this page and return later.','Bạn có thể rời trang và quay lại sau.') }}</p>
        </section>
        <div v-if="shots.length" ref="scenes" class="scroll-mt-4"><ClientStoryboard :shots="shots" :frames="frames" :current-lang="currentLang" :archived="archived" :action="action" :busy="busy" @approve="(name,value)=>emit('approve',name,value)" @redraw="name=>emit('redraw',name)" @review="version=>emit('review',version)" @history="name=>emit('history',name)" /></div>
        <details class="text-sm border-t border-outline-border pt-4"><summary class="cursor-pointer text-ink-muted">{{ t('Your brief & images','Ý tưởng và hình ảnh') }}</summary>
          <p class="my-3 whitespace-pre-wrap text-ink-secondary">{{ prompt }}</p>
          <div class="flex flex-wrap gap-3"><img v-for="asset in images" :key="asset.name" :src="asset.file || asset.file_url" :alt="asset.label || asset.asset_name || ''" class="w-24 h-24 object-contain rounded border border-outline-border" /></div>
          <button v-if="!archived && access.can_use_advanced_editor" class="underline mt-3" @click="emit('advanced')">{{ t('Edit brief and images','Chỉnh sửa ý tưởng và hình ảnh') }}</button>
        </details>
      </template>
      <p v-else role="alert">{{ t('Could not load this video.','Không tải được video.') }} <button class="underline" @click="emit('refresh')">{{ t('Try again','Thử lại') }}</button></p>
    </main>
  </div>
</template>
<script setup>
import ClientStoryboard from './ClientStoryboard.vue';
import VideoReviewDialog from './VideoReviewDialog.vue';
import {shortCaption,sceneAction} from '../../utils/storyboard';
import RoleBadge from '../RoleBadge.vue';
import {useSession} from "../../stores/session";
import { computed, ref, watch } from 'vue';
import {usePreviewPlayback} from '../../composables/usePreviewPlayback';
const props=defineProps({project:String,title:String,currentLang:String,workspace:Object,loading:Boolean,prompt:{type:String,default:''},shots:{type:Array,default:()=>[]},frames:{type:Array,default:()=>[]},video:Object,reviewVersion:{type:String,default:''},reviewFocused:{type:String,default:''},reviewStartFrame:{type:Number,default:null},reviewRevision:{type:Number,default:0},action:String,busy:Boolean,error:String});
const emit=defineEmits(['back','history','working-edit','advanced','settings','continue','assemble','update:prompt','approve','redraw','restore','refresh','review','feedback-saved','review-close']);
const t=(en,vi)=>props.currentLang==='vi'?vi:en;
const {access}=useSession();
const scenes=ref(null),inlineReview=ref(null);
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
const frame=shot=>props.frames.find(f=>f.shot===shot.name);
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

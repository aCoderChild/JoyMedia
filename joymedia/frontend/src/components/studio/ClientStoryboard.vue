<template>
 <section class="jm-board" data-test="storyboard-review">
  <header class="jm-storyboard-title"><h2 class="font-semibold">{{ t('Storyboard','Bảng phân cảnh') }}</h2><span class="text-xs text-ink-muted">{{ shots.length }} {{ t('scenes','cảnh') }} · {{ totalDuration }}s</span></header>
  <p class="text-sm text-ink-muted">{{ t('Select a scene to review.','Chọn cảnh để duyệt.') }}</p>
  <div class="jm-storyboard-grid" data-test="client-storyboard">
   <article v-for="(shot,index) in shots" :key="shot.name" class="jm-board-card" :data-client-scene="shot.name">
    <button class="jm-board-image" :aria-label="t('Open scene','Mở cảnh')+' '+(index+1)" @click="selected=shot.name">
     <img v-if="frame(shot)?.url" :src="frame(shot).url" :alt="title(shot,index)" loading="lazy" />
     <span v-else class="jm-board-empty">{{ t('No preview yet','Chưa có ảnh') }}</span>
     <span class="jm-board-number">{{ String(index+1).padStart(2,'0') }}</span><span class="jm-board-duration">{{ duration(shot) }}s</span>
    </button>
    <div class="jm-board-copy">
     <span class="jm-board-status" :data-state="state(shot)">{{ status(shot) }}</span>
     <p v-if="shot.is_outdated" class="text-xs text-ink-muted" data-test="scene-direction-mismatch">{{ t('Selected video follows an earlier direction.','Video đang chọn theo mô tả cũ.') }}</p>
     <h3 class="font-semibold text-sm">{{ title(shot,index) }}</h3>
     <p class="jm-board-caption text-sm text-ink-secondary" data-test="scene-short-caption">{{ shortCaption(actionText(shot)) }}</p>
     <div v-if="canApprove(shot)" class="flex flex-wrap items-center gap-3 text-xs">
      <button v-if="frame(shot).status==='Approved'" class="underline" :disabled="busy" @click="emit('approve',shot.name,false)">{{ t('Undo approval','Huỷ duyệt') }}</button>
      <button v-else class="jm-button-primary" :disabled="busy" @click="emit('approve',shot.name,true)">{{ t('Use this image','Dùng ảnh này') }}</button>
      <button class="underline" :disabled="busy" @click="emit('redraw',shot.name)">{{ t('Try another image','Tạo ảnh khác') }}</button>
     </div>
     <div v-if="hasVideo(shot)" class="flex flex-wrap gap-3 text-xs">
      <button v-if="shot.selected_output_asset_version" class="underline" data-test="review-scene-video" @click="emit('review',shot.selected_output_asset_version)">{{ t('Review video','Duyệt video') }}</button>
      <button class="text-ink-muted underline" data-test="scene-version-history" @click="emit('history',shot.name)">{{ Number(shot.take_count)>Number(shot.take_index||0) ? t('Review new take','Duyệt bản mới') : t('Versions','Phiên bản') }}</button>
     </div>
     <details class="jm-board-details text-xs"><summary>{{ t('Details','Chi tiết') }}</summary>
      <p class="whitespace-pre-wrap mt-2">{{ actionText(shot) }}</p>
      <details v-if="physicalChecks(shot).length" class="mt-3"><summary>{{ t('Logic & continuity checks','Kiểm tra logic và tính liên tục') }}</summary><ul class="list-disc pl-4 space-y-2 mt-2"><li v-for="claim in physicalChecks(shot)" :key="claim">{{ claim }}</li></ul></details>
     </details>
    </div>
   </article>
  </div>
  <StoryboardSceneDialog v-if="selectedShot" :shot="selectedShot" :frame="frame(selectedShot)" :index="selectedIndex" :count="shots.length" :current-lang="currentLang" :can-approve="canApprove(selectedShot)" :busy="busy" :checks="physicalChecks(selectedShot)" :status="status(selectedShot)" :state="state(selectedShot)" @close="selected=null" @navigate="navigate" @approve="approved=>emit('approve',selectedShot.name,approved)" @redraw="emit('redraw',selectedShot.name)" @review="version=>emit('review',version)" />
 </section>
</template>
<script setup>
import {computed,ref} from 'vue';
import StoryboardSceneDialog from './StoryboardSceneDialog.vue';
import {sceneAction,shortCaption,sceneChecks,sceneReviewState} from '../../utils/storyboard';
const props=defineProps({shots:{type:Array,default:()=>[]},frames:{type:Array,default:()=>[]},currentLang:String,archived:Boolean,busy:Boolean,action:String});
const emit=defineEmits(['approve','redraw','review','history']);
const t=(en,vi)=>props.currentLang==='vi'?vi:en;
const selected=ref(null),selectedIndex=computed(()=>props.shots.findIndex(shot=>shot.name===selected.value)),selectedShot=computed(()=>props.shots[selectedIndex.value]);
const totalDuration=computed(()=>Math.round(props.shots.reduce((sum,shot)=>sum+Number(shot.duration_seconds||0),0)*10)/10);
const duration=shot=>Math.round(Number(shot.duration_seconds||0)*10)/10;
const frame=shot=>props.frames.find(row=>row.shot===shot.name);
const title=(shot,index)=>shot.shot_name||shot.title||t('Scene','Cảnh')+' '+(index+1);
const actionText=sceneAction,physicalChecks=sceneChecks;
const hasVideo=shot=>Boolean(shot.selected_output_file||shot.output_video||Number(shot.take_count)>0);
const state=shot=>sceneReviewState(shot,frame(shot));
const status=shot=>({stale:t('Update image','Cần cập nhật ảnh'),missing:t('No preview','Chưa có ảnh'),image_selected:t('Image selected','Đã chọn ảnh'),video_review:t('Review video','Cần duyệt video'),outdated:t('Video needs update','Cần cập nhật video'),review:t('Needs review','Cần duyệt')}[state(shot)]);
const canApprove=shot=>!props.archived&&['review','render'].includes(props.action)&&frame(shot)?.needs_keyframe&&Boolean(frame(shot)?.url)&&!frame(shot)?.stale;
function navigate(direction){const index=selectedIndex.value+direction;if(index>=0&&index<props.shots.length)selected.value=props.shots[index].name;}
</script>

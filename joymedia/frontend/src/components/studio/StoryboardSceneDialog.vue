<template>
 <div class="fixed inset-0 z-[115] bg-black/75 overflow-y-auto p-3 sm:p-6" @click.self="emit('close')">
  <section ref="dialog" role="dialog" aria-modal="true" :aria-label="t('Review scene','Duyệt cảnh')" tabindex="-1" class="jm-board-inspector" data-test="storyboard-scene-dialog">
   <header class="flex justify-between items-center gap-3"><strong>{{ t('Scene','Cảnh') }} {{ index+1 }} / {{ count }}</strong><button :aria-label="t('Close scene','Đóng cảnh')" class="p-2" @click="emit('close')">✕</button></header>
   <div class="jm-board-inspect-body">
    <div class="jm-board-large-image"><img v-if="frame?.url" :key="shot.name+frame.url" :src="frame.url" :alt="shot.shot_name||shot.title||t('Scene preview','Ảnh xem trước')" /><p v-else>{{ t('No preview yet','Chưa có ảnh') }}</p></div>
    <div class="space-y-4 min-w-0">
     <span class="jm-board-status" :data-state="state">{{ status }}</span>
     <p v-if="frame?.review_notes && frame?.status!=='Approved'" class="text-sm text-amber-700">{{ frame.review_notes }}</p>
     <h2 class="font-semibold text-lg">{{ shot.shot_name||shot.title }}</h2>
     <p class="text-sm">{{ shortCaption(sceneAction(shot)) }}</p>
     <p v-if="shot.sheet_direction?.camera" class="text-sm whitespace-pre-wrap"><strong>{{ t('Camera direction','Chỉ đạo góc máy') }}:</strong> {{ shot.sheet_direction.camera }}</p>
     <details class="jm-board-details text-sm"><summary>{{ t('Details','Chi tiết') }}</summary><p class="mt-3 whitespace-pre-wrap">{{ sceneAction(shot) }}</p><ul v-if="checks.length" class="mt-3 list-disc pl-4 space-y-2 text-xs"><li v-for="claim in checks" :key="claim">{{ claim }}</li></ul></details>
     <div v-if="canApprove" class="flex flex-wrap gap-3 items-center">
      <button v-if="frame.status==='Approved'" class="text-sm underline" :disabled="busy" @click="emit('approve',false)">{{ t('Undo approval','Huỷ duyệt') }}</button>
      <button v-else class="jm-button-primary" :disabled="busy||reviewBlocked()" @click="emit('approve',true)">{{ t('Use this image','Dùng ảnh này') }}</button>
      <button v-if="!frame?.authored_frame" class="text-sm underline" :disabled="busy" @click="emit('redraw')">{{ t('Try another image','Tạo ảnh khác') }}</button>
     </div>
     <button v-if="shot.selected_output_asset_version" class="jm-button-secondary" @click="emit('review',shot.selected_output_asset_version);emit('close')">{{ t('Review video','Duyệt video') }}</button>
    </div>
   </div>
   <footer class="flex justify-between gap-3"><button class="jm-button-secondary" :disabled="index===0||busy" @click="emit('navigate',-1)">← {{ t('Previous','Trước') }}</button><span class="text-sm text-ink-muted">{{ Number(shot.duration_seconds||0) }}s</span><button class="jm-button-secondary" :disabled="index===count-1||busy" @click="emit('navigate',1)">{{ t('Next','Tiếp') }} →</button></footer>
  </section>
 </div>
</template>
<script setup>
import {ref} from 'vue';
import {useDialogFocus} from '../../composables/useDialogFocus';
import {sceneAction,shortCaption} from '../../utils/storyboard';
const props=defineProps({shot:Object,frame:Object,index:Number,count:Number,currentLang:String,canApprove:Boolean,busy:Boolean,checks:Array,status:String,state:String});
const emit=defineEmits(['close','navigate','approve','redraw','review']);
const dialog=ref(null);useDialogFocus(dialog,()=>emit('close'));
const t=(en,vi)=>props.currentLang==='vi'?vi:en;
const reviewBlocked=()=>props.frame?.review_status==='Checking'||String(props.frame?.review_notes||'').includes('Critical ');
</script>

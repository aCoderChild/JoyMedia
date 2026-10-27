<template>
  <div :class="embedded?'jm-review-inline':'fixed inset-0 z-[120] bg-black/70 overflow-y-auto p-3 sm:p-6'" @click.self="emit('close')">
    <section :role="embedded?'region':'dialog'" :aria-modal="embedded?undefined:true" :aria-label="t('Review video','Duyệt video')" tabindex="-1" ref="dialog" :class="embedded?'p-4 space-y-3':'max-w-6xl mx-auto rounded-xl bg-surface-card border border-outline-border p-4 sm:p-6 space-y-4'" data-test="video-review-dialog">
      <header v-if="!embedded" class="flex justify-between items-center gap-3"><div><h2 class="text-lg font-bold">{{ t('Review video','Duyệt video') }}</h2><p class="text-xs text-ink-muted">{{ t('Feedback stays with this exact version. It is sent to the administrator, without regenerating the video.','Góp ý được lưu đúng phiên bản này để quản trị viên xử lý, không tự tạo lại video.') }}</p></div><button :aria-label="t('Close review','Đóng duyệt video')" class="p-2" @click="emit('close')">✕</button></header>
      <p v-if="error" role="alert" class="text-sm text-rose-500">{{ error }} <button v-if="!data" class="underline" @click="load()">{{ t('Try again','Thử lại') }}</button></p>
      <p v-if="loading&&!data" role="status">{{ t('Loading review…','Đang tải…') }}</p>
      <div v-if="data" class="grid lg:grid-cols-[minmax(0,3fr)_minmax(280px,2fr)] gap-5">
        <div class="space-y-3 min-w-0">
          <div class="mx-auto relative bg-black" :style="videoStyle" data-test="review-surface" tabindex="0" :aria-label="t('Video frame; use left and right arrows to step','Khung hình; dùng phím trái và phải để chuyển')" @keydown.left.prevent="step(-1)" @keydown.right.prevent="step(1)">
            <video ref="video" :src="data.file" controls playsinline preload="metadata" class="w-full h-full" @loadedmetadata="metadata" @seeking="seeking=true" @seeked="seeking=false" @timeupdate="time=currentTime()" @play="drawing=false;playback.play($event)" />
            <svg v-if="visibleBox || drawing" viewBox="0 0 1 1" preserveAspectRatio="none" class="absolute inset-0 w-full h-full" :class="drawing?'cursor-crosshair touch-none':'pointer-events-none'" data-test="review-annotation" :aria-busy="seeking" @pointerdown="beginBox" @pointermove="moveBox" @pointerup="endBox" @pointercancel="drawing=false">
              <ellipse v-if="visibleBox?.type==='point'" :cx="visibleBox.x" :cy="visibleBox.y" rx=".025" :ry=".025*ratio" fill="#fbbf2440" stroke="#fbbf24" vector-effect="non-scaling-stroke" style="stroke-width:3px" />
              <rect v-else-if="visibleBox" :x="visibleBox.x" :y="visibleBox.y" :width="visibleBox.width" :height="visibleBox.height" fill="#fbbf2420" stroke="#fbbf24" stroke-width=".005" vector-effect="non-scaling-stroke" style="stroke-width:3px" />
            </svg>
          </div>
          <div class="flex flex-wrap items-center gap-2 text-xs rounded-lg bg-surface-muted p-2" data-test="review-tools">
            <button class="border border-outline-border rounded px-2 py-2" :disabled="!ready||saving" :aria-label="t('Previous frame','Khung hình trước')" @click="step(-1)">←</button>
            <button class="border border-outline-border rounded px-2 py-2" :disabled="!ready||saving" :aria-label="t('Next frame','Khung hình tiếp')" @click="step(1)">→</button>
            <label v-if="access.can_use_advanced_editor" class="flex items-center gap-1">{{ t('Frame','Khung hình') }} <input type="number" :value="displayFrame" min="1" :max="data.total_frames" :disabled="!ready||saving" :aria-label="t('Go to frame','Đến khung hình')" class="w-20 border border-outline-border rounded bg-surface-card px-2 py-1" @change="jumpFrame($event.target)" /> / {{ data.total_frames }}</label>
            <span class="tabular-nums text-ink-secondary">{{ clock(time) }} / {{ clock(data.total_frames / data.fps) }}</span>
            <template v-if="data.allow_feedback!==false">
              <button type="button" class="border border-outline-border rounded px-3 py-2" :class="{'border-rio-500':drawing&&markTool==='point'}" :disabled="!ready||saving" data-test="review-point-tool" @click="chooseMark('point')" :title="t('Click the exact spot on the picture','Bấm đúng chỗ lỗi trên hình')">⌖ {{ t('Mark a spot','Chấm vào lỗi') }}</button>
              <button type="button" class="border border-outline-border rounded px-3 py-2" :class="{'border-rio-500':drawing&&markTool==='box'}" :disabled="!ready||saving" data-test="review-box-tool" @click="chooseMark('box')" :title="t('Drag a box around the problem','Kéo khung quanh chỗ lỗi')">▢ {{ t('Draw a box','Khoanh vùng lỗi') }}</button>
            </template>
          </div>
          <p class="text-xs text-ink-muted">{{ t('Pause where something should change, then press "Comment at this moment". You can also mark the spot on the picture.','Dừng video ở chỗ cần sửa, rồi bấm "Góp ý tại thời điểm này". Có thể chấm hoặc khoanh vùng lỗi trên hình.') }}</p>
          <ReviewTimeline :src="data.file" :fps="data.fps" :total-frames="data.total_frames" :time="time" :segments="timing?.segments || []" :markers="timelineMarkers" :timing-source="timing?.timing_source" :ready="ready" :can-comment="false" :current-lang="currentLang" @seek="seek" @comment="capture" @marker="focus" />
          <button v-if="data.allow_feedback!==false" class="jm-btn-primary px-4 py-2 text-sm" :disabled="!ready||saving" data-test="review-comment-here" @click="capture">{{ t('Comment at this moment','Góp ý tại thời điểm này') }}</button>

        </div>
        <aside class="space-y-3 min-w-0 lg:max-h-[80vh] lg:overflow-y-auto lg:pr-1">
          <div class="flex justify-between gap-2"><h3 class="font-semibold text-sm">{{ t('Feedback on this version','Góp ý cho phiên bản này') }}</h3><button class="text-xs underline" :disabled="loading||saving" @click="load()">{{ t('Refresh','Làm mới') }}</button></div>
          <form v-if="composing" class="space-y-3 border border-outline-border rounded-xl p-3" @submit.prevent="save" data-test="feedback-form">
            <div class="text-xs flex flex-wrap gap-3 items-center"><strong>{{ whole?t('Whole video','Cả video'):clock(start/data.fps)+(end!==start?' – '+clock((end+1)/data.fps):'') }}</strong><label class="flex gap-2 items-center"><input v-model="whole" type="checkbox" :disabled="saving" @change="changeScope" />{{ t('Whole video','Cả video') }}</label></div>
            <div v-if="!whole" class="flex flex-wrap gap-3 text-xs"><button type="button" class="underline" :disabled="saving" @click="markEnd">{{ t('Set range end at playhead','Chọn điểm kết thúc tại vị trí đang xem') }}</button><button type="button" class="underline" :disabled="saving" @click="chooseMark('box')">{{ t('Mark problem area','Đánh dấu vùng có lỗi') }}</button><button v-if="box" type="button" class="underline" @click="box=null">{{ t('Clear mark','Xoá đánh dấu') }}</button></div>
            <p v-if="drawing" class="text-xs text-amber-500">{{ markTool==='point'?t('Click the exact problem in the paused frame.','Bấm đúng điểm có lỗi trên khung hình đã dừng.'):t('Drag a rectangle around the problem in the paused video.','Kéo hình chữ nhật quanh vùng có lỗi trên video đã dừng.') }}</p>
            <textarea v-model="text" :disabled="saving" rows="3" maxlength="4000" :aria-label="t('Describe the problem','Mô tả vấn đề')" :placeholder="t('What looks wrong? What should happen instead?','Chi tiết nào chưa đúng? Bạn muốn thay đổi thế nào?')" class="w-full rounded-lg bg-surface-muted border border-outline-border p-3 text-sm" />
            <details class="text-xs"><summary class="cursor-pointer">{{ t('Problem type & priority (optional)','Loại vấn đề và mức ưu tiên (tuỳ chọn)') }}</summary><div class="flex flex-wrap gap-3 mt-2"><label>{{ t('Problem type','Loại vấn đề') }} <select :aria-label="t('Problem type','Loại vấn đề')" v-model="category" class="bg-surface-muted rounded p-1" :disabled="saving"><option v-for="item in categories" :key="item[0]" :value="item[0]">{{ t(item[0],item[1]) }}</option></select></label><label>{{ t('Priority','Ưu tiên') }} <select :aria-label="t('Priority','Ưu tiên')" v-model="priority" class="bg-surface-muted rounded p-1" :disabled="saving"><option value="Normal">{{ t('Normal','Bình thường') }}</option><option value="High">{{ t('High','Cao') }}</option></select></label></div></details>
            <div class="flex gap-3"><button class="jm-btn-primary px-3 py-2 text-sm" :disabled="saving||!text.trim()" data-test="save-video-feedback">{{ saving?t('Saving…','Đang lưu…'):t('Send feedback','Gửi góp ý') }}</button><button type="button" class="text-sm" :disabled="saving" @click="composing=false;drawing=false;box=null">{{ t('Cancel','Huỷ') }}</button></div>
          </form>
          <label class="flex items-center gap-2 text-xs text-ink-muted"><input v-model="showClosed" type="checkbox" :disabled="loading||saving" @change="load()" />{{ t('Show closed comments','Hiện góp ý đã xử lý') }}</label>
          <p v-if="!items.length" class="text-sm text-ink-muted">{{ t('No feedback yet. Pause the video where you see a problem.','Chưa có góp ý. Dừng video tại chi tiết cần sửa.') }}</p>
          <article v-for="item in shownItems" :key="item.name" :data-feedback="item.name" class="rounded-lg border border-outline-border p-3 text-sm space-y-2" :class="{'border-rio-500':focused?.name===item.name}">
            <div class="flex items-center justify-between gap-2"><button class="font-semibold text-rio-500 underline" @click="focus(item)">{{ item.scope==='Video'?t('Whole video','Cả video'):clock(item.start_seconds) }}</button><span class="text-xs">{{ statusText(item.status) }}</span></div>
            <p class="whitespace-pre-wrap break-words">{{ item.feedback }}</p>
            <p class="text-xs text-ink-muted">{{ item.author_name }} · {{ date(item.creation) }} · {{ categoryText(item.category) }}</p>
            <p v-if="item.annotation" class="text-xs text-ink-muted">{{ t('Includes a marked area. Click the timestamp to view it.','Có vùng đánh dấu. Bấm thời điểm để xem.') }}</p>
            <p v-if="item.admin_response" class="text-xs rounded bg-surface-muted p-2 whitespace-pre-wrap"><strong>{{ t('Administrator','Quản trị viên') }}:</strong> {{ item.admin_response }}</p>
          </article>
          <button v-if="data.has_more" class="text-sm underline" :disabled="loading" @click="load(true)">{{ t('Load more','Xem thêm') }}</button>
        </aside>
      </div>
    </section>
  </div>
</template>
<script setup>
import ReviewTimeline from './ReviewTimeline.vue';
import {videoFrameIndex} from '../../utils/videoFrames';
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue';
import { call } from 'frappe-ui';
import { errorMessage } from '../../utils/errors';
import {useDialogFocus} from '../../composables/useDialogFocus';
import {usePreviewPlayback} from '../../composables/usePreviewPlayback';
import { useI18n } from '../../stores/i18n';
import { useSession } from '../../stores/session';
const props=defineProps({project:{type:String,required:true},assetVersion:{type:String,required:true},focusedName:{type:String,default:''},initialFrame:{type:Number,default:null},embedded:Boolean});
const {access}=useSession();
const emit=defineEmits(['close','saved']);
const {currentLang}=useI18n();
const playback=usePreviewPlayback();
const t=(en,vi)=>currentLang.value==='vi'?vi:en;
const timing=ref(null),showClosed=ref(false);
const timelineMarkers=computed(()=>[...new Map([...(timing.value?.markers||[]),...items.value].map(row=>[row.name,row])).values()].filter(row=>showClosed.value||!['Resolved','Dismissed'].includes(row.status)||row.name===focused.value?.name));
const data=ref(null),items=ref([]),loading=ref(false),saving=ref(false),error=ref(''),video=ref(null),dialog=ref(null),ready=ref(false),ratio=ref(16/9),time=ref(0);
const markTool=ref('box'),seeking=ref(false);
const shownItems=computed(()=>focused.value?[focused.value,...items.value.filter(item=>item.name!==focused.value.name)]:items.value);
const composing=ref(false),start=ref(0),end=ref(0),whole=ref(false),text=ref(''),category=ref('Other'),priority=ref('Normal'),box=ref(null),drawing=ref(false),focused=ref(null);
if(!props.embedded)useDialogFocus(dialog,()=>emit('close'));
defineExpose({capture,seek,focus,ready});
let requestId=crypto.randomUUID(),origin=null,serial=0,disposed=false,loadedCount=0;
const categories=[['Other','Khác'],['Brand','Thương hiệu'],['Anatomy','Hình thể'],['Physics','Vật lý'],['Continuity','Tính liên tục'],['Audio','Âm thanh'],['Text','Chữ viết']];
const categoryText=value=>{const item=categories.find(i=>i[0]===value);return item?t(...item):value;};
const statusText=value=>({Open:t('Open','Chưa xử lý'),Investigating:t('Investigating','Đang kiểm tra'),Resolved:t('Resolved','Đã xử lý'),Dismissed:t('Dismissed','Đã đóng')}[value]||value);
const videoStyle=computed(()=>({width:`min(100%, ${58*ratio.value}vh)`,aspectRatio:String(ratio.value)}));
const currentTime=()=>Number(video.value?.currentTime||0);
const frame=()=>videoFrameIndex(currentTime(),data.value.fps,data.value.total_frames);
// Exact frame numbers are a production tool; reviewers work with time and the picture.
const displayFrame=computed(()=>data.value?videoFrameIndex(time.value,data.value.fps,data.value.total_frames)+1:1);
function jumpFrame(input){const at=Number(input.value);if(Number.isInteger(at)&&at>=1&&at<=data.value.total_frames)seek((at-1)/data.value.fps);input.value=displayFrame.value;}
const visibleBox=computed(()=>{
 if(composing.value && box.value && Math.abs(time.value*data.value.fps-start.value)<1.1)return box.value;
 if(!composing.value && focused.value?.annotation && time.value*data.value.fps>=focused.value.start_frame-.1 && time.value*data.value.fps<=focused.value.end_frame+1)return focused.value.annotation;
 return null;
});
function clock(value){const s=Math.max(0,Number(value||0));return `${Math.floor(s/60)}:${Math.floor(s%60).toString().padStart(2,'0')}`;}
function date(value){const d=new Date(String(value).replace(' ','T'));return Number.isNaN(d.getTime())?value:d.toLocaleString(currentLang.value==='vi'?'vi-VN':'en-GB');}
async function load(more=false){const token=++serial;loading.value=true;error.value='';try{
 const result=await call('joymedia.services.review.feedback.get_feedback',{project_name:props.project,asset_version:props.assetVersion,start:more?loadedCount:0,include_closed:showClosed.value,focused_name:props.focusedName||null});
 if(disposed||token!==serial)return;data.value=result;loadedCount=(more?loadedCount:0)+result.items.length;items.value=more?[...new Map([...items.value,...result.items].map(item=>[item.name,item])).values()]:result.items;
 if(!more&&result.focused){focused.value=result.focused;if(!items.value.some(i=>i.name===result.focused.name))items.value=[result.focused,...items.value];}
 }catch(e){if(!disposed&&token===serial)error.value=errorMessage(e,t('Could not load feedback.','Không tải được góp ý.'));}finally{if(token===serial)loading.value=false;}}
function metadata(){ready.value=true;ratio.value=video.value.videoWidth/video.value.videoHeight||16/9;if(focused.value)focus(focused.value);else if(Number.isInteger(props.initialFrame)){
 const at=Math.max(0,Math.min(data.value.total_frames-1,props.initialFrame));seek(at/data.value.fps);
 if(data.value.allow_feedback!==false){start.value=end.value=at;composing.value=true;}
}}
function seek(seconds){video.value?.pause();if(video.value)video.value.currentTime=seconds;time.value=seconds;}
async function focus(item){
 if(saving.value)return;focused.value=item;video.value?.pause();
 const at=Number.isInteger(item.start_frame)?item.start_frame/data.value.fps:Number(item.start_seconds||0);
 if(video.value){video.value.currentTime=at;time.value=at;}
 composing.value=false;drawing.value=false;box.value=null;
 if(!Object.hasOwn(item,'annotation'))try{
  const result=await call('joymedia.services.review.feedback.get_feedback',{project_name:props.project,asset_version:props.assetVersion,focused_name:item.name,include_closed:showClosed.value});
  if(!disposed&&focused.value?.name===item.name&&result.focused)focused.value=result.focused;
 }catch(e){if(!disposed)error.value=errorMessage(e,t('Could not load this comment.','Không tải được góp ý này.'));}
}
function step(direction){if(!ready.value||saving.value)return;drawing.value=false;origin=null;video.value.pause();video.value.currentTime=Math.min(data.value.total_frames-1,Math.max(0,frame()+direction))/data.value.fps;time.value=currentTime();}
function capture(){if(!ready.value||saving.value||!video.value)return;video.value.pause();time.value=currentTime();start.value=end.value=frame();whole.value=false;box.value=null;focused.value=null;composing.value=true;drawing.value=false;requestId=crypto.randomUUID();}
function changeScope(){box.value=null;drawing.value=false;if(!whole.value){video.value.pause();start.value=end.value=frame();}}
function markEnd(){video.value.pause();end.value=Math.max(start.value,frame());}
function chooseMark(tool){if(!ready.value||saving.value)return;if(!composing.value||whole.value)capture();else if(start.value===end.value){start.value=end.value=frame();box.value=null;}markTool.value=tool;markArea();}
function markArea(){video.value.pause();if(Math.abs(video.value.currentTime-start.value/data.value.fps)>.00001)video.value.currentTime=start.value/data.value.fps;time.value=video.value.currentTime;drawing.value=true;nextTick(()=>video.value?.scrollIntoView({block:'center'}));}
function point(event){const rect=event.currentTarget.getBoundingClientRect();return {x:Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),y:Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))};}
function beginBox(event){if(!drawing.value||saving.value||seeking.value)return;event.preventDefault();origin=point(event);if(markTool.value==='point'){box.value={type:'point',...origin};origin=null;drawing.value=false;return;}box.value=null;event.currentTarget.setPointerCapture(event.pointerId);}
function moveBox(event){if(!origin||!drawing.value)return;const p=point(event);box.value={x:Math.min(origin.x,p.x),y:Math.min(origin.y,p.y),width:Math.abs(p.x-origin.x),height:Math.abs(p.y-origin.y)};}
function endBox(event){if(!origin)return;moveBox(event);if(box.value?.width<.005||box.value?.height<.005)box.value=null;origin=null;drawing.value=false;}
watch([text,category,priority,whole,start,end,box],()=>{if(!saving.value)requestId=crypto.randomUUID();},{deep:true});
async function save(){if(saving.value||!text.value.trim())return;saving.value=true;error.value='';try{
 const result=await call('joymedia.services.review.feedback.add_feedback',{project_name:props.project,asset_version:props.assetVersion,feedback:text.value,request_id:requestId,start_frame:whole.value?null:start.value,end_frame:whole.value?null:end.value,category:category.value,priority:priority.value,annotation_json:box.value});
 if(disposed)return;composing.value=false;drawing.value=false;box.value=null;text.value='';await load();if(!items.value.some(i=>i.name===result.name))items.value.push(result);focused.value=result;emit('saved',result);
 }catch(e){if(!disposed)error.value=errorMessage(e,t('Could not save your feedback. Your draft is kept; try again.','Không lưu được góp ý. Nội dung vẫn được giữ; hãy thử lại.'));}finally{saving.value=false;}}
onMounted(async()=>{playback.pauseAll();await nextTick();if(!props.embedded)dialog.value?.focus();load();try{timing.value=await call('joymedia.services.review.timeline.get_review_timeline',{project_name:props.project,asset_version:props.assetVersion});}catch{/* Playback and comments remain available when old timing is absent. */}});
onBeforeUnmount(()=>{disposed=true;serial++;video.value?.pause();});
</script>

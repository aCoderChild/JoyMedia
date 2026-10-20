<template>
 <section class="jm-review-timeline" data-test="review-timeline" :aria-label="t('Video timeline','Dòng thời gian video')">
  <div class="jm-timeline-tools"><strong>{{ t('Timeline','Dòng thời gian') }}</strong><output data-test="timeline-timecode">{{ timecode(frame) }} / {{ timecode(totalFrames) }}</output><span class="flex-1"></span><button type="button" :disabled="zoom===1" :aria-label="t('Zoom out timeline','Thu nhỏ dòng thời gian')" @click="zoom=Math.max(1,zoom/2)">−</button><button type="button" :disabled="zoom===4" :aria-label="t('Zoom in timeline','Phóng to dòng thời gian')" @click="zoom=Math.min(4,zoom*2)">+</button></div>
  <div ref="scrollArea" class="jm-timeline-scroll"><div class="jm-timeline-content" :style="{width:100*zoom+'%'}">
   <div class="jm-timeline-ruler"><span v-for="i in 7" :key="i" :style="{left:(i-1)/6*100+'%'}">{{ clock((i-1)/6*totalFrames/fps) }}</span></div>
   <input type="range" min="0" :max="Math.max(0,totalFrames-1)" step="1" :value="frame" :disabled="!ready" :aria-label="t('Timeline playhead frame','Khung hình đang xem')" :aria-valuetext="timecode(frame)" @input="emit('seek',Number($event.target.value)/fps)" />
   <div class="jm-timeline-film" @click="seekAt"><img v-for="(image,index) in thumbs" :key="index" :src="image.src" alt="" /><div class="jm-timeline-playhead" :style="{left:percent(frame)}"></div></div>
   <div v-if="segments.length" class="jm-timeline-scenes"><button v-for="(segment,index) in segments" :key="segment.id" type="button" :data-segment="segment.id" :style="{left:percent(segment.start_frame),width:percent(segment.end_frame-segment.start_frame)}" :aria-label="segment.title+' '+timecode(segment.start_frame)" :title="segment.title" @click="emit('seek',segment.start_frame/fps)"><span aria-hidden="true">◆</span> {{ index+1 }} · {{ segment.title }}</button></div>
   <div class="jm-timeline-comments" :aria-label="t('Comment markers','Dấu góp ý')"><template v-for="(marker,index) in frameMarkers" :key="marker.name"><span v-if="marker.end_frame>marker.start_frame" :data-range="marker.name" class="jm-comment-range" aria-hidden="true" :style="{left:percent(marker.start_frame),width:percent(marker.end_frame-marker.start_frame+1),top:(index%2)*17+7+'px'}"></span><button type="button" :data-marker="marker.name" :style="{left:percent(marker.start_frame),top:(index%2)*17+'px'}" :aria-label="t('Comment','Góp ý')+' '+timecode(marker.start_frame)+': '+marker.feedback" :title="marker.feedback" @click="emit('marker',marker)">●</button></template></div>
  </div></div>
  <p v-if="timingSource==='unavailable'" class="jm-timeline-note">{{ t('Scene boundaries were not saved with this older export. Comments still use its exact video frames.','Bản xuất cũ chưa lưu mốc cảnh. Góp ý vẫn gắn đúng khung hình của video này.') }}</p>
  <div class="jm-timeline-tools"><span class="text-xs text-ink-muted">{{ t('◆ Scene starts · ● Comments','◆ Đầu cảnh · ● Góp ý') }}</span><button v-if="canComment" type="button" class="jm-button-secondary ml-auto" :disabled="!ready" data-test="timeline-comment" @click="emit('comment',frame)">{{ t('Comment at playhead','Góp ý tại đây') }}</button></div>
 </section>
</template>
<script setup>
import {computed,ref,watch} from 'vue';
import {videoFrameIndex} from '../../utils/videoFrames';
import {useVideoThumbnails} from '../../composables/useVideoThumbnails';
const props=defineProps({src:String,fps:{type:Number,default:24},totalFrames:{type:Number,default:1},time:{type:Number,default:0},segments:{type:Array,default:()=>[]},markers:{type:Array,default:()=>[]},timingSource:String,ready:Boolean,canComment:{type:Boolean,default:true},currentLang:{type:String,default:'en'}});
const emit=defineEmits(['seek','comment','marker']);
const t=(en,vi)=>props.currentLang==='vi'?vi:en,zoom=ref(1),scrollArea=ref(null);
const frame=computed(()=>videoFrameIndex(props.time,props.fps,props.totalFrames));
watch([frame,zoom],()=>{const area=scrollArea.value;if(!area)return;const x=frame.value/props.totalFrames*area.scrollWidth;if(x<area.scrollLeft+16||x>area.scrollLeft+area.clientWidth-16)area.scrollLeft=Math.max(0,x-area.clientWidth/2);},{flush:'post'});
const frameMarkers=computed(()=>props.markers.filter(m=>m.scope!=='Video'&&Number.isInteger(m.start_frame)));
const positions=computed(()=>props.totalFrames>1?Array.from({length:8},(_,i)=>i*(props.totalFrames-1)/7/props.fps):[]);
const thumbs=useVideoThumbnails(()=>props.src,positions);
const percent=n=>Math.max(0,Math.min(100,n/props.totalFrames*100))+'%';
function clock(value){const s=Math.max(0,Math.floor(value));return `${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;}
function timecode(value){return clock(value/props.fps)+':'+String(Math.floor(value%props.fps)).padStart(2,'0');}
function seekAt(event){if(!props.ready)return;const r=event.currentTarget.getBoundingClientRect();const f=Math.min(props.totalFrames-1,Math.max(0,Math.floor((event.clientX-r.left)/r.width*props.totalFrames)));emit('seek',f/props.fps);}
</script>

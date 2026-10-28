<template>
  <div class="fixed inset-0 z-[100] bg-black/50 flex justify-end" @click.self="emit('close')">
    <section ref="historyDialog" tabindex="-1" role="dialog" aria-modal="true" :aria-label="simple?t('Version history','Lịch sử phiên bản'):t('Versions & history','Phiên bản & lịch sử')" class="w-full max-w-2xl h-full bg-surface-card border-l border-outline-border shadow-xl flex flex-col" data-test="project-history">
      <header class="p-4 border-b border-outline-border flex justify-between items-center">
        <div><h2 class="font-bold">{{ simple?t('Version history','Lịch sử phiên bản'):t('Versions & history','Phiên bản & lịch sử') }}</h2><p class="text-xs text-ink-muted mt-1">{{ data?.family?.project_name }}</p></div>
        <button type="button" class="p-2 rounded hover:bg-surface-hover" :aria-label="t('Close history','Đóng lịch sử')" @click="emit('close')">✕</button>
      </header>
      <nav class="flex gap-2 px-4 pt-3 overflow-x-auto shrink-0" :aria-label="t('History category','Loại lịch sử')">
        <button v-for="tab in tabs" :key="tab.key" type="button" class="px-3 py-2 rounded-lg text-xs font-semibold" :class="kind===tab.key?'bg-rio-600 text-white':'bg-surface-muted text-ink-secondary'" @click="kind=tab.key">{{ tab.label }}</button>
      </nav>
      <div class="px-4 py-3 text-xs text-ink-muted">{{ kind==='edits' ? t('Each edit keeps its own scenes and timeline. Switching does not change approvals.','Mỗi bản dựng giữ riêng cảnh và dòng thời gian. Đổi bản không thay đổi phê duyệt.') : kind==='exports' ? t('Saved video files. The source edit may have changed since export.','Các tệp video đã xuất. Bản dựng nguồn có thể đã thay đổi sau khi xuất.') : t('All scene takes, including earlier and experimental results.','Mọi lần dựng cảnh, bao gồm các kết quả cũ và thử nghiệm.') }}</div>
      <label v-if="kind==='takes'" class="px-4 pb-3 text-xs flex flex-col gap-2">
        {{ t('Scene','Cảnh') }}
        <select v-model="selectedShot" data-test="history-scene-filter" class="w-full rounded-lg border border-outline-border bg-surface-card p-2">
          <option value="">{{ t('All scenes','Tất cả các cảnh') }}</option>
          <option v-for="scene in data?.scenes || []" :key="scene.name" :value="scene.name">{{ t('Scene','Cảnh') }} {{ scene.shot_number }} · {{ scene.shot_name }} · {{ scene.edit_label }}</option>
        </select>
      </label>
      <div v-if="kind==='edits'" class="px-4 pb-3 flex gap-2">
        <input v-model="newLabel" maxlength="100" class="flex-1 min-w-0 text-xs rounded-lg bg-surface-muted border border-outline-border px-3 py-2" :placeholder="t('Name a new edit','Tên bản dựng mới')" :aria-label="t('New edit name','Tên bản dựng mới')" />
        <button type="button" class="rounded-lg bg-rio-600 text-white text-xs px-3 disabled:opacity-50" :disabled="busy||!newLabel.trim()||data?.family?.archived" @click="create">{{ t('New edit','Bản dựng mới') }}</button>
      </div>
      <p v-if="error" role="alert" class="m-4 text-sm text-rose-400">{{ error }}</p>
      <div class="overflow-y-auto flex-1 p-4 space-y-3">
        <p v-if="loading" class="text-xs text-ink-muted">{{ t('Loading…','Đang tải…') }}</p>
        <p v-if="!loading&&!items.length" class="text-sm text-ink-muted">{{ t('No history in this category yet.','Chưa có lịch sử trong mục này.') }}</p>
        <article v-for="item in items" :key="item.name" class="rounded-xl border border-outline-border p-3 bg-surface-muted/40" :data-edit="kind==='edits'?item.name:undefined" :data-version="item.name" :data-shot="item.shot">
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <h3 class="text-sm font-semibold break-words">{{ kind==='edits'?item.label:kind==='activity'?t('Generation','Lần tạo'):kind==='exports'?`${t('Video','Video')} ${item.version_number}`:`${t('Scene','Cảnh')} ${item.shot_number || ''} · ${t('Take','Lần dựng')} ${item.version_number}` }}</h3>
              <p class="text-[11px] text-ink-muted mt-1">{{ date(item.creation) }} <span v-if="item.version_label"> · {{ item.version_label }}</span></p>
            </div>
            <span v-if="item.is_working_edit" class="shrink-0 px-2 py-1 rounded bg-rio-500/15 text-rio-400 text-[10px]">{{ t('Working edit','Bản đang dùng') }}</span>
            <span v-else-if="item.version_kind==='Experiment'" class="shrink-0 px-2 py-1 rounded bg-amber-500/10 text-amber-500 text-[10px]">{{ t('Experiment','Thử nghiệm') }}</span>
          </div>
          <template v-if="kind==='edits'">
            <p class="text-xs text-ink-muted mt-2">{{ item.status==='Archived'?t('Archived','Đã lưu trữ'):item.has_export?t('Has saved export','Có video đã xuất'):t('No exported video','Chưa xuất video') }}</p>
            <div class="flex flex-wrap gap-2 mt-3">
              <button type="button" class="history-action" @click="open(item.name)">{{ t('Open edit','Mở bản dựng') }}</button>
              <button v-if="!item.is_working_edit&&item.status!=='Archived'" type="button" class="history-action" :disabled="busy||data?.family?.archived" @click="makeCurrent(item)">{{ t('Set as working edit','Chọn làm bản đang dùng') }}</button>
              <button type="button" class="history-action" :disabled="busy||item.status==='Archived'||data?.family?.archived" @click="rename(item)">{{ t('Rename','Đổi tên') }}</button>
              <button v-if="item.name!==data?.family?.root&&!item.is_working_edit" type="button" class="history-action" :disabled="busy||data?.family?.archived" @click="archive(item)">{{ item.status==='Archived'?t('Restore edit','Khôi phục bản dựng'):t('Archive edit','Lưu trữ bản dựng') }}</button>
            </div>
          </template>
          <template v-else-if="kind==='activity'">
            <p class="text-xs text-ink-muted mt-2">{{ item.status }} · {{ item.completed_tasks }}/{{ item.total_tasks }} {{ t('tasks completed','tác vụ đã xong') }}</p>
            <p v-if="item.failed_tasks" class="text-xs text-rose-400 mt-1">{{ item.failed_tasks }} {{ t('failed','tác vụ lỗi') }}</p>
            <button type="button" class="history-action mt-3" @click="open(item.media_project)">{{ t('Open source edit','Mở bản dựng nguồn') }}</button>
          </template>
          <template v-else>
            <p v-if="item.is_selected" class="text-xs text-rio-400 mt-2">{{ t('Selected in source edit · approval is separate','Đang được chọn trong bản dựng nguồn · cần duyệt riêng') }}</p>
            <p v-if="item.source==='Derived'" class="text-xs text-ink-muted mt-1">{{ t('Reused source media','Tái sử dụng tư liệu nguồn') }}</p>
            <p class="text-xs text-ink-muted mt-2">{{ Number(item.duration_seconds||0).toFixed(1) }}s · {{ item.width }}×{{ item.height }} · {{ item.purpose==='release'?t('Release export','Bản xuất phát hành'):t('Review only','Chỉ để duyệt') }}</p>
            <p v-if="!simple&&kind==='exports'&&!item.has_edit_snapshot" class="text-[11px] text-ink-muted mt-1">{{ t('Older export · edit snapshot unavailable','Bản xuất cũ · không có bản chụp dữ liệu dựng') }}</p>
            <video v-if="preview===item.name" :src="item.file" controls playsinline preload="metadata" @play="playback.play" class="mt-3 max-h-80 w-full bg-black rounded" data-test="history-video" />
            <div class="flex flex-wrap gap-2 mt-3">
              <button type="button" class="history-action" @click="preview=preview===item.name?'':item.name">{{ t('Preview','Xem') }}</button>
              <button v-if="kind==='takes'&&!item.is_selected&&item.media_project===sourceEdit&&data?.can_select_takes" type="button" class="history-action" data-test="use-reviewed-take" :disabled="busy" @click="useTake(item)">{{ t('Use this take','Dùng bản này') }}</button>
              <button type="button" class="history-action" data-test="history-review" @click="emit('review',item.name)">{{ t('Review & comment','Duyệt và góp ý') }}</button>
              <a :href="item.file" :download="`${item.name}.mp4`" class="history-action">{{ t('Download','Tải xuống') }}</a>
              <button v-if="!simple" type="button" class="history-action" @click="open(item.media_project)">{{ t('Open source edit','Mở bản dựng nguồn') }}</button>
            </div>
          </template>
        </article>
        <button v-if="data?.has_more" type="button" class="history-action" :disabled="loading" @click="load(true)">{{ t('Load more','Xem thêm') }}</button>
      </div>
    </section>
  </div>
</template>
<script setup>
import { ref, computed, watch } from 'vue';
import {useDialogFocus} from '../../composables/useDialogFocus';
import {usePreviewPlayback} from '../../composables/usePreviewPlayback';
const playback=usePreviewPlayback();
import { call } from 'frappe-ui';
import { errorMessage } from '../../utils/errors';
import { rioPrompt } from '../../utils/rioDialog';
const props=defineProps({project:{type:String,required:true},currentLang:{type:String,default:'en'},sourceEdit:{type:String,default:''},simple:{type:Boolean,default:false},initialShot:{type:String,default:''}});
const emit=defineEmits(['close','open','changed','review']);
const historyDialog=ref(null);useDialogFocus(historyDialog,()=>emit('close'));
const t=(en,vi)=>props.currentLang==='vi'?vi:en;
const selectedShot=ref(props.initialShot);
const kind=ref(props.initialShot?'takes':props.simple?'exports':'edits'),data=ref(null),items=ref([]),loading=ref(false),busy=ref(false),error=ref(''),preview=ref(''),newLabel=ref('');
const tabs=computed(()=>props.simple ? [{key:'exports',label:t('Full videos','Video hoàn chỉnh')},{key:'takes',label:t('Scene versions','Phiên bản cảnh')}] : [{key:'edits',label:t('Edits','Bản dựng')},{key:'exports',label:t('Exported videos','Video đã xuất')},{key:'takes',label:t('Scene takes','Các lần dựng cảnh')},{key:'activity',label:t('Activity','Hoạt động')}]);
let serial=0;
async function load(more=false){const token=++serial;loading.value=true;error.value='';try{const result=await call('joymedia.services.project.versions.get_history',{project_name:props.project,kind:kind.value,shot_name:kind.value==='takes'?selectedShot.value:null,start:more?items.value.length:0});if(token!==serial)return;data.value=result;items.value=more?[...items.value,...result.items]:result.items;}catch(e){if(token===serial)error.value=errorMessage(e,'Could not load history');}finally{if(token===serial)loading.value=false;}}
async function mutate(fn){if(busy.value)return;busy.value=true;error.value='';try{await fn();emit('changed');}catch(e){error.value=errorMessage(e,'Could not update versions');}finally{busy.value=false;}}
function open(name){emit('open',name);}
function useTake(item){return mutate(async()=>{await call('joymedia.services.generation.takes.use_reviewed_take',{project_name:item.media_project,shot_name:item.shot,asset_version:item.name,expected_current:item.selected_version||''});await load();});}
function makeCurrent(item){return mutate(async()=>{await call('joymedia.services.project.versions.set_working_edit',{project_name:props.project,edit_name:item.name,expected_current:data.value.family.current_edit});await load();});}
function archive(item){return mutate(async()=>{await call(item.status==='Archived'?'joymedia.api.projects.restore_project':'joymedia.api.projects.archive_project',{project_name:item.name});await load();});}
function create(){return mutate(async()=>{const result=await call('joymedia.services.project.versions.create_edit',{project_name:props.sourceEdit||data.value.family.current_edit||props.project,label:newLabel.value,expected_current:data.value.family.current_edit});open(result.edit);});}
async function rename(item){const label=await rioPrompt(t('Edit name','Tên bản dựng'),item.label);if(label===null)return;return mutate(async()=>{await call('joymedia.services.project.versions.rename_edit',{project_name:item.name,label});await load();});}
function date(value){const parsed=new Date(String(value).replace(' ','T'));return Number.isNaN(parsed.getTime())?value:new Intl.DateTimeFormat(props.currentLang==='vi'?'vi-VN':'en-GB',{dateStyle:'medium',timeStyle:'short'}).format(parsed);}
watch([()=>props.project,kind,selectedShot],()=>{items.value=[];preview.value='';load();},{immediate:true});
</script>
<style scoped>
.history-action{display:inline-flex;align-items:center;border:1px solid var(--outline-border,#64748b55);border-radius:.5rem;padding:.35rem .65rem;font-size:.75rem;cursor:pointer}.history-action:hover{background:#0e749022}.history-action:disabled{opacity:.5;cursor:default}
</style>

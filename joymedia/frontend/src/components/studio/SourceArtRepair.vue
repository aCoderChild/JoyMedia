<template>
  <Dialog :model-value="true" title="Restore original artwork" size="3xl" @update:model-value="value => !value && $emit('close')">
    <template #default>
      <div class="space-y-3" data-test="source-art-repair">
        <p class="text-sm">Choose the same flat surface in the original artwork and the target image. Click four corners in perimeter order, starting at the top left.</p>
        <p class="text-xs text-ink-muted">Use this for labels, logos and flat artwork. A turning or deforming character needs approved identity views, animation controls or a rig.</p>
        <label class="block text-sm">Original artwork
          <select v-model="artwork" class="w-full rounded border p-2" :disabled="Boolean(job)" data-test="repair-artwork">
            <option value="">Choose a source reference</option>
            <option v-for="asset in images" :key="asset.asset_version" :value="asset.asset_version">{{ asset.label || asset.reference_key || asset.asset_version }}</option>
          </select>
        </label>
        <div class="grid grid-cols-2 gap-3">
          <div v-for="side in ['source', 'target']" :key="side">
            <p class="text-xs">{{ side === 'source' ? 'Original surface' : 'Matching surface in the first video frame' }} · {{ points[side].length }}/4
              <button class="underline" :disabled="Boolean(job)" @click="clear(side)">Reset</button>
            </p>
            <canvas :ref="element => canvases[side] = element" :data-test="`repair-${side}`" class="mt-2 h-auto w-full border cursor-crosshair" @click="pick(side, $event)" />
          </div>
        </div>
        <label v-if="mode === 'video'" class="block text-sm"><input v-model="matchLighting" type="checkbox" :disabled="Boolean(job)" /> Match scene lighting</label>
        <p v-if="matchLighting" class="text-xs text-ink-muted">Artwork colors adapt to the scene. Check the brand colors in the result.</p>
        <label class="block text-sm"><input v-model="unobstructed" type="checkbox" :disabled="Boolean(job)" /> Nothing passes in front of the selected surface.</label>
        <label v-if="!unobstructed && mode === 'video'" class="block text-sm">Foreground occlusion mask clip (white hides the artwork)
          <select v-model="occlusion" class="w-full rounded border p-2" :disabled="Boolean(job)">
            <option value="">Choose a mask with the same dimensions, frames and frame rate</option>
            <option v-for="asset in masks" :key="asset.asset_version" :value="asset.asset_version">{{ asset.label || asset.asset_version }}</option>
          </select>
        </label>
        <p v-if="error" class="text-sm text-red-600" role="alert">{{ error }}</p>
        <p v-if="job" class="text-sm">{{ status }}. The current take stays selected until every protected frame passes tracking.</p>
        <div v-if="candidate" class="space-y-2" data-test="opening-art-candidate">
          <p class="text-sm">Review the printed surface, opening, support and contact. This candidate has not replaced the opening.</p>
          <img :src="candidate.file" class="max-h-96 mx-auto" alt="Repaired opening candidate" />
          <Button variant="solid" data-test="use-opening-art-repair" :loading="submitting" @click="useOpening">Use reviewed opening</Button>
        </div>
        <div class="flex gap-2">
          <Button v-if="!job && !candidate" variant="solid" :disabled="!ready" :loading="submitting" data-test="repair-submit" @click="submit">{{ mode === 'image' ? 'Preview opening repair' : 'Restore artwork in a new take' }}</Button>
          <Button v-if="job" @click="cancel">Stop repair</Button>
          <Button @click="$emit('close')">Close</Button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { Button, Dialog, call } from 'frappe-ui';
import { errorMessage } from '../../utils/errors';

const props = defineProps({ project: String, shot: Object, mode: { type: String, default: 'video' }, assets: { type: Array, default: () => [] } });
const emit = defineEmits(['close', 'done']);
const images = computed(() => props.assets.filter(asset => asset.media_type === 'Image' && asset.file));
const masks = computed(() => props.assets.filter(asset => asset.media_type === 'Video' && asset.file));
const artwork = ref(''), occlusion = ref(''), unobstructed = ref(false);
const matchLighting = ref(false);
const expectedFrame = ref(null), candidate = ref(null);
const points = reactive({ source: [], target: [] });
const canvases = {}, pictures = {};
const error = ref(''), submitting = ref(false), job = ref(''), status = ref('');
let timer, captureVideo, disposed = false;
const ready = computed(() => artwork.value && points.source.length === 4 && points.target.length === 4 && (unobstructed.value || occlusion.value));

function redraw(side) {
  const canvas = canvases[side], picture = pictures[side];
  if (!canvas || !picture) return;
  const context = canvas.getContext('2d');
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.drawImage(picture, 0, 0, canvas.width, canvas.height);
  if (!points[side].length) return;
  context.strokeStyle = '#ff2360'; context.fillStyle = '#ff2360'; context.lineWidth = Math.max(2, canvas.width/300);
  context.beginPath();
  points[side].forEach(([x,y], i) => i ? context.lineTo(x,y) : context.moveTo(x,y));
  if (points[side].length === 4) context.closePath();
  context.stroke();
  points[side].forEach(([x,y]) => { context.beginPath(); context.arc(x,y,Math.max(4,canvas.width/150),0,Math.PI*2); context.fill(); });
}
function clear(side) { points[side] = []; redraw(side); }
function pick(side, event) {
  if (job.value || points[side].length >= 4 || !pictures[side]) return;
  const canvas = canvases[side], box = canvas.getBoundingClientRect();
  points[side].push([Math.min(canvas.width-1,Math.max(0,(event.clientX-box.left)*canvas.width/box.width)), Math.min(canvas.height-1,Math.max(0,(event.clientY-box.top)*canvas.height/box.height))]);
  redraw(side);
}
watch(artwork, async version => {
  clear('source');
  const asset = images.value.find(asset => asset.asset_version === version);
  if (!asset) return;
  const image = new Image();
  image.onload = async () => {
    if (disposed || artwork.value !== version) return;
    await nextTick();
    pictures.source = image;
    canvases.source.width = image.naturalWidth; canvases.source.height = image.naturalHeight;
    redraw('source');
  };
  image.onerror = () => error.value = 'The source image could not be loaded.';
  image.src = asset.file;
});
onMounted(() => {
  if (props.mode === 'image') {
    call('joymedia.services.keyframes.source_art.get_opening_art_source', {project_name:props.project, shot_name:props.shot.name}).then(async source => {
      if (disposed) return;
      expectedFrame.value = source.expected_frame;
      const image = new Image();
      image.onload = async () => {
        if (disposed) return;
        await nextTick(); pictures.target = image;
        canvases.target.width = image.naturalWidth; canvases.target.height = image.naturalHeight; redraw('target');
      };
      image.onerror = () => error.value = 'The opening image could not be loaded.';
      image.src = source.file;
    }).catch(e => error.value = errorMessage(e, 'Could not load the opening.'));
    return;
  }
  const video = document.createElement('video');
  captureVideo = video;
  video.preload = 'auto'; video.muted = true;
  video.onloadeddata = () => {
    if (disposed) return;
    const still = document.createElement('canvas');
    still.width = video.videoWidth; still.height = video.videoHeight;
    still.getContext('2d').drawImage(video,0,0);
    pictures.target = still;
    canvases.target.width = still.width; canvases.target.height = still.height;
    redraw('target'); video.removeAttribute('src'); video.load();
  };
  video.onerror = () => error.value = 'The video first frame could not be loaded.';
  video.src = props.shot.output_video;
});
async function submit() {
  submitting.value = true; error.value = '';
  try {
    if (props.mode === 'image') {
      candidate.value = await call('joymedia.services.keyframes.source_art.repair_opening_art', {
        project_name:props.project, shot_name:props.shot.name, expected_frame:expectedFrame.value,
        planes:[{artwork:artwork.value, source_quad:points.source, target_quad:points.target, blend_mode:matchLighting.value ? 'seamless' : 'source'}],
      });
      return;
    }
    const plane = { artwork: artwork.value, source_quad: points.source, target_quad: points.target, blend_mode: matchLighting.value ? 'seamless' : 'source' };
    if (!unobstructed.value) plane.occlusion = occlusion.value;
    const result = await call('joymedia.services.consistency.repair.queue_source_art_repair', {
      project_name: props.project, shot_name: props.shot.name, expected_take: props.shot.selected_output_asset_version, planes: [plane],
    });
    job.value = result.job_id; status.value = 'Queued'; poll();
  } catch (e) { error.value = errorMessage(e, 'Could not queue the artwork repair.'); }
  finally { submitting.value = false; }
}
async function useOpening() {
  submitting.value = true; error.value = '';
  try {
    await call('joymedia.services.keyframes.source_art.use_opening_art_repair', {
      project_name:props.project, shot_name:props.shot.name,
      asset_version:candidate.value.asset_version, expected_frame:candidate.value.expected_frame,
    });
    emit('done');
  } catch (e) { error.value = errorMessage(e, 'Could not use the repaired opening.'); }
  finally { submitting.value = false; }
}
async function poll() {
  try {
    const result = await call('joymedia.services.consistency.repair.source_art_repair_status', { project_name: props.project, job_id: job.value });
    if (disposed) return;
    status.value = result.status;
    if (/finished/i.test(result.status)) { emit('done'); return; }
    if (/failed|canceled|cancelled|stopped/i.test(result.status)) { error.value = 'Repair stopped without replacing the current take. Check the selected surface, motion and occlusion mask.'; job.value = ''; return; }
  } catch (e) { if (!disposed) error.value = errorMessage(e, 'Could not read repair progress.'); }
  if (!disposed) timer = setTimeout(poll, 3000);
}
async function cancel() {
  try { await call('joymedia.services.consistency.repair.source_art_repair_status', { project_name: props.project, job_id: job.value, cancel: true }); }
  catch (e) { error.value = errorMessage(e, 'Could not stop repair.'); }
}
onUnmounted(() => {
  disposed = true; clearTimeout(timer);
  if (captureVideo) { captureVideo.onloadeddata = null; captureVideo.onerror = null; captureVideo.removeAttribute('src'); captureVideo.load(); }
});
</script>

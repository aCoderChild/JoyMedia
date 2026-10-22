<template>
  <div ref="dialog" class="fixed inset-0 z-50 bg-black/90 flex flex-col text-white" role="dialog" aria-modal="true" tabindex="-1" data-test="compare-videos">
    <header class="flex flex-wrap items-center gap-3 px-4 py-3">
      <h2 class="font-semibold flex-1">{{ tr('Compare videos', 'So sánh video') }}</h2>
      <button class="jm-button-secondary" data-test="compare-mode" @click="mode = mode === 'sbs' ? 'wipe' : 'sbs'">{{ mode === 'sbs' ? tr('Slide to compare', 'Kéo để so sánh') : tr('Side by side', 'Đặt cạnh nhau') }}</button>
      <button class="jm-button-secondary" @click="emit('close')">{{ tr('Close', 'Đóng') }}</button>
    </header>
    <!-- Side by side: two players on one clock. Wipe: B over A, revealed right of the divider (FreeFrame). -->
    <div ref="stage" class="relative flex-1 min-h-0 flex gap-2 px-4" :class="mode === 'wipe' && 'select-none'">
      <figure v-for="(video, i) in pair" :key="video.name" class="flex flex-col min-h-0" :class="mode === 'sbs' ? 'flex-1' : 'absolute inset-0 px-4'" :style="mode === 'wipe' && i === 1 ? { clipPath: `inset(0 0 0 ${split}%)` } : null">
        <figcaption class="text-xs py-1 flex items-center gap-2" :class="mode === 'wipe' && i === 1 && 'justify-end'">
          <span class="rounded px-1.5 py-0.5 font-semibold" :class="i ? 'bg-emerald-600' : 'bg-sky-600'">{{ video.label }}</span>
          <button class="underline" :aria-pressed="audible === side(i)" @click="audible = audible === side(i) ? null : side(i)">{{ audible === side(i) ? tr('Sound on', 'Đang bật tiếng') : tr('Play this sound', 'Nghe tiếng bản này') }}</button>
        </figcaption>
        <video :ref="i ? setB : setA" :src="video.video" class="flex-1 min-h-0 w-full object-contain bg-black" playsinline preload="auto" :muted="audible !== side(i)" />
      </figure>
      <div v-if="mode === 'wipe'" class="absolute top-0 bottom-0 z-10 w-4 -translate-x-1/2 cursor-col-resize" :style="{ left: `${split}%` }" data-test="wipe-divider" @pointerdown="drag">
        <div class="mx-auto h-full w-0.5 bg-white/90" />
      </div>
    </div>
    <footer class="flex items-center gap-3 px-4 py-3">
      <button class="jm-button-primary" data-test="compare-play" @click="toggle">{{ isPlaying ? tr('Pause', 'Tạm dừng') : tr('Play both', 'Phát cả hai') }}</button>
      <input type="range" class="flex-1" min="0" :max="total || 0" step="0.04" :value="t" :aria-label="tr('Position', 'Vị trí')" @input="seekTo(Number($event.target.value))" />
      <span class="text-xs tabular-nums">{{ t.toFixed(1) }} / {{ total.toFixed(1) }}s</span>
    </footer>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import { tr } from '../../stores/i18n';
import { useDialogFocus } from '../../composables/useDialogFocus';
import { useSyncedTransport } from '../../vendor/freeframe/compareTime';

defineProps({ pair: { type: Array, required: true } });
const emit = defineEmits(['close']);
const dialog = ref(null), stage = ref(null), videoA = ref(null), videoB = ref(null);
const mode = ref('sbs'), split = ref(50), audible = ref('a');
const setA = (el) => { videoA.value = el; };
const setB = (el) => { videoB.value = el; };
const side = (i) => (i ? 'b' : 'a');
const { t, total, isPlaying, toggle, seekTo } = useSyncedTransport(videoA, videoB, audible);
useDialogFocus(dialog, () => emit('close'));

function drag() {
  const move = (ev) => {
    const rect = stage.value?.getBoundingClientRect();
    if (rect?.width) split.value = Math.min(Math.max(((ev.clientX - rect.left) / rect.width) * 100, 0), 100);
  };
  const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
}
</script>

<template>
  <span class="audio-waveform" aria-hidden="true">
    <i
      v-for="(peak, index) in peaks"
      :key="index"
      :style="{ height: `${Math.max(2, Math.round(peak * 18))}px` }"
    />
  </span>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from "vue";

const props = defineProps({
  src: { type: String, default: "" },
  barCount: { type: Number, default: 96 },
});

const peaks = ref([]);
let audioContext = null;

async function loadWaveform() {
  peaks.value = [];
  if (!props.src) return;
  try {
    const response = await fetch(props.src);
    if (!response.ok) return;
    const bytes = await response.arrayBuffer();
    audioContext ||= new AudioContext();
    const buffer = await audioContext.decodeAudioData(bytes);
    const samples = buffer.getChannelData(0);
    const count = Math.max(16, Math.min(props.barCount, samples.length));
    const step = Math.max(1, Math.floor(samples.length / count));
    const values = [];
    let maximum = 0;
    for (let index = 0; index < count; index += 1) {
      const start = index * step;
      const end = Math.min(samples.length, start + step);
      let peak = 0;
      for (let sample = start; sample < end; sample += 1) {
        peak = Math.max(peak, Math.abs(samples[sample]));
      }
      values.push(peak);
      maximum = Math.max(maximum, peak);
    }
    peaks.value = values.map((value) => (maximum ? value / maximum : 0));
  } catch (_) {
    peaks.value = [];
  }
}

watch(() => props.src, loadWaveform, { immediate: true });

onBeforeUnmount(() => {
  audioContext?.close();
  audioContext = null;
});
</script>

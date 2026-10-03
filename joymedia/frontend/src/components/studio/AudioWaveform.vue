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
  sourceInFrame: { type: Number, default: 0 },
  sourceOutFrame: { type: Number, default: 0 },
  fps: { type: Number, default: 24 },
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
    const sampleRate = buffer.sampleRate;
    const fpsValue = Math.max(1, Number(props.fps || 24));
    const startSample = Math.min(
      samples.length,
      Math.max(0, Math.floor((Number(props.sourceInFrame || 0) / fpsValue) * sampleRate)),
    );
    const sourceOutFrame = Number(props.sourceOutFrame || 0);
    const endSample = sourceOutFrame > 0
      ? Math.min(samples.length, Math.ceil((sourceOutFrame / fpsValue) * sampleRate))
      : samples.length;
    const visibleSamples = samples.subarray(startSample, Math.max(startSample, endSample));
    const count = Math.max(16, Math.min(props.barCount, visibleSamples.length));
    const step = Math.max(1, Math.floor(visibleSamples.length / count));
    const values = [];
    let maximum = 0;
    for (let index = 0; index < count; index += 1) {
      const start = index * step;
      const end = Math.min(visibleSamples.length, start + step);
      let peak = 0;
      for (let sample = start; sample < end; sample += 1) {
        peak = Math.max(peak, Math.abs(visibleSamples[sample]));
      }
      values.push(peak);
      maximum = Math.max(maximum, peak);
    }
    peaks.value = values.map((value) => (maximum ? value / maximum : 0));
  } catch (_) {
    peaks.value = [];
  }
}

watch(
  () => [props.src, props.sourceInFrame, props.sourceOutFrame, props.fps, props.barCount],
  loadWaveform,
  { immediate: true },
);

onBeforeUnmount(() => {
  audioContext?.close();
  audioContext = null;
});
</script>

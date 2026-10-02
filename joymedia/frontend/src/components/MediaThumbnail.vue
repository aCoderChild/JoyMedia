<template>
  <div
    class="media-thumbnail-root relative overflow-hidden rounded-xl bg-surface-muted border border-outline-border flex items-center justify-center select-none group"
    :class="[aspectClass, customClass, { 'ring-2 ring-indigo-500': selected }]"
  >
    <!-- Top-left Badge (e.g. Reference Role) -->
    <span
      v-if="badge"
      class="absolute top-2 left-2 z-10 text-[10px] font-bold px-2 py-0.5 rounded-md backdrop-blur-md shadow-xs bg-indigo-600/90 text-white uppercase tracking-wider"
    >
      {{ badge }}
    </span>

    <!-- CASE 1: Video -->
    <template v-if="resolvedType === 'Video' && src">
      <video
        ref="videoRef"
        :src="src"
        :poster="poster || undefined"
        class="w-full h-full object-cover pointer-events-none"
        preload="metadata"
        muted
        playsinline
        loop
      />
      <!-- Play overlay icon -->
      <div class="absolute inset-0 z-10 flex items-center justify-center bg-black/25 group-hover:bg-black/35 transition-colors pointer-events-none">
        <div v-if="showPlayOverlay" class="size-8 sm:size-9 rounded-full bg-white/90 dark:bg-zinc-900/90 flex items-center justify-center text-indigo-600 shadow-md group-hover:scale-110 transition-transform">
          <svg class="size-4 fill-current ml-0.5" viewBox="0 0 24 24">
            <polygon points="5 3 19 12 5 21 5 3" />
          </svg>
        </div>
      </div>
      <!-- Duration Badge -->
      <span
        v-if="formattedDuration"
        class="absolute bottom-1.5 right-1.5 z-10 text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded bg-black/70 text-white/90 backdrop-blur-xs"
      >
        {{ formattedDuration }}
      </span>
    </template>

    <!-- CASE 2: Audio -->
    <template v-else-if="resolvedType === 'Audio'">
      <div class="w-full h-full flex flex-col items-center justify-center p-3 bg-gradient-to-br from-indigo-950/40 via-surface-card to-purple-950/30 text-center">
        <!-- Audio Waveform Graphic -->
        <div class="flex items-end justify-center gap-1 h-8 mb-2">
          <span class="w-1 bg-indigo-400 rounded-full h-3 group-hover:h-5 transition-all" />
          <span class="w-1 bg-indigo-500 rounded-full h-6 group-hover:h-8 transition-all" />
          <span class="w-1 bg-indigo-400 rounded-full h-4 group-hover:h-6 transition-all" />
          <span class="w-1 bg-purple-400 rounded-full h-7 group-hover:h-7 transition-all" />
          <span class="w-1 bg-purple-500 rounded-full h-5 group-hover:h-8 transition-all" />
          <span class="w-1 bg-indigo-400 rounded-full h-2 group-hover:h-4 transition-all" />
        </div>
        <span class="text-xs font-semibold text-ink-primary truncate max-w-full px-2">
          {{ alt || "Audio Track" }}
        </span>
        <span v-if="formattedDuration" class="text-[10px] text-ink-muted font-mono mt-0.5">
          {{ formattedDuration }}
        </span>
      </div>
    </template>

    <!-- CASE 3: Image -->
    <template v-else-if="src">
      <img
        :src="src"
        :alt="alt || 'Media thumbnail'"
        class="w-full h-full transition-transform duration-300 group-hover:scale-105"
        :class="contain ? 'object-contain' : 'object-cover'"
        loading="lazy"
        @error="onImageError"
      />
    </template>

    <!-- CASE 4: Empty Fallback -->
    <template v-else>
      <div class="flex flex-col items-center justify-center p-3 text-ink-muted">
        <span class="text-2xl mb-1 opacity-60">🖼️</span>
        <span class="text-[11px] font-medium">{{ alt || "No preview" }}</span>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref } from "vue";

const props = defineProps({
  src: { type: String, default: "" },
  poster: { type: String, default: "" },
  mediaType: { type: String, default: "" },
  alt: { type: String, default: "" },
  aspect: { type: String, default: "aspect-video" },
  duration: { type: [Number, String], default: null },
  badge: { type: String, default: "" },
  contain: { type: Boolean, default: false },
  selected: { type: Boolean, default: false },
  showPlayOverlay: { type: Boolean, default: true },
  customClass: { type: String, default: "" },
});

const videoRef = ref(null);
const imageFailed = ref(false);

const aspectClass = computed(() => {
  if (props.aspect === "square" || props.aspect === "aspect-square") return "aspect-square";
  if (props.aspect === "video" || props.aspect === "aspect-video") return "aspect-video";
  if (props.aspect === "portrait") return "aspect-[9/16]";
  return props.aspect || "aspect-video";
});

const resolvedType = computed(() => {
  if (props.mediaType) {
    const t = props.mediaType.toLowerCase();
    if (t.includes("video")) return "Video";
    if (t.includes("audio")) return "Audio";
    if (t.includes("image")) return "Image";
  }
  const url = (props.src || "").toLowerCase();
  if (/\.(mp4|webm|mov|m4v|mkv)$/i.test(url)) return "Video";
  if (/\.(mp3|wav|ogg|aac|flac|m4a)$/i.test(url)) return "Audio";
  if (/\.(png|jpe?g|webp|gif|svg|avif)$/i.test(url)) return "Image";
  return "Image";
});

const formattedDuration = computed(() => {
  const d = Number(props.duration);
  if (!d || isNaN(d)) return "";
  const mins = Math.floor(d / 60);
  const secs = Math.floor(d % 60);
  return `${mins}:${secs < 10 ? "0" : ""}${secs}`;
});

function onImageError() {
  imageFailed.value = true;
}
</script>

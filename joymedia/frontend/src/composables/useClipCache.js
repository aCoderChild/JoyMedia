import { reactive } from "vue";

// Private media is served "no-store", so the browser downloads a clip again at
// every cut and the preview shows black frames while it loads. Timeline clips
// are fetched once and played from memory instead.
const MAX_CACHED_CLIPS = 6;
const objectUrls = reactive(new Map());
const pending = new Set();

function evictOldestClip() {
  const oldest = objectUrls.keys().next().value;
  if (!oldest) return;
  URL.revokeObjectURL(objectUrls.get(oldest));
  objectUrls.delete(oldest);
}

function rememberClip(url, objectUrl) {
  if (objectUrls.has(url)) {
    URL.revokeObjectURL(objectUrls.get(url));
    objectUrls.delete(url);
  }
  objectUrls.set(url, objectUrl);
  while (objectUrls.size > MAX_CACHED_CLIPS) evictOldestClip();
}

export function cachedClipUrl(url) {
  if (!url) return url;
  const cached = objectUrls.get(url);
  if (cached) {
    // Map insertion order is our lightweight LRU policy.
    objectUrls.delete(url);
    objectUrls.set(url, cached);
    return cached;
  }
  warmClip(url);
  return url;
}

export function warmClip(url) {
  if (!url || objectUrls.has(url) || pending.has(url)) return;
  pending.add(url);
  fetch(url, { credentials: "include" })
    .then((response) => (response.ok ? response.blob() : null))
    .then((blob) => {
      if (blob) rememberClip(url, URL.createObjectURL(blob));
    })
    .catch(() => {})
    .finally(() => pending.delete(url));
}

export function clearClipCache() {
  for (const objectUrl of objectUrls.values()) URL.revokeObjectURL(objectUrl);
  objectUrls.clear();
}

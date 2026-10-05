import { reactive } from "vue";

// Private media is served "no-store", so the browser downloads a clip again at
// every cut and the preview shows black frames while it loads. Timeline clips
// are fetched once and played from memory instead.
const objectUrls = reactive(new Map());
const pending = new Set();

export function cachedClipUrl(url) {
  if (!url) return url;
  const cached = objectUrls.get(url);
  if (cached) return cached;
  warmClip(url);
  return url;
}

export function warmClip(url) {
  if (!url || objectUrls.has(url) || pending.has(url)) return;
  pending.add(url);
  fetch(url, { credentials: "include" })
    .then((response) => (response.ok ? response.blob() : null))
    .then((blob) => {
      if (blob) objectUrls.set(url, URL.createObjectURL(blob));
    })
    .catch(() => {})
    .finally(() => pending.delete(url));
}

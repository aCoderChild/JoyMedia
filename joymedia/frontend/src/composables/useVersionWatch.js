import { onUnmounted, ref } from "vue";

// Detects when the deployed build has moved past the one running in this tab.
// A single-page app loaded hours ago keeps running its old bundle with no signal
// to refresh; this surfaces that so the person can reload to the current version
// instead of staring at a stale (or, mid-redeploy, broken) page.

// The hash of the bundle that actually loaded this tab, read from its own tag.
function runningBundle() {
  const tag = document.querySelector('script[src*="/frontend/assets/index-"]');
  const match = tag?.getAttribute("src")?.match(/index-[A-Za-z0-9_-]+\.js/);
  return match ? match[0] : null;
}

// The bundle the server would serve a fresh load right now. The entry HTML is
// no-store, so this reflects the live deployment, not a cache.
async function deployedBundle() {
  const res = await fetch(window.location.pathname, { cache: "no-store", headers: { "X-Requested-With": "version-check" } });
  if (!res.ok) return null;
  const html = await res.text();
  const match = html.match(/index-[A-Za-z0-9_-]+\.js/);
  return match ? match[0] : null;
}

export function useVersionWatch({ intervalMs = 5 * 60 * 1000 } = {}) {
  const updateAvailable = ref(false);
  const current = runningBundle();
  let timer = null;
  let checking = false;

  async function check() {
    // Nothing to compare against, or already flagged — no need to keep polling.
    if (!current || updateAvailable.value || checking) return;
    checking = true;
    try {
      const latest = await deployedBundle();
      if (latest && latest !== current) updateAvailable.value = true;
    } catch {
      // A failed check is not a new version; try again on the next tick.
    } finally {
      checking = false;
    }
  }

  // Check when the tab regains focus (the common moment someone returns to a
  // long-open page), and on a slow interval as a backstop.
  function onFocus() {
    if (document.visibilityState === "visible") check();
  }
  document.addEventListener("visibilitychange", onFocus);
  window.addEventListener("focus", onFocus);
  timer = window.setInterval(check, intervalMs);
  // One check shortly after load catches a redeploy that landed moments ago.
  const initial = window.setTimeout(check, 15000);

  onUnmounted(() => {
    document.removeEventListener("visibilitychange", onFocus);
    window.removeEventListener("focus", onFocus);
    clearInterval(timer);
    clearTimeout(initial);
  });

  function reload() {
    window.location.reload();
  }

  return { updateAvailable, reload, check };
}

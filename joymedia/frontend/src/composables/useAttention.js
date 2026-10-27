import { computed, ref } from "vue";
import { call } from "frappe-ui";
import { notify } from "../utils/notify";
import { tr } from "../stores/i18n";

// What the user's AI videos wait for, checked app-wide so nobody has to keep a page open.
const items = ref([]);
const waitingCount = computed(() => items.value.filter((item) => item.state === "waiting").length);
const permission = ref(typeof Notification === "undefined" ? "unsupported" : Notification.permission);
let timer = null;
let baseTitle = "";

function storageKey(user) {
  return `joymedia_attention_${user}`;
}

function remembered(user) {
  try {
    return JSON.parse(localStorage.getItem(storageKey(user)) || "null");
  } catch {
    return null;
  }
}

function announce(item) {
  const title = item.state === "ready" ? tr("Your video is ready", "Video đã xong") : tr("A video needs you", "Có video cần bạn xem");
  const text = item.title || tr("Open it to continue.", "Mở để tiếp tục.");
  notify({ title, text, type: item.state === "ready" ? "success" : "info" });
  if (permission.value === "granted" && document.hidden) {
    const shown = new Notification(title, { body: text, tag: item.project });
    shown.onclick = () => {
      window.focus();
      window.location.assign(`/joymedia/projects/${item.project}`);
    };
  }
}

async function check(user) {
  try {
    items.value = (await call("joymedia.api.creative.get_attention")) || [];
  } catch {
    return;
  }
  const before = remembered(user);
  const now = Object.fromEntries(items.value.map((item) => [item.project, item.state]));
  // The first check only remembers; later checks announce what changed since.
  if (before) items.value.filter((item) => before[item.project] !== item.state).forEach(announce);
  try {
    localStorage.setItem(storageKey(user), JSON.stringify(now));
  } catch {
    /* private mode: alerts still show while the page is open */
  }
  baseTitle = baseTitle || document.title.replace(/^\(\d+\)\s*/, "");
  document.title = waitingCount.value ? `(${waitingCount.value}) ${baseTitle}` : baseTitle;
}

export function useAttention() {
  function start(user) {
    if (timer || !user) return;
    check(user);
    timer = setInterval(() => check(user), 60000);
  }
  async function enableBrowserAlerts() {
    if (typeof Notification === "undefined") return;
    permission.value = await Notification.requestPermission();
  }
  return { items, waitingCount, permission, start, enableBrowserAlerts };
}

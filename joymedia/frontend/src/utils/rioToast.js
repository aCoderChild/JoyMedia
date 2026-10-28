import { reactive } from "vue";
import { useI18n } from "../stores/i18n";

// RIO Studio toasts: a title, a message, a coloured edge and a draining progress
// bar. Hovering holds the toast open so a long message stays readable.
const TYPES = {
  info: { title: ["NOTICE", "THÔNG BÁO"], duration: 4500 },
  success: { title: ["DONE", "HOÀN TẤT"], duration: 4500 },
  warning: { title: ["WARNING", "CẢNH BÁO"], duration: 5000 },
  error: { title: ["SYSTEM ERROR", "LỖI HỆ THỐNG"], duration: 6000 },
  process: { title: ["IN PROGRESS", "TIẾN TRÌNH RIO"], duration: 6000 },
};

export const toasts = reactive([]);

const timers = new Map();
let nextId = 0;

function defaultTitle(type) {
  const [en, vi] = (TYPES[type] || TYPES.info).title;
  return useI18n().currentLang.value === "vi" ? vi : en;
}

function clearTimer(id) {
  const timer = timers.get(id);
  if (!timer) return;
  clearTimeout(timer.handle);
  timers.delete(id);
}

export function close(id) {
  clearTimer(id);
  const toast = toasts.find((item) => item.id === id);
  if (!toast || toast.closing) return;
  // Let the slide-out transition finish before the node leaves the list.
  toast.closing = true;
  setTimeout(() => {
    const index = toasts.findIndex((item) => item.id === id);
    if (index !== -1) toasts.splice(index, 1);
  }, 320);
}

/** Holds the dismiss timer while the pointer rests on a toast. */
export function pause(id) {
  const timer = timers.get(id);
  if (!timer) return;
  clearTimeout(timer.handle);
  timer.remaining -= Date.now() - timer.startedAt;
  timer.handle = null;
}

export function resume(id) {
  const timer = timers.get(id);
  if (!timer || timer.handle) return;
  if (timer.remaining <= 0) return close(id);
  timer.startedAt = Date.now();
  timer.handle = setTimeout(() => close(id), timer.remaining);
}

export function show(options) {
  const config = typeof options === "string" ? { message: options } : options || {};
  const type = TYPES[config.type] ? config.type : "info";
  const duration = typeof config.duration === "number" ? config.duration : TYPES[type].duration;
  const id = ++nextId;
  toasts.push({
    id,
    type,
    title: config.title || defaultTitle(type),
    message: config.message || "",
    duration,
    closable: config.closable !== false,
    closing: false,
  });
  if (duration > 0) {
    timers.set(id, { remaining: duration, startedAt: Date.now(), handle: setTimeout(() => close(id), duration) });
  }
  return { id, close: () => close(id) };
}

export const rioToast = {
  show,
  close,
  info: (message, title, duration) => show({ message, title, duration, type: "info" }),
  success: (message, title, duration) => show({ message, title, duration, type: "success" }),
  warning: (message, title, duration) => show({ message, title, duration, type: "warning" }),
  error: (message, title, duration) => show({ message, title, duration, type: "error" }),
  process: (message, title, duration) => show({ message, title, duration, type: "process" }),
};

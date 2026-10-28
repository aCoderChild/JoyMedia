import { reactive } from "vue";
import { useI18n } from "../stores/i18n";

// Themed stand-ins for window.alert/confirm/prompt so a decision looks like the
// rest of the studio. The newest dialog is the one on screen, so a dialog opened
// from inside another still behaves.
export const dialogs = reactive([]);

let nextId = 0;

function label(en, vi) {
  return useI18n().currentLang.value === "vi" ? vi : en;
}

function open(options) {
  return new Promise((resolve) => {
    dialogs.push({
      id: ++nextId,
      kind: options.kind,
      title: options.title || defaultTitle(options.kind),
      message: options.message || "",
      defaultValue: options.defaultValue == null ? "" : String(options.defaultValue),
      placeholder: options.placeholder || label("Type here…", "Nhập tại đây…"),
      confirmText: options.confirmText || (options.kind === "confirm" ? label("Confirm", "Xác nhận") : label("OK", "Đồng ý")),
      cancelText: options.cancelText || label("Cancel", "Hủy bỏ"),
      destructive: Boolean(options.destructive),
      closing: false,
      resolve,
    });
  });
}

function defaultTitle(kind) {
  if (kind === "confirm") return label("CONFIRM ACTION", "XÁC NHẬN HÀNH ĐỘNG");
  if (kind === "prompt") return label("ENTER DETAILS", "NHẬP DỮ LIỆU");
  return label("NOTICE", "THÔNG BÁO RIO");
}

/** Settles a dialog and lets its close transition finish before it unmounts. */
export function settle(id, result) {
  const dialog = dialogs.find((item) => item.id === id);
  if (!dialog || dialog.closing) return;
  dialog.closing = true;
  setTimeout(() => {
    const index = dialogs.findIndex((item) => item.id === id);
    if (index !== -1) dialogs.splice(index, 1);
    dialog.resolve(result);
  }, 240);
}

/** The value a dismissal resolves to: null for a prompt, false for a confirm. */
export function dismissValue(dialog) {
  if (dialog.kind === "prompt") return null;
  if (dialog.kind === "confirm") return false;
  return true;
}

export const rioAlert = (message, title) => open({ kind: "alert", message, title });
export const rioConfirm = (message, options = {}) => open({ kind: "confirm", message, ...options });
export const rioPrompt = (message, defaultValue, options = {}) =>
  open({ kind: "prompt", message, defaultValue, ...options });

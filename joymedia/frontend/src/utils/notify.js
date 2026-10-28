import { useI18n } from "../stores/i18n";
import { PHRASES_VI } from "./phrases";
import { rioToast } from "./rioToast";

function translate(text) {
  if (!text || useI18n().currentLang.value !== "vi") return text;
  return PHRASES_VI[text] || text;
}

// The title stays the toast's heading and the detail its body, so a long error
// keeps its shape instead of collapsing into one line.
function show(type, title, description = "") {
  return rioToast.show({ type, title: translate(title), message: translate(description) });
}

function notify(options) {
  const { title, text, type = "info", duration } = options || {};
  return rioToast.show({ type, title: translate(title), message: translate(text), duration });
}

Object.assign(notify, {
  success: (title, description) => show("success", title, description),
  error: (title, description) => show("error", title, description),
  warning: (title, description) => show("warning", title, description),
  info: (title, description) => show("info", title, description),
  // Long-running work: a spinning icon. Pass duration 0 to hold it open.
  process: (title, description) => show("process", title, description),
});

export { notify };

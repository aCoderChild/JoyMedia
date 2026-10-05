import { toast } from "frappe-ui";
import { useI18n } from "../stores/i18n";
import { PHRASES_VI } from "./phrases";

function translate(text) {
  if (!text || useI18n().currentLang.value !== "vi") return text;
  return PHRASES_VI[text] || text;
}

function show(type, title, description = "") {
  const message = [translate(title), translate(description)].filter(Boolean).join(" — ");
  return toast[type](message);
}

function notify(options) {
  const { title, text, type = "info" } = options || {};
  return show(type, title, text);
}

Object.assign(notify, {
  success: (title, description) => show("success", title, description),
  error: (title, description) => show("error", title, description),
  warning: (title, description) => show("warning", title, description),
  info: (title, description) => show("info", title, description),
});

export { notify };

import { toast } from "frappe-ui";

function show(type, title, description = "") {
  const message = [title, description].filter(Boolean).join(" — ");
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

<template>
  <div
    v-if="current"
    class="rio-dialog-overlay"
    :class="current.closing ? 'rio-dialog-closing' : 'rio-dialog-visible'"
    @click.self="dismiss"
  >
    <div
      ref="boxRef"
      class="rio-dialog-box"
      data-test="rio-dialog"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="`rio-dialog-title-${current.id}`"
      :aria-describedby="`rio-dialog-message-${current.id}`"
      @keydown.esc.prevent.stop="dismiss"
      @keydown.enter="onEnter"
      @keydown.tab="trapFocus"
    >
      <div class="rio-dialog-glow-bar" :class="{ destructive: current.destructive }" />
      <div class="rio-dialog-header">
        <div class="rio-dialog-title-group">
          <span class="rio-dialog-icon" :class="{ destructive: current.destructive }" aria-hidden="true">
            <svg v-if="current.kind === 'confirm'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg>
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" /></svg>
          </span>
          <span :id="`rio-dialog-title-${current.id}`" class="rio-dialog-title">{{ current.title }}</span>
        </div>
        <button type="button" class="rio-dialog-btn-close" :aria-label="t('Close', 'Đóng')" @click="dismiss">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
        </button>
      </div>
      <div class="rio-dialog-body">
        <p :id="`rio-dialog-message-${current.id}`" class="rio-dialog-message">{{ current.message }}</p>
        <div v-if="current.kind === 'prompt'" class="rio-dialog-input-wrap">
          <input
            ref="inputRef"
            v-model="inputValue"
            type="text"
            class="rio-dialog-input"
            :placeholder="current.placeholder"
            :aria-label="current.message || current.title"
          />
        </div>
      </div>
      <div class="rio-dialog-footer">
        <button
          v-if="current.kind !== 'alert'"
          type="button"
          class="rio-dialog-btn rio-dialog-btn-cancel"
          data-test="rio-dialog-cancel"
          @click="dismiss"
        >
          {{ current.cancelText }}
        </button>
        <button
          ref="confirmRef"
          type="button"
          class="rio-dialog-btn rio-dialog-btn-confirm"
          :class="{ destructive: current.destructive }"
          data-test="rio-dialog-confirm"
          @click="accept"
        >
          {{ current.confirmText }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { dialogs, dismissValue, settle } from "../utils/rioDialog";
import { useI18n } from "../stores/i18n";

const { currentLang } = useI18n();
const t = (en, vi) => (currentLang.value === "vi" ? vi : en);

const boxRef = ref(null);
const inputRef = ref(null);
const confirmRef = ref(null);
const inputValue = ref("");

// The newest dialog is the visible one, so nesting works without extra state.
const current = computed(() => dialogs[dialogs.length - 1] || null);

let previouslyFocused = null;

watch(
  () => current.value?.id,
  async (id) => {
    if (!id) {
      // Hand focus back to whatever opened the dialog.
      if (previouslyFocused?.isConnected) previouslyFocused.focus();
      previouslyFocused = null;
      return;
    }
    if (!previouslyFocused) previouslyFocused = document.activeElement;
    inputValue.value = current.value.defaultValue;
    await nextTick();
    if (inputRef.value) {
      inputRef.value.focus();
      inputRef.value.select();
    } else confirmRef.value?.focus();
  },
  { immediate: true },
);

function accept() {
  if (!current.value) return;
  settle(current.value.id, current.value.kind === "prompt" ? inputValue.value : true);
}

function dismiss() {
  if (!current.value) return;
  settle(current.value.id, dismissValue(current.value));
}

function onEnter(event) {
  // Enter submits, except from the cancel button where it means "cancel".
  if (event.target instanceof HTMLButtonElement && event.target !== confirmRef.value) return;
  event.preventDefault();
  accept();
}

function trapFocus(event) {
  const focusable = boxRef.value?.querySelectorAll("button, input");
  if (!focusable?.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}
</script>

<style scoped>
.rio-dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 100001;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: rgba(3, 6, 10, 0.72);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  opacity: 0;
  transition: opacity 0.24s ease;
}
.rio-dialog-overlay.rio-dialog-visible { opacity: 1; }
.rio-dialog-overlay.rio-dialog-closing { opacity: 0; }
.rio-dialog-box {
  position: relative;
  width: 440px;
  max-width: 100%;
  overflow: hidden;
  border: 1px solid var(--outline-border);
  border-radius: 12px;
  background: color-mix(in srgb, var(--surface-card) 96%, transparent);
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.8);
  color: var(--ink-primary);
  font: 13px Inter, system-ui, sans-serif;
  transform: translateY(10px) scale(0.97);
  transition: transform 0.24s cubic-bezier(0.16, 1, 0.3, 1);
}
.rio-dialog-overlay.rio-dialog-visible .rio-dialog-box { transform: translateY(0) scale(1); }
.rio-dialog-glow-bar { height: 2px; background: linear-gradient(90deg, transparent, #00f0ff, transparent); }
.rio-dialog-glow-bar.destructive { background: linear-gradient(90deg, transparent, #f43f5e, transparent); }
.rio-dialog-header { display: flex; align-items: center; gap: 10px; padding: 13px 14px; border-bottom: 1px solid #22293d; }
.rio-dialog-title-group { display: flex; align-items: center; gap: 9px; flex: 1; min-width: 0; }
.rio-dialog-icon { width: 20px; height: 20px; flex: none; color: #00f0ff; }
.rio-dialog-icon.destructive { color: #f43f5e; }
.rio-dialog-icon svg { width: 100%; height: 100%; }
.rio-dialog-title { font-size: 12px; font-weight: 800; letter-spacing: 0.9px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rio-dialog-btn-close { width: 20px; height: 20px; flex: none; color: var(--ink-muted); cursor: pointer; }
.rio-dialog-btn-close:hover { color: var(--ink-primary); }
.rio-dialog-btn-close svg { width: 100%; height: 100%; }
.rio-dialog-body { padding: 16px 14px; }
/* pre-line keeps the blank line in messages that join a server notice to a question. */
.rio-dialog-message { color: var(--ink-secondary); font-size: 13px; line-height: 1.6; overflow-wrap: anywhere; white-space: pre-line; }
.rio-dialog-input-wrap { margin-top: 12px; }
.rio-dialog-input {
  width: 100%;
  padding: 9px 11px;
  border: 1px solid var(--outline-border);
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.06);
  color: var(--ink-primary);
  font: inherit;
}
.rio-dialog-input:focus { outline: 1px solid #00f0ff; border-color: #00f0ff; }
.rio-dialog-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 14px; border-top: 1px solid #22293d; }
.rio-dialog-btn { padding: 7px 15px; border-radius: 7px; font-size: 12px; font-weight: 700; cursor: pointer; }
.rio-dialog-btn-cancel { border: 1px solid var(--outline-border); background: transparent; color: var(--ink-secondary); }
.rio-dialog-btn-cancel:hover { border-color: var(--ink-muted); color: var(--ink-primary); }
.rio-dialog-btn-confirm { border: 1px solid #00f0ff; background: #00f0ff; color: #04121a; }
.rio-dialog-btn-confirm:hover { filter: brightness(1.12); }
.rio-dialog-btn-confirm.destructive { border-color: #f43f5e; background: #f43f5e; color: #fff; }
.rio-dialog-btn:focus-visible { outline: 2px solid #f8fafc; outline-offset: 2px; }

@media (prefers-reduced-motion: reduce) {
  .rio-dialog-box { transition: none; transform: none; }
  .rio-dialog-overlay.rio-dialog-visible .rio-dialog-box { transform: none; }
}
</style>

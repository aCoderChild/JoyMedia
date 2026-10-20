import {nextTick,onMounted,onBeforeUnmount} from 'vue';

export function useDialogFocus(element,close) {
  const previous=document.activeElement;
  function keydown(event) {
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close();return;}
    if(event.key!=='Tab')return;
    const controls=[...element.value.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),textarea:not(:disabled),select:not(:disabled),video[controls],[tabindex="0"]')].filter(node=>node.getClientRects().length && node.getAttribute('aria-hidden')!=='true');
    if(!controls.length){event.preventDefault();element.value.focus();return;}
    const first=controls[0],last=controls.at(-1),active=document.activeElement;
    if(event.shiftKey && (active===first || active===element.value)){event.preventDefault();last.focus();}
    else if(!event.shiftKey && (active===last || active===element.value)){event.preventDefault();first.focus();}
  }
  onMounted(async()=>{await nextTick();element.value?.addEventListener('keydown',keydown);element.value?.focus();});
  onBeforeUnmount(()=>{element.value?.removeEventListener('keydown',keydown);if(previous?.isConnected)previous.focus({preventScroll:true});});
}

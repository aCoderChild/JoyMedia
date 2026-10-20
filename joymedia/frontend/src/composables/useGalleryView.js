import { ref, watch } from 'vue';
export function useGalleryView(key) {
  let stored='grid';
  try {stored=localStorage.getItem(key)||'grid';}catch{}
  const view=ref(stored==='list'?'list':'grid');
  watch(view,value=>{try{localStorage.setItem(key,value);}catch{}});
  return view;
}

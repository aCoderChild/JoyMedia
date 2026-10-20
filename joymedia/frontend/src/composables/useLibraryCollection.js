import { onBeforeUnmount, reactive } from 'vue';
import { call } from 'frappe-ui';

/** A paged gallery whose late requests cannot replace a newer search or filter. */
export function useLibraryCollection(url, enabled=true) {
  const state=reactive({data:null,loading:false,error:null});
  let serial=0,disposed=false,params={};
  async function fetch(nextParams={},append=false) {
    const token=++serial;
    params={...nextParams};state.loading=true;state.error=null;
    try {
      const data=await call(url,nextParams);
      if(disposed||token!==serial)return;
      state.data=append?{...data,items:[...new Map([...(state.data?.items||[]),...data.items].map(item=>[item.name,item])).values()]}:data;
      return data;
    } catch(error) {if(!disposed&&token===serial)state.error=error;}
    finally {if(!disposed&&token===serial)state.loading=false;}
  }
  function reload(){return fetch({...params,start:0});}
  function more(){if(state.loading)return;return fetch({...params,start:state.data?.items?.length||0},true);}
  onBeforeUnmount(()=>{disposed=true;serial++;});
  if(enabled)fetch();
  return Object.assign(state,{fetch,reload,more,invalidate:()=>{serial++;state.loading=true;}});
}

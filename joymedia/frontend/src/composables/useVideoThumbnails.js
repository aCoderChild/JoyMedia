import {onBeforeUnmount,ref,watch} from 'vue';

/** Bounded thumbnails from the exact review video; never from another take's stills. */
export function useVideoThumbnails(source,positions) {
 const images=ref([]);let dispose=()=>{};
 watch([source,positions],async([url,times])=>{
  dispose();images.value=[];
  if(!url||!times.length)return;
  const video=document.createElement('video'),canvas=document.createElement('canvas');
  let cancelled=false,stopWait=()=>{};
  dispose=()=>{cancelled=true;stopWait();video.removeAttribute('src');video.load();};
  const wait=event=>new Promise(resolve=>{
   let timer;const done=value=>{clearTimeout(timer);video.removeEventListener(event,loaded);video.removeEventListener('error',failed);resolve(value);};
   const loaded=()=>done(true),failed=()=>done(false);
   stopWait=failed;video.addEventListener(event,loaded,{once:true});video.addEventListener('error',failed,{once:true});timer=setTimeout(failed,8000);
  });
  video.muted=true;video.playsInline=true;video.preload='auto';
  const metadata=wait('loadeddata');video.src=url;if(!await metadata||cancelled)return;
  canvas.width=128;canvas.height=Math.max(1,Math.round(128*video.videoHeight/video.videoWidth));
  if(canvas.height>228){canvas.height=228;canvas.width=Math.max(1,Math.round(228*video.videoWidth/video.videoHeight));}
  const values=[];
  for(const time of times.slice(0,12)){
   const target=Math.max(0,Math.min(video.duration-.05,time));
   if(Math.abs(video.currentTime-target)>.005){const seeked=wait('seeked');video.currentTime=target;if(!await seeked||cancelled)break;}
   try{canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);values.push({time,src:canvas.toDataURL('image/jpeg',.65)});}catch{break;}
   if(!cancelled)images.value=[...values];
  }
  if(!cancelled){video.removeAttribute('src');video.load();}
 },{immediate:true});
 onBeforeUnmount(()=>dispose());
 return images;
}

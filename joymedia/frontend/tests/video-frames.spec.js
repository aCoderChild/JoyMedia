import {test,expect} from '@playwright/test';
import {videoFrameIndex} from '../src/utils/videoFrames.js';
test('frame boundaries tolerate browser microsecond truncation across frame rates',()=>{
 for(const fps of [23.976,24,25,29.97,30,60,120]){
  for(let frame=0;frame<900;frame++){
   const browserTime=Math.floor(frame/fps*1e6)/1e6;
   expect(videoFrameIndex(browserTime,fps,900)).toBe(frame);
   expect(videoFrameIndex((frame+.5)/fps,fps,900)).toBe(frame);
  }
  expect(videoFrameIndex(999,fps,900)).toBe(899);
  expect(videoFrameIndex(-1,fps,900)).toBe(0);
 }
});

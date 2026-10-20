export const sceneAction=shot=>String(shot.authored_action||shot.storyboard_action||shot.sheet_direction?.action||shot.direction?.action||shot.description||shot.visual_description||shot.action||'');
export function shortCaption(value,limit=140){
 const text=String(value||'').replace(/\s+/g,' ').trim();
 if(text.length<=limit)return text;
 const clipped=text.slice(0,limit-1);
 return (clipped.replace(/\s+\S*$/u,'')||clipped)+'…';
}
export function sceneChecks(shot){
 if(Array.isArray(shot.continuity_checks))return shot.continuity_checks;
 try{const plan=typeof shot.motion_plan_json==='string'?JSON.parse(shot.motion_plan_json):shot.motion_plan_json;return [...new Set((plan?.scene_contract?.checks||[]).map(row=>row.claim))];}catch{return [];}
}

// A source-image choice never certifies the action in a moving take.
export function sceneReviewState(shot,frame){
 if(shot.is_outdated)return 'outdated';
 if(shot.selected_output_asset_version||shot.output_video||shot.selected_output_file)return 'video_review';
 if(frame?.stale)return 'stale';
 if(!frame?.url)return 'missing';
 return frame.status==='Approved'?'image_selected':'review';
}

/* Hosted Muse Image comparison UI. No provider secrets in the browser. */
(()=>{'use strict';
window.MetaMediaWorkspace=ctx=>{
 const $=id=>document.getElementById(id),esc=ctx.esc;
 let model=null,action='generate',source=null,active=null,result=null,timer=null,clock=null,started=0,fileEpoch=0;
 const errors={meta_not_configured:'Add MODEL_API_KEY in Render to use Model API.',meta_auth:'AI rejected the API key. Check MODEL_API_KEY.',meta_access:'This account does not have access to the requested model.',meta_model_unavailable:'This model is not available to the configured account.',meta_quota:'The provider reports insufficient quota or credit.',meta_rate_limit:'The provider rate limit was reached. Try again later.',meta_timeout:'The provider did not finish within the time limit.',media_invalid_image:'Use a still PNG, JPEG or WebP, up to 4 MB and 4 million pixels (maximum side 4096).',media_image_too_large:'The image is too large. Maximum upload: 4 MB.',media_request_needs_clarification:'AI+ could not preserve this request as one supported prompt.',media_output_too_large:'The result exceeded the safe image limit.',media_invalid_response:'The provider returned an unusable result.',job_expired:'This job has expired. Run the comparison again.',busy:'Another job is running. Wait for it to finish.',rate_limit:'Too many requests. Wait before running again.',compute_failed:'The comparison failed. Please try again.',meta_request_rejected:'AI rejected the request. Check this model’s access and supported inputs.',meta_format:'The provider returned an incomplete or unexpected response.'};
 const message=code=>errors[code]||('Request failed ('+code+').');
 const text=(id,value)=>{$(id).textContent=value;};
 function failure(code){$('mediaError').hidden=false;text('mediaError',message(code));}
 function controls(){
  const busy=ctx.busy();
  $('mediaRun').disabled=busy||!model?.configured||!$('mediaPrompt').value.trim()||(action!=='generate'&&!source);
  for(const id of ['generateImage','editImage','mediaPrompt','mediaFile','loadMediaSample'])$(id).disabled=busy;
  $('mediaCancel').hidden=!active;$('mediaCancel').classList.toggle('cancel-running',!!active);
  $('mediaEvidence').disabled=!result;$('mediaExportEvidence').disabled=!result;
  let next='';
  if(!busy){
   if(action!=='generate'&&!source)next='mediaFile';
   else if(!$('mediaPrompt').value.trim())next='mediaPrompt';
   else if(!$('mediaRun').disabled&&!result)next='mediaRun';
  }
  for(const id of ['mediaFile','mediaPrompt','mediaRun'])$(id).classList.toggle('next-step',next===id);
  $('mediaUploadLabel').classList.toggle('next-step',next==='mediaFile');$('mediaPromptLabel').classList.toggle('next-step',next==='mediaPrompt');
  $('mediaRun').title=!model?.configured?'Connection unavailable. Open Technical data.':action!=='generate'&&!source?'Upload an image first.':!$('mediaPrompt').value.trim()?'Enter your request first.':'';
 }
 function clear(){result=null;$('mediaError').hidden=true;text('mediaComparison','');text('mediaStatus','');
  $('mediaDirect').innerHTML='<p class="empty">Enter your request, then press Compare.</p>';
  $('mediaAssisted').innerHTML='<p class="empty">Both results will appear here.</p>';controls();
 }
 function render(){
  text('generateImage',window.MetaTests.label(model?.id,'image','generate','Generate image'));
  text('editImage',window.MetaTests.label(model?.id,'image','edit','Edit image'));
  $('loadMediaSample').hidden=action!=='generate';
  text('mediaUploadLabel','1. Upload image');$('imageUploadGroup').hidden=action==='generate';
  $('generateImage').setAttribute('aria-pressed',String(action==='generate'));$('editImage').setAttribute('aria-pressed',String(action==='edit'));
  text('mediaPromptLabel',(action==='generate'?'1. ':'2. ')+'Your image request');
  text('mediaRun',(action==='generate'?'2. ':'3. ')+'Compare');text('mediaResultsTitle',(action==='generate'?'3. ':'4. ')+'Results');
  text('mediaHint',action==='generate'?'Describe a new image. Compare your original request with the same request clarified by AI+.':'Upload a source image and describe what to change. Both paths receive the same image.');
  $('mediaPrompt').placeholder=action==='generate'?'Describe the image you want to create.':'Describe the changes you want and what should remain unchanged.';
  text('mediaDirectTitle',model?.label||'AI');text('mediaAssistedTitle',(model?.label||'AI')+' + prompt preparation');
  text('mediaUsage','Compare runs both paths. AI+ also calls Muse Spark 1.3 to prepare the request. Provider usage may consume credits or incur charges.');
  text('mediaComparisonHint','Same target model and image settings. AI+ prepares the prompt first.');
  text('mediaAboutTitle','What is AI+ for images?');
  text('mediaAboutText','AI sends your original request to Muse Image. AI+ first asks Muse Spark 1.3 to clarify that request while preserving its requirements, then uses Muse Image with the same settings and, for editing, the same source image.');
  controls();
 }
 $('loadMediaSample').onclick=()=>{
  if(ctx.busy()||action!=='generate')return;
  $('mediaPrompt').value='I want an elephant doing biceps curls with a barbell and wearing a Santa hat.';
  clear();controls();$('mediaPrompt').focus();
 };
 function setAction(next){if(ctx.busy())return;action=next;clear();render();}
 $('generateImage').onclick=()=>setAction('generate');$('editImage').onclick=()=>setAction('edit');
 $('mediaPrompt').addEventListener('input',()=>{if(!active)clear();controls();});
 $('mediaFile').addEventListener('change',async()=>{
  if(ctx.busy())return;
  const epoch=++fileEpoch,file=$('mediaFile').files?.[0];source=null;$('mediaPreview').hidden=true;clear();
  if(!file)return;
  if(file.size>4*1024*1024||!['image/png','image/jpeg','image/webp'].includes(file.type)){failure('media_invalid_image');return;}
  try{const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});
   if(epoch!==fileEpoch)return;source=data;$('mediaPreview').src=data;$('mediaPreview').hidden=false;controls();
  }catch{failure('media_invalid_image');}
 });
 function renderResult(){
  if(!result)return;
  for(const [name,target] of [['meta','mediaDirect'],['assisted','mediaAssisted']]){
   const arm=result.engines?.[name];if(!arm)continue;
   let html='<p class="media-time">'+(arm.total_ms/1000).toFixed(2)+' s</p><p class="small">Total path time · '+esc(arm.model_calls)+' model call'+(arm.model_calls===1?'':'s')+'</p>';
   if(arm.status!=='completed')html+='<p class="error">'+esc(message(arm.error))+'</p>';
   else{
    const files=(arm.artifacts||[]).filter(a=>/^\/api\/media\/jobs\/[a-f0-9]{32}\/assets\/(meta|assisted)-image\.png$/.test(a.url));
    const preview=files.find(a=>a.filename.endsWith('image.png'));
    if(preview)html+='<img class="media-output" src="'+esc(preview.url)+'" alt="'+(name==='meta'?'Direct':'Assisted')+' result">';
    html+='<div class="media-downloads">'+files.map(a=>'<a class="media-download" href="'+esc(a.url)+'?download=true" download="'+esc(a.filename)+'">Download '+esc(a.filename.replace(/^(meta|assisted)-/,'').replace('.png',''))+'</a>').join('')+'</div>';
   }
   html+='<details class="media-prompt-details"><summary>'+(name==='meta'?'Original prompt':'Prompt sent to the model')+'</summary><p>'+esc(arm.prompt)+'</p>';
   if(arm.preparation)html+='<p class="small">'+('Prepared with '+esc(arm.preparation.model))+' · '+(arm.preparation.elapsed_ms/1000).toFixed(2)+' s (included above).</p><p>'+esc(arm.preparation.note)+'</p>';
   html+='</details>';$(target).innerHTML=html;
  }
  const ratio=result.comparison?.latency_ratio_meta_over_assisted;
  const latency=Number.isFinite(ratio)?(ratio>=1?'AI+':'AI')+' · '+(ratio>=1?ratio:1/ratio).toFixed(2)+'× faster in total path time. ':'';
  text('mediaComparison',latency+(result.comparison?.quality_note||'Waiting for the other path…'));
  text('mediaEvidenceText',JSON.stringify(result,null,2));controls();
 }
 function finish(status){clearTimeout(timer);clearInterval(clock);timer=clock=null;active=null;ctx.store.del('mq-media-active');ctx.setWorking(false);text('mediaStatus',status);controls();}
 function apply(job){
  if(job.mode!=='media'){finish('Unable to restore media job.');return;}
  if(job.result||job.partial){result=job.result||job.partial;renderResult();}
  if(['completed','failed','cancelled'].includes(job.status)){
   const succeeded=job.status==='completed'&&Object.values(result?.engines||{}).every(a=>a.status==='completed');
   finish(job.status==='completed'?(succeeded?'Completed. Download your results.':'Comparison finished with an error. Check each path.'):job.status==='cancelled'?'Cancelled. Work already submitted may still be billed.':'Comparison failed.');
   if(job.status!=='completed')text('mediaComparison','Comparison stopped. No latency or quality winner is declared. Completed artifacts remain available.');
   if(job.status==='failed')failure(job.error||'compute_failed');
  }
 }
 async function poll(){
  if(!active)return;const id=active;
  try{const job=await ctx.api('/api/jobs/'+id);if(active!==id)return;apply(job);if(active)timer=setTimeout(poll,1200);}
  catch(e){if(active!==id)return;if(e.http===404){finish('Job unavailable.');failure('job_expired');}else{failure(e.message);timer=setTimeout(poll,4000);}}
 }
 function beginClock(){clearInterval(clock);clock=setInterval(()=>text('mediaStatus','Running both paths… '+Math.floor((Date.now()-started)/1000)+' s'),1000);}
 $('mediaRun').onclick=async()=>{
  if($('mediaRun').disabled)return;clear();ctx.setWorking(true);
  const id=ctx.requestId();active=id.replaceAll('-','');started=Date.now();
  ctx.store.set('mq-media-active',JSON.stringify({id:active,model:model.id,started}));
  $('mediaDirect').innerHTML='<p class="empty">Running original request…</p>';
  $('mediaAssisted').innerHTML='<p class="empty">'+'Preparing the request with Muse Spark 1.3…'+'</p>';
  text('mediaStatus','Starting comparison…');beginClock();controls();
  try{const job=await ctx.api('/api/media/jobs',{request_id:id,model:model.id,action,prompt:$('mediaPrompt').value,image:action==='generate'?null:source});apply(job);if(active)poll();}
  catch(e){if(e.http){finish('Could not start comparison.');failure(e.message);}else{failure(e.message);poll();}}
 };
 $('mediaCancel').onclick=async()=>{if(!active)return;$('mediaCancel').disabled=true;try{await ctx.api('/api/jobs/'+active+'/cancel',{});text('mediaStatus','Cancelling…');}catch(e){failure(e.message);}finally{$('mediaCancel').disabled=false;}};
 $('mediaEvidence').onclick=()=>$('mediaEvidenceDialog').showModal();
 $('mediaExportEvidence').onclick=()=>{if(result)ctx.download('ai-plus-media-comparison.json',result);};
 return {controls,get active(){return active},setModel(value){
   const changed=model?.id!==value?.id;model=value;
   if(changed){action='generate';$('mediaPrompt').value='';source=null;$('mediaFile').value='';$('mediaPreview').hidden=true;fileEpoch++;clear();}render();
  },async restore(){let saved;try{saved=JSON.parse(ctx.store.get('mq-media-active'));}catch{}if(!saved||!/^[a-f0-9]{32}$/.test(saved.id))return;
   if(saved.model&&saved.model!=='muse-image-1.0'){ctx.store.del('mq-media-active');return;}
   try{const job=await ctx.api('/api/jobs/'+saved.id);if(job.mode!=='media')throw Error('media_invalid_response');if(job.model!=='muse-image-1.0'||!['generate','edit'].includes(job.action)){ctx.store.del('mq-media-active');return;}ctx.select(job.model);action=job.action;$('mediaPrompt').value=job.question;render();active=job.id;started=job.created_at*1000;ctx.setWorking(true);apply(job);if(active){beginClock();poll();}}
   catch(e){ctx.store.del('mq-media-active');failure(e.message);}
  },showAbout(){ $('mediaAboutDialog').showModal();},showTechnical(){if(!result)text('mediaEvidenceText',JSON.stringify({model:model?.label,provider:'Model API',credential_configured:!!model?.configured,model_access:'Checked when the request runs; configuration alone does not prove access.',planner:'Muse Spark 1.3',optimizer_used:false},null,2));$('mediaEvidenceDialog').showModal();}};
};
})();

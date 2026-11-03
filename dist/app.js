(()=>{'use strict';
const $=id=>document.getElementById(id),D=window.MQ_I18N;
const store={get(k){try{return localStorage.getItem(k)}catch{return null}},set(k,v){try{localStorage.setItem(k,v)}catch{}},del(k){try{localStorage.removeItem(k)}catch{}}};
let lang=store.get('mq-language')||'en';if(!D[lang])lang='en';
let problemInput='',planId=null,selectedModel=null;
let workspace=null,mediaWorkspace=null;
let info=null,category='channels',preset=null,result=null,active=null,lastJob=null,working=false,started=0,timer=null;
let infoRefresh=null,infoCheckedAt=0,infoRefreshFailed=false;
let eventStream=null,streamWatchdog=null,firstSeen={};
let statusCode='ready',clockOrigin=null,clockOffset=0,elapsedMs=null,clockTimer=null;
const t=k=>D[lang][k]||D.en[k]||k,loc=o=>o?.[lang]||o?.en||'',esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(x,d=2)=>Number(x).toLocaleString({en:'en-GB',es:'es-ES',fr:'fr-FR',de:'de-DE'}[lang],{maximumFractionDigits:d}),ms=x=>x<1000?num(x,1)+' ms':num(x/1000,2)+' s';
function error(code,issues=[]){$('error').hidden=false;$('error').textContent=t(code)===code?t('error')+' ('+code+')':t(code);if(issues.length)$('error').textContent+=' '+issues.map(x=>x.field+': '+x.code).join('; ')}
function clearError(){$('error').hidden=true}
async function api(url,body,method,timeoutMs=170000){const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),timeoutMs);try{const r=await fetch(url,{method:method||(body?'POST':'GET'),credentials:'same-origin',headers:{'Content-Type':'application/json','X-Metaquant-Request':'1'},body:body?JSON.stringify(body):undefined,signal:controller.signal});let d;try{d=await r.json()}catch{const e=new Error('server_unavailable');e.http=r.status;throw e}if(r.status===401&&d.detail==='authentication_required'){location.replace('/login');throw new Error('authentication_required')}if(!r.ok){let e=new Error(typeof d.detail==='string'?d.detail:d.detail?.code||'invalid_problem_data');e.userMessage=d.detail?.message;e.issues=d.detail?.issues||[];e.providerStatus=d.detail?.provider_status;e.http=r.status;throw e}return d}finally{clearTimeout(timeout)}}
function requestId(){if(typeof crypto.randomUUID==='function')return crypto.randomUUID();const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;const hex=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`}
function controls(){
 const busy=working||!!active,locked=busy||!!workspace?.batching;
 const hasSpec=workspace?.mode==='data'?workspace.requiresGPU:!!problemInput.trim(),hasText=!!$('intent').value.trim();
 $('modelSelect').disabled=locked;
 $('run').disabled=locked||((hasSpec&&!info?.gpu_configured))||!modelReady()||!(hasSpec||hasText)||!workspace?.canRun();
 $('intent').disabled=locked;$('problemSelect').disabled=locked;$('cancel').hidden=!active;$('cancel').classList.toggle('cancel-running',!!active);$('cancel').disabled=statusCode==='cancelling';
 $('explain').disabled=locked||!result?.complete||!modelReady();$('export').disabled=!result;$('csv').disabled=!result?.complete;$('showEvidence').disabled=!result;
 workspace?.controls();mediaWorkspace?.controls();renderStatus();
}
function modelLabel(id){return info?.models?.find(m=>m.id===id)?.label||id||'AI'}
function selected(){return info?.models?.find(m=>m.id===selectedModel)}
function modelReady(){return !!selected()?.enabled&&(selected()?.configured??!!info?.meta_configured)}
function isMedia(){return selected()?.modality==='image'}
function renderModel(){
 if(!info)return;
 if(!selected()){selectedModel=info.default_model;store.set('mq-ai-model',selectedModel);}
 const menu=$('modelSelect');menu.replaceChildren();
 for(const m of info.models){const option=document.createElement('option');option.value=m.id;option.textContent=m.label+(m.provider==='fireworks'?' · Fireworks':'');menu.append(option);}
 menu.value=selectedModel;
 $('taskWorkspace').hidden=isMedia();$('mediaWorkspace').hidden=!isMedia();
 document.querySelector('h1 span:last-child').textContent='"Enhancements for Meta AI models"';
 const descriptions={'muse-spark-open':'Open-weight reasoning and task solving','muse-spark-1.3':'Reasoning, coding and task solving','muse-wonder-1.0':'Complex reasoning and multi-step tasks','muse-image-1.0':'Image Generation & Editing','muse-glimmer-30b':'Compact reasoning and task solving','llama4-scout':'Multimodal understanding and task solving','llama4-maverick':'Multimodal reasoning and task solving','llama31-70b':'Text understanding and task solving'};
 $('modelDescription').textContent=descriptions[selectedModel]||'Reasoning and task solving';
 document.querySelector('.combination-note').textContent=isMedia()?'Compare the original request with a request prepared by AI.':'Combination of AI + Simulated Bifurcation + NVIDIA + Modal';
 for(const label of ['NVIDIA','Modal'])document.querySelector('.header-logos [aria-label="'+label+'"]').hidden=isMedia();
 if(isMedia())mediaWorkspace?.setModel(selected());
 setModelNote(modelLabel(selectedModel));
 renderTestLabels();
}
function renderTestLabels(){
 for(const option of $('dataFormat').options){
  option.textContent=window.MetaTests.label(selectedModel,'excel',option.value,option.value==='sample'?'Complex Real Sample':t('useOwnData'));
 }
 for(const option of $('problemSelect').options){
  option.textContent=window.MetaTests.label(selectedModel,'problems',option.value,option.value==='own'?t('own'):t('category_'+option.value));
 }
 const key=preset?category:'own';
 $('categoryTitle').textContent=window.MetaTests.label(selectedModel,'problems',key,key==='own'?t('own'):t('category_'+key));
}
function selectModel(id){if(working||active)return;selectedModel=id;store.set('mq-ai-model',id);planId=null;workspace?.modelChanged();resetResult();clearError();renderModel();renderConnection();controls();return refreshInfo(true);}
$('modelSelect').onchange=()=>selectModel($('modelSelect').value);
function planMessage(text=''){$('planMessage').textContent=text;$('planMessage').hidden=!text}
function resetResult(){resetClock();result=null;lastJob=null;for(const n of ['meta','assisted']){$(n).innerHTML='<div class="empty">'+esc(t('empty'))+'</div>';document.querySelector('[data-download="'+n+'"]').hidden=true}$('metaState').textContent='';$('assistedState').textContent='';$('comparison').textContent='';$('runSummary').textContent=t('same');$('explanation').textContent='';$('evidence').textContent='';$('hardware').textContent='';workspace?.empty();}
function stopPending(code){for(const name of ['meta','assisted']){if(!result?.engines?.[name]){$(name).innerHTML='<div class="empty">'+esc(t(code))+'</div>';$(name==='meta'?'metaState':'assistedState').textContent=t(code)}}if(result&&!result.complete)$('comparison').textContent=t('incomplete')}
function renderStatus(){const suffix=elapsedMs===null?'':' · '+t('elapsed')+': '+num(Math.floor(elapsedMs/1000),0)+' s';$('status').textContent=(statusCode==='ready'?(workspace?.readyStatus??t(statusCode)):t(statusCode))+suffix;$('status').classList.toggle('busy',working||!!active)}
function tickClock(){if(clockOrigin!==null)elapsedMs=clockOffset+performance.now()-clockOrigin;renderStatus()}
function startClock(wallStarted=Date.now()){clearInterval(clockTimer);started=Number.isFinite(wallStarted)?wallStarted:Date.now();clockOffset=Math.max(0,Date.now()-started);clockOrigin=performance.now();tickClock();clockTimer=setInterval(tickClock,250)}
function stopClock(){if(clockOrigin!==null)tickClock();clockOrigin=null;clearInterval(clockTimer);clockTimer=null;renderStatus()}
function resetClock(){stopClock();elapsedMs=null;renderStatus()}
function status(code){statusCode=code;renderStatus()}
function choose(p){if(!p||active||working)return;resetResult();planId=null;preset=p;category=p.category;$('intent').value=presetPrompt(p);problemInput=JSON.stringify(p.spec,null,2);planMessage();clearError();renderCatalog();status('ready')}
function presetPrompt(p){
 const c=info.categories.find(c=>c.id===p.category);
 return [loc(c.title),num(p.spec.size,0)+' '+t('variables'),loc(c.description),loc(c.limits)].join(' · ');
}
function chooseOwn(){
 if(active||working)return;
 resetResult();planId=null;clearError();preset=null;category='own';problemInput='';
 $('intent').value='';planMessage();renderCatalog();status('ready');$('intent').focus();
}
function renderCatalog(){
 if(!info)return;
 const select=$('problemSelect');select.replaceChildren();
 for(const c of info.categories){
  if(c.id==='assignment')continue;
  if(!info.presets.some(p=>p.category===c.id))continue;
  const option=document.createElement('option');option.value=c.id;option.textContent=t('category_'+c.id);select.append(option);
 }
 const own=document.createElement('option');own.value='own';own.textContent=t('own');select.append(own);
 select.value=preset?category:'own';
 const c=preset?info.categories.find(c=>c.id===category):null;
 $('categoryTitle').textContent=c?t('category_'+c.id):t('own');
 $('description').textContent=c?loc(c.description):t('ownHint');
 $('intent').placeholder=t('ownHint');
 $('exampleExplanation').textContent=c?t('example_'+c.id):t('ownExplanation');
 $('limits').textContent=c?loc(c.limits):'';$('limits').hidden=!c;
 $('scale').textContent=preset?num(preset.spec.size,0)+' '+t('variables')+' · '+t('synthetic'):'';
 $('scale').hidden=!preset;
 renderTestLabels();
 controls();
}
$('problemSelect').onchange=()=>{
 if(active||working)return;
 if($('problemSelect').value==='own')chooseOwn();
 else choose(info.presets.find(p=>p.category===$('problemSelect').value));
};
function translate(){document.documentElement.lang=lang;document.querySelectorAll('[data-t]').forEach(e=>e.textContent=t(e.dataset.t));document.querySelectorAll('[data-lang]').forEach(b=>b.classList.toggle('active',b.dataset.lang===lang));if(preset&&!active&&workspace?.mode==='example')$('intent').value=presetPrompt(preset);renderModel();renderCatalog();if(result)renderResult();else if(!active&&!working)resetResult();if(!active&&!working)status('ready');renderConnection();renderStatus();workspace?.render();workspace?.empty()}
function connectionDetails(){
 const m=selected(),key=m?.provider==='meta'?'MODEL_API_KEY':'META_API_KEY';
 return (m?.label||'Selected model')+' · '+(m?.provider==='meta'?'Model API':'Fireworks')+'. '+
  (modelReady()?'Credential detected by the running server. Model access is checked when you run.':key+' is not detected by the running server. In Render, use Save and deploy and wait for Live, then refresh this connection.')+
  (infoRefreshFailed?' The last refresh failed; the displayed configuration is the last known state.':infoCheckedAt?' Last checked: '+new Date(infoCheckedAt).toLocaleTimeString()+'.':'');
}
function renderConnection(){
 if(!info)return;
 $('connection').textContent=isMedia()?'Model API':(info.gpu_configured?t('configured'):t('noGPU'))+' · '+(selected()?.provider==='meta'?'Model API':'Fireworks');
 $('modelConnectionDetails').textContent=connectionDetails();$('mediaConnectionDetails').textContent=connectionDetails();
 for(const id of ['run','interpretRequest','mediaRun'])$(id).title=modelReady()?'':'Connection unavailable. Open Technical data.';
 if(!info.gpu_configured&&!active&&problemInput.trim())status('missing');
}
async function refreshInfo(force=false){
 if(!info||working||active||workspace?.batching)return false;
 if(infoRefresh)return infoRefresh;
 if(!force&&Date.now()-infoCheckedAt<5000)return false;
 infoRefresh=(async()=>{
  try{
   const latest=await api('/api/info',undefined,undefined,12000);
   if(!Array.isArray(latest.models))throw Error('invalid_configuration');
   info=latest;infoCheckedAt=Date.now();infoRefreshFailed=false;
   // Only connection/model presentation is refreshed: preserve data, interpretation and results.
   renderModel();renderConnection();controls();return true;
  }catch{infoRefreshFailed=true;renderConnection();return false;}
  finally{infoRefresh=null;}
 })();return infoRefresh;
}
window.addEventListener('focus',()=>refreshInfo(true));
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshInfo(true)});
const configTimer=setInterval(()=>{if(!document.hidden&&!modelReady())refreshInfo()},15000);
window.addEventListener('pagehide',()=>clearInterval(configTimer));
for(const id of ['refreshModelConnection','refreshMediaConnection'])$(id).onclick=async()=>{
 $(id).disabled=true;try{await refreshInfo(true)}finally{$(id).disabled=false}
};

function download(name,data,type='application/json'){const a=document.createElement('a'),url=URL.createObjectURL(new Blob([typeof data==='string'?data:JSON.stringify(data,null,2)],{type}));a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),5000)}
function showTimedComparison(prefix,ratio,suffix=''){
 const speed=document.createElement('strong');speed.className='comparison-speed';
 speed.textContent=num(ratio>=1?ratio:1/ratio)+'× '+t('faster')+'.';
 $('comparison').replaceChildren(document.createTextNode(prefix+' · '),speed,document.createTextNode(suffix));
}
function resultText(value){return String(value??'').replace(/\b(?:Global\s+)?optimality is not proven\.?/gi,'').replace(/[ \t]{2,}/g,' ').trim()}
function optimizerStatus(e){
 const ev=e.evidence||{};
 if(!ev.gpu_execution_verified)return '';
 const valid=ev.solver_solution_valid,device=ev.tool_result?.hardware?.sb_device_name;
 return `<p class="tool-status">${esc(t('gpu_executed'))}${device?' · '+esc(device):''}</p><p class="tool-status ${valid===false?'error':''}">${esc(t(valid===true?'solver_valid':valid===false?'solver_invalid':'solver_validity_unknown'))}</p>${ev.tool_result?.quality_search?.method==='simulated_bifurcation_with_tabu_refinement'?`<p class="small">${esc(t('quality_search_used'))}</p>`:''}`;
}
function renderResult(){
 if(!result)return;
 if(result.mode==='question'){renderQuestionResult();return}
 const r=result;
 const model=r.protocol?.model;
 $('runSummary').textContent=(model?.label||modelLabel(model?.selection_id))+' · '+num(r.workspace?.decision_count??r.problem.variables,0)+' '+t('variables')+' · '+(r.workspace?.data_origin==='template_sample'?'Template sample data':r.problem.data_source==='synthetic'?t('synthetic'):'Uploaded data');
 for(const name of ['meta','assisted']){
  const e=r.engines[name];if(!e)continue;
  const valid=e.status==='completed'&&e.decoded?.feasible===true;
  $(name==='meta'?'metaState':'assistedState').textContent=t(e.status==='completed'?'done':'failed');
  const plan=r.workspace?.plans?.[name];
  const metrics=Object.entries(plan?{}:e.decoded?.metrics||{}).map(([k,v])=>`<div class="metric-detail"><span>${esc(metricLabel(k))}</span><strong>${esc(num(v,3))}</strong></div>`).join('');
  $(name).innerHTML=`<div class="metrics"><div><span class="value">${esc(ms(e.end_to_end_ms))}</span><span class="label">${esc(t('time'))}</span></div><div><span class="value">${Number.isFinite(plan?.display_value)?esc(num(plan.display_value,3)):Number.isFinite(e.energy)?esc(num(e.energy,3)):'—'}</span><span class="label">${esc(plan?.metric||t('cost'))}</span></div></div><span class="valid ${valid?'':'invalid'}">${esc(t(valid?'feasible':e.status==='failed'?'failed':'infeasible'))}</span>${e.error?`<p class="error">${esc(t(e.error))}</p>`:''}${metrics}${workspace?.planMarkup(name,r)||''}${workspace?.solutionMarkup(e)||''}<p class="small">${esc(t('calls'))}: ${esc(e.model_calls)} · ${esc(t('tokens'))}: ${e.usage?.total_tokens??'not reported'}</p><p class="small muted">${esc(t('sumTrials'))}: ${esc(ms(e.meta_ms))}</p>${e.status==='completed'&&e.at_proven_optimum===true?`<p class="small">${esc(t('optimum'))}</p>`:''}<p class="small">${esc(resultText(e.summary))}</p><p class="small muted">${esc(t('costUnavailable'))}</p>`;
  if(name==='assisted')$(name).insertAdjacentHTML('beforeend',optimizerStatus(e));
  document.querySelector('[data-download="'+name+'"]').hidden=false;
 }
 if(r.complete){
  const c=r.comparison;
  if(c.both_valid){
   const ratio=c.assisted_time_ratio,fast=ratio>=1?t('assisted_short'):t('cpu');
   const quality=c.same_objective?t('quality_equal'):t(c.assisted_objective_minus_meta<0?'quality_assisted':'quality_meta');
   showTimedComparison(quality+' '+fast,ratio);
  }else $('comparison').textContent=t('no_valid_comparison');
 }else $('comparison').textContent=t(r.engines.assisted&&r.engines.meta?'verifying':r.engines.assisted?'waiting_cpu':r.engines.meta?'waiting_gpu':'running');
 workspace?.onResult(r);
 $('evidence').textContent=JSON.stringify(r,null,2);
 $('hardware').textContent=JSON.stringify({model:r.protocol?.model,hardware:r.hardware||r.engines.assisted?.evidence?.tool_result?.hardware||null,budgets:r.protocol?.gpu_budget},null,2);
 controls();
}
function renderQuestionResult(){
 const r=result,m=r.protocol?.model;
 $('runSummary').textContent=(m?.label||modelLabel(m?.selection_id))+' · '+t('general_question');
 for(const name of ['meta','assisted']){
  const e=r.engines[name];if(!e)continue;
  const ok=e.status==='completed',ev=e.evidence||{};
  const tool=name==='assisted'&&!ev.gpu_execution_verified?(ev.tool_requested?t('question_tool_failed'):ev.tool_available===false?t('question_no_gpu'):t('tool_unused')):'';
  $(name==='meta'?'metaState':'assistedState').textContent=t(ok?'done':'failed');
  $(name).innerHTML=`<div class="metrics"><div><span class="value">${esc(ms(e.end_to_end_ms))}</span><span class="label">${esc(t('time'))}</span></div></div><span class="valid ${ok?'':'invalid'}">${esc(t(ok?'response_received':'failed'))}</span>${optimizerStatus(e)}${tool?`<p class="tool-status">${esc(tool)}</p>`:''}${e.error?`<p class="error">${esc(t(e.error))}</p>`:''}${e.answer?`<div class="answer-text">${esc(resultText(e.answer))}</div>`:''}${workspace?.solutionMarkup(e)||''}<p class="question-note">${esc(t(e.csv_solution?.source==='verified_optimizer_result'?'solver_output_checked':'quality_unverified'))}</p>${ev.gpu_execution_verified?`<p class="question-note">${esc(t('question_formulation'))}</p>`:''}<p class="small">${esc(t('calls'))}: ${esc(e.model_calls)} · ${esc(t('tokens'))}: ${esc(e.usage?.total_tokens??'not reported')}</p><p class="small">${esc(t('sumTrials'))}: ${esc(ms(e.meta_ms))}</p><p class="small muted">${esc(t('costUnavailable'))}</p>`;
  document.querySelector('[data-download="'+name+'"]').hidden=false;
 }
 if(r.complete){
  const c=r.comparison;
  if(c.both_completed){
   const ratio=c.assisted_time_ratio,fast=ratio>=1?t('assisted_short'):t('cpu');
   showTimedComparison(fast,ratio,' '+t('latency_only')+(!c.optimizer_used?' '+t('no_optimizer_benefit'):''));
  }else $('comparison').textContent=t('question_failed_comparison');
 }else $('comparison').textContent=t('running');
 workspace?.onResult(r);
 $('evidence').textContent=JSON.stringify(r,null,2);
 $('hardware').textContent=JSON.stringify({model:m,hardware:r.hardware||r.engines.assisted?.evidence?.tool_result?.hardware||null,optimizer_available:r.protocol?.optimizer_available},null,2);
 controls();
}
function exportQuestionCSV(){
 const m=result.protocol?.model||{};
 const rows=Object.entries(result.engines).map(([name,e])=>[name,e.status,e.answer||'',e.error||'',e.end_to_end_ms,e.evidence?.tool_used||false,e.evidence?.gpu_execution_verified||false,false,e.model_calls,e.usage?.total_tokens??'',m.model,m.reasoning_effort??'not applicable']);
 download('ai-plus-answers.csv',window.MetaExcelCSV('path,status,answer,error,total_path_ms,optimizer_used,gpu_verified,answer_quality_verified,model_calls,total_tokens,model_endpoint,reasoning_effort'.split(','),rows),'text/csv;charset=utf-8');
}

function metricLabel(k){const labels={remaining_interference:['Audience conflict cost','Coste de conflicto de público'],avoided_interference:['Avoided conflicts','Conflictos evitados'],channel_1_count:['Session A events','Eventos sesión A'],channel_2_count:['Session B events','Eventos sesión B'],load_a:['Zone A load','Carga zona A'],load_b:['Zone B load','Carga zona B'],load_difference:['Load difference','Diferencia de carga'],contention_cost:['Resource contention','Competencia por recursos'],balance_cost:['Balance cost','Coste de equilibrio'],benefit:['Restoration value','Valor de restauración'],pair_cost:['Interaction cost','Coste de interacción'],net_value:['Net value','Valor neto'],selected_count:['Selected actions','Actuaciones seleccionadas'],execution_cost:['Handling cost','Coste de manipulación'],interaction_cost:['Pairwise transport cost','Coste entre parejas'],pool_a_count:['Hub A shipments','Pedidos centro A'],pool_b_count:['Hub B shipments','Pedidos centro B']};return labels[k]?.[lang==='es'?1:0]||k.replaceAll('_',' ')}
function pendingStage(stage,armStages={}){for(const name of ['meta','assisted']){if(result?.engines?.[name])continue;const code=armStages[name]||stage;$(name).innerHTML='<div class="empty">'+esc(t(code))+'</div>';$(name==='meta'?'metaState':'assistedState').textContent=''}}
function pending(){firstSeen={};result=null;lastJob=null;for(const n of ['meta','assisted']){$(n).innerHTML='<div class="empty">'+esc(t('connecting'))+'</div>';document.querySelector('[data-download="'+n+'"]').hidden=true}$('metaState').textContent='';$('assistedState').textContent='';$('comparison').textContent='';$('explanation').textContent=t('explanationHint');$('evidence').textContent='';$('export').disabled=true;$('csv').disabled=true}
function finish(){closeStream();clearTimeout(timer);timer=null;lastJob=active;active=null;store.del('mq-ai-v2-active');stopClock();controls()}
function closeStream(){if(eventStream){eventStream.close();eventStream=null}clearTimeout(streamWatchdog);streamWatchdog=null}
function applyJob(job){
 if(!job||!job.status)return;
 renderModel();
 const incoming=job.status==='completed'?job.result:job.partial;
 if(incoming){
  const now=clockOrigin===null?(elapsedMs||0):clockOffset+performance.now()-clockOrigin;
  for(const name of Object.keys(incoming.engines||{}))if(firstSeen[name]===undefined)firstSeen[name]=Math.round(now);
  result={...incoming,delivery:{gateway_timeline:job.gateway_timeline||[],worker_timeline:job.worker_timeline||[],gateway_elapsed_ms:job.gateway_elapsed_ms,first_visible_ms:{...firstSeen},transport:eventStream?'server_sent_events':'polling'}};
  renderResult();
 }
 if(job.status==='completed'){finish();status('completed');workspace?.record(job,result)}
 else if(['failed','cancelled'].includes(job.status)){finish();status(job.status==='failed'?'failed':job.stage);stopPending(job.status==='failed'?'failed':'cancelled');if(job.status==='failed')error(job.error||'compute_failed');workspace?.record(job,result)}
 else{const stage=job.stage==='running'&&result?.engines?.assisted&&!result?.engines?.meta?'waiting_cpu':job.stage==='running'&&result?.engines?.meta&&!result?.engines?.assisted?'waiting_gpu':job.stage;status(stage);pendingStage(stage,job.arm_stages||{})}
}
async function poll(){if(!active)return;const id=active;try{const job=await api('/api/jobs/'+id);if(active!==id)return;applyJob(job);if(active)timer=setTimeout(poll,1000)}catch(e){if(active!==id)return;if(e.http===404){finish();stopPending('job_expired');status('job_expired');error(e.message)}else{status('error');timer=setTimeout(poll,4000)}}}
function watchJob(){
 closeStream();clearTimeout(timer);timer=null;
 if(!active)return;
 if(!info?.streaming||typeof EventSource!=='function'){poll();return}
 const id=active;
 const fallback=()=>{if(active!==id)return;closeStream();poll()};
 const arm=()=>{clearTimeout(streamWatchdog);streamWatchdog=setTimeout(fallback,45000)};
 try{
  const source=new EventSource('/api/jobs/'+id+'/events');eventStream=source;
  streamWatchdog=setTimeout(fallback,8000);
  source.onopen=()=>{if(eventStream===source)arm()};
  source.addEventListener('heartbeat',()=>{if(eventStream===source)arm()});
  source.onmessage=event=>{if(active!==id||eventStream!==source)return;arm();try{applyJob(JSON.parse(event.data))}catch{fallback()}};
  source.onerror=()=>{if(eventStream===source)fallback()};
 }catch{fallback()}
}

$('intent').addEventListener('input',()=>{if(workspace?.mode!=='example'){workspace.invalidate();resetResult();status('ready');controls();return}preset=null;category='own';problemInput='';planId=null;resetResult();clearError();planMessage();renderCatalog();workspace?.render();status('ready')});
document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>$(b.dataset.close).close());
$('showEvidence').onclick=()=>$('evidenceDialog').showModal();
async function runCurrent(){
 if(working||active)return false;
 if(workspace?.mode!=='example'&&!workspace.canRun())return false;
 if(workspace&&!await workspace.prepareRun())return false;
 clearError();working=true;startClock();controls();status('validating');
 try{
  let payload;
  const input=problemInput.trim();
  if(workspace?.mode!=='example'){payload=null;}else if(input){
   const checked=await api('/api/validate',{question:input,language:lang});
   problemInput=JSON.stringify(checked.spec,null,2);
   payload={spec:checked.spec,plan_id:planId};
  }else{
   const question=$('intent').value.trim();
   if(!question)throw new Error('invalid_problem_data');
   payload={question};
  }
  const id=requestId();pending();active=id.replaceAll('-','');
  store.set('mq-ai-v2-active',JSON.stringify({id:active,started,model:selectedModel}));controls();status('connecting');
  const submitted=workspace?.mode!=='example'?await workspace.submit(id,lang):await api('/api/jobs',{request_id:id,...payload,language:lang,model:selectedModel});planId=null;applyJob(submitted);if(active)watchJob();return true;
 }catch(e){
  if(e.http){if(active){finish();stopPending('failed')}error(e.message,e.issues);status('failed')}
  else if(active){watchJob()}
  else{error(e.message,e.issues);status('failed')}
  if(e.userMessage)$('error').textContent=e.userMessage;
  return !!active;
 }finally{working=false;if(!active)stopClock();controls();renderStatus()}
}
$('run').onclick=()=>{if(!workspace?.batching)runCurrent()};
$('cancel').onclick=async()=>{if(!active)return;try{await api('/api/jobs/'+active+'/cancel',{});status('cancelling');controls()}catch(e){error(e.message)}};
$('explain').onclick=async()=>{
 if(!lastJob||working)return;
 clearError();working=true;controls();
 const box=$('explanation');
 box.textContent=t('explaining');
 box.classList.toggle('loading',true);
 box.setAttribute('aria-busy','true');
 try{
  setModelNote(result?.protocol?.model?.label||modelLabel(selectedModel));$('explanationDialog').showModal();
  const d=await api('/api/jobs/'+lastJob+'/explain',{});
  box.textContent=resultText(d.text);result.meta_explanation=d;setModelNote(result?.protocol?.model?.label||d.meta?.provider_model);$('evidence').textContent=JSON.stringify(result,null,2);
 }catch(e){
  box.textContent=t(e.message)+(Number.isInteger(e.providerStatus)?' (HTTP '+e.providerStatus+')':'');
  error(e.message);
 }finally{
  box.classList.toggle('loading',false);
  box.setAttribute('aria-busy','false');
  working=false;controls();
 }
};
$('aboutAIPlus').onclick=()=>isMedia()?mediaWorkspace.showAbout():$('aboutAIPlusDialog').showModal();
$('export').onclick=()=>{if(result)download('ai-plus-measurement.json',result)};
$('csv').onclick=()=>{if(!result?.complete)return;if(result.mode==='question'){exportQuestionCSV();return}const a=result.engines.meta,b=result.engines.assisted,m=result.protocol?.model||{};const rows=Array.from({length:result.problem.variables},(_,i)=>[i+1,a.bits?.[i]??'',b.bits?.[i]??'',a.status,b.status,m.model,m.base_model,m.reasoning_effort??'not applicable',m.max_tokens_per_call]);download('ai-plus-decisions.csv',window.MetaExcelCSV('decision,meta_ai_binary,meta_ai_optimizer_binary,meta_ai_status,meta_ai_optimizer_status,model_endpoint,base_model,reasoning_effort,max_tokens_per_call'.split(','),rows),'text/csv;charset=utf-8')};

document.querySelectorAll('[data-download]').forEach(b=>b.onclick=()=>{const name=b.dataset.download;if(workspace?.downloadSolution(name))return;if(workspace?.downloadPlan(name))return;if(result?.engines[name])download('ai-plus-'+name+'.json',{mode:result.mode||'optimization',question:result.question,problem:result.problem,protocol:result.protocol,hardware:result.hardware,engine:result.engines[name],complete:result.complete})});
document.querySelectorAll('[data-lang]').forEach(b=>b.onclick=()=>{lang=b.dataset.lang;store.set('mq-language',lang);translate()});
$('technical').onclick=()=>{refreshInfo(true);if(isMedia())mediaWorkspace.showTechnical();else $('technicalDialog').showModal()};$('closeDialog').onclick=()=>$('technicalDialog').close();
function setModelNote(model){const text=model==='accounts/fireworks/models/muse-spark-open'?'Muse Spark Open':model;$('metaModelNote').querySelector('strong').textContent=text||'Configured model';$('explanationModel').textContent=text||'';const direct=selected()?.provider==='meta';$('metaModelNote').querySelector('[data-t="metaModelAccess"]').textContent=direct?', accessed through Model API.':', accessed through the Fireworks API.';$('metaModelNote').querySelector('svg').hidden=direct;}
async function init(){try{info=await api('/api/info');infoCheckedAt=Date.now();selectedModel=info.models.some(m=>m.id===store.get('mq-ai-model'))?store.get('mq-ai-model'):info.default_model;renderModel();setModelNote(modelLabel(selectedModel));choose(info.presets[0]);if(workspace?.mode!=='example'){chooseOwn();workspace.render()}translate();await workspace.initialize();let saved;try{saved=JSON.parse(store.get('mq-ai-v2-active'))}catch{}if(saved&&/^[a-f0-9]{32}$/.test(saved.id)){selectedModel=info.models.some(m=>m.id===saved.model)?saved.model:selectedModel;active=saved.id;renderModel();startClock(saved.started);pending();controls();status('connecting');watchJob()}else{await mediaWorkspace.restore()}}catch(e){error(e.message);status('error')}}
$('signOut').onclick=async()=>{try{await api('/api/logout',{});store.del('mq-ai-v2-active');location.replace('/login')}catch(e){error(e.message)}};
workspace=window.MetaWorkspace({api,download,esc,num,t,lang:()=>lang,model:()=>selectedModel,result:()=>result,
 canUseMeta:()=>modelReady()&&!isMedia(),
 busy:()=>working||!!active,setWorking:value=>{working=value;controls()},reset:()=>{resetResult();clearError();status('ready')},controls,
 numeric:()=>workspace?.mode==='data'?(workspace.numerical&&workspace.canRun()):!!problemInput.trim(),useText:chooseOwn,run:runCurrent,cancel:()=>{if(active)$('cancel').click()},
 restoreExample:()=>{if(info)choose(info.presets.find(p=>p.category===category)||info.presets[0])}});
mediaWorkspace=window.MetaMediaWorkspace({api,download,esc,requestId,store,select:selectModel,busy:()=>working||!!active,setWorking:value=>{working=value;controls()}});
translate();controls();init();
})();

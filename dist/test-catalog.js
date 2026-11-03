/* Stable test IDs for recording comparisons. Labels never enter model prompts. */
(()=>{'use strict';
 const coreModels=['muse-spark-open','muse-spark-1.3','muse-wonder-1.0'];
 const additionalModels=['muse-glimmer-30b','llama4-scout','llama4-maverick','llama31-70b'];
 const excelCases=[['sample','Complex Real Sample']];
 const problemCases=[['channels','Radio Channels'],['partition','Balance Tasks'],['projects','Select Projects'],['custom','Advanced QUBO']];
 const entries=[];
 function add(model,workspace,cases){
  for(const [key,name] of cases)entries.push(Object.freeze({id:entries.length+1,model,workspace,key,name}));
 }
 // Finish each model before the next: Fireworks 1–5, Spark 1.3 6–10, Wonder 11–15.
 // My data, Ask anything and Edit image have no test IDs.
 // Optional deployments never renumber the main tests.
 for(const model of coreModels){add(model,'excel',excelCases);add(model,'problems',problemCases);}
 add('muse-image-1.0','image',[['generate','Generate image']]);
 for(const model of additionalModels){add(model,'excel',excelCases);add(model,'problems',problemCases);}
 const find=(model,workspace,key)=>entries.find(e=>e.model===model&&e.workspace===workspace&&e.key===key);
 window.MetaTests=Object.freeze({
  entries:Object.freeze(entries),
  id(model,workspace,key){return find(model,workspace,key)?.id??null;},
  label(model,workspace,key,name){const test=find(model,workspace,key);return test?'Test '+test.id+'. '+name:name;}
 });
})();

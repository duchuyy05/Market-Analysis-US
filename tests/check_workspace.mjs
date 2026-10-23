// Local workbench bindings with mocked HTTP responses. No browser or API credits used.
import fs from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const html=await fs.readFile('market_radar/assets/workspace.html','utf8');
const code=await fs.readFile('market_radar/assets/workspace.js','utf8');
const config=JSON.parse(await fs.readFile('config/seasonal.json','utf8'));
const formIds=new Set([...html.match(/<form id="studyForm">([\s\S]*?)<\/form>/)[1].matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]));
const elements=new Map(),generated=new Map();
class Element {
  constructor(id){Object.assign(this,{id,value:'',checked:false,hidden:false,disabled:false,dataset:{},handlers:{},_html:'',textContent:'',style:{},classList:{toggle(){},add(){}}});}
  set innerHTML(value){this._html=value;const children=[];
    for(const tag of value.matchAll(/<(button|input)\b([^>]*)>/g)){
      const e=new Element('generated');for(const attr of tag[2].matchAll(/data-([\w-]+)="([^"]*)"/g))e.dataset[attr[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=attr[2];
      const val=tag[2].match(/\bvalue="([^"]*)"/);if(val)e.value=val[1];children.push(e);
    }generated.set(this.id,children);}
  get innerHTML(){return this._html;}
  addEventListener(type,fn){(this.handlers[type]??=[]).push(fn);}
  setAttribute(k,v){this[k]=v;}
  scrollIntoView(){}
  showModal(){this.open=true;}
  close(){this.open=false;}
  querySelectorAll(){return this.id==='studyForm' ? [...elements.values()].filter(e=>formIds.has(e.id)) : [];}
  async fire(type){for(const fn of this.handlers[type]||[])await fn({target:this,preventDefault(){}});}
}
for(const tag of html.matchAll(/<[^>]*\bid="([^"]+)"[^>]*>/g)){
  const e=new Element(tag[1]);e.hidden=/\bhidden\b/.test(tag[0]);const val=tag[0].match(/\bvalue="([^"]*)"/);if(val)e.value=val[1];elements.set(e.id,e);
}
const get=id=>{assert.ok(elements.has(id),'Shell element exists: '+id);return elements.get(id);};
for(const [k,v] of Object.entries({presetSelect:'custom',quarterSelect:'4',sampleSize:'2',topCount:'5',requestBudget:'56',supplementBudget:'12'}))get(k).value=v;
let newStudy=null,planRequest,runRequest,reportRequest,supplementRequest,planned;
const q4={id:'seasonal-gifts-us',category:config.category,niches:config.niches.map(n=>n.name),months:[10,11,12],years:config.years,as_of_date:config.as_of_date,products:22,reviews:80,ready:true,status:'completed',config};
q4.report={available:true,current:true,mode:'deterministic_source_backed_no_llm',llm:null,generated_at_utc:'2026-10-22T13:00:00Z'};
q4.exports=[{filename:'monthly_top5.csv',title:'Sản phẩm theo tháng',description:'Top sản phẩm',rows:15},{filename:'reviews.csv',title:'Nhận xét',description:'Nội dung khách hàng',rows:80},{filename:'../private.csv',title:'Invalid',rows:0}];
q4.summary={products:22,reviews:80,keywords:12,web_sources:23,reviewed_products:10,missing_prices:1,median_price_usd:9.99,
  price_bins:[{label:'Under 10',count:13},{label:'10-20',count:5},{label:'20-30',count:3},{label:'30+',count:0}],
  groups:[{name:'Halloween',products:10,reviewed_products:5,reviews:40},{name:'Thanksgiving',products:4,reviewed_products:1,reviews:8},{name:'Christmas',products:8,reviewed_products:4,reviews:32}]};
const fetch=async(path,options={})=>({ok:true,json:async()=>{
  if(path==='/api/bootstrap')return {token:'test-token',today:'2026-10-22',studies:[q4],presets:[],keys:{OPENROUTER_API_KEY:true,SERPAPI_API_KEY:true},model:'test:free',jobs:[]};
  if(path==='/api/studies')return newStudy?[q4,newStudy]:[q4];
  if(path==='/api/supplement'){
    supplementRequest=JSON.parse(options.body);
    return {id:'supplement-test',kind:'supplement',study_id:q4.id,status:'queued',stage:'queued',logs:[]};
  }
  if(path==='/api/jobs/supplement-test'){
    q4.summary.full_reviews=88;q4.summary.review_excerpts=99;
    return {id:'supplement-test',kind:'supplement',study_id:q4.id,status:'completed',stage:'done',message:'Supplement ready',logs:[]};
  }
  if(path==='/api/report'){
    reportRequest=JSON.parse(options.body);
    return {id:'report-test',kind:'report',study_id:reportRequest.study_id,status:'queued',stage:'queued',logs:[]};
  }
  if(path==='/api/jobs/report-test'){
    q4.report={available:true,current:true,mode:'rules_plus_llm',ai_input_available:true,llm:{model:'test:free',insight_count:6,created_at_utc:'2026-10-22T14:00:00Z'},generated_at_utc:'2026-10-22T14:00:01Z'};
    return {id:'report-test',kind:'report',study_id:'seasonal-gifts-us',status:'completed',stage:'done',message:'Report ready',logs:[]};
  }
  if(path==='/api/plan'){
    planRequest=JSON.parse(options.body);planned={...structuredClone(config),category:planRequest.topic,months:planRequest.months,years:planRequest.years,top_n:5,max_serpapi_requests:56};
    return {id:'plan-test',kind:'plan',status:'queued',progress:0};
  }
  if(path==='/api/jobs/plan-test')return {id:'plan-test',kind:'plan',status:'completed',progress:100,result:{config:planned,planning:{mode:'manual',warnings:[]}}};
  if(path==='/api/run'){
    runRequest=JSON.parse(options.body);newStudy={...q4,id:'new-q1-study',category:runRequest.config.category,months:runRequest.config.months,config:runRequest.config};
    return {id:'run-test',kind:'run',status:'queued',progress:0};
  }
  if(path==='/api/jobs/run-test')return {id:'run-test',kind:'run',study_id:'new-q1-study',status:'completed',stage:'done',progress:100,message:'Done',logs:[]};
  throw new Error('Unexpected route '+path);
}});
const document={getElementById:get,querySelectorAll:selector=>{
  const k=selector.match(/^\[data-([\w-]+)\]$/)?.[1]?.replace(/-([a-z])/g,(_,c)=>c.toUpperCase());
  return k?[...generated.values()].flat().filter(e=>k in e.dataset):[];
},createElement:()=>new Element('anchor')};
const window={location:{origin:'http://127.0.0.1:8765'},listeners:{},addEventListener(type,fn){this.listeners[type]=fn;}};
get('resultFrame').contentWindow={};
const context=vm.createContext({document,window,fetch,localStorage:{getItem(){return null;},setItem(){}},structuredClone,console,Map,Set,Number,String,Math,JSON,Date,Intl,URL,Blob,setTimeout,clearTimeout});
vm.runInContext(code,context,{timeout:5000});
const settle=()=>new Promise(resolve=>setTimeout(resolve,20));
await settle();
assert.equal(get('resultTitle').textContent,config.category);
assert.match(get('resultFrame').src,/seasonal-gifts-us\/dashboard.html/);
assert.match(get('librarySummary').innerHTML,/80/);
assert.match(get('librarySummary').innerHTML,/12/);
assert.match(get('priceChart').innerHTML,/13 sản phẩm/);
assert.match(get('coverageChart').innerHTML,/5\/10 sản phẩm/);
assert.equal(get('productsCSV').href,'/runs/seasonal-gifts-us/products.csv');
assert.equal(get('reportPanel').hidden,false);
assert.equal(get('reportStatus').textContent,'Chưa có phân tích AI');
assert.equal(get('downloadReportHTML').href,'/runs/seasonal-gifts-us/report.html?download=1');
assert.equal(get('downloadReportMD').href,'/runs/seasonal-gifts-us/report.md?download=1');
assert.equal(get('printReport').href,'/runs/seasonal-gifts-us/report.html?print=1');
assert.equal(get('csvDownloads').hidden,false);
assert.equal(get('csvFileCount').textContent,'2 file trong nghiên cứu này');
assert.match(get('csvFileList').innerHTML,/href="\/runs\/seasonal-gifts-us\/monthly_top5.csv" download="monthly_top5.csv"/);
assert.match(get('csvFileList').innerHTML,/80 dòng dữ liệu/);
assert.ok(!get('csvFileList').innerHTML.includes('private.csv'));
const heightMessage={data:{type:'market-analysis:height',height:4302},source:get('resultFrame').contentWindow,origin:window.location.origin};
window.listeners.message({...heightMessage,origin:'https://unrelated.example'});
assert.notEqual(get('resultFrame').style.height,'4302px');
window.listeners.message(heightMessage);
assert.equal(get('resultFrame').style.height,'4302px');
window.listeners.message({...heightMessage,data:{type:'market-analysis:height',height:-1}});
assert.equal(get('resultFrame').style.height,'4302px');
vm.runInContext("updateJob({kind:'report',study_id:'seasonal-gifts-us',status:'running',stage:'writing',logs:[]})",context);
assert.equal((get('jobSteps').innerHTML.match(/<li /g)||[]).length,2,'Report-only task has no source collection step');
assert.equal(get('aiReportButton').disabled,true);
assert.equal(get('reportStatus').textContent,'Đang viết phân tích AI');
vm.runInContext("updateJob({kind:'report',status:'completed',stage:'done',logs:[]})",context);
await get('aiReportButton').fire('click');await settle();
assert.deepEqual(reportRequest,{study_id:'seasonal-gifts-us'});
assert.equal(get('reportStatus').textContent,'Đã có phân tích AI');
assert.match(get('reportModel').textContent,/test:free/);
assert.equal(get('aiReportFiles').hidden,false);
assert.equal(get('aiInsightsLink').hidden,false);
assert.equal(get('aiReportButton').disabled,false);
vm.runInContext("updateJob({kind:'report',status:'completed_with_warnings',stage:'done',result:{llm_updated:false},warnings:['HTTP 429'],logs:[]})",context);
assert.equal((get('jobSteps').innerHTML.match(/class=\"failed\"/g)||[]).length,1,'AI failure is not shown as a completed writing step');
assert.equal((get('jobSteps').innerHTML.match(/class=\"complete\"/g)||[]).length,1,'The source-backed report is still exported');
const detailMessage={data:{type:'market-analysis:product',product:{asin:'B0F831L31B',product_name:'<script>bad</script>',source_url:'javascript:bad'}},source:get('resultFrame').contentWindow,origin:window.location.origin};
window.listeners.message({...detailMessage,origin:'https://unrelated.example'});
assert.notEqual(get('productModal').open,true,'Ignore other origins');
window.listeners.message({...detailMessage,source:{}});
assert.notEqual(get('productModal').open,true,'Only accept messages from the results iframe');
window.listeners.message(detailMessage);
assert.equal(get('productModal').open,true,'Product dialog opens in the top-level workbench');
assert.ok(get('productModalBody').innerHTML.includes('&lt;script&gt;'));
assert.ok(!get('productModalBody').innerHTML.includes('<script>'));
assert.ok(!get('productModalBody').innerHTML.includes('href="javascript:'));
await get('closeProductModal').fire('click');assert.equal(get('productModal').open,false);
vm.runInContext("updateJob({kind:'plan',status:'running',stage:'planning',logs:[]})",context);
assert.equal((get('jobSteps').innerHTML.match(/<li /g)||[]).length,1,'Preparing keywords is a single step, not a fake collection pipeline');
assert.ok(get('jobSteps').innerHTML.includes('Đang làm'));
vm.runInContext("updateJob({kind:'run',status:'failed',stage:'failed',failed_stage:'building',logs:[]})",context);
assert.equal((get('jobSteps').innerHTML.match(/class=\"complete\"/g)||[]).length,1);
assert.equal((get('jobSteps').innerHTML.match(/class=\"failed\"/g)||[]).length,1);
vm.runInContext("updateJob({kind:'run',status:'completed',stage:'done',logs:[]})",context);
await get('supplementButton').fire('click');await settle();
assert.deepEqual(supplementRequest,{study_id:q4.id,max_requests:12});
assert.match(get('librarySummary').innerHTML,/88/);
assert.match(get('librarySummary').innerHTML,/99/);
assert.match(get('jobSteps').innerHTML,/Lấy thêm nhãn mua và nhận xét Amazon/);
assert.equal(get('supplementButton').disabled,false);
q4.summary.full_reviews=89;
await get('refreshLibrary').fire('click');await settle();
assert.match(get('librarySummary').innerHTML,/89/,'Manual refresh updates the selected study, not only library cards');
await get('createTab').fire('click');assert.equal(get('createView').hidden,false);
get('topicInput').value='Desk organizers';get('keywordsInput').value='desk organizer';get('quarterSelect').value='1';
await get('refreshLibrary').fire('click');await settle();
assert.equal(get('createView').hidden,false,'Refreshing results preserves the user\'s current screen');
assert.equal(get('topicInput').value,'Desk organizers','Refreshing results does not reset an unfinished form');
await get('quarterSelect').fire('change');await get('studyForm').fire('change');
await get('studyForm').fire('submit');await settle();
assert.deepEqual(planRequest.months,[1,2,3]);assert.equal(get('planPanel').hidden,false);
await get('runButton').fire('click');await settle();
assert.deepEqual(runRequest.config.months,[1,2,3]);assert.match(get('resultFrame').src,/new-q1-study\/dashboard.html/);
assert.equal(get('resultTitle').textContent,'Desk organizers');
const q4button=document.querySelectorAll('[data-study]').find(e=>e.dataset.study==='seasonal-gifts-us');
await q4button.fire('click');assert.match(get('resultFrame').src,/seasonal-gifts-us\/dashboard.html/);
console.log('Workspace logic passed: CSV file choices/downloads, embedded height validation, AI report action/status/exports, summaries, parent product dialog, processing steps, Q4/Q1 switching and background jobs.');

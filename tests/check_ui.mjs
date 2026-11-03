// DOM event checks without a browser or third-party dependencies. HTTP tests
// separately verify that the browser receives executable JavaScript MIME types.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/market_research/ui/assets/app.js', import.meta.url), 'utf8');
const html = readFileSync(new URL('../src/market_research/ui/assets/index.html', import.meta.url), 'utf8');
const stages = [['understand', 'Hiểu mô tả'], ['history', 'Lịch sử và dự báo'], ['report', 'Dựng báo cáo']];
const saved = {run_id: 'example-q4', status: 'partial', mode: 'offline', summary: {category: 'Q4'}, has_report: true};
const completed = {run_id: 'new-q4', status: 'partial', mode: 'offline', summary: {category: 'Q4'}, has_report: true, files: ['report.html', 'report.md', 'catalog.html', 'dataset.json'], stages: Object.fromEntries(stages.map(([id]) => [id, {status: 'complete'}]))};

function element(id = '') {
  return {
    id, value: '', checked: false,
    disabled: ['start', 'demo', 'refresh'].includes(id),
    hidden: ['run-panel', 'preview-panel'].includes(id),
    textContent: '', children: [], listeners: {},
    append(...items) { this.children.push(...items); },
    replaceChildren(...items) { this.children = items; },
    addEventListener(event, action) { this.listeners[event] = action; },
    setAttribute(name, value) { this[name] = value; },
    getAttribute(name) { return this[name]; },
    scrollIntoView() { this.scrolled = true; },
  };
}

function harness(fetcher) {
  const elements = Object.fromEntries([...html.matchAll(/\bid="([^"]+)"/g)].map(([, id]) => [id, element(id)]));
  const context = vm.createContext({
    document: {getElementById: id => elements[id], createElement: () => element()},
    fetch: fetcher, AbortController, Intl, Date, URLSearchParams,
    // Polling is driven explicitly by the tests; API calls are bounded by the runner.
    setTimeout: () => 1, clearTimeout: () => {},
  });
  vm.runInContext(source, context, {filename: 'app.js'});
  return {elements, context};
}

async function until(condition, timeout = 15000) {
  const deadline = Date.now() + timeout;
  while (!condition()) {
    assert.ok(Date.now() < deadline, 'UI did not reach the expected state');
    await new Promise(resolve => setTimeout(resolve, 10));
  }
}

function mockApi(postError, initialRun = completed, capabilities = {seasonal_history:true,company_domain:true,design_month_screening:true,manufacturing_models:true,design_content:true,exa_discovery:true}, keys={SERPAPI_API_KEY:true}) {
  const posts = [];
  const requests = [];
  let created = false;
  const run = {...initialRun};
  const products = [
    {product_id:'P-expensive',title:'Expensive sample',price:10,currency:'USD',source:'amazon',rating:5,review_count:10,run_id:'new-q4',url:'https://amazon.com/dp/B012345678',saved:false},
    {product_id:'P-cheap',title:'Cheap sample',price:2,currency:'USD',source:'shopping',rating:5,review_count:100,run_id:'new-q4',url:'https://shop.test/item',saved:false},
  ];
  const fetcher = async (path, options = {}) => {
    let body;
    if (options.method === 'POST') {
      const input=JSON.parse(options.body); posts.push(input); requests.push({path,body:input});
      if (postError) return {ok: false, json: async () => ({error: postError})};
      if(path.endsWith('/stop')) {run.status='cancelled';run.can_stop=false;body={run_id:run.run_id,status:'cancelled'};}
      else if(path==='/api/workspace/save') {products.find(p=>p.product_id===input.product_id).saved=input.saved;body={saved:input.saved};}
      else if(path.endsWith('/editor')) body={saved:true,updated_at:'2026-10-28T00:00:00Z',url:'/outputs/new-q4/report-edited.html'};
      else {created=true;body = {run_id: run.run_id};}
    } else if (path === '/api/settings') body = {stages, keys, capabilities, limits: {serpapi_requests:17,tavily_requests:2,llm_requests:4,directions_per_niche:1,top_keywords:10}};
    else if (path === '/api/runs') body = created?[run,saved]:[saved];
    else if(path.endsWith('/editor')) body={title:'Original report',content:'# Original report\nBody',edited:false};
    else if(path.startsWith('/api/products?')) {
      const query=new URLSearchParams(path.split('?')[1]); let items=[...products];
      const rules=query.has('sorts')?JSON.parse(query.get('sorts')):[{field:query.get('sort'),order:query.get('order')}];
      for(const rule of [...rules].reverse()) if(['price','rating','review_count'].includes(rule.field)) items.sort((a,b)=>(a[rule.field]-b[rule.field])*(rule.order==='desc'?-1:1));
      if(query.get('saved')==='1') items=items.filter(p=>p.saved);
      body={items,total:items.length,page:1,page_size:40,saved_count:products.filter(p=>p.saved).length};
    } else if(path.includes('/stages/')) {const stage=path.split('/').at(-1);body={stage,label:'Chi tiết '+stage,status:run.stages?.[stage]?.status||'complete',summary:{keywords:['candle warmer','photo ornament']},logs:[{at:'2026-10-29T00:00:00Z',event:'llm_response',message:'Đã nhận keyword',details:{keywords:['candle warmer']}}]};}
    else body = run;
    return {ok: true, json: async () => body};
  };
  return {fetcher, posts, requests};
}

test('initialization loads saved runs and enables the form', async () => {
  const {elements: ui} = harness(mockApi().fetcher);
  await until(() => !ui.start.disabled);
  assert.equal(ui.library.children.length, 1);
  assert.equal(ui.library.children[0].children[0].textContent, 'Q4');
  assert.equal(ui.progress.max, stages.length);
  assert.equal(Number(ui.budget.value), 17);
  assert.equal(Number(ui['tavily-budget'].value), 2);
  assert.equal(Number(ui['llm-budget'].value), 4);
  assert.equal(Number(ui['top-keywords'].value), 10);
  assert.equal(ui.notice.hidden, true);
});

test('November design research submits a separate exact analysis year and keeps screening active', async () => {
  const api=mockApi(),{elements:ui}=harness(api.fetcher);await until(()=>!ui.start.disabled);
  ui.brief.value='Tháng 11 nên in áo ca sĩ nào?';ui.cutoff.value='2026-11-02';
  ui['analysis-year'].value='2026';ui['history-months'].value='11';ui['history-months'].listeners.input();
  assert.match(ui['history-scope-help'].textContent,/Sàng lọc từng mẫu trong năm 2026/);
  assert.doesNotMatch(ui['request-estimate'].textContent,/bỏ sàng lọc/);
  ui['research-form'].listeners.submit({preventDefault(){}});await until(()=>api.posts.length===1);
  assert.equal(api.posts[0].trends.analysis_year,2026);
  assert.deepEqual(api.posts[0].trends.history_months,[11]);
  assert.equal(api.posts[0].sources.trends,true);
  assert.equal(api.posts[0].discovery.focus,'designs');
  assert.deepEqual(api.posts[0].history_years,[2023,2024,2025]);
});

test('a future analysis year is rejected before a research request', async () => {
  const api=mockApi(),{elements:ui}=harness(api.fetcher);await until(()=>!ui.start.disabled);
  ui.brief.value='Gift wrap patterns';ui.cutoff.value='2026-11-02';ui['analysis-year'].value='2027';
  ui['research-form'].listeners.submit({preventDefault(){}});
  assert.equal(api.posts.length,0);assert.match(ui.notice.textContent,/Năm phân tích Trends/);
});

test('discovery focus switches between design content and physical models without narrowing categories',async()=>{
  for(const focus of ['designs','models','auto']){
    const api=mockApi(),{elements:ui}=harness(api.fetcher);await until(()=>!ui.start.disabled);
    ui.brief.value='Tìm mẫu móc khóa, áo và lịch';ui.cutoff.value='2026-11-02';ui['discovery-focus'].value=focus;
    ui['research-form'].listeners.submit({preventDefault(){}});await until(()=>api.posts.length===1);
    assert.equal(api.posts[0].discovery.focus,focus);assert.ok(api.posts[0].business.categories.length>1);
  }
});

test('content discovery shows missing source coverage instead of implying every candidate is sourced',async()=>{
  const {context,elements:ui}=harness(mockApi().fetcher);await until(()=>!ui.start.disabled);
  context.renderDiscovery({discovery_overview:{research_focus:{content_focus:'designs'},coverage:{source_content_candidates:1,hypothesis_candidates:4,content_coverage:[{name:'Áo',source_candidates:0}]},rows:[]}});
  assert.match(ui['discovery-note'].textContent,/1 keyword có nguồn/);assert.match(ui['discovery-note'].textContent,/4 giả thuyết/);assert.match(ui['discovery-note'].textContent,/Chưa tìm.*Áo/);
});

test('Exa can run discovery with Tavily disabled and submits its own cap',async()=>{
  const api=mockApi(),{elements:ui}=harness(api.fetcher);await until(()=>!ui.start.disabled);
  ui.brief.value='Tìm hình in áo và móc khóa';ui['tavily-budget'].value='0';ui['exa-budget'].value='3';ui['web-provider'].value='exa';
  ui['research-form'].listeners.submit({preventDefault(){}});await until(()=>api.posts.length===1);
  assert.equal(api.posts[0].limits.exa_requests,3);assert.equal(api.posts[0].limits.tavily_requests,0);
  assert.equal(api.posts[0].discovery.web_provider,'exa');assert.equal(api.posts[0].sources.web,true);
});

test('both configured keys select combined discovery and reconnect preserves the users choice',async()=>{
  const api=mockApi(null,completed,undefined,{TAVILY_API_KEY:true,EXA_API_KEY:true}),{elements:ui,context}=harness(api.fetcher);await until(()=>!ui.start.disabled);
  assert.equal(ui['web-provider'].value,'combined');assert.match(ui['web-provider-status'].textContent,/Exa: đã có key/);
  ui['web-provider'].value='auto';await context.initializeApplication();
  assert.equal(ui['web-provider'].value,'auto');
});

test('credit economy preset saves requests without changing caps dates or company scope and makes no API call',async()=>{
  const api=mockApi(),{elements:ui}=harness(api.fetcher);await until(()=>!ui.start.disabled);
  ui.brief.value='Tìm mẫu lịch và áo';ui['analysis-year'].value='2025';ui['history-months'].value='7';ui['history-months'].listeners.input();
  ui['budget'].value='7';ui['tavily-budget'].value='0';ui['exa-budget'].value='2';
  ui['business-apparel'].checked=true;ui['business-keychains'].checked=false;
  ui['credit-economy-preset'].onclick();
  assert.equal(api.posts.length,0);assert.equal(ui.brief.value,'Tìm mẫu lịch và áo');assert.equal(ui['analysis-year'].value,'2025');
  assert.equal(ui['history-months'].value,'7');assert.equal(ui['business-keychains'].checked,false);
  assert.equal(ui['budget'].value,'7');assert.equal(ui['tavily-budget'].value,'0');assert.equal(ui['exa-budget'].value,'2');
  assert.equal(ui['candidate-keywords'].value,'16');assert.equal(ui['top-keywords'].value,'5');
});

test('month screening displays observed days instead of inventing 28 day growth', async () => {
  const api=mockApi(),{elements:ui,context}=harness(api.fetcher);await until(()=>!ui.start.disabled);
  context.renderDiscovery({discovery_overview:{selection_basis:'selected_month_observations',rows:[{keyword:'star print wrapping paper',relative_interest:2,observed_days:2,score:80,rank:1,selected:true}]}});
  assert.equal(ui['screen-growth-heading'].textContent,'Ngày đã quan sát');
  assert.equal(ui['screening-rows'].children[0].children[2].textContent,'2');
});

test('resolved stage errors stay in history without appearing as current warnings', async () => {
  const {context,elements:ui}=harness(mockApi().fetcher);
  await until(()=>!ui.start.disabled);
  context.renderWarnings({warnings:[],errors:[{stage:'understand',message:'Old empty response'}],stages:{understand:{status:'complete'}}});
  assert.equal(ui['warnings-panel'].hidden,true);
  context.renderWarnings({warnings:[],errors:[{stage:'understand',message:'Current empty response'}],stages:{understand:{status:'failed',error:'Current empty response'}}});
  assert.equal(ui['warnings-panel'].hidden,false);
});

test('historical comparison windows are editable, removable and submitted as independent ranges', async () => {
  const api=mockApi();const {elements:ui}=harness(api.fetcher);
  await until(()=>!ui.start.disabled);ui.brief.value='Quà Noel';ui.cutoff.value='2026-10-29';
  ui['comparison-q4'].onclick();
  assert.equal(ui['comparison-periods'].children.length,3);
  const first=ui['comparison-periods'].children[0];
  assert.equal(first.children[1].children[0].value,'2023-10');
  assert.equal(first.children[2].children[0].value,'2023-12');
  await ui['comparison-periods'].children[2].children[3].onclick();
  assert.equal(ui['comparison-periods'].children.length,2);
  ui['research-form'].listeners.submit({preventDefault(){}});
  await until(()=>api.posts.length===1&&!ui.start.disabled);
  assert.deepEqual(api.posts[0].comparison_periods,[{start:'2023-10',end:'2023-12'},{start:'2024-10',end:'2024-12'}]);
  ui['comparison-annual'].onclick();assert.equal(ui['comparison-periods'].children.length,0);
});

test('future comparison months are rejected before provider work starts', async () => {
  const api=mockApi();const {elements:ui}=harness(api.fetcher);
  await until(()=>!ui.start.disabled);ui.brief.value='Quà';ui.cutoff.value='2024-10-29';ui['comparison-q4'].onclick();
  ui['research-form'].listeners.submit({preventDefault(){}});
  assert.equal(api.posts.length,0);assert.match(ui.notice.textContent,/không sau tháng/);
});

test('2021 preset submits explicit history years, target year and matching Q4 windows', async () => {
  const api=mockApi();const {elements:ui}=harness(api.fetcher);
  await until(()=>!ui.start.disabled);ui.brief.value='Gifts';ui.cutoff.value='2026-10-29';
  ui['history-2021-preset'].onclick();ui['comparison-q4'].onclick();
  assert.equal(ui['comparison-periods'].children.length,5);
  ui['research-form'].listeners.submit({preventDefault(){}});
  await until(()=>api.posts.length===1&&!ui.start.disabled);
  assert.deepEqual(api.posts[0].history_years,[2021,2022,2023,2024,2025]);
  assert.equal(api.posts[0].target_year,2026);
  assert.equal(api.posts[0].comparison_periods[0].start,'2021-10');
});

test('invalid history range and target are rejected before submission', async () => {
  const api=mockApi();const {elements:ui}=harness(api.fetcher);
  await until(()=>!ui.start.disabled);ui.brief.value='Gifts';ui.cutoff.value='2026-10-29';
  for(const [start,end,target] of [['2020','2026','2027'],['2021','2026','2027'],['2025','2021','2026'],['2021','2025','2025']]) {
    ui['history-start'].value=start;ui['history-end'].value=end;ui['forecast-year'].value=target;
    ui['research-form'].listeners.submit({preventDefault(){}});assert.equal(api.posts.length,0);
    assert.equal(ui.notice.hidden,false);
  }
});

test('collection year and month controls are visible before advanced settings', () => {
  const form=html.slice(html.indexOf('<form id="research-form"'),html.indexOf('</form>'));
  const visible=form.slice(0,form.indexOf('<details>'));
  for(const id of ['history-year-mode','history-start','history-end','forecast-year','history-years-custom','history-month-options']){
    assert.ok(visible.includes(`id="${id}"`),`${id} must not be buried in advanced settings`);
    assert.equal([...form.matchAll(new RegExp(`id="${id}"`,'g'))].length,1);
  }
});

test('custom years and month checkboxes submit exact selected scope and update costs', async () => {
  const api=mockApi(),{elements:ui}=harness(api.fetcher);await until(()=>!ui.start.disabled);
  ui.brief.value='Printed Christmas gifts';ui.cutoff.value='2026-10-30';
  ui['history-year-mode'].value='custom';ui['history-year-mode'].listeners.change();
  assert.equal(ui['history-year-range'].hidden,true);assert.equal(ui['history-year-custom'].hidden,false);
  assert.equal(ui['history-start'].disabled,true);assert.equal(ui['forecast-year'].disabled,false);
  ui['history-years-custom'].value='2025,2021,2023,2023';ui['history-years-custom'].listeners.change();
  ui['history-month-11'].checked=false;ui['history-month-11'].listeners.change();
  assert.equal(ui['history-months'].value,'10,12');
  assert.match(ui['history-scope-help'].textContent,/2021, 2023, 2025\. 6 cửa sổ/);
  assert.match(ui['history-help'].textContent,/Năm không liên tiếp/);
  ui['seasonal-economy-preset'].onclick();
  assert.equal(ui['history-months'].value,'10,12');assert.match(ui['request-estimate'].textContent,/Lịch sử 10 keyword: khoảng 18 lượt SerpApi/);
  ui['comparison-q4'].onclick();
  assert.equal(ui['comparison-periods'].children.length,3);
  // Q4 summaries include November, outside this selection: clear them before
  // submitting rather than silently widening the actual collection scope.
  ui['comparison-annual'].onclick();assert.equal(api.posts.length,0);
  await ui['research-form'].listeners.submit({preventDefault(){}});await until(()=>api.posts.length===1);
  assert.deepEqual(api.posts[0].history_years,[2021,2023,2025]);
  assert.deepEqual(api.posts[0].trends.history_months,[10,12]);
});

test('typed months, quick choices and full mode keep month selection synchronized', async () => {
  const api=mockApi(),{elements:ui}=harness(api.fetcher);await until(()=>!ui.start.disabled);
  ui['history-months'].value='12,10,10';ui['history-months'].listeners.input();
  assert.equal(ui['history-month-10'].checked,true);assert.equal(ui['history-month-11'].checked,false);assert.equal(ui['history-month-12'].checked,true);
  ui['history-scope'].value='full';ui['history-scope'].listeners.change();
  for(let month=1;month<=12;month++){assert.equal(ui['history-month-'+month].checked,true);assert.equal(ui['history-month-'+month].disabled,true);}
  ui['history-scope'].value='seasonal';ui['history-scope'].listeners.change();
  assert.equal(ui['history-month-11'].checked,false);assert.equal(ui['history-month-11'].disabled,false);
  assert.match(ui['monthly-enabled-label'].textContent,/các tháng đã chọn/);
  ui['history-months-all'].onclick();for(let month=1;month<=12;month++)assert.equal(ui['history-month-'+month].checked,true);
  ui['history-months-q4'].onclick();assert.equal(ui['history-months'].value,'10,11,12');assert.equal(api.posts.length,0);
});

test('invalid custom years and empty month choices do not start research', async () => {
  const api=mockApi(),{elements:ui}=harness(api.fetcher);await until(()=>!ui.start.disabled);
  ui.brief.value='Manufactured gifts';ui.cutoff.value='2026-10-30';ui['history-year-mode'].value='custom';
  for(const years of ['2025','2025,2025','2003,2025','2021,2026','2021,2022,2023,2024,2025,2019,2020','2021,,2025','2021.5,2025']){
    ui['history-years-custom'].value=years;await ui['research-form'].listeners.submit({preventDefault(){}});
    assert.equal(api.posts.length,0);assert.equal(ui.notice.hidden,false);
  }
  ui['history-years-custom'].value='2021,2023,2025';
  for(let month=1;month<=12;month++)ui['history-month-'+month].checked=false;
  ui['history-month-12'].listeners.change();assert.equal(ui['history-months'].value,'');
  await ui['research-form'].listeners.submit({preventDefault(){}});
  assert.equal(api.posts.length,0);assert.match(ui.notice.textContent,/tháng lấy dữ liệu/);
});

test('generated PDF is a direct download when the run exposes it', async () => {
  const api=mockApi(null,{...completed,files:[...completed.files,'report.pdf']});
  const {elements:ui}=harness(api.fetcher);
  await until(()=>!ui.demo.disabled);await ui.demo.onclick();
  const pdf=ui.actions.children.find(item=>item.href?.endsWith('/report.pdf'));
  assert.ok(pdf);assert.equal(pdf.download,'report.pdf');
  assert.ok(ui.files.children.some(item=>item.href?.endsWith('/report.pdf')));
});

test('historical quality panel displays measured coverage and errors without inventing accuracy', async () => {
  const api=mockApi(null,{...completed,input:{history_years:[2021,2022,2023,2024,2025],target_year:2026},
    historical_overview:[{direction_id:'D1',measurement_query:'photo ornament',usable_years:[2021,2022,2023,2024,2025],
      metrics:{mae:3,wape_pct:12},baseline_metrics:{mae:2},confidence:{level:'limited',coverage_pct:100,fold_count:3,reasons:['Model error exceeds baseline']}}]});
  const {elements:ui}=harness(api.fetcher);await until(()=>!ui.demo.disabled);await ui.demo.onclick();
  assert.equal(ui['quality-panel'].hidden,false);
  assert.equal(ui['quality-rows'].children[0].children[0].textContent,'photo ornament');
  assert.equal(ui['quality-rows'].children[0].children[4].textContent,'3 / 2');
  assert.match(ui['quality-reasons'].children[0].textContent,/Model error exceeds baseline/);
  assert.match(ui['quality-note'].textContent,/2021, 2022, 2023, 2024, 2025/);
});

test('stage boxes open bounded result/log detail and close without starting work', async () => {
  const api=mockApi();const gets=[];
  const fetcher=(path,options)=>{if(path.includes('/stages/'))gets.push(path);return api.fetcher(path,options);};
  const {elements:ui,context}=harness(fetcher);
  await until(()=>!ui.demo.disabled);await ui.demo.onclick();
  assert.equal(gets.length,0);
  await ui.steps.children[0].children[0].onclick();
  assert.equal(ui['stage-detail'].hidden,false);
  assert.match(ui['stage-summary'].textContent,/candle warmer/);
  assert.equal(ui['stage-logs'].children[0].children[1].textContent,'Đã nhận keyword');
  assert.deepEqual(gets,['/api/runs/new-q4/stages/understand']);
  await vm.runInContext('refreshStatus()',context);
  assert.equal(gets.length,2);assert.ok(gets.every(path=>path.endsWith('/understand')));
  ui['stage-detail-close'].onclick();
  assert.equal(ui['stage-detail'].hidden,true);assert.equal(api.posts.length,1);
});

test('awaiting Trends offers retry/new-budget actions and leaves new research enabled', async () => {
  const waiting={...completed,status:'awaiting_trends',files:[],has_report:false,waiting_reason:'Chưa có phép đo sau nguồn dự phòng',stages:{understand:{status:'complete'},history:{status:'waiting'},report:{status:'waiting'}}};
  const api=mockApi(null,waiting);const {elements:ui}=harness(api.fetcher);
  await until(()=>!ui.demo.disabled);await ui.demo.onclick();
  assert.equal(ui['run-status'].textContent,'Chờ dữ liệu Trends');
  assert.match(ui['run-message'].textContent,/sau nguồn dự phòng/);
  assert.ok(ui.actions.children.some(item=>item.textContent==='Thử lại bước Trends'));
  assert.ok(ui.actions.children.some(item=>item.textContent.includes('Điều chỉnh ngân sách')));
  assert.equal(ui['preview-panel'].hidden,true);assert.equal(ui.start.disabled,false);
  assert.equal(ui.steps.children[1].children[0].children[1].textContent,'Chờ xử lý');
});

test('sparse Trends diagnosis is visible and a new study keeps the old budgets without starting requests', async () => {
  const input={brief:'Móc khóa và ví nhỏ làm quà',as_of_date:'2026-11-02',history_years:[2023,2024,2025],target_year:2026,
    limits:{serpapi_requests:30,tavily_requests:10,llm_requests:10,candidate_keywords:64,top_keywords:10,trends_serpapi_requests:8,serpapi_product_reserve:10},
    trends:{provider:'auto',history_scope:'seasonal',history_months:[10,11,12],analysis_year:null},
    business:{profile:'custom_manufacturing',categories:['keychains','gift_accessories']},sources:{trends:true,amazon:true,web:true,shopping:false}};
  const waiting={...completed,mode:'live',status:'awaiting_trends',files:[],input,waiting_reason:'Old generic wait',
    stages:{understand:{status:'complete'},screen:{status:'waiting',started_at:'2026-11-02T02:36:00Z'},monthly:{status:'waiting'}},
    screening_diagnostics:{blocked:true,measured:32,summary:'Đã đo 32/38 · 32 ít tín hiệu · 6 chưa đo · Trends 8/8.',explanation:'Keyword quá chi tiết.',action:'Sửa keyword trong lượt mới.',can_retry:true,retry_kind:'free_only',retry_hint:'Không tăng trần trả phí.'}};
  const api=mockApi(null,waiting),{elements:ui,context}=harness(api.fetcher);await until(()=>!ui.demo.disabled);await ui.demo.onclick();
  await vm.runInContext("stageNames=[['understand','Hiểu mô tả'],['screen','Sàng lọc Trends US'],['monthly','Xếp hạng tháng']];renderStages(currentRun)",context);
  assert.equal(ui['screen-diagnostic'].hidden,false);assert.match(ui['screen-diagnostic-summary'].textContent,/32\/38/);
  assert.match(ui['run-message'].textContent,/8\/8/);
  assert.equal(ui.steps.children[1].children[0].children[1].textContent,'Đã đo · Chưa đủ tín hiệu');
  assert.equal(ui.steps.children[2].children[0].children[1].textContent,'Chưa chạy · chờ sàng lọc');
  assert.ok(ui.actions.children.some(item=>item.textContent.includes('nguồn miễn phí')));
  const requests=api.posts.length;ui['screen-diagnostic-new'].onclick();
  assert.equal(api.posts.length,requests);assert.equal(ui.brief.value,input.brief);
  assert.equal(ui['budget-custom'].value,'30');assert.equal(ui['tavily-budget-custom'].value,'10');assert.equal(ui['llm-budget-custom'].value,'10');
  assert.equal(ui['trends-serp-budget'].value,'8');assert.equal(ui['candidate-keywords'].value,'64');
  assert.equal(ui['history-months'].value,'10,11,12');
});

test('Shopping estimate uses only its selected keyword cap and exposes Trends paid ceiling', async () => {
  const {elements:ui}=harness(mockApi().fetcher);await until(()=>!ui.start.disabled);
  ui['history-scope'].value='full';ui['monthly-enabled'].checked=false;ui['candidate-keywords'].value='32';
  ui['source-shopping'].checked=true;ui['shopping-keywords'].value='2';
  ui['source-shopping'].listeners.change();
  assert.match(ui['request-estimate'].textContent,/10 Amazon \+ 2 Shopping = 12 lượt/);
  assert.match(ui['request-estimate'].textContent,/Trends được dùng tối đa 7 lượt/); // total17, reserve10
  assert.match(ui['request-estimate'].textContent,/Lịch sử 10 keyword: khoảng 2 lượt SerpApi/);
  assert.match(ui['request-estimate'].textContent,/Dành trước 2 lượt trong trần Trends/);
  assert.match(ui['request-estimate'].textContent,/thấp hơn dự trù 10/);
});

test('broad monthly preset is explicit and exposes the full history budget', async () => {
  const api=mockApi(),{elements:ui}=harness(api.fetcher);await until(()=>!ui.start.disabled);
  ui['history-scope'].value='full';
  ui['broad-monthly-preset'].onclick();
  assert.equal(ui['candidate-keywords'].value,'64');assert.equal(ui['monthly-enabled'].checked,true);
  assert.equal(ui['budget-custom'].value,'50');assert.equal(ui['trends-serp-budget'].value,'34');
  assert.match(ui['request-estimate'].textContent,/Lịch sử 64 keyword: khoảng 16 lượt SerpApi/);
  assert.equal(api.posts.length,0);
});

test('seasonal presets count separate Q4 years honestly and keep discovery distinct', async () => {
  const api=mockApi(),{elements:ui}=harness(api.fetcher);await until(()=>!ui.start.disabled);
  ui['history-start'].value='2023';ui['history-end'].value='2025';ui['history-scope'].value='seasonal';ui['history-months'].value='10,11,12';
  ui['broad-monthly-preset'].onclick();
  assert.equal(ui['budget-custom'].value,'70');assert.equal(ui['trends-serp-budget'].value,'54');
  assert.match(ui['request-estimate'].textContent,/Lịch sử 64 keyword: khoảng 48 lượt SerpApi/);
  ui['seasonal-economy-preset'].onclick();
  assert.equal(ui['candidate-keywords'].value,'12');assert.equal(ui['monthly-keywords'].value,'10');assert.equal(ui['top-keywords'].value,'5');
  assert.equal(ui['budget-custom'].value,'20');assert.match(ui['request-estimate'].textContent,/Tổng dự trù 17 lượt/);
  assert.equal(api.posts.length,0);
});

test('company and Q4 settings are explicit and invalid season ranges do not submit', async () => {
  const api=mockApi(),{elements:ui}=harness(api.fetcher);await until(()=>!ui.start.disabled);
  ui.brief.value='Printed Christmas shirts and tote bags';
  await ui['research-form'].listeners.submit({preventDefault(){}});
  await until(()=>api.posts.length===1);
  assert.equal(api.posts[0].business.profile,'custom_manufacturing');assert.ok(api.posts[0].business.categories.includes('phone_accessories'));
  assert.equal(api.posts[0].trends.history_scope,'seasonal');assert.deepEqual(api.posts[0].trends.history_months,[10,11,12]);
  const other=mockApi(),h=harness(other.fetcher);await until(()=>!h.elements.start.disabled);h.elements.brief.value='Christmas gifts';
  h.elements.months.value='1,2';await h.elements['research-form'].listeners.submit({preventDefault(){}});
  assert.equal(other.posts.length,0);assert.match(h.elements.notice.textContent,/Tháng bán phải nằm/);
});

test('monthly panel changes calendar month and preserves missing keyword evidence', async () => {
  const {context,elements:ui}=harness(mockApi().fetcher);await until(()=>!ui.start.disabled);
  const run={run_id:'new-q4',files:['keyword-monthly.html','tables/keyword_monthly.csv'],monthly_overview:{note:'Mùa vụ khác nhu cầu',rows:[
    {month:1,keyword:'mug',measurement_query:'mug',seasonality_rank:1,seasonal_score:80,demand_rank:1,comparison_group:'A',comparison_label:'Anchor chung',usable_years:[2023,2024],reason:'Có hai năm',status:'available'},
    {month:1,keyword:'unknown',measurement_query:'unknown',seasonality_rank:null,seasonal_score:null,demand_rank:null,usable_years:[],reason:'Thiếu lịch sử',status:'insufficient_history'},
    {month:12,keyword:'ornament',measurement_query:'ornament',seasonality_rank:1,seasonal_score:100,demand_rank:null,usable_years:[2023,2024],reason:'Mùa Noel',status:'available'}]}};
  context.renderMonthlyKeywords(run);assert.equal(ui['monthly-table'].children.length,2);assert.match(ui['monthly-count'].textContent,/1\/2 keyword/);
  run.input={limits:{monthly_rows:1}};context.renderMonthlyKeywords(run);assert.equal(ui['monthly-table'].children.length,1);assert.equal(run.monthly_overview.rows.length,3);
  ui['monthly-month'].value='12';context.renderMonthlyKeywords(run);assert.equal(ui['monthly-table'].children.length,1);assert.equal(ui['monthly-table'].children[0].children[0].textContent,'ornament');
  assert.equal(ui['monthly-downloads'].children.length,2);
});

test('demo click shows immediate feedback, progress and report links', async () => {
  const api = mockApi();
  const {elements: ui} = harness(api.fetcher);
  await until(() => !ui.demo.disabled);
  const action = ui.demo.onclick();
  assert.equal(ui.start.disabled, true);
  assert.match(ui.notice.textContent, /Q4/);
  await action;
  assert.equal(api.posts[0].mode, 'offline');
  assert.equal(api.posts[0].llm.enabled, false);
  assert.equal(ui['run-panel'].hidden, false);
  assert.equal(ui['run-panel'].scrolled, true);
  assert.equal(ui.progress.value, stages.length);
  assert.equal(ui['preview-panel'].hidden, false);
  assert.match(ui.preview.src, /new-q4\/report\.html/);
  assert.ok(ui.actions.children.some(item => item.href?.endsWith('/report.html')));
  assert.equal(ui.start.disabled, false);
  ui['close-run'].onclick();
  assert.equal(ui['view-history'].hidden, false);
  assert.equal(ui['view-run'].hidden, true);
  assert.equal(ui.preview.src, 'about:blank');
  assert.equal(api.requests.length, 1); // Closing does not start/stop/delete a run.
  ui['nav-reports'].onclick();
  await ui['report-list'].children[0].children[3].children[0].onclick();
  assert.equal(ui['view-run'].hidden, false);
  ui['close-run'].onclick();
  assert.equal(ui['view-reports'].hidden, false);
});

test('Vietnamese brief submit sends the entered description and displays the result', async () => {
  const api = mockApi();
  const {elements: ui} = harness(api.fetcher);
  await until(() => !ui.start.disabled);
  ui.brief.value = 'quà decor giáng sinh';
  ui.budget.value = 'custom'; ui['budget-custom'].value='7';
  ui['tavily-budget'].value='0'; ui['exa-budget'].value='0'; ui['llm-budget'].value='2';
  ui['top-keywords'].value='custom';ui['top-keywords-custom'].value='7';
  let prevented = false;
  ui['research-form'].listeners.submit({preventDefault() { prevented = true; }});
  await until(() => !ui.start.disabled && api.posts.length === 1);
  assert.equal(prevented, true);
  assert.equal(api.posts[0].brief, 'quà decor giáng sinh');
  assert.equal(api.posts[0].mode, 'live');
  assert.equal(api.posts[0].limits.serpapi_requests, 7);
  assert.equal(api.posts[0].limits.tavily_requests, 0);
  assert.equal(api.posts[0].limits.llm_requests, 2);
  assert.equal(api.posts[0].limits.top_keywords, 7);
  assert.equal(api.posts[0].sources.web, false);
  assert.equal(api.posts[0].sources.shopping, false);
  assert.equal(api.posts[0].trends.provider, 'auto');
  assert.equal(api.posts[0].limits.trends_serpapi_requests, 8);
  assert.equal(api.posts[0].limits.serpapi_product_reserve, 10);
  assert.equal(api.posts[0].limits.shopping_keywords, 2);
  assert.equal(api.posts[0].sources.trends, true);
  assert.equal(api.posts[0].limits.free_trends_requests, 40);
  assert.equal(ui['preview-panel'].hidden, false);
});

test('source choices and free Trends are independent from a zero SerpApi budget', async () => {
  const api=mockApi();const {elements:ui}=harness(api.fetcher);
  await until(()=>!ui.start.disabled);
  ui.brief.value='Quà cuối năm';ui.budget.value='0';ui['free-trends-budget'].value='8';ui['candidate-keywords'].value='12';ui['product-details'].value='0';
  ui['trends-provider'].value='free';
  for(const site of ['tiktok','facebook','etsy','walmart','pinterest','ebay'])ui['source-'+site].checked=site==='etsy';
  ui['research-form'].listeners.submit({preventDefault(){}});
  await until(()=>api.posts.length===1&&!ui.start.disabled);
  const posted=api.posts[0];
  assert.equal(posted.sources.amazon,false);assert.equal(posted.sources.trends,true);assert.equal(posted.trends.provider,'free');
  assert.equal(posted.limits.free_trends_requests,8);assert.equal(posted.limits.candidate_keywords,12);assert.deepEqual(posted.discovery.sites,['etsy']);
});

test('screening view labels measured and unverified selections and links public pages', async () => {
  const result={...completed,discovery_overview:{note:'Measured within candidates',sources:[{sites:['etsy'],status:'available',count:1}],pages:[{title:'Warm light',url:'https://etsy.com/listing/1',platform:'etsy'}],rows:[{keyword:'candle warmer',relative_interest:2,growth_pct:10,score:80,rank:1,selected:true},{keyword:'other gift',relative_interest:null,growth_pct:null,score:null,rank:null,selected:true}]}};
  const {elements:ui}=harness(mockApi(null,result).fetcher);
  await until(()=>!ui.demo.disabled);await ui.demo.onclick();
  assert.equal(ui['discovery-panel'].hidden,false);assert.equal(ui['screening-rows'].children.length,2);
  assert.match(ui['screening-rows'].children[1].children[4].textContent,/chưa xác minh/);
  assert.equal(ui['discovery-links'].children[0].href,'https://etsy.com/listing/1');
});

test('submission errors stay visible and buttons allow another attempt', async () => {
  const {elements: ui} = harness(mockApi('Thiếu cấu hình nguồn').fetcher);
  await until(() => !ui.demo.disabled);
  await ui.demo.onclick();
  assert.equal(ui.notice.hidden, false);
  assert.match(ui.notice.textContent, /Thiếu cấu hình nguồn/);
  assert.equal(ui.start.disabled, false);
  assert.equal(ui['run-panel'].hidden, true);
});

test('initialization errors are visible and the form stays disabled', async () => {
  const {elements: ui} = harness(async () => { throw new Error('Không kết nối được'); });
  await until(() => ui.notice.textContent.includes('Không khởi tạo'));
  assert.equal(ui.notice.hidden, false);
  assert.equal(ui.start.disabled, true);
  assert.equal(ui.demo.disabled, true);
});

test('stale backend is detected before a new Trends configuration can be submitted', async () => {
  for(const capabilities of [null,{}, {seasonal_history:false,company_domain:true}, {seasonal_history:true,company_domain:false}, {seasonal_history:true,company_domain:true,design_month_screening:false}, {seasonal_history:true,company_domain:true,design_month_screening:true,manufacturing_models:false}]){
    const api=mockApi(null,completed,capabilities),{elements:ui}=harness(api.fetcher);
    await until(()=>ui.notice.textContent.includes('Server đang chạy code cũ'));
    assert.equal(ui.start.disabled,true);assert.equal(ui.demo.disabled,true);assert.equal(api.posts.length,0);
    assert.match(ui.notice.textContent,/Ctrl\+C/);assert.match(ui.notice.textContent,/python run\.py/);
    assert.match(ui['start-status'].textContent,/Server đang chạy code cũ/);
    assert.equal(ui['connection-retry'].hidden,false);
  }
});

test('backend reconnect preserves entered inputs and cannot be bypassed by refreshing history', async () => {
  const capabilities={},api=mockApi(null,completed,capabilities);
  const {elements:ui,context}=harness(api.fetcher);
  await until(()=>ui['start-status'].textContent.includes('Server đang chạy code cũ'));
  ui.brief.value='Custom printed gifts';ui['history-year-mode'].value='custom';ui['history-years-custom'].value='2021,2023,2025';
  ui['history-months'].value='10,12';ui['budget-custom'].value='31';ui.budget.value='custom';
  const monthOptions=ui['monthly-month'].children.length,budgetOptions=ui.budget.children.length;
  await context.loadLibrary();assert.equal(ui.start.disabled,true);
  await context.startResearch({brief:'Cannot bypass readiness',mode:'live'});assert.equal(api.posts.length,0);
  capabilities.seasonal_history=capabilities.company_domain=capabilities.design_month_screening=capabilities.manufacturing_models=capabilities.design_content=capabilities.exa_discovery=true;
  await ui['connection-retry'].onclick();
  assert.equal(ui.start.disabled,false);assert.match(ui['start-status'].textContent,/Sẵn sàng/);
  assert.equal(ui['connection-retry'].hidden,true);assert.equal(ui.brief.value,'Custom printed gifts');
  assert.equal(ui['history-years-custom'].value,'2021,2023,2025');assert.equal(ui['history-months'].value,'10,12');
  assert.equal(ui['budget-custom'].value,'31');assert.equal(ui.budget.value,'custom');
  assert.equal(ui['monthly-month'].children.length,monthOptions);assert.equal(ui.budget.children.length,budgetOptions);assert.equal(api.posts.length,0);
});

test('failed reconnect remains blocked and permits another check without erasing input', async () => {
  const capabilities={},api=mockApi(null,completed,capabilities);let unavailable=false;
  const {elements:ui}=harness((path,options)=>{if(unavailable&&path==='/api/settings')throw new Error('Server unavailable');return api.fetcher(path,options);});
  await until(()=>ui['start-status'].textContent.includes('Server đang chạy code cũ'));ui.brief.value='Keep my description';
  unavailable=true;await ui['connection-retry'].onclick();
  assert.equal(ui.start.disabled,true);assert.equal(ui['connection-retry'].disabled,false);assert.match(ui['start-status'].textContent,/Server unavailable/);
  unavailable=false;capabilities.seasonal_history=capabilities.company_domain=capabilities.design_month_screening=capabilities.manufacturing_models=capabilities.design_content=capabilities.exa_discovery=true;
  await ui['connection-retry'].onclick();assert.equal(ui.start.disabled,false);assert.equal(ui.brief.value,'Keep my description');assert.equal(api.posts.length,0);
});

test('reconnect keeps start blocked with an explanation while research is active', async () => {
  const capabilities={},api=mockApi(null,{...completed,status:'running'},capabilities);
  const {elements:ui}=harness(async(path,options)=>path==='/api/runs'&&!options?.method?{ok:true,json:async()=>[{...completed,status:'running'}]}:api.fetcher(path,options));
  await until(()=>ui['start-status'].textContent.includes('Server đang chạy code cũ'));
  capabilities.seasonal_history=capabilities.company_domain=capabilities.design_month_screening=capabilities.manufacturing_models=capabilities.design_content=capabilities.exa_discovery=true;
  await ui['connection-retry'].onclick();
  assert.match(ui['start-status'].textContent,/Một nghiên cứu đang chạy/);
  assert.equal(ui.start.disabled,true);assert.equal(api.posts.length,0);
});

test('zero LLM budget requires explicit seeds before any submission', async () => {
  const api=mockApi(); const {elements:ui}=harness(api.fetcher);
  await until(()=>!ui.start.disabled); ui.brief.value='Decor'; ui['llm-budget'].value='0';
  ui['research-form'].listeners.submit({preventDefault(){}});
  assert.equal(api.posts.length,0); assert.match(ui.notice.textContent,/keyword tiếng Anh/);
  ui['seed-keywords'].value='christmas ornament';
  ui['research-form'].listeners.submit({preventDefault(){}});
  await until(()=>api.posts.length===1&&!ui.start.disabled);
  assert.equal(api.posts[0].llm.enabled,false);
  assert.equal(api.posts[0].niches[0].seeds[0],'christmas ornament');
});

test('stop action updates the active run and reenables new research', async () => {
  const api=mockApi(null,{...completed,status:'running',can_stop:true});
  const {elements:ui,context}=harness(api.fetcher);
  await until(()=>!ui.demo.disabled); await ui.demo.onclick();
  assert.equal(ui.start.disabled,true); assert.equal(ui['active-job'].hidden,false);
  await vm.runInContext('stopRun(selectedRun)',context);
  assert.ok(api.requests.some(request=>request.path.endsWith('/stop')));
  assert.equal(ui['run-status'].textContent,'Đã dừng');
  assert.equal(ui.start.disabled,false);
});

test('product grid sorts numeric prices and exports the same query', async () => {
  const api=mockApi(); const {elements:ui}=harness(api.fetcher);
  await until(()=>!ui.start.disabled); ui['nav-products'].onclick();
  await until(()=>ui['product-rows'].children.length===2);
  await ui['sort-price'].onclick();
  assert.equal(ui['product-rows'].children[0].children[1].children[0].textContent,'Cheap sample');
  assert.match(ui['export-products'].href,/sort=price/); assert.match(ui['export-products'].href,/order=asc/);
  await ui['product-rows'].children[0].children[0].children[0].onclick();
  assert.ok(api.requests.some(request=>request.path==='/api/workspace/save'&&request.body.product_id==='P-cheap'&&request.body.saved));
  await ui['sort-stars-price'].onclick();
  const query=new URLSearchParams(ui['export-products'].href.split('?')[1]);
  assert.deepEqual(JSON.parse(query.get('sorts')),[{field:'rating',order:'desc'},{field:'price',order:'asc'}]);
  assert.equal(ui['sort-rules'].children.length,2);
  assert.equal(ui['product-rows'].children[0].children[1].children[0].textContent,'Cheap sample');
  assert.match(ui['sort-rating'].textContent,/↓ 1/);assert.match(ui['sort-price'].textContent,/↑ 2/);
  // Move price above rating, then apply: the export must use the new priority.
  await ui['sort-rules'].children[1].children[3].onclick();
  await ui['sort-apply'].onclick();
  const reordered=new URLSearchParams(ui['export-products'].href.split('?')[1]);
  assert.equal(JSON.parse(reordered.get('sorts'))[0].field,'price');
});

test('report editor saves a separate copy without changing the generated report', async () => {
  const api=mockApi(); const {elements:ui,context}=harness(api.fetcher);
  await until(()=>!ui.start.disabled); await vm.runInContext('openEditor("new-q4")',context);
  ui['editor-content'].value='# User edit'; ui['editor-content'].listeners.input();
  assert.match(ui['editor-state'].textContent,/chưa lưu/);
  await ui['editor-save'].onclick();
  const request=api.requests.find(request=>request.path.endsWith('/editor'));
  assert.equal(request.body.content,'# User edit');
  assert.match(ui['editor-links'].children[0].href,/report-edited.html/);
});

test('Q4 click reaches the HTTP workflow and opens a report with annual history', {skip: !process.env.RESEARCH_UI_BASE}, async () => {
  const base = process.env.RESEARCH_UI_BASE;
  const {elements: ui, context} = harness((path, options) => fetch(new URL(path, base), options));
  await until(() => !ui.demo.disabled);
  await ui.demo.onclick();
  assert.equal(ui['run-panel'].hidden, false);
  const deadline = Date.now() + 20000;
  while (ui['preview-panel'].hidden) {
    assert.ok(Date.now() < deadline, [ui.notice.textContent, ui['run-status'].textContent, ui['run-message'].textContent].filter(Boolean).join(' · ') || 'Q4 report was not created');
    await new Promise(resolve => setTimeout(resolve, 30));
    await vm.runInContext('refreshStatus()', context);
  }
  const report = await (await fetch(new URL(ui.preview.src, base))).text();
  assert.match(report, /Lịch sử 2023, 2024, 2025 và dự báo tham khảo 2026/);
  assert.match(report, /PHÁT LẠI DỮ LIỆU ĐÃ LƯU/);
  const usageUrl = new URL(ui.preview.src.replace(/report\.html.*/, 'usage.json'), base);
  const usage = await (await fetch(usageUrl)).json();
  assert.equal(usage.requests.length, 0);
});

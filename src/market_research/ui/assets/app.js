'use strict';

const byId = id => document.getElementById(id);
const statusLabels = {complete:'Hoàn tất',partial:'Có phần thiếu',failed:'Cần xử lý lỗi',running:'Đang chạy',queued:'Đang chờ',pending:'Chưa chạy',interrupted:'Đã gián đoạn',cancelled:'Đã dừng',cancelling:'Đang dừng…',awaiting_trends:'Chờ dữ liệu Trends',blocked:'Chờ xử lý',waiting:'Chờ xử lý',skipped:'Không áp dụng'};
const activeStatuses = ['running','queued','cancelling'];
const viewNames = ['new','run','history','products','reports','saved','editor'];
const viewLabels = {new:'Nghiên cứu mới',run:'Tiến trình nghiên cứu',history:'Lịch sử nghiên cứu',products:'Thư viện sản phẩm',reports:'Báo cáo',saved:'Đã lưu',editor:'Biên tập báo cáo'};
const budgetFields = {serpapi_requests:'budget',tavily_requests:'tavily-budget',exa_requests:'exa-budget',llm_requests:'llm-budget'};
let selectedRun = null, currentRun = null, stageNames = [], defaultLimits = {}, runs = [], activeRun = null;
let pollTimer = null, previewKind = 'report', currentView = 'new', submitting = false;
let connectionReady=false, connectionChecking=false, connectionError='', formInitialized=false;
const sortLabels={title:'Sản phẩm',price:'Giá',rating:'Điểm sao',review_count:'Lượt đánh giá',observed_at:'Ngày quan sát'};
let productSorts=[{field:'observed_at',order:'desc'}], sortDraft=productSorts.map(rule=>({...rule}));
let productPage = 1, productPages = 1, productRequest = 0;
let editorRun = null, editorDirty = false;
let runReturnView = 'reports';
let selectedStage=null, stageDetailRequest=0;
let comparisonPeriods=[];
let monthlyScopeKey='';
let recoveryInput=null;
const companyCategories=['apparel','bags_textiles','printed_paper','keychains','phone_accessories','home_decor','gift_accessories'];

function collectionMonths(validate=true) {
  if(byId('history-scope').value!=='seasonal')return Array.from({length:12},(_,index)=>index+1);
  const parts=byId('history-months').value.split(',').map(value=>value.trim()),months=parts.map(Number);
  if(!parts.length||parts.some(value=>!value)||months.some(value=>!Number.isInteger(value)||value<1||value>12)){
    if(validate)throw new Error('Nhập các tháng lấy dữ liệu từ 1–12, ví dụ 10,11,12');return [];
  }
  return [...new Set(months)].sort((a,b)=>a-b);
}
function seasonWindowCount() {
  const months=collectionMonths(false),groups=months.filter((month,index)=>index===0||month!==months[index-1]+1).length;
  return groups*historicalYears(false).length;
}
function analysisYear(validate=true) {
  const value=byId('analysis-year').value.trim();
  if(!value)return null;
  const year=Number(value),cutoffYear=Number((byId('cutoff').value||'').slice(0,4));
  if(!/^\d{4}$/.test(value)||!Number.isInteger(year)||year<2004||year>cutoffYear){
    if(validate)throw new Error('Năm phân tích Trends phải từ 2004 đến năm của ngày chốt');return null;
  }
  return year;
}
function analysisWindowInfo() {
  const months=collectionMonths(false),cutoff=byId('cutoff').value||'',cutoffYear=Number(cutoff.slice(0,4)),cutoffMonth=Number(cutoff.slice(5,7));
  const year=analysisYear(false)??(months.every(month=>month<=cutoffMonth)?cutoffYear:cutoffYear-1);
  const groups=months.filter((month,index)=>index===0||month!==months[index-1]+1).length;
  const observed=months.filter(month=>year<cutoffYear||year===cutoffYear&&month<=cutoffMonth);
  const count=observed.filter((month,index)=>index===0||month!==observed[index-1]+1).length;
  return {year,count,groups,months,shared:historicalYears(false).includes(year)?count:0};
}
function renderCollectionHelp() {
  const seasonal=byId('history-scope').value==='seasonal',months=collectionMonths(false),years=historicalYears(false);
  byId('history-months').disabled=!seasonal;
  const selected=byId('history-months').value.split(',').map(value=>Number(value.trim()));
  for(let month=1;month<=12;month++){const input=byId('history-month-'+month);input.checked=!seasonal||selected.includes(month);input.disabled=!seasonal;}
  for(const id of ['history-months-q4','history-months-all'])byId(id).disabled=!seasonal;
  byId('analysis-year').disabled=!seasonal;
  byId('analysis-year').max=String(Number((byId('cutoff').value||'').slice(0,4)));
  byId('monthly-enabled-label').textContent=seasonal?'Đối chiếu thêm lịch sử trong các tháng đã chọn':'Đo lịch sử cho tập ứng viên và xếp hạng tháng 1–12';
  if(seasonal){byId('monthly-enabled').checked=true;byId('monthly-enabled').disabled=true;}else byId('monthly-enabled').disabled=false;
  byId('history-scope-help').textContent=seasonal?`Tháng ${months.join(', ')||'chưa chọn'}; đối chiếu ${years.join(', ')||'các năm lịch sử'}. ${seasonWindowCount()} cửa sổ lịch sử. Sàng lọc từng mẫu trong năm ${analysisWindowInfo().year||'đã chọn'}, chỉ lấy đúng tháng và đến ngày chốt; dùng lại dữ liệu nếu trùng kỳ lịch sử. Mức quan tâm trong tháng quyết định chọn mẫu; dự báo nhiều năm được trình bày riêng.`:'Sàng lọc theo mức quan tâm gần đây. Lịch sử dùng chuỗi liên tục từ năm đầu đến ngày chốt để đối chiếu mùa vụ cả năm. Muốn đo mẫu trong một tháng/năm cụ thể, chọn phạm vi theo tháng.';
}

function historicalYears(validate=true) {
  const start=Number(byId('history-start').value),end=Number(byId('history-end').value),target=Number(byId('forecast-year').value);
  const cutoff=Number((byId('cutoff').value||'').slice(0,4));
  let years;
  if(byId('history-year-mode').value==='custom'){
    const parts=byId('history-years-custom').value.split(',').map(value=>value.trim());
    years=[...new Set(parts.map(Number))].sort((a,b)=>a-b);
    if(parts.some(value=>!/^\d{4}$/.test(value))||years.length<2||years.length>6||years.some(year=>year<2004)){
      if(validate)throw new Error('Nhập 2–6 năm khác nhau từ 2004, ngăn cách bằng dấu phẩy; ví dụ 2021,2023,2025');return [];
    }
  }else{
    if(!Number.isInteger(start)||!Number.isInteger(end)||start<2004||end<start||end-start<1||end-start>5) {
      if(validate)throw new Error('Chọn từ 2 đến 6 năm lịch sử liên tiếp, bắt đầu từ 2004');return [];
    }
    years=Array.from({length:end-start+1},(_,index)=>start+index);
  }
  if(validate&&years.at(-1)>=cutoff)throw new Error('Năm lịch sử phải đã hoàn tất trước năm của ngày chốt');
  if(validate&&(!Number.isInteger(target)||target<=years.at(-1)))throw new Error('Năm dự báo phải sau các năm lịch sử');
  return years;
}
function renderHistoryHelp() {
  const years=historicalYears(false),end=years.at(-1),target=Number(byId('forecast-year').value),custom=byId('history-year-mode').value==='custom';
  byId('history-year-range').hidden=custom;byId('history-year-custom').hidden=!custom;
  byId('history-start').disabled=byId('history-end').disabled=custom;byId('history-years-custom').disabled=!custom;
  byId('history-start').max=byId('history-end').max=String(Number((byId('cutoff').value||'2026').slice(0,4))-1);
  byId('forecast-year').min=String((end||2004)+1);
  const sparse=years.some((year,index)=>index>0&&year!==years[index-1]+1);
  byId('history-help').textContent=years.length?`Các năm đối chiếu: ${years.join(', ')}. Tối đa ${Math.max(0,years.length-2)} năm kiểm chứng khi dữ liệu đủ. Dự báo ${target} chỉ học từ các năm lịch sử hoàn tất; báo cáo ghi MAE, WAPE và so với cùng tháng năm trước.${sparse?' Năm không liên tiếp có thể thiếu mốc so cùng kỳ năm liền trước.':''} Mức bằng chứng không phải xác suất chính xác.`:'Chọn 2–6 năm lịch sử đã hoàn tất để đối chiếu; có thể chọn từ năm 2004.';
  byId('comparison-q4').textContent=years.length?`Q4 năm ${sparse?years.join(', '):years[0]+'–'+end}`:'Q4 các năm đã chọn';
  renderCollectionHelp();
}
function comparisonValues(validate=true) {
  const values=comparisonPeriods.map(period=>({start:period.startInput?.value??period.start,end:period.endInput?.value??period.end}));
  if(!validate)return values;
  const last=(byId('cutoff').value||'').slice(0,7), seen=new Set();
  for(const value of values) {
    if(!/^\d{4}-(0[1-9]|1[0-2])$/.test(value.start)||!/^\d{4}-(0[1-9]|1[0-2])$/.test(value.end))throw new Error('Mỗi khoảng so sánh cần tháng bắt đầu và kết thúc');
    if(value.start>value.end)throw new Error('Tháng bắt đầu phải trước hoặc bằng tháng kết thúc');
    if(value.start<'2004-01'||last&&value.end>last)throw new Error('Khoảng so sánh phải từ 2004 và không sau tháng của ngày chốt');
    const key=value.start+'/'+value.end;if(seen.has(key))throw new Error('Không nhập trùng khoảng so sánh');seen.add(key);
  }
  return values;
}
function renderComparisonPeriods() {
  byId('comparison-periods').replaceChildren();
  comparisonPeriods.forEach((period,index)=>{
    const row=node('div',undefined,'comparison-period-row'), from=node('label','Từ tháng'), to=node('label','Đến tháng');
    const start=node('input'),end=node('input');start.type=end.type='month';start.min=end.min='2004-01';
    start.max=end.max=(byId('cutoff').value||'').slice(0,7);start.value=period.start;end.value=period.end;
    start.setAttribute('aria-label',`Tháng bắt đầu khoảng ${index+1}`);end.setAttribute('aria-label',`Tháng kết thúc khoảng ${index+1}`);
    period.startInput=start;period.endInput=end;from.append(start);to.append(end);
    row.append(node('span',String(index+1),'period-number'),from,to,button('×',()=>{comparisonPeriods=comparisonValues(false);comparisonPeriods.splice(index,1);renderComparisonPeriods();},'text-button'));byId('comparison-periods').append(row);
  });
  byId('comparison-add').disabled=comparisonPeriods.length>=12;
  const years=historicalYears(false);
  byId('comparison-help').textContent=byId('history-scope').value==='seasonal'?`Các khoảng này dùng để so sánh trong phạm vi tháng ${collectionMonths(false).join(', ')} và năm ${years.join(', ')} đã chọn ở phần thu thập. Khoảng ngoài phạm vi sẽ bị từ chối; tháng không thu không được tính là 0. Giá và review Amazon vẫn chỉ là quan sát thực tế đã lưu.`:comparisonPeriods.length?`Đã chọn ${comparisonPeriods.length} khoảng để so sánh trên cùng chuỗi Trends US. Dữ liệu thiếu/partial được ghi riêng. Không lọc ngày review hoặc giá Amazon quá khứ; chuỗi đầy đủ vẫn dùng cho dự báo, không nhân API theo từng khoảng.`:`Chưa chọn khoảng riêng: phân tích cả năm ${years.join(', ')}. Chọn Q4 hoặc thêm khoảng tháng độc lập. Đây là mức quan tâm Trends; giá và review quá khứ chỉ có khi đã lưu quan sát sản phẩm thực tế.`;
}

async function api(path, body) {
  const options = body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-Research-Client':'local'},body:JSON.stringify(body)};
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(),15000);
  try {
    const response = await fetch(path,{...options,signal:controller.signal});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Không kết nối được ứng dụng');
    return result;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('Ứng dụng chưa phản hồi sau 15 giây. Kiểm tra cửa sổ server rồi thử lại.');
    throw error;
  } finally { clearTimeout(timeout); }
}
function notice(message = '') { byId('notice').hidden = !message; byId('notice').textContent = message; }
function guard(action) { return (...args) => Promise.resolve().then(() => action(...args)).catch(error => notice(error.message)); }
function node(tag,text,css='') { const item=document.createElement(tag); if(text!==undefined) item.textContent=text; item.className=css; return item; }
function button(label,action,css='secondary') { const item=node('button',label,css); item.type='button'; item.onclick=guard(action); return item; }
function anchor(label,url) { const item=node('a',label); if (/^(https?:\/\/|\/)/i.test(url || '')) item.href=url; item.target='_blank'; item.rel='noopener noreferrer'; return item; }
function titleOf(run) { return run.user_title || run.summary?.category || run.input?.brief?.slice(0,120) || run.run_id; }
function formatDate(value) { return value ? String(value).slice(0,16).replace('T',' ')+' UTC' : '—'; }
function number(value) { return value === null || value === undefined ? '—' : new Intl.NumberFormat('vi-VN',{maximumFractionDigits:2}).format(value); }
function setSubmitting(busy) {
  submitting=busy;
  byId('start').disabled=busy || Boolean(activeRun) || !connectionReady;
  byId('demo').disabled=busy || Boolean(activeRun) || !connectionReady;
  byId('start').textContent=busy?'Đang tạo nghiên cứu…':!connectionReady?(connectionChecking?'Đang kết nối…':'Chưa thể bắt đầu'):activeRun?'Đang có nghiên cứu chạy':'Bắt đầu nghiên cứu ↗';
  byId('start-status').textContent=!connectionReady?(connectionError||'Đang kiểm tra kết nối ứng dụng…'):busy?'Đang gửi mô tả; chờ tạo lượt nghiên cứu.':activeRun?'Một nghiên cứu đang chạy. Mở tiến trình để theo dõi hoặc dừng trước khi bắt đầu lượt khác.':'Sẵn sàng. Chỉ gọi API khi bạn bắt đầu nghiên cứu.';
  byId('connection-retry').hidden=connectionReady;
  byId('connection-retry').disabled=connectionChecking;
  byId('research-form').setAttribute('aria-busy',String(busy||connectionChecking));
}
function setView(name) {
  if (currentView==='editor' && editorDirty && name!=='editor' && globalThis.confirm && !globalThis.confirm('Bạn chưa lưu bản biên tập. Rời màn hình này?')) return false;
  currentView=name;
  for (const view of viewNames) byId('view-'+view).hidden=view!==name;
  for (const view of ['history','products','reports','saved']) byId('nav-'+view).className='nav-item'+(view===name || view==='reports'&&name==='editor'?' active':'');
  byId('page-title').textContent=viewLabels[name];
  globalThis.scrollTo?.({top:0,behavior:'smooth'});
  if (name==='products') loadProducts().catch(error=>notice(error.message));
  return true;
}
function populateBudgets() {
  for (const [key,id] of Object.entries(budgetFields)) {
    const select=byId(id); select.replaceChildren();
    const amounts=[...new Set([0,1,2,3,4,5,8,10,15,20,30,40,50,80,100,defaultLimits[key]??(key==='exa_requests'?4:0)])].sort((a,b)=>a-b);
    for (const amount of amounts) { const item=node('option',amount===0?'0 — Không gọi':amount+' lượt'); item.value=String(amount); select.append(item); }
    const custom=node('option','Tùy chỉnh…'); custom.value='custom'; select.append(custom);
    select.value=String(defaultLimits[key]??(key==='exa_requests'?4:0));
    byId(id+'-custom').hidden=true; byId(id+'-custom').required=false;
    select.onchange=()=>{ const custom=select.value==='custom'; byId(id+'-custom').hidden=!custom; byId(id+'-custom').required=custom; };
  }
}
function budgetValue(id) {
  const field=byId(id).value==='custom'?byId(id+'-custom'):byId(id);
  const value=Number(field.value);
  if (field.value==='' || !Number.isInteger(value) || value<0 || value>1000) throw new Error('Số lượt API phải là số nguyên từ 0 đến 1000');
  return value;
}
function applyCreditEconomyPreset(){
  // Keep the user's API caps, scope and dates. Save requests by reducing the
  // candidate/history set, rather than increasing any provider's budget.
  byId('web-provider').value='combined';byId('trends-provider').value='auto';
  byId('candidate-keywords').value='16';byId('monthly-keywords').value='8';byId('monthly-rows').value='5';
  byId('top-keywords').value='5';byId('top-keywords-custom').hidden=true;
  byId('monthly-enabled').checked=true;byId('product-details').value='2';byId('source-shopping').checked=false;
  estimateRequests();notice('Đã chọn cấu hình tiết kiệm: 16 ứng viên, Top 5 tìm mẫu, lịch sử tối đa 8 keyword. Giữ nguyên tháng/năm, nhóm hàng và mọi trần API. Kiểm tra quota/credit miễn phí còn lại trên tài khoản trước khi bắt đầu.');
}
function populateTopKeywords() {
  if(!Number.isInteger(defaultLimits.top_keywords)) throw new Error('Server chưa hỗ trợ chọn Top keyword; hãy dừng server cũ và chạy lại python run.py');
  const select=byId('top-keywords');select.replaceChildren();
  const amounts=[...new Set([3,5,10,15,20,30,50,defaultLimits.top_keywords])].sort((a,b)=>a-b);
  for(const amount of amounts){const option=node('option','Top '+amount+' keyword');option.value=String(amount);select.append(option);}
  const custom=node('option','Tùy chỉnh…');custom.value='custom';select.append(custom);
  select.value=String(defaultLimits.top_keywords);
  select.onchange=()=>{const custom=select.value==='custom';byId('top-keywords-custom').hidden=!custom;byId('top-keywords-custom').required=custom;};
}
function topKeywordValue() {
  const input=byId('top-keywords').value==='custom'?byId('top-keywords-custom'):byId('top-keywords');
  const value=Number(input.value);
  if(input.value===''||!Number.isInteger(value)||value<1||value>100) throw new Error('Top keyword phải là số nguyên từ 1 đến 100');
  return value;
}
const publicSites=['tiktok','facebook','etsy','walmart','pinterest','ebay'];
function integerInput(id,minimum,maximum) {
  const value=Number(byId(id).value);
  if(byId(id).value===''||!Number.isInteger(value)||value<minimum||value>maximum) throw new Error(`Giới hạn ${id} phải là số nguyên ${minimum}–${maximum}`);
  return value;
}
function estimateRequests() {
  try {
    const top=topKeywordValue(), details=integerInput('product-details',0,1000), pool=integerInput('candidate-keywords',1,100);
    const total=budgetValue('budget'), trendCap=integerInput('trends-serp-budget',0,1000), reserve=integerInput('product-reserve',0,1000), provider=byId('trends-provider').value;
    const effective=provider==='free'||provider==='off'?0:Math.min(trendCap,Math.max(0,total-(byId('product-collection-mode').value==='scraper'?0:reserve)));
    const direct=byId('product-collection-mode').value==='scraper';
    const shopping=!direct&&byId('source-shopping').checked?Math.min(top,integerInput('shopping-keywords',0,100)):0;
    const searches=(direct?0:top)+shopping;
    const seasonal=byId('history-scope').value==='seasonal',monthly=seasonal||byId('monthly-enabled').checked, historyKeywords=monthly?Math.min(pool,integerInput('monthly-keywords',1,100)):top;
    const observation=analysisWindowInfo(),screening=seasonal?Math.ceil(pool/4)*observation.count:Math.ceil(pool/4), history=Math.ceil(historyKeywords/(monthly?4:5))*(seasonal?seasonWindowCount():1),shared=seasonal?Math.min(Math.ceil(pool/4),Math.ceil(historyKeywords/4))*observation.shared:0;
    const historyReserve=seasonal?Math.min(screening+history-shared,effective):Math.min(history,monthly?Math.max(1,Math.floor(effective/2)):Math.max(0,effective-1),Math.max(0,effective-1));
    const estimate=screening+history-shared, productEstimate=searches+(direct?0:details);
    const warning=effective>0&&estimate>effective?` Cần lưu ý: nếu miễn phí lỗi, trần Trends ${effective} thấp hơn dự trù ${estimate}; nên giảm ứng viên/Top keyword hoặc chỉnh lại trần trước khi chạy.`:'';
    const totalWarning=effective>0&&estimate+productEstimate>total?` Tổng dự trù ${estimate+productEstimate} SerpApi vượt trần ${total}, chưa tính thử lại.`:'';
    const phase=seasonal?`Sàng lọc ${pool} mẫu/keyword trong tháng ${collectionMonths(false).join(', ')} năm ${observation.year}: khoảng ${2*screening} HTTP miễn phí hoặc ${screening} lượt SerpApi. Dùng lại kỳ trùng lịch sử; Related khám phá trong cùng phạm vi nếu có ngân sách.`:`Sàng lọc ${pool} ứng viên: khoảng ${2*screening} HTTP miễn phí hoặc ${screening} lượt SerpApi.`;
    byId('request-estimate').textContent=`Trần tổng SerpApi: ${total} lượt, gồm Trends và mẫu hàng. Trends được dùng tối đa ${effective} lượt trong trần này; bảo vệ tối thiểu ${Math.min(total,reserve)} lượt cho mẫu hàng. Tìm mẫu cần khoảng ${top} Amazon + ${shopping} Shopping = ${searches} lượt, rồi tối đa ${details} chi tiết, chưa tính thử lại. ${phase} Lịch sử ${historyKeywords} keyword: khoảng ${history} lượt SerpApi, ${monthly?'4 keyword + anchor/yêu cầu; dùng lại chuỗi khi phân tích sản phẩm':'gom tối đa 5 keyword/yêu cầu'}. Dành trước ${historyReserve} lượt trong trần Trends cho lịch sử. Tổng dự trù ${estimate+productEstimate} lượt nếu Trends miễn phí không dùng được; không có cache. Số thực tế phụ thuộc keyword trùng, chất lượng và thử lại; không cam kết đủ mọi keyword.${warning}${totalWarning}`;
    if(direct)byId('request-estimate').textContent=`Công cụ sản phẩm không dùng API: tối đa ${byId('scraper-budget').value} HTTP cho Amazon/Etsy/Reddit và chi tiết, dùng cache trước. ${phase} Lịch sử ${historyKeywords} keyword: khoảng ${history} lượt SerpApi nếu miễn phí không dùng được. API dành cho khám phá keyword và Trends; không gọi Amazon/Shopping API ở chế độ này. Nguồn bị chặn giữ trạng thái thiếu bằng chứng.`;
  } catch (_) { byId('request-estimate').textContent=''; }
}
function renderCollectionMode(){
  const direct=byId('product-collection-mode').value==='scraper';
  byId('source-shopping').disabled=direct;byId('product-details').disabled=direct;
  byId('product-reserve').disabled=direct;
  estimateRequests();
}
function applyResearchPreset(economy=false) {
  if(economy)byId('history-scope').value='seasonal';
  const seasonal=byId('history-scope').value==='seasonal';collectionMonths();
  const count=economy?10:64,top=economy?5:10,details=economy?2:3,shopping=economy?1:2;
  const pool=economy?12:64,observation=analysisWindowInfo(),history=Math.ceil(count/4)*(seasonal?seasonWindowCount():1),screen=seasonal?Math.ceil(pool/4)*observation.count:Math.ceil(pool/4),shared=seasonal?Math.ceil(count/4)*observation.shared:0,trendEstimate=history+screen-shared,products=top+details+shopping;
  const total=seasonal?Math.ceil((trendEstimate+products+(economy?3:6))/10)*10:50;
  const trendCap=seasonal?trendEstimate+(economy?2:6):34;
  for(const [id,value] of [['budget',total],['tavily-budget',economy?4:6],['llm-budget',economy?15:20]]){byId(id).value='custom';byId(id+'-custom').value=String(value);byId(id+'-custom').hidden=false;byId(id+'-custom').required=true;}
  byId('candidate-keywords').value=String(pool);byId('top-keywords').value=String(top);byId('monthly-enabled').checked=true;byId('monthly-keywords').value=String(count);byId('monthly-rows').value='10';byId('trends-serp-budget').value=String(trendCap);byId('product-reserve').value=economy?'8':'14';byId('product-details').value=String(details);byId('source-shopping').checked=true;byId('shopping-keywords').value=String(shopping);
  renderCollectionHelp();estimateRequests();notice(`Đã chọn ${pool} ứng viên, tối đa ${count} keyword đối chiếu lịch sử và ${top} keyword tìm mẫu. Trần SerpApi ${total}, Trends ${trendCap}. Các giá trị đang ở biểu mẫu; bắt đầu nghiên cứu sẽ dùng các trần này.`);
}
function closeStageDetail() {
  selectedStage=null;stageDetailRequest++;byId('stage-detail').hidden=true;
  if(currentRun)renderStages(currentRun);
}
async function loadStageDetail() {
  if(!selectedRun||!selectedStage)return;
  const runId=selectedRun, stage=selectedStage, request=++stageDetailRequest;
  try {
    const detail=await api(`/api/runs/${runId}/stages/${stage}`);
    if(request!==stageDetailRequest||runId!==selectedRun||stage!==selectedStage)return;
    byId('stage-detail-title').textContent=detail.label||stage;
    byId('stage-detail-status').textContent=statusLabels[detail.status]||detail.status||'Chưa chạy';
    const timing=detail.timing||{};
    byId('stage-detail-message').textContent=`${detail.note?detail.note+' ':''}${detail.reason?detail.reason+' ':''}${timing.started_at?'Bắt đầu '+formatDate(timing.started_at):'Chưa bắt đầu'}${timing.elapsed_seconds!=null?' · '+number(timing.elapsed_seconds)+' giây':''}${timing.attempts?' · lần thực hiện '+timing.attempts:''}. Nhật ký được cập nhật khi bước đang chạy.`;
    byId('stage-summary').textContent=JSON.stringify(detail.summary||{},null,2);
    byId('stage-logs').replaceChildren();
    for(const log of detail.logs||[]) {
      const item=node('li',undefined,/error|fail/.test(log.event||'')?'log-error':/warning|fallback|recover/.test(log.event||'')?'log-warning':'');
      item.append(node('small',`${formatDate(log.at)} · ${log.event||'event'}`),node('p',log.message||''));
      if(log.details&&Object.keys(log.details).length){const extra=node('details');extra.append(node('summary','Dữ liệu xử lý / phản hồi'),node('pre',JSON.stringify(log.details,null,2)));item.append(extra);}
      byId('stage-logs').append(item);
    }
    byId('stage-log-note').textContent=(detail.logs||[]).length?(detail.truncated?'Chỉ hiển thị phần nhật ký gần nhất để giữ giao diện nhẹ.':'Nhật ký của riêng bước đang chọn.'):'Chưa có sự kiện riêng cho bước này. Kết quả checkpoint của lượt cũ vẫn xem được ở trên.';
  } catch(error) {if(request===stageDetailRequest)byId('stage-detail-message').textContent='Không tải được chi tiết: '+error.message;}
}
async function openStageDetail(stage) {
  if(selectedStage===stage){closeStageDetail();return;}
  selectedStage=stage;byId('stage-detail').hidden=false;
  byId('stage-detail-title').textContent=stageNames.find(([id])=>id===stage)?.[1]||stage;
  byId('stage-detail-message').textContent='Đang tải kết quả và nhật ký…';byId('stage-summary').textContent='';byId('stage-logs').replaceChildren();
  if(currentRun)renderStages(currentRun);
  await loadStageDetail();
}
function renderDiscovery(run) {
  const info=run.discovery_overview||{}, rows=info.rows||[], sources=info.sources||[], pages=info.pages||[];
  const monthScope=info.selection_basis==='selected_month_observations'||rows.some(row=>row.selection_basis==='selected_month_observations');
  byId('screen-growth-heading').textContent=monthScope?'Ngày đã quan sát':'Tăng trưởng 28 ngày';
  byId('discovery-panel').hidden=!(rows.length||sources.length||pages.length);
  byId('discovery-note').textContent=info.note||'Đang thu thập ứng viên; chưa đủ dữ liệu xếp hạng.';
  if(info.research_focus?.content_focus==='designs'){
    const coverage=info.coverage||{},groups=coverage.content_coverage||[],missing=groups.filter(group=>!group.source_candidates).map(group=>group.name);
    byId('discovery-note').textContent+=` Nội dung hình/câu chữ: ${coverage.source_content_candidates??0} keyword có nguồn; ${coverage.hypothesis_candidates??0} giả thuyết chưa có nguồn.`+(missing.length?` Chưa tìm được nội dung có nguồn ở: ${missing.join(', ')}.`:'');
  }
  byId('screening-rows').replaceChildren();byId('discovery-sources').replaceChildren();byId('discovery-links').replaceChildren();
  for(const source of sources)byId('discovery-sources').append(node('span',`${(source.sites||[source.provider||source.branch]).join(', ')} · ${source.status} · ${source.count??0} trang`,'badge'));
  for(const row of rows) {
    const tr=node('tr');
    const keyword=row.keyword+(row.measurement_query&&row.measurement_query.toLowerCase()!==row.keyword.toLowerCase()?` · Truy vấn đo: ${row.measurement_query}`:'')+(row.qualifying_months?.length?` · đủ tín hiệu tháng ${row.qualifying_months.join(', ')}`:'');
    const observation=monthScope?row.observed_days??'—':row.growth_pct==null?'—':number(row.growth_pct)+'%';
    for(const value of [keyword,number(row.relative_interest),String(observation),number(row.score),row.selected?(row.rank?'Đã chọn · có phép đo':'Đã chọn · chưa xác minh'):row.status==='low_signal'?'Tín hiệu quá ít':'Chưa chọn'])tr.append(node('td',value));
    byId('screening-rows').append(tr);
  }
  for(const page of pages){
    byId('discovery-links').append(anchor(`${page.platform} · ${page.title}`,page.url));
    const picture=page.image||(page.image_links||[])[0];
    if(picture)byId('discovery-links').append(anchor(`Ảnh trên trang nguồn · ${page.title}`,picture));
  }
}
function schedulePoll() {
  clearTimeout(pollTimer);
  if (!activeRun && !activeStatuses.includes(currentRun?.status)) return;
  pollTimer=setTimeout(async()=>{
    try { await loadLibrary(); if(selectedRun) await refreshStatus(); }
    catch(error){ notice(error.message); }
    schedulePoll();
  },1500);
}
async function loadLibrary() {
  runs=await api('/api/runs');
  activeRun=runs.find(run=>activeStatuses.includes(run.status)) || null;
  byId('active-job').hidden=!activeRun;
  if(activeRun) {
    byId('active-label').textContent=(statusLabels[activeRun.status]||'Đang chạy')+' · '+titleOf(activeRun).slice(0,90);
    byId('active-stop').hidden=activeRun.can_stop===false;
    byId('active-stop').disabled=activeRun.status==='cancelling';
  }
  setSubmitting(submitting);
  byId('history-count').textContent=String(runs.length);
  byId('library').replaceChildren();
  for(const run of runs.slice(0,4)) {
    const item=button('',()=>selectRun(run.run_id),'run-item'+(run.run_id===selectedRun?' active':''));
    item.append(node('strong',titleOf(run)),node('small',(statusLabels[run.status]||run.status)+' · '+(run.mode==='offline'?'Dữ liệu lưu trữ':'Nguồn thật')));
    byId('library').append(item);
  }
  if(!runs.length) byId('library').textContent='Chưa có nghiên cứu';
  const previous=byId('product-run').value || 'all';
  byId('product-run').replaceChildren(); const all=node('option','Tất cả nghiên cứu'); all.value='all'; byId('product-run').append(all);
  for(const run of runs) { const item=node('option',titleOf(run).slice(0,70)); item.value=run.run_id; byId('product-run').append(item); }
  byId('product-run').value=runs.some(run=>run.run_id===previous)?previous:'all';
  renderResearchCards();
  schedulePoll();
}
function researchCard(run,report=false) {
  const card=node('article',undefined,'research-card');
  const top=node('div',undefined,'card-top'); top.append(node('span',statusLabels[run.status]||run.status,'badge'),button(run.saved?'★':'☆',()=>saveRun(run),'save-star'+(run.saved?' saved':'')));
  card.append(top,node('h3',titleOf(run)),node('p',(run.mode==='offline'?'Dữ liệu lưu trữ':'Nguồn thật')+' · '+formatDate(run.created_at)));
  const actions=node('div',undefined,'actions');
  actions.append(button(report?'Xem báo cáo ↗':'Mở nghiên cứu ↗',()=>selectRun(run.run_id)));
  if(run.has_report) actions.append(button('Biên tập',()=>openEditor(run.run_id),'text-button'));
  if(run.has_edit) actions.append(anchor('Bản biên tập ↗',`/outputs/${run.run_id}/report-edited.html`));
  card.append(actions); return card;
}
function renderResearchCards() {
  const search=byId('history-search').value.trim().toLocaleLowerCase('vi');
  const filter=byId('history-status').value || 'all';
  const filtered=runs.filter(run=>(titleOf(run)+' '+run.run_id).toLocaleLowerCase('vi').includes(search) && (filter==='all' || filter==='running'&&activeStatuses.includes(run.status) || filter==='failed'&&['failed','interrupted'].includes(run.status) || run.status===filter));
  for(const [id,rows,isReport] of [['history-list',filtered,false],['report-list',runs.filter(run=>run.has_report),true],['saved-list',runs.filter(run=>run.saved),true]]) {
    byId(id).replaceChildren(...rows.map(run=>researchCard(run,isReport)));
    if(!rows.length) byId(id).append(node('div',id==='saved-list'?'Nhấn ☆ để lưu nghiên cứu hoặc mẫu sản phẩm.':'Chưa có mục phù hợp. Bắt đầu một nghiên cứu hoặc chạy demo Q4.','empty-state'));
  }
}
async function saveRun(run) {
  await api('/api/workspace/save',{kind:'run',run_id:run.run_id,saved:!run.saved});
  await loadLibrary(); if(selectedRun===run.run_id) await refreshStatus();
}
async function selectRun(runId) {
  const origin=currentView;
  if(!setView('run')) return;
  if(['history','products','reports','saved'].includes(origin)) runReturnView=origin;
  else if(origin!=='run') runReturnView=runs.some(run=>run.run_id===runId&&run.has_report)?'reports':'history';
  if(selectedRun!==runId){selectedStage=null;stageDetailRequest++;byId('stage-detail').hidden=true;}
  selectedRun=runId; previewKind='report';
  byId('run-panel').hidden=false; byId('run-panel').scrollIntoView({behavior:'smooth',block:'start'});
  await refreshStatus(); await loadLibrary();
}
function closeRun() {
  if(currentView!=='run') return;
  setView(runReturnView);
  selectedRun=null; currentRun=null;
  selectedStage=null;stageDetailRequest++;byId('stage-detail').hidden=true;
  byId('run-panel').hidden=true; byId('preview-panel').hidden=true;
  byId('preview').src='about:blank';
  byId('nav-'+runReturnView)?.focus?.();
  schedulePoll();
}
async function runAction(action) {
  if(action==='stop') return stopRun(selectedRun);
  await api(`/api/runs/${selectedRun}/${action}`,{});
  notice(action==='resume'?'Đang khôi phục từ checkpoint; ngân sách của lượt cũ được giữ nguyên.':'Đang dựng báo cáo từ dữ liệu đã lưu, không gọi API.');
  await loadLibrary(); await refreshStatus();
}
async function stopRun(runId) {
  await api(`/api/runs/${runId}/stop`,{});
  notice('Đã yêu cầu dừng. Yêu cầu API đã gửi có thể vẫn tính quota; ứng dụng lưu phản hồi và không gửi yêu cầu tiếp theo.');
  await loadLibrary(); if(selectedRun===runId) await refreshStatus();
}
function renderMonthlyKeywords(run) {
  const data=run.monthly_overview||{},seasonal=run.input?.trends?.history_scope==='seasonal',months=seasonal?(run.input.trends.history_months||[10,11,12]):Array.from({length:12},(_,index)=>index+1),key=run.run_id+':'+months.join(',');
  byId('monthly-heading').textContent=seasonal?'Đối chiếu lịch sử · keyword tháng '+months.join(', '):'Đối chiếu lịch sử · keyword tháng 1–12';
  if(monthlyScopeKey!==key){monthlyScopeKey=key;const previous=Number(byId('monthly-month').value);byId('monthly-month').replaceChildren();for(const month of months){const option=node('option','Tháng '+month);option.value=String(month);byId('monthly-month').append(option);}byId('monthly-month').value=String(months.includes(previous)?previous:months[0]);}
  const rows=(data.rows||[]).filter(row=>row.month===Number(byId('monthly-month').value||months[0]));
  byId('monthly-panel').hidden=!(data.rows||[]).length;
  byId('monthly-note').textContent=data.note||'Hạng mùa vụ so với đỉnh riêng của từng keyword; hạng quan tâm chỉ so trong cùng nhóm thang đo. Không phải doanh số.';
  const sort=byId('monthly-sort').value;
  rows.sort((a,b)=>sort==='keyword'?a.measurement_query.localeCompare(b.measurement_query):sort==='demand'?(String(a.comparison_group||'zz').localeCompare(String(b.comparison_group||'zz'))||((a.demand_rank??9999)-(b.demand_rank??9999))):((a.seasonality_rank??9999)-(b.seasonality_rank??9999))||a.measurement_query.localeCompare(b.measurement_query));
  byId('monthly-table').replaceChildren();
  const shown=rows.slice(0,run.input?.limits?.monthly_rows??50);
  for(const row of shown){const tr=node('tr');for(const value of [row.keyword===row.measurement_query?row.keyword:row.keyword+' → '+row.measurement_query,row.seasonality_rank??'—',number(row.seasonal_score),row.demand_rank??'—',row.comparison_label||'Chưa có thang chung',(row.usable_years||[]).join(', ')||'Chưa đủ',row.reason||'Chưa có dữ liệu'])tr.append(node('td',String(value)));byId('monthly-table').append(tr);}
  byId('monthly-count').textContent=`Tháng ${byId('monthly-month').value||1}: ${rows.filter(row=>row.status==='available').length}/${rows.length} keyword đủ dữ liệu; hiển thị ${shown.length} dòng. Toàn bộ dòng nằm trong bản đầy đủ/CSV. Các dòng thiếu giữ rõ; không thêm keyword giả để đủ số lượng.`;
  byId('monthly-downloads').replaceChildren();
  if((run.files||[]).includes('keyword-monthly.html'))byId('monthly-downloads').append(anchor('Xem toàn bộ keyword và 12 tháng',`/outputs/${run.run_id}/keyword-monthly.html`));
  if((run.files||[]).includes('tables/keyword_monthly.csv'))byId('monthly-downloads').append(anchor('Tải bảng keyword × tháng CSV',`/outputs/${run.run_id}/tables/keyword_monthly.csv`));
}
function renderStages(run) {
  const diagnostic=run.screening_diagnostics||{};
  byId('screen-diagnostic').hidden=!(run.status==='awaiting_trends'&&diagnostic.blocked);
  byId('screen-diagnostic-summary').textContent=diagnostic.summary||'';
  byId('screen-diagnostic-explanation').textContent=diagnostic.explanation||'';
  byId('screen-diagnostic-action').textContent=diagnostic.action||'';
  renderDiscovery(run);
  renderMonthlyKeywords(run);
  const history=run.historical_overview||[],levels={insufficient:'Chưa đủ',limited:'Hạn chế',moderate:'Vừa',stronger_evidence:'Nhiều bằng chứng'};
  byId('quality-panel').hidden=!history.length;byId('quality-rows').replaceChildren();byId('quality-reasons').replaceChildren();
  const seasonalHistory=run.input?.trends?.history_scope==='seasonal';
  byId('quality-note').textContent=`Lịch sử ${(run.input?.history_years||[]).join(', ')} → dự báo ${run.input?.target_year||'—'}. ${seasonalHistory?'Chỉ tháng '+run.input.trends.history_months.join(', ')+'. Đơn vị quan tâm so anchor = 100, có thể vượt 100; không kết luận mùa vụ cả năm. MAE tính trên tỷ lệ này.':'MAE là sai số điểm Trends.'} WAPE là tổng sai số tuyệt đối / tổng giá trị thực. So với mốc cùng tháng năm liền trước trên cùng mẫu. Mức bằng chứng không phải xác suất chính xác hay độ chính xác doanh số.`;
  for(const row of history) {
    const confidence=row.confidence||{},tr=node('tr');
    for(const value of [row.measurement_query||row.direction_id,(row.usable_years||[]).join(', ')||'Chưa đủ',confidence.coverage_pct==null?'—':number(confidence.coverage_pct)+'%',String(confidence.fold_count??0),number(row.metrics?.mae)+' / '+number(row.baseline_metrics?.mae),row.metrics?.wape_pct==null?'—':number(row.metrics.wape_pct)+'%',levels[confidence.level]||'Chưa kiểm chứng'])tr.append(node('td',value));
    byId('quality-rows').append(tr);
    if(row.reason||(confidence.reasons||[]).length)byId('quality-reasons').append(node('p',`${row.measurement_query||row.direction_id}: ${row.reason||(confidence.reasons||[]).join('; ')}`));
  }
  byId('steps').replaceChildren(); let completed=0;
  for(const [id,name] of stageNames) {
    const storedState=run.stages?.[id]?.status || 'pending';
    const paused=run.status==='awaiting_trends'&&diagnostic.blocked;
    const downstream=paused&&id!=='screen'&&storedState==='waiting'&&!run.stages?.[id]?.started_at;
    const state=downstream?'pending':paused&&id==='screen'&&diagnostic.measured?'partial':storedState;
    const item=node('li',undefined,state+(selectedStage===id?' selected':''));
    const control=button('',()=>openStageDetail(id),'stage-button');
    if(run.stages?.[id]?.note)control.title=run.stages[id].note;
    control.setAttribute('aria-expanded',String(selectedStage===id));control.setAttribute('aria-controls','stage-detail');
    const label=downstream?'Chưa chạy · chờ sàng lọc':paused&&id==='screen'&&diagnostic.measured?'Đã đo · Chưa đủ tín hiệu':statusLabels[state]||state;
    control.append(node('span',(state==='complete'?'✓ ':state==='running'?'● ':['partial','cancelled'].includes(state)?'△ ':['failed','blocked','waiting','awaiting_trends'].includes(state)?'! ':'')+name),node('small',label));
    item.append(control);byId('steps').append(item);
    if(['complete','partial','skipped'].includes(state)) completed++;
  }
  byId('progress').value=completed;
  byId('run-metrics').replaceChildren();
  for(const [key,label] of [['niches','Niche'],['keywords','Từ khóa khám phá'],['selected_keywords','Keyword tìm mẫu'],['products','Sản phẩm'],['ideas','Ý tưởng']]) if(run.summary?.[key]!==undefined) {
    const item=node('div',label,'metric'); item.append(node('b',String(run.summary[key]))); byId('run-metrics').append(item);
  }
  byId('api-usage').replaceChildren();
  for(const [provider,key,label] of [['public_scraper','scraper_requests','Công cụ sản phẩm · HTTP'],['serpapi','serpapi_requests','SerpApi'],['tavily','tavily_requests','Tavily'],['exa','exa_requests','Exa'],['openrouter','llm_requests','OpenRouter'],['google_trends_free','free_trends_requests','Trends miễn phí · HTTP']]) {
    const used=run.request_counts?.[provider] ?? (run.usage||[]).filter(item=>item.provider===provider).length;
    const cap=run.input?.limits?.[key] ?? defaultLimits[key] ?? 0;
    const card=node('div',label,'usage-item'); card.append(node('strong',`${used} / ${cap} lượt`));
    const meter=node('meter'); meter.min=0; meter.max=Math.max(1,cap); meter.value=Math.min(used,meter.max); card.append(meter); byId('api-usage').append(card);
    if(provider==='exa'){
      const costs=(run.usage||[]).filter(item=>item.provider==='exa'&&Number.isFinite(item.cost_usd)).map(item=>item.cost_usd);
      if(costs.length)card.append(node('small',`Exa báo $${costs.reduce((a,b)=>a+b,0).toFixed(4)} · có thể trừ credit`));
    }
  }
}
function renderFiles(run) {
  const available=run.files||[], base=`/outputs/${run.run_id}/`;
  byId('actions').replaceChildren();
  if(available.includes('report.html')) {
    byId('actions').append(anchor('Mở báo cáo ↗',base+'report.html'),anchor('Markdown ↓',base+'report.md'),anchor('Catalog ↗',base+'catalog.html'),button('Biên tập báo cáo',()=>openEditor(run.run_id)));
    if(available.includes('report-edited.html')) byId('actions').append(anchor('Bản biên tập ↗',base+'report-edited.html'));
    if(available.includes('report.pdf')) {const pdf=anchor('Tải PDF có liên kết ↓',base+'report.pdf');pdf.download='report.pdf';byId('actions').append(pdf);}
    byId('preview-panel').hidden=false;
    const src=base+previewKind+'.html?v='+encodeURIComponent(run.report_rebuilt_at||run.finished_at||run.updated_at||'');
    if(byId('preview').getAttribute('src')!==src) byId('preview').src=src;
    byId('actions').append(button('Xem bảng sản phẩm',()=>{ byId('product-run').value=run.run_id; productPage=1; setView('products'); }));
  } else byId('preview-panel').hidden=true;
  if(run.can_stop) byId('actions').append(button(run.status==='cancelling'?'Đang dừng…':'Dừng nghiên cứu',()=>stopRun(run.run_id),'danger'));
  if(!activeStatuses.includes(run.status)) {
    const info=run.screening_diagnostics;
    const retry=button(run.status==='awaiting_trends'&&info?.retry_kind==='free_only'?'Thử lại phần chưa đo bằng nguồn miễn phí':run.status==='awaiting_trends'?'Thử lại bước Trends':'Chạy tiếp phần thiếu',()=>runAction('resume'));
    if(run.status==='awaiting_trends'&&info){retry.disabled=!info.can_retry;retry.title=info.retry_hint||info.action;}
    byId('actions').append(retry);
    if(run.status==='awaiting_trends')byId('actions').append(button('Điều chỉnh ngân sách / keyword trong lượt mới',()=>prepareNewResearch(run)));
    if(available.includes('dataset.json')) byId('actions').append(button('Xuất lại báo cáo',()=>runAction('report')));
  }
  if(available.includes('screening-diagnostic.html'))byId('actions').append(anchor('Xem chẩn đoán sàng lọc ↗',base+'screening-diagnostic.html'));
  byId('actions').append(button(run.saved?'★ Đã lưu':'☆ Lưu nghiên cứu',()=>saveRun(run),'text-button'));
  byId('files-panel').hidden=!available.length; byId('files').replaceChildren();
  for(const name of available.filter(file=>file.endsWith('.csv') || ['report.pdf','pdf-status.json','sources.json','usage.json','validation.json','dataset.json','report-edited.md'].includes(file))) {
    const item=anchor(name,base+name); item.download=name.split('/').at(-1); byId('files').append(item);
  }
}
function prepareNewResearch(run) {
  const config=JSON.parse(JSON.stringify(run.input||{})),limits=config.limits||{};
  recoveryInput=config;
  byId('brief').value=config.brief||'';
  for(const [key,id] of Object.entries(budgetFields))if(limits[key]!=null){byId(id).value='custom';byId(id+'-custom').value=String(limits[key]);byId(id+'-custom').hidden=false;byId(id+'-custom').required=true;}
  if(limits.top_keywords!=null){byId('top-keywords').value='custom';byId('top-keywords-custom').value=String(limits.top_keywords);byId('top-keywords-custom').hidden=false;byId('top-keywords-custom').required=true;}
  for(const [key,id] of Object.entries({free_trends_requests:'free-trends-budget',candidate_keywords:'candidate-keywords',product_details:'product-details',trends_serpapi_requests:'trends-serp-budget',serpapi_product_reserve:'product-reserve',shopping_keywords:'shopping-keywords',monthly_keywords:'monthly-keywords',monthly_rows:'monthly-rows',directions_per_niche:'directions'}))if(limits[key]!=null)byId(id).value=String(limits[key]);
  const trends=config.trends||{},sources=config.sources||{},business=config.business||{};
  byId('history-scope').value=trends.history_scope||'full';byId('history-months').value=(trends.history_months||config.selling_months||[10,11,12]).join(',');byId('analysis-year').value=trends.analysis_year==null?'':String(trends.analysis_year);
  byId('trends-provider').value=sources.trends===false?'off':trends.provider||'auto';byId('monthly-enabled').checked=Boolean(trends.monthly_rankings);
  byId('source-shopping').checked=Boolean(sources.shopping);byId('commentary').checked=Boolean(config.llm?.commentary);
  byId('discovery-focus').value=config.discovery?.focus||'auto';
  byId('web-provider').value=config.discovery?.web_provider||'auto';
  byId('product-collection-mode').value=config.product_collection?.mode||'api';
  for(const source of ['amazon','etsy','reddit'])byId('scrape-'+source).checked=(config.product_collection?.sources||['amazon','etsy','reddit']).includes(source);
  byId('scraper-budget').value=String(config.limits?.scraper_requests??30);
  byId('scraper-detail-limit').value=String(config.product_collection?.detail_limit??2);
  byId('scraper-product-limit').value=String(config.limits?.products_per_direction??20);
  renderCollectionMode();
  byId('business-profile').value=business.profile||'custom_manufacturing';for(const category of companyCategories)byId('business-'+category).checked=business.categories?.includes(category)??true;
  for(const site of publicSites)byId('source-'+site).checked=sources.web!==false&&(config.discovery?.sites||publicSites).includes(site);
  if(config.as_of_date)byId('cutoff').value=config.as_of_date;
  if(config.target_year)byId('forecast-year').value=String(config.target_year);
  if(config.history_years?.length){byId('history-year-mode').value='custom';byId('history-years-custom').value=config.history_years.join(',');byId('history-start').value=String(config.history_years[0]);byId('history-end').value=String(config.history_years.at(-1));}
  byId('months').value=(config.selling_months||[]).join(',');byId('min-price').value=config.price_range?.[0]??'';byId('max-price').value=config.price_range?.[1]??'';byId('preparation').value=config.preparation_days??'';
  byId('seed-keywords').value=(config.niches||[]).flatMap(niche=>niche.seeds||[]).join(', ');
  comparisonPeriods=(config.comparison_periods||[]).map(period=>({...period}));renderHistoryHelp();renderComparisonPeriods();estimateRequests();setView('new');
  notice('Đã điền cấu hình lượt cũ để bạn chỉnh keyword, phạm vi hoặc ngân sách. Chưa tạo lượt mới, chưa gọi API và chưa đổi dữ liệu lượt cũ.');
}
function renderWarnings(run) {
  const activeErrors=(run.errors||[]).filter(error=>run.stages?.[error.stage]?.status==='failed'&&(!run.stages[error.stage].error||run.stages[error.stage].error===error.message));
  const warnings=[...new Set([...(run.warnings||[]),...activeErrors.map(error=>`${error.stage}: ${error.message}`)])];
  byId('warnings-panel').hidden=!warnings.length; byId('warnings').replaceChildren(...warnings.map(warning=>node('li',warning)));
}
async function refreshStatus() {
  if(!selectedRun) return;
  const requestedRun=selectedRun;
  try {
    const run=await api(`/api/runs/${requestedRun}`); if(requestedRun!==selectedRun) return;
    currentRun=run;
    byId('run-title').textContent=titleOf(run); byId('run-id').textContent=run.run_id;
    byId('run-status').textContent=statusLabels[run.status]||run.status;
    renderStages(run); renderFiles(run); renderWarnings(run);
    const messages={partial:'Báo cáo đã có; xem rõ các nguồn còn thiếu bên dưới.',complete:'Đã xuất báo cáo, catalog và dữ liệu.',cancelled:'Đã dừng. Dữ liệu đã nhận và checkpoint được giữ lại; có thể chạy tiếp.',cancelling:'Đang dừng sau yêu cầu hiện tại; không gửi yêu cầu API tiếp theo.',interrupted:'Tiến trình trước đã dừng. Bấm Chạy tiếp phần thiếu để khôi phục.',awaiting_trends:'Chưa có phép đo Trends hợp lệ nên chưa tìm mẫu bằng keyword chưa xác minh. Mở ô Sàng lọc Trends để xem nguồn đã thử và lỗi. Có thể thử lại; nếu ngân sách cũ đã hết, tạo lượt mới để điều chỉnh.'};
    byId('run-message').textContent=run.error||(run.status==='awaiting_trends'&&run.screening_diagnostics?.summary)||run.waiting_reason||run.message||run.stages?.[run.failed_stage]?.error||messages[run.status]||'Đang xử lý: '+(stageNames.find(([id])=>id===run.current_stage)?.[1]||'Chuẩn bị nghiên cứu')+'. Tiến trình cập nhật tự động.';
    if(selectedStage)await loadStageDetail();
    schedulePoll();
  } catch(error) { notice(error.message); }
}
async function startResearch(config) {
  if(!connectionReady){notice(connectionError||'Ứng dụng chưa kết nối xong. Bấm Kiểm tra kết nối lại cạnh nút bắt đầu.');setSubmitting(false);return;}
  notice(config.mode==='offline'?'Đang tạo lượt phân tích từ dữ liệu Q4 đã lưu…':'Đang gửi mô tả và tạo lượt nghiên cứu…');
  setSubmitting(true);
  try { const result=await api('/api/runs',config); notice(); await selectRun(result.run_id); }
  catch(error) { notice(error.message); }
  finally { setSubmitting(false); }
}

function defaultSortOrder(field) { return ['rating','review_count','observed_at'].includes(field)?'desc':'asc'; }
function sortOrderLabel(field,order) {
  if(field==='title') return order==='asc'?'A → Z':'Z → A';
  if(field==='observed_at') return order==='asc'?'Cũ → Mới':'Mới → Cũ';
  return order==='asc'?'Thấp → Cao':'Cao → Thấp';
}
function renderSortEditor() {
  byId('sort-rules').replaceChildren();
  sortDraft.forEach((rule,index)=>{
    const row=node('div',undefined,'sort-rule');
    row.append(node('span','Ưu tiên '+(index+1),'sort-priority'));
    const field=node('select'); field.setAttribute('aria-label','Cột ưu tiên '+(index+1));
    for(const [key,label] of Object.entries(sortLabels)) {
      const option=node('option',label); option.value=key;
      option.disabled=sortDraft.some((other,i)=>i!==index&&other.field===key); field.append(option);
    }
    field.value=rule.field;
    field.onchange=()=>{rule.field=field.value;rule.order=defaultSortOrder(field.value);renderSortEditor();};
    const order=node('select'); order.setAttribute('aria-label','Chiều sắp xếp ưu tiên '+(index+1));
    for(const value of ['asc','desc']){const option=node('option',sortOrderLabel(rule.field,value));option.value=value;order.append(option);}
    order.value=rule.order; order.onchange=()=>{rule.order=order.value;};
    const up=button('↑',()=>{[sortDraft[index-1],sortDraft[index]]=[sortDraft[index],sortDraft[index-1]];renderSortEditor();},'sort-move');
    up.disabled=index===0;up.setAttribute('aria-label','Tăng ưu tiên '+sortLabels[rule.field]);
    const down=button('↓',()=>{[sortDraft[index+1],sortDraft[index]]=[sortDraft[index],sortDraft[index+1]];renderSortEditor();},'sort-move');
    down.disabled=index===sortDraft.length-1;down.setAttribute('aria-label','Giảm ưu tiên '+sortLabels[rule.field]);
    const remove=button('×',()=>{sortDraft.splice(index,1);renderSortEditor();},'sort-move');remove.disabled=sortDraft.length===1;remove.setAttribute('aria-label','Bỏ tiêu chí '+sortLabels[rule.field]);
    row.append(field,order,up,down,remove);byId('sort-rules').append(row);
  });
  byId('sort-add').disabled=sortDraft.length>=Object.keys(sortLabels).length;
  byId('sort-summary').textContent='Đang áp dụng: '+productSorts.map((rule,index)=>`${index+1}. ${sortLabels[rule.field]} (${sortOrderLabel(rule.field,rule.order)})`).join(' → ');
}
function applyProductSorts(rules) {
  if(!rules.length||new Set(rules.map(rule=>rule.field)).size!==rules.length) throw new Error('Chọn ít nhất một tiêu chí; mỗi cột chỉ chọn một lần');
  productSorts=rules.map(rule=>({...rule}));sortDraft=productSorts.map(rule=>({...rule}));
  productPage=1;renderSortEditor();return loadProducts();
}
function productQuery() {
  const primary=productSorts[0];
  const query=new URLSearchParams({run_id:byId('product-run').value||'all',source:byId('product-source').value||'all',q:byId('product-search').value.trim(),saved:byId('products-saved').checked?'1':'0',sort:primary.field,order:primary.order,page:String(productPage)});
  if(productSorts.length>1) query.set('sorts',JSON.stringify(productSorts));
  if(byId('filter-min').value!=='') query.set('min_price',byId('filter-min').value);
  if(byId('filter-max').value!=='') query.set('max_price',byId('filter-max').value);
  return query;
}
async function loadProducts() {
  const token=++productRequest, query=productQuery();
  byId('product-count').textContent='Đang tải sản phẩm…';
  const data=await api('/api/products?'+query);
  if(token!==productRequest) return;
  productPages=Math.max(1,Math.ceil(data.total/data.page_size));
  if(productPage>productPages) { productPage=productPages; return loadProducts(); }
  byId('product-count').textContent=`${data.total} sản phẩm phù hợp · ${data.saved_count} mẫu đã lưu`;
  byId('product-page').textContent=`Trang ${productPage} / ${productPages}`;
  byId('products-prev').disabled=productPage<=1; byId('products-next').disabled=productPage>=productPages;
  byId('products-empty').hidden=data.items.length>0; byId('product-rows').replaceChildren();
  for(const row of data.items) {
    const tr=node('tr'), star=node('td'); star.append(button(row.saved?'★':'☆',async()=>{await api('/api/workspace/save',{kind:'product',run_id:row.run_id,product_id:row.product_id,saved:!row.saved}); await loadProducts();},'save-star'+(row.saved?' saved':''))); tr.append(star);
    const name=node('td',undefined,'product-name'); name.append(anchor(row.title,row.url),node('small',row.asin||row.product_id)); tr.append(name);
    tr.append(node('td',row.price===null?'—':number(row.price)+' '+(row.currency||'?'),'number'),node('td',number(row.rating),'number'),node('td',number(row.review_count),'number'));
    const source=node('td',row.source==='amazon'?'Amazon':'Shopping'); source.append(node('small',row.merchant||'')); tr.append(source,node('td',String(row.observed_at||'—').slice(0,10)));
    const research=node('td',undefined,'research-cell'); research.append(button(row.research,()=>selectRun(row.run_id),'text-button'),node('small',row.mode==='offline'?'Dữ liệu lưu trữ':'Nguồn thật')); tr.append(research);
    byId('product-rows').append(tr);
  }
  for(const field of Object.keys(sortLabels)) {
    const index=productSorts.findIndex(rule=>rule.field===field), rule=productSorts[index];
    byId('sort-'+field).className=rule?'sorted':'';
    byId('sort-'+field).textContent=sortLabels[field]+' '+(rule?(rule.order==='asc'?'↑':'↓')+' '+(index+1):'↕');
  }
  query.delete('page'); byId('export-products').href='/api/products/export.csv?'+query;
}
async function openEditor(runId) {
  const data=await api(`/api/runs/${runId}/editor`);
  if(!setView('editor')) return;
  editorRun=runId; editorDirty=false;
  byId('editor-title').value=data.title; byId('editor-content').value=data.content;
  byId('editor-state').textContent=data.updated_at?'Đã lưu '+formatDate(data.updated_at):'Đang xem nội dung từ báo cáo gốc';
  byId('editor-links').replaceChildren();
  if(data.edited) byId('editor-links').append(anchor('Mở bản biên tập ↗',`/outputs/${runId}/report-edited.html`),anchor('Tải Markdown ↓',`/outputs/${runId}/report-edited.md`));
}
async function saveEditor() {
  byId('editor-save').disabled=true;
  byId('editor-title').disabled=true; byId('editor-content').disabled=true;
  try {
    const result=await api(`/api/runs/${editorRun}/editor`,{title:byId('editor-title').value,content:byId('editor-content').value});
    editorDirty=false; byId('editor-state').textContent='Đã lưu '+formatDate(result.updated_at);
    byId('editor-links').replaceChildren(anchor('Mở bản biên tập ↗',result.url),anchor('Tải Markdown ↓',`/outputs/${editorRun}/report-edited.md`));
    notice('Đã lưu bản biên tập riêng; báo cáo gốc được giữ nguyên.'); await loadLibrary();
  } finally { byId('editor-save').disabled=false; byId('editor-title').disabled=false; byId('editor-content').disabled=false; }
}

byId('research-form').addEventListener('submit',event=>{
  event.preventDefault();
  try {
    const limits=Object.fromEntries(Object.entries(budgetFields).map(([key,id])=>[key,budgetValue(id)]));
    limits.directions_per_niche=Number(byId('directions').value);
    limits.top_keywords=topKeywordValue();
    const seeds=byId('seed-keywords').value.split(',').map(value=>value.trim()).filter(Boolean);
    if(!limits.llm_requests && !seeds.length) throw new Error('Đặt OpenRouter bằng 0 cần nhập keyword tiếng Anh trong Thiết lập nghiên cứu. Hoặc chọn ít nhất 1 lượt LLM để hiểu mô tả.');
    if(seeds.some(seed=>!/^[\x20-\x7e]{2,200}$/.test(seed))) throw new Error('Keyword nhập sẵn cần là cụm từ tiếng Anh từ 2–200 ký tự');
    limits.free_trends_requests=integerInput('free-trends-budget',0,1000);
    limits.candidate_keywords=integerInput('candidate-keywords',1,100);
    limits.product_details=integerInput('product-details',0,1000);
    limits.trends_serpapi_requests=integerInput('trends-serp-budget',0,1000);
    limits.serpapi_product_reserve=integerInput('product-reserve',0,1000);
    limits.shopping_keywords=integerInput('shopping-keywords',0,100);
    limits.monthly_keywords=integerInput('monthly-keywords',1,100);
    limits.monthly_rows=integerInput('monthly-rows',1,50);
    limits.scraper_requests=integerInput('scraper-budget',0,1000);
    limits.products_per_direction=integerInput('scraper-product-limit',1,100);
    const collectionMode=byId('product-collection-mode').value||'scraper';
    const provider=byId('trends-provider').value;
    const sites=publicSites.filter(site=>byId('source-'+site).checked);
    const config={brief:byId('brief').value.trim(),mode:'live',limits,llm:{enabled:limits.llm_requests>0,commentary:byId('commentary').checked},
      business:{profile:byId('business-profile').value,categories:companyCategories.filter(category=>byId('business-'+category).checked)},
      product_collection:{mode:collectionMode,sources:['amazon','etsy','reddit'].filter(source=>byId('scrape-'+source).checked),detail_limit:integerInput('scraper-detail-limit',0,20),cache_hours:24},
      discovery:{enabled:true,sites,web_provider:['auto','tavily','exa','combined'].includes(byId('web-provider').value)?byId('web-provider').value:'auto',focus:['auto','designs','models'].includes(byId('discovery-focus').value)?byId('discovery-focus').value:'designs'},trends:{provider:['auto','free','serpapi'].includes(provider)?provider:'free',monthly_rankings:byId('monthly-enabled').checked,history_scope:byId('history-scope').value,history_months:collectionMonths(),analysis_year:byId('history-scope').value==='seasonal'?analysisYear():null},
      sources:{trends:provider!=='off',amazon:limits.serpapi_requests>0,shopping:byId('source-shopping').checked&&limits.serpapi_requests>0,web:sites.length>0&&(byId('web-provider').value==='exa'?limits.exa_requests>0:byId('web-provider').value==='tavily'?limits.tavily_requests>0:limits.tavily_requests+limits.exa_requests>0)}};
    if(recoveryInput){
      for(const field of ['required_features','excluded_features','preferences','category','assumptions'])if(recoveryInput[field]!=null)config[field]=recoveryInput[field];
      for(const [key,value] of Object.entries(recoveryInput.limits||{}))if(!(key in config.limits))config.limits[key]=value;
      for(const field of ['anchor','screen_days','cache_hours','required'])if(recoveryInput.trends?.[field]!=null)config.trends[field]=recoveryInput.trends[field];
      if(recoveryInput.sources?.amazon===false&&limits.serpapi_requests===recoveryInput.limits?.serpapi_requests)config.sources.amazon=false;
      if(recoveryInput.llm?.enabled===false&&limits.llm_requests===recoveryInput.limits?.llm_requests)config.llm.enabled=false;
    }
    if(collectionMode==='scraper'){config.sources.amazon=false;config.sources.shopping=false;config.limits.serpapi_product_reserve=0;}
    if(config.business.profile==='custom_manufacturing'&&!config.business.categories.length)throw new Error('Chọn ít nhất một nhóm hàng công ty có thể gia công');
    if(seeds.length) config.niches=recoveryInput?.niches?.length&&seeds.join(',')===recoveryInput.niches.flatMap(niche=>niche.seeds||[]).join(',')?recoveryInput.niches:[{name:config.brief.slice(0,120)||'Nghiên cứu từ keyword nhập sẵn',name_en:seeds[0],seeds}];
    if(byId('cutoff').value) config.as_of_date=byId('cutoff').value;
    config.comparison_periods=comparisonValues();
    config.history_years=historicalYears();
    config.target_year=Number(byId('forecast-year').value);
    if(byId('months').value.trim()) config.selling_months=byId('months').value.split(',').map(value=>Number(value.trim()));
    if(config.trends.history_scope==='seasonal'){
      config.trends.monthly_rankings=true;
      if(config.selling_months?.some(month=>!config.trends.history_months.includes(month)))throw new Error('Tháng bán phải nằm trong các tháng được thu thập theo mùa');
      for(const period of config.comparison_periods){const [sy,sm]=period.start.split('-').map(Number),[ey,em]=period.end.split('-').map(Number);for(let value=sy*12+sm-1;value<=ey*12+em-1;value++){if(!config.history_years.includes(Math.floor(value/12))||!config.trends.history_months.includes(value%12+1))throw new Error('Khoảng so sánh vượt các năm/tháng được chọn thu thập');}}
    }
    if(byId('min-price').value!=='' && byId('max-price').value!=='') config.price_range=[Number(byId('min-price').value),Number(byId('max-price').value)];
    if(byId('preparation').value!=='') config.preparation_days=Number(byId('preparation').value);
    startResearch(config);
  } catch(error) { notice(error.message); }
});
byId('demo').onclick=()=>{
  try {return startResearch({brief:'Phát lại nghiên cứu quà và decor Q4: Halloween, Thanksgiving, Christmas tại Mỹ.',mode:'offline',as_of_date:'2026-10-22',target_year:2026,selling_months:[10,11,12],limits:{serpapi_requests:0,tavily_requests:0,llm_requests:0,top_keywords:topKeywordValue()},llm:{enabled:false,commentary:false}});}
  catch(error){notice(error.message);}
};
byId('refresh').onclick=guard(loadLibrary);
byId('connection-retry').onclick=()=>initializeApplication();
byId('close-run').onclick=closeRun;
byId('stage-detail-close').onclick=closeStageDetail;
byId('comparison-add').onclick=()=>{comparisonPeriods=comparisonValues(false);if(comparisonPeriods.length<12){const year=Number((byId('cutoff').value||'2026').slice(0,4))-3+comparisonPeriods.length;comparisonPeriods.push({start:`${year}-10`,end:`${year}-12`});renderComparisonPeriods();}};
byId('comparison-q4').onclick=()=>{comparisonPeriods=historicalYears(false).map(year=>({start:`${year}-10`,end:`${year}-12`}));renderComparisonPeriods();};
byId('comparison-annual').onclick=()=>{comparisonPeriods=[];renderComparisonPeriods();};
byId('history-2021-preset').onclick=()=>{byId('history-year-mode').value='range';byId('history-start').value='2021';byId('history-end').value='2025';byId('history-years-custom').value='2021,2022,2023,2024,2025';byId('forecast-year').value='2026';renderHistoryHelp();renderComparisonPeriods();estimateRequests();};
for(const id of ['history-year-mode','history-start','history-end','history-years-custom','forecast-year','cutoff'])byId(id).addEventListener('change',()=>{
  if(['history-start','history-end'].includes(id)&&byId('history-year-mode').value!=='custom')byId('history-years-custom').value=historicalYears(false).join(',');
  comparisonPeriods=comparisonValues(false);renderHistoryHelp();renderComparisonPeriods();estimateRequests();
});
byId('nav-new').onclick=()=>{if(setView('new')){recoveryInput=null;byId('brief').value='';byId('brief').focus?.();}};
byId('screen-diagnostic-new').onclick=()=>{if(currentRun)prepareNewResearch(currentRun);};
for(const view of ['history','products','reports','saved']) byId('nav-'+view).onclick=()=>{setView(view);if(view!=='products') loadLibrary().catch(error=>notice(error.message));};
byId('budget-defaults').onclick=()=>{populateBudgets();byId('trends-serp-budget').value=String(defaultLimits.trends_serpapi_requests??8);byId('product-reserve').value=String(defaultLimits.serpapi_product_reserve??10);byId('free-trends-budget').value=String(defaultLimits.free_trends_requests??40);estimateRequests();};
byId('credit-economy-preset').onclick=applyCreditEconomyPreset;
byId('product-collection-mode').addEventListener('change',renderCollectionMode);
byId('scraper-budget').addEventListener('change',estimateRequests);
for(const id of ['top-keywords','top-keywords-custom','candidate-keywords','product-details','source-shopping','shopping-keywords','budget','budget-custom','trends-provider','trends-serp-budget','product-reserve','monthly-enabled','monthly-keywords'])byId(id).addEventListener('change',estimateRequests);
byId('broad-monthly-preset').onclick=()=>{try{applyResearchPreset(false);}catch(error){notice(error.message);}};
byId('seasonal-economy-preset').onclick=()=>{try{applyResearchPreset(true);}catch(error){notice(error.message);}};
for(const id of ['history-scope','history-months','analysis-year'])byId(id).addEventListener('change',()=>{renderCollectionHelp();renderComparisonPeriods();estimateRequests();});
byId('history-months').addEventListener('input',()=>{renderCollectionHelp();renderComparisonPeriods();estimateRequests();});
for(let month=1;month<=12;month++)byId('history-month-'+month).addEventListener('change',()=>{
  byId('history-months').value=Array.from({length:12},(_,index)=>index+1).filter(value=>byId('history-month-'+value).checked).join(',');
  renderCollectionHelp();renderComparisonPeriods();estimateRequests();
});
for(const [id,months] of [['history-months-q4','10,11,12'],['history-months-all','1,2,3,4,5,6,7,8,9,10,11,12']])byId(id).onclick=()=>{
  byId('history-months').value=months;renderCollectionHelp();renderComparisonPeriods();estimateRequests();
};
for(const id of ['monthly-month','monthly-sort'])byId(id).addEventListener('change',()=>{if(currentRun)renderMonthlyKeywords(currentRun);});
byId('active-open').onclick=guard(()=>activeRun&&selectRun(activeRun.run_id));
byId('active-stop').onclick=guard(()=>activeRun&&stopRun(activeRun.run_id));
byId('show-report').onclick=()=>{previewKind='report';refreshStatus();};
byId('show-catalog').onclick=()=>{previewKind='catalog';refreshStatus();};
byId('history-search').addEventListener('input',renderResearchCards); byId('history-status').onchange=renderResearchCards;
for(const id of ['product-run','product-source','products-saved']) byId(id).onchange=guard(()=>{productPage=1;return loadProducts();});
byId('filter-apply').onclick=guard(()=>{productPage=1;return loadProducts();});
byId('product-search').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();productPage=1;loadProducts().catch(error=>notice(error.message));}});
byId('filter-reset').onclick=guard(()=>{for(const id of ['product-search','filter-min','filter-max'])byId(id).value='';byId('product-run').value='all';byId('product-source').value='all';byId('products-saved').checked=false;productPage=1;return loadProducts();});
for(const field of Object.keys(sortLabels)) byId('sort-'+field).onclick=guard(()=>applyProductSorts([{field,order:productSorts.length===1&&productSorts[0].field===field?(productSorts[0].order==='asc'?'desc':'asc'):defaultSortOrder(field)}]));
byId('sort-add').onclick=()=>{const field=Object.keys(sortLabels).find(field=>!sortDraft.some(rule=>rule.field===field));if(field){sortDraft.push({field,order:defaultSortOrder(field)});renderSortEditor();}};
byId('sort-apply').onclick=guard(()=>applyProductSorts(sortDraft));
byId('sort-stars-price').onclick=guard(()=>applyProductSorts([{field:'rating',order:'desc'},{field:'price',order:'asc'}]));
byId('sort-price-stars').onclick=guard(()=>applyProductSorts([{field:'price',order:'asc'},{field:'rating',order:'desc'}]));
byId('sort-default').onclick=guard(()=>applyProductSorts([{field:'observed_at',order:'desc'}]));
byId('products-prev').onclick=guard(()=>{if(productPage>1)productPage--;return loadProducts();});
byId('products-next').onclick=guard(()=>{if(productPage<productPages)productPage++;return loadProducts();});
byId('open-saved-products').onclick=()=>{byId('products-saved').checked=true;byId('product-run').value='all';productPage=1;setView('products');};
for(const id of ['editor-title','editor-content'])byId(id).addEventListener('input',()=>{editorDirty=true;byId('editor-state').textContent='Có thay đổi chưa lưu';});
byId('editor-save').onclick=guard(saveEditor); byId('editor-cancel').onclick=()=>setView('reports');
globalThis.addEventListener?.('beforeunload',event=>{if(editorDirty){event.preventDefault();event.returnValue='';}});

async function initializeApplication(){
  if(connectionChecking)return;
  connectionChecking=true;connectionReady=false;connectionError='';setSubmitting(submitting);
  try {
    const settings=await api('/api/settings');
    const incompatible=settings.capabilities?.seasonal_history!==true||settings.capabilities?.company_domain!==true||settings.capabilities?.design_month_screening!==true||settings.capabilities?.manufacturing_models!==true||settings.capabilities?.design_content!==true||settings.capabilities?.exa_discovery!==true||settings.capabilities?.public_scrapers!==true;
    byId('web-provider-status').textContent=`Tavily: ${settings.keys?.TAVILY_API_KEY?'đã có key':'chưa có key'} · Exa: ${settings.keys?.EXA_API_KEY?'đã có key':'chưa có key — thêm EXA_API_KEY vào .env'}`;
    defaultLimits=settings.limits; stageNames=settings.stages;
    if(!formInitialized){
    populateBudgets();populateTopKeywords();renderSortEditor(); byId('directions').value=String(Math.min(4,defaultLimits.directions_per_niche||1)); byId('progress').max=stageNames.length;
    byId('free-trends-budget').value=String(defaultLimits.free_trends_requests??40);byId('candidate-keywords').value=String(defaultLimits.candidate_keywords??64);byId('product-details').value=String(defaultLimits.product_details??3);byId('trends-provider').value='auto';
    byId('monthly-enabled').checked=true;byId('monthly-keywords').value=String(defaultLimits.monthly_keywords??64);byId('monthly-rows').value=String(defaultLimits.monthly_rows??10);
    for(let month=1;month<=12;month++){const option=node('option','Tháng '+month);option.value=String(month);byId('monthly-month').append(option);}byId('monthly-month').value='1';byId('monthly-sort').value='seasonality';
    byId('trends-serp-budget').value=String(defaultLimits.trends_serpapi_requests??8);byId('product-reserve').value=String(defaultLimits.serpapi_product_reserve??10);
    byId('shopping-keywords').value=String(defaultLimits.shopping_keywords??2);
    byId('history-scope').value='seasonal';byId('history-months').value='10,11,12';byId('business-profile').value='custom_manufacturing';for(const category of companyCategories)byId('business-'+category).checked=true;
    byId('product-collection-mode').value='scraper';
    for(const source of ['amazon','etsy','reddit'])byId('scrape-'+source).checked=true;
    byId('scraper-budget').value=String(defaultLimits.scraper_requests??30);byId('scraper-detail-limit').value='2';
    byId('scraper-product-limit').value='20';
    renderCollectionMode();
    byId('discovery-focus').value='designs';
    byId('web-provider').value=settings.keys?.TAVILY_API_KEY&&settings.keys?.EXA_API_KEY?'combined':'auto';
    for(const site of publicSites)byId('source-'+site).checked=true;
    estimateRequests();
    const missing=Object.entries(settings.keys).filter(([,present])=>!present).map(([key])=>key.replace('_API_KEY',''));
    byId('keys').textContent=missing.length?'Chưa có key: '+missing.join(', '):'Các nguồn đã có key cấu hình';
    const date=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Bangkok',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
    const part=name=>date.find(item=>item.type===name).value; byId('cutoff').value=`${part('year')}-${part('month')}-${part('day')}`;
    const currentYear=Number(part('year'));byId('history-year-mode').value='range';byId('history-start').value=String(currentYear-3);byId('history-end').value=String(currentYear-1);byId('forecast-year').value=String(currentYear);byId('history-years-custom').value=historicalYears(false).join(',');
    renderHistoryHelp();renderComparisonPeriods();estimateRequests();
    byId('product-source').value='all'; byId('history-status').value='all';
    formInitialized=true;
    }
    await loadLibrary();byId('refresh').disabled=false;
    if(incompatible)throw new Error('Server đang chạy code cũ, chưa hỗ trợ Exa và khám phá nội dung mẫu gia công theo tháng/năm của giao diện mới. Dừng server cũ bằng Ctrl+C, chạy lại python run.py rồi bấm Kiểm tra kết nối lại.');
    connectionReady=true;notice();
  } catch(error){connectionError='Không khởi tạo được giao diện: '+error.message;notice(connectionError);}
  finally{connectionChecking=false;setSubmitting(submitting);}
}
initializeApplication();

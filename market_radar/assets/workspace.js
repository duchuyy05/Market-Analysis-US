'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g,c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dateText = value => /^\d{4}-\d{2}-\d{2}/.test(value || '') ? value.slice(0,10).split('-').reverse().join('/') : '';
const num = value => new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(value);
const safeURL = value => /^https?:\/\//i.test(value || '') ? esc(value) : '#';
let boot, token, studies = [], selectedId = null, view = 'results', draft = null, planning = {}, jobId = null, lastJob = null, timer = null;
let months = new Set([10,11,12]);
const ongoing = job => ['queued','running'].includes(job?.status);
const aiAvailable = () => !!boot?.keys.OPENROUTER_API_KEY && (boot.model.endsWith(':free') || boot.model==='openrouter/free');
const dateTimeText = value => value && Number.isFinite(Date.parse(value)) ? new Intl.DateTimeFormat('vi-VN',{dateStyle:'short',timeStyle:'short',timeZone:'Asia/Bangkok'}).format(new Date(value)) : '';
function notify(text,kind='') { $('notice').textContent=text; $('notice').className='notice '+kind; $('notice').hidden=!text; }
async function api(path,payload) {
  const options = payload === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-Radar-Token':token},body:JSON.stringify(payload)};
  const response = await fetch(path,options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Yêu cầu chưa hoàn tất');
  return result;
}
function setView(next) {
  view=next;
  for (const name of ['results','create','progress']) {
    $(name+'View').hidden=name!==next;
    $(name+'Tab').setAttribute('aria-selected',String(name===next));
  }
}
function renderLibrary() {
  const query=$('studySearch').value.trim().toLowerCase();
  const shown=studies.filter(s => (s.category+' '+(s.display_name || '')+' '+s.niches.join(' ')).toLowerCase().includes(query));
  $('studyList').innerHTML=shown.map(s => `<button type="button" class="study-card" data-study="${esc(s.id)}" aria-selected="${s.id===selectedId}"><span class="scope">Tháng ${s.months.join(', ')} / ${s.years[0]}–${s.years.at(-1)}</span><strong>${esc(s.display_name || s.category)}</strong><small>${s.products} sản phẩm · ${s.reviews} nội dung nhận xét</small><small>${s.ready ? '● Có báo cáo' : '◌ Chưa có báo cáo'}${s.status==='failed' ? ' · Cần kiểm tra lỗi' : ''}</small></button>`).join('') || '<p class="help">Chưa có nghiên cứu phù hợp.</p>';
  document.querySelectorAll('[data-study]').forEach(b => b.addEventListener('click',() => selectStudy(b.dataset.study)));
}
function selectStudy(id) {
  const study=studies.find(s => s.id===id);
  if (!study) return;
  if ($('productModal').open) $('productModal').close();
  selectedId=id;
  try { localStorage.setItem('radar-selected-study',id); } catch {}
  renderLibrary(); setView('results');
  $('resultTitle').textContent=study.display_name || study.category;
  $('resultMeta').textContent=`Tháng ${study.months.join(', ')} · Các năm ${study.years.join(', ')} · Dữ liệu tìm kiếm đến ${dateText(study.as_of_date)}`;
  $('cloneButton').disabled=false;
  $('rebuildButton').disabled=ongoing(lastJob);
  $('supplementPanel').hidden=!study.ready;
  $('supplementButton').disabled=ongoing(lastJob) || !study.ready || !boot?.keys.SERPAPI_API_KEY;
  renderReport(study);
  $('resultEmpty').hidden=study.ready;
  $('resultFrame').hidden=!study.ready;
  $('resultFrame').src=study.ready ? '/runs/'+encodeURIComponent(id)+'/dashboard.html?embed=1&v='+Date.now() : 'about:blank';
  renderSummary(study);
  const warnings=[...(study.warnings || []),...(study.source_errors || []).map(e => e.source+': '+e.error)];
  if (!study.ready) warnings.unshift('Lượt này chưa có kết quả hoàn chỉnh. Có thể thử dựng lại offline từ các nguồn đã lưu.');
  $('resultWarnings').textContent=[...new Set(warnings)].join('\n'); $('resultWarnings').hidden=!warnings.length;
}

function renderReport(study) {
  $('reportPanel').hidden=!study.ready;
  const report=study.report || {}, llm=report.llm, available=!!report.available;
  const root='/runs/'+encodeURIComponent(study.id)+'/';
  const running=ongoing(lastJob) && lastJob.kind==='report' && lastJob.study_id===study.id;
  $('reportStatus').textContent=running ? 'Đang viết phân tích AI' : !available ? 'Chưa có báo cáo' : !report.current ? 'Cần cập nhật theo dữ liệu mới' : llm ? 'Đã có phân tích AI' : 'Chưa có phân tích AI';
  $('reportStatus').className='report-status '+(llm && report.current ? 'ready' : '');
  $('reportDescription').textContent=llm ? `Báo cáo có ${llm.insight_count} nhận định AI kèm nguồn để bạn đối chiếu với số liệu.` : 'Bản hiện tại tổng hợp số liệu, sản phẩm và xu hướng theo tháng. Bạn có thể thêm phân tích AI từ chính dữ liệu này.';
  $('reportModel').textContent=(llm ? `Model đã dùng: ${llm.model} · Viết lúc ${dateTimeText(llm.created_at_utc)}. ` : '')+(report.generated_at_utc ? `Xuất báo cáo lúc ${dateTimeText(report.generated_at_utc)} (giờ Việt Nam).` : '');
  $('aiReportButton').textContent=llm ? 'Viết lại phân tích bằng AI' : 'Tạo báo cáo bằng AI';
  $('aiReportButton').disabled=ongoing(lastJob) || !study.ready || !aiAvailable();
  $('aiReportHelp').textContent=aiAvailable() ? `Chỉ gọi OpenRouter với model ${boot.model}; dùng dữ liệu đã lưu, không lấy lại qua SerpApi/Tavily. Có thể mất vài phút tùy tốc độ phản hồi của model.` : 'Để dùng AI, điền OPENROUTER_API_KEY và chọn OPENROUTER_MODEL miễn phí (:free) trong api/.env, sau đó tải lại trang.';
  for (const [id,file,query] of [['reportLink','report.html',''],['downloadReportHTML','report.html','?download=1'],['downloadReportMD','report.md','?download=1'],['printReport','report.html','?print=1']]) {
    $(id).hidden=!available; $(id).href=root+file+query;
  }
  $('aiReportFiles').hidden=!report.ai_input_available;
  $('aiInputLink').href=root+'ai-input.json';
  $('aiInsightsLink').href=root+'llm-insights.json'; $('aiInsightsLink').hidden=!llm;
  $('reportWarnings').textContent=(study.report_warnings || []).join('\n'); $('reportWarnings').hidden=!(study.report_warnings || []).length;
  const files=(study.exports || []).filter(f => /^[a-z][a-z0-9_]*\.csv$/.test(f.filename));
  $('csvDownloads').hidden=!files.length;
  $('csvFileCount').textContent=`${files.length} file trong nghiên cứu này`;
  $('csvFileList').innerHTML=files.map(f => `<a class="csv-file" href="${root+encodeURIComponent(f.filename)}" download="${esc(f.filename)}"><span class="csv-file-info"><strong>${esc(f.title)}</strong><small>${esc(f.description)}</small><code>${esc(f.filename)} · ${num(f.rows)} dòng dữ liệu</code></span><span class="csv-file-action">Tải CSV ↓</span></a>`).join('');
}

function renderSummary(study) {
  const summary=study.summary;
  $('librarySummary').hidden=!summary || !study.ready;
  $('datasetOverview').hidden=!summary || !study.ready;
  if (!summary || !study.ready) return;
  $('librarySummary').innerHTML='<h3>Tóm tắt dữ liệu đang xem</h3><div class="summary-numbers">'+
    [['Sản phẩm',summary.products],['Nhận xét đầy đủ',summary.full_reviews ?? summary.reviews],['Trích đoạn nhận xét',summary.review_excerpts ?? 0],['Từ khóa',summary.keywords]]
      .map(([label,value]) => `<div><strong>${num(value)}</strong><span>${label}</span></div>`).join('')+
    `</div><p>${summary.reviewed_products}/${summary.products} sản phẩm có nhận xét hoặc trích đoạn. ${summary.web_sources} trang web tham khảo.</p>`;
  const bar=(label,value,total,text,note='') => `<div class="summary-bar"><div class="summary-bar-label"><span>${esc(label)}</span><strong>${esc(text)}</strong></div><div class="summary-bar-track"><span style="width:${total ? Math.max(0,Math.min(100,value/total*100)) : 0}%"></span></div>${note ? `<small>${esc(note)}</small>` : ''}</div>`;
  $('priceChart').innerHTML=summary.price_bins.map(b => bar(b.label,b.count,summary.products,`${b.count} sản phẩm`)).join('');
  $('priceNote').textContent=(summary.median_price_usd == null ? 'Chưa có giá để tính trung vị.' : `Giá trung vị: $${num(summary.median_price_usd)}.`)+
    (summary.missing_prices ? ` Có ${summary.missing_prices} sản phẩm chưa có giá.` : '');
  $('coverageChart').innerHTML=summary.groups.map(g => bar(g.name,g.reviewed_products,g.products,`${g.reviewed_products}/${g.products} sản phẩm`,`${g.reviews} nội dung nhận xét và trích đoạn`)).join('');
  $('productsCSV').href='/runs/'+encodeURIComponent(study.id)+'/products.csv';
  $('reviewsCSV').href='/runs/'+encodeURIComponent(study.id)+'/reviews.csv';
}

function showProductModal(product) {
  const fields=[['Mã ASIN',product.asin],['Thương hiệu',product.brand],['Giá cả gói (USD)',product.price_usd],['Màu sắc',product.color],
    ['Kích cỡ',product.size],['Kích thước',product.dimensions],['Chất liệu',product.material],['Mùi hương',product.scent],
    ['Số món theo mô tả',product.listing_number_of_items],['Lượt mua Amazon hiển thị',product.bought_past_month_text],['Nhận xét đầy đủ',product.full_reviews_collected ?? product.customer_reviews_collected],['Trích đoạn nhận xét',product.review_excerpts_collected ?? 0]];
  $('productModalBody').innerHTML=`<p class="eyebrow">THÔNG TIN SẢN PHẨM</p><h2 id="productModalTitle">${esc(product.product_name)}</h2><p class="help">ASIN là mã gồm 10 chữ hoặc số dùng để nhận diện sản phẩm trên Amazon.</p><dl>${fields.map(([label,value]) => `<div><dt>${label}</dt><dd>${esc(value ?? 'Chưa có thông tin')}</dd></div>`).join('')}</dl><h3>Mô tả từ trang sản phẩm</h3><p class="description">${esc(product.description || product.seller_features || 'Chưa có mô tả')}</p><a class="source-link" href="${safeURL(product.source_url)}" target="_blank" rel="noopener">Xem sản phẩm trên Amazon ↗</a><p class="help">Ngày lấy dữ liệu: ${dateText(product.observed_at_utc) || 'Chưa rõ'}. Màu sắc, kích thước và chất liệu là thông tin do người bán cung cấp.</p>`;
  if (!$('productModal').open) $('productModal').showModal();
}
window.addEventListener('message',event => {
  if (event.origin!==window.location.origin || event.source!==$('resultFrame').contentWindow || $('resultFrame').hidden) return;
  const message=event.data;
  if (message?.type==='market-analysis:height') {
    if (typeof message.height==='number' && Number.isFinite(message.height) && message.height>=300 && message.height<=100000) $('resultFrame').style.height=Math.ceil(message.height)+'px';
    return;
  }
  if (message?.type!=='market-analysis:product' || !message.product || !/^[A-Z0-9]{10}$/.test(message.product.asin || '')) return;
  showProductModal(message.product);
});
$('closeProductModal').addEventListener('click',() => $('productModal').close());
async function refreshStudies() {
  studies=await api('/api/studies'); renderLibrary();
  const selected=studies.find(s => s.id===selectedId);
  if (selected) {
    const previousView=view;
    selectStudy(selected.id);
    setView(previousView);
  }
}
function renderMonths() {
  $('monthPicker').innerHTML=Array.from({length:12},(_,i) => `<button type="button" data-pick-month="${i+1}" aria-pressed="${months.has(i+1)}">T${i+1}</button>`).join('');
  document.querySelectorAll('[data-pick-month]').forEach(b => b.addEventListener('click',() => {
    const m=Number(b.dataset.pickMonth); months.has(m) ? months.delete(m) : months.add(m);
    $('quarterSelect').value='custom'; invalidateDraft(); renderMonths();
  }));
}
function invalidateDraft() { draft=null; $('planPanel').hidden=true; }
function setForm(config) {
  $('topicInput').value=config.category;
  $('nicheInput').value=config.niches.map(n => n.name_vi || n.name).join(', ');
  $('keywordsInput').value=config.families.map(f => f.keyword).join('\n');
  months=new Set(config.months); renderMonths();
  $('quarterSelect').value=[1,2,3,4].find(q => JSON.stringify([...months].sort((a,b) => a-b))===JSON.stringify([q*3-2,q*3-1,q*3])) || 'custom';
  $('startYear').value=Math.min(...config.years); $('endYear').value=Math.max(...config.years);
  $('asOfInput').value=config.as_of_date; $('sampleSize').value=config.products_per_family;
  $('topCount').value=config.top_n || 5; $('requestBudget').value=config.max_serpapi_requests || 56;
}
function formRequest() {
  const start=Number($('startYear').value), end=Number($('endYear').value);
  if (!Number.isInteger(start) || !Number.isInteger(end) || end<start || end-start>=8) throw new Error('Chọn khoảng năm hợp lệ, tối đa tám năm.');
  if (!months.size) throw new Error('Chọn ít nhất một tháng.');
  const request={topic:$('topicInput').value.trim(),niche:$('nicheInput').value.trim(),keywords:$('keywordsInput').value,
    months:[...months].sort((a,b) => a-b),years:Array.from({length:end-start+1},(_,i) => start+i),as_of_date:$('asOfInput').value,
    products_per_family:Number($('sampleSize').value),top_n:Number($('topCount').value),
    max_serpapi_requests:Number($('requestBudget').value),use_llm:$('useAIPlan').checked};
  const preset=boot.presets.find(p => p.id===$('presetSelect').value);
  if (preset?.config && preset.keywords.join('\n')===request.keywords && preset.topic===request.topic) {
    request.config={...structuredClone(preset.config),category:request.topic,months:request.months,years:request.years,
      as_of_date:request.as_of_date,products_per_family:request.products_per_family,top_n:request.top_n,max_serpapi_requests:request.max_serpapi_requests};
  }
  return request;
}
function renderPlan() {
  if (!draft) return;
  $('planPanel').hidden=false;
  const count=draft.families.length, expected=count*(2+draft.products_per_family)+draft.max_mobile_review_requests;
  const planSource={openrouter:'AI gợi ý',manual:'Từ khóa bạn đã nhập',configured:'Cấu hình có sẵn',cloned:'Sao chép từ nghiên cứu trước',topic_fallback:'Dùng chủ đề làm từ khóa'};
  $('planSummary').textContent=`${draft.niches.length} nhóm nghiên cứu, ${count} loại sản phẩm; tháng ${draft.months.join(', ')}. Dự kiến lấy tối đa ${count*draft.products_per_family} sản phẩm trước khi lọc. Nếu chưa có dữ liệu lưu sẵn, cần khoảng ${expected} lần gọi SerpApi và ${draft.niches.length} lần gọi Tavily. Giới hạn SerpApi: ${draft.max_serpapi_requests}. ${planSource[planning.mode] || 'Theo cấu hình bạn chọn'}.`;
  const warnings=[...(planning.warnings || [])];
  if (expected>draft.max_serpapi_requests) warnings.push('Cỡ mẫu dự kiến có thể vượt giới hạn yêu cầu; giảm số nhóm/cỡ mẫu hoặc tăng giới hạn trong phạm vi quota của bạn.');
  $('planWarnings').textContent=warnings.join('\n'); $('planWarnings').hidden=!warnings.length;
  $('planRows').innerHTML=draft.families.map((f,i) => `<tr><td><input data-family="${i}" data-field="name_vi" aria-label="Tên nhóm ${i+1}" value="${esc(f.name_vi)}"><small>${esc(f.id)}</small></td><td>${esc(draft.niches.find(n => n.id===f.niche_id)?.name_vi || f.niche_id)}</td><td><input data-family="${i}" data-field="keyword" aria-label="Keyword nhóm ${i+1}" value="${esc(f.keyword)}"></td><td><input data-family="${i}" data-field="amazon_query" aria-label="Truy vấn Amazon nhóm ${i+1}" value="${esc(f.amazon_query)}"></td></tr>`).join('');
  document.querySelectorAll('[data-family]').forEach(input => input.addEventListener('input',() => {
    draft.families[Number(input.dataset.family)][input.dataset.field]=input.value;
    $('configEditor').value=JSON.stringify(draft,null,2);
  }));
  $('configEditor').value=JSON.stringify(draft,null,2);
  $('runButton').disabled=ongoing(lastJob);
}
function readableLog(message) {
  if (/Network\/timeout/.test(message)) return 'Không kết nối được dịch vụ hoặc chờ quá lâu. Dữ liệu đã lấy được giữ lại.';
  if (/Local .*request budget reached/.test(message)) return 'Đã đạt giới hạn số lần gọi API của nghiên cứu.';
  if (/^Nguồn: trends_/.test(message)) return 'Tra cứu xu hướng tìm kiếm trên Google Trends';
  if (/^Nguồn: search_/.test(message)) return 'Tìm sản phẩm trên Amazon';
  if (/^Nguồn: reviews_mobile_/.test(message)) return 'Tìm thêm nhận xét của sản phẩm trên Amazon';
  if (/^Nguồn: product_/.test(message)) return 'Lấy thông tin chi tiết sản phẩm Amazon';
  if (/^Nguồn: tavily_/.test(message)) return 'Tìm trang web tham khảo bằng Tavily';
  if (/^Cache:/.test(message)) return 'Dùng dữ liệu đã lưu cho yêu cầu này';
  if (/^Calling: openrouter/.test(message)) return 'Đang chờ model phản hồi';
  if (/^Calling:/.test(message)) return 'Đã gửi yêu cầu lấy dữ liệu';
  return message;
}
function updateJob(job) {
  lastJob=job;
  const busy=ongoing(job);
  $('jobDot').className=busy ? 'busy' : '';
  $('planButton').disabled=busy; $('runButton').disabled=busy;
  $('rebuildButton').disabled=busy || !selectedId;
  $('supplementButton').disabled=busy || !selectedId || !boot?.keys.SERPAPI_API_KEY;
  const selected=studies.find(s => s.id===selectedId); if (selected) renderReport(selected);
  for (const field of $('studyForm').querySelectorAll('input,select,textarea,button')) field.disabled=busy && job.kind==='plan';
  $('planButton').disabled=busy;
  $('jobTitle').textContent=job.topic || studies.find(s => s.id===job.study_id)?.display_name || (job.kind==='plan' ? 'Chuẩn bị nhóm sản phẩm và từ khóa' : job.kind==='report' ? 'Viết phân tích AI và xuất báo cáo' : job.kind==='rebuild' ? 'Tạo lại báo cáo từ dữ liệu đã lưu' : 'Lấy dữ liệu và tạo báo cáo');
  const messages={queued:'Đang chuẩn bị xử lý yêu cầu.',planning:'Đang chuẩn bị nhóm sản phẩm và từ khóa tiếng Anh.',collecting:'Đang lấy xu hướng tìm kiếm, thông tin sản phẩm và nhận xét.',building:'Đang làm sạch dữ liệu và phân tích theo các tháng bạn chọn.',writing:'Đang chờ AI viết nhận định từ dữ liệu đã lấy.',reporting:'Đang xuất báo cáo, biểu đồ và kiểm tra số liệu.'};
  $('jobMessage').textContent=busy ? (job.kind==='supplement' && job.stage==='collecting' ? 'Đang kiểm tra hạn mức miễn phí và lấy thêm dữ liệu của các ASIN đã có.' : messages[job.stage] || 'Đang xử lý…') : job.status==='completed' ? (job.kind==='plan' ? 'Danh sách từ khóa đã sẵn sàng để xem lại.' : 'Đã hoàn tất. Bạn có thể mở báo cáo và dữ liệu.') : readableLog(job.message || '');
  const labels={queued:'Đang chờ',running:'Đang xử lý',completed:'Đã hoàn tất',completed_with_warnings:job.kind==='report' ? 'AI chưa viết được phần mới' : 'Đã có báo cáo, còn thiếu dữ liệu',failed:'Xử lý bị dừng',interrupted:'Đã gián đoạn'};
  $('jobStatus').textContent=labels[job.status] || job.status;
  const steps=job.kind==='plan' ? ['Chuẩn bị nhóm sản phẩm và từ khóa'] : job.kind==='report' ? ['AI đọc dữ liệu và viết phân tích có dẫn nguồn','Xuất và kiểm tra báo cáo HTML / Markdown'] : job.kind==='rebuild' ? ['Tổng hợp lại dữ liệu','Tạo và kiểm tra báo cáo'] : [job.kind==='supplement' ? 'Lấy thêm nhãn mua và nhận xét Amazon' : 'Lấy dữ liệu từ web và Amazon','Làm sạch và phân tích dữ liệu','Tạo và kiểm tra báo cáo'];
  const stage=job.failed_stage || job.stage;
  const current=job.kind==='plan' ? 0 : job.kind==='report' ? (stage==='writing' || stage==='queued' ? 0 : 1) : job.kind==='rebuild' ? (stage==='building' || stage==='queued' ? 0 : 1) : ({queued:0,collecting:0,building:1,writing:2,reporting:2,done:2}[stage] ?? 0);
  $('jobSteps').innerHTML=steps.map((name,index) => {
    const aiFailed=job.kind==='report' && job.status==='completed_with_warnings' && job.result?.llm_updated===false && index===0;
    const complete=!aiFailed && (job.status.startsWith('completed') || index<current);
    const failed=aiFailed || (!busy && !job.status.startsWith('completed') && index===current);
    const active=busy && job.status!=='queued' && index===current;
    const state=complete ? 'complete' : failed ? 'failed' : active ? 'current' : '';
    return `<li class="${state}"><span class="step-index">${complete ? '✓' : index+1}</span><span class="step-name">${name}</span><span class="step-label">${complete ? 'Đã xong' : failed ? 'Chưa hoàn tất' : active ? 'Đang làm' : 'Chưa bắt đầu'}</span></li>`;
  }).join('');
  const start=Date.parse(job.created_at_utc || '');
  if (Number.isFinite(start)) {
    const seconds=Math.max(0,Math.round(((busy ? Date.now() : Date.parse(job.updated_at_utc || job.created_at_utc))-start)/1000));
    const elapsed=seconds>=60 ? `${Math.floor(seconds/60)} phút ${seconds%60} giây` : `${seconds} giây`;
    $('jobTiming').textContent=`Bắt đầu lúc ${new Intl.DateTimeFormat('vi-VN',{hour:'2-digit',minute:'2-digit',timeZone:'Asia/Bangkok'}).format(new Date(start))} · ${busy ? 'Đã chạy' : 'Thời gian xử lý'} ${elapsed}`;
  } else $('jobTiming').textContent='';
  $('jobLogs').textContent=(job.logs || []).map(e => new Intl.DateTimeFormat('vi-VN',{hour:'2-digit',minute:'2-digit',second:'2-digit',timeZone:'Asia/Bangkok'}).format(new Date(e.at))+'  '+readableLog(e.message)).join('\n');
  $('jobLogs').scrollTop=$('jobLogs').scrollHeight;
  $('jobWarnings').textContent=(job.warnings || []).map(readableLog).join('\n'); $('jobWarnings').hidden=!(job.warnings || []).length;
  $('openFinished').hidden=busy || !job.study_id;
}
async function watchJob(id) {
  clearTimeout(timer); jobId=id;
  try {
    const job=await api('/api/jobs/'+encodeURIComponent(id));
    if (jobId!==id) return;
    updateJob(job);
    if (ongoing(job)) { timer=setTimeout(() => watchJob(id),1300); return; }
    if (job.status==='completed' && job.kind==='plan') {
      draft=job.result.config; planning=job.result.planning; renderPlan(); setView('create');
      notify('Đã chuẩn bị xong. Bạn xem lại từ khóa và nhóm sản phẩm rồi bấm “Lấy dữ liệu và tạo báo cáo”.');
      $('planPanel').scrollIntoView({behavior:'smooth',block:'start'});
    } else if (job.study_id) {
      await refreshStudies();
      if (job.status.startsWith('completed') && view==='progress') selectStudy(job.study_id);
      notify(job.message,job.status==='failed' ? 'error' : job.status==='completed_with_warnings' ? 'warning' : '');
    } else if (job.status==='failed' || job.status==='interrupted') notify(job.message,'error');
  } catch (error) {
    notify('Mất kết nối server local. Kiểm tra terminal; có thể tải lại trang sau khi server hoạt động.','error');
  }
}
async function startJob(path,request) {
  notify('');
  const job=await api(path,request); updateJob(job); setView('progress'); watchJob(job.id);
}
$('studyForm').addEventListener('submit',async event => {
  event.preventDefault();
  try { await startJob('/api/plan',formRequest()); } catch (error) { notify(error.message,'error'); }
});
$('studyForm').addEventListener('input',invalidateDraft);
$('studyForm').addEventListener('change',invalidateDraft);
$('quarterSelect').addEventListener('change',() => {
  const value=$('quarterSelect').value;
  if (value==='all') months=new Set(Array.from({length:12},(_,i) => i+1));
  else if (value!=='custom') {const q=Number(value); months=new Set([q*3-2,q*3-1,q*3]);}
  renderMonths();
});
$('presetSelect').addEventListener('change',() => {
  const p=boot.presets.find(p => p.id===$('presetSelect').value);
  if (!p) return;
  $('topicInput').value=p.topic; $('nicheInput').value=p.niche; $('keywordsInput').value=p.keywords.join('\n');
  months=new Set(p.months); $('quarterSelect').value=p.id.replace('q',''); renderMonths();
});
$('applyConfig').addEventListener('click',() => {
  try {
    const config=JSON.parse($('configEditor').value);
    if (!Array.isArray(config.families) || !Array.isArray(config.niches) || !Array.isArray(config.months) || !Array.isArray(config.years)) throw new Error('JSON cần families, niches, months và years.');
    draft=config; setForm(config); renderPlan(); notify('Đã áp dụng JSON vào kế hoạch. Server sẽ kiểm tra đầy đủ trước khi thu thập.');
  } catch (error) { notify('JSON chưa hợp lệ: '+error.message,'error'); }
});
$('runButton').addEventListener('click',async () => {
  try {
    if (!draft) throw new Error('Cần lập kế hoạch trước.');
    if ($('configEditor').value!==JSON.stringify(draft,null,2)) throw new Error('Bạn đã sửa JSON nâng cao; bấm “Áp dụng JSON” trước khi chạy.');
    await startJob('/api/run',{config:draft,planning,use_llm_report:$('useAIReport').checked,fresh:$('freshSources').checked});
  } catch (error) { notify(error.message,'error'); }
});
$('exportConfig').addEventListener('click',() => {
  if (!draft) return;
  const href=URL.createObjectURL(new Blob([JSON.stringify(draft,null,2)],{type:'application/json'}));
  const a=document.createElement('a'); a.href=href; a.download='market-radar-study.json'; a.click(); URL.revokeObjectURL(href);
});
$('cloneButton').addEventListener('click',() => {
  const study=studies.find(s => s.id===selectedId); if (!study) return;
  $('presetSelect').value='custom'; draft=structuredClone(study.config); planning={mode:'cloned',warnings:[]};
  setForm(draft); renderPlan(); setView('create'); notify('Đã sao chép thông tin nghiên cứu. Nếu đổi chủ đề hoặc thời gian, hãy chuẩn bị lại danh sách từ khóa. Kết quả mới sẽ được lưu riêng.');
});
$('rebuildButton').addEventListener('click',async () => {
  try { await startJob('/api/rebuild',{study_id:selectedId}); } catch (error) { notify(error.message,'error'); }
});
$('supplementButton').addEventListener('click',async () => {
  try { await startJob('/api/supplement',{study_id:selectedId,max_requests:Number($('supplementBudget').value)}); } catch (error) { notify(error.message,'error'); }
});
$('aiReportButton').addEventListener('click',async () => {
  try { await startJob('/api/report',{study_id:selectedId}); } catch (error) { notify(error.message,'error'); }
});
for (const id of ['newStudyTop','emptyCreate','createTab']) $(id).addEventListener('click',() => setView('create'));
$('resultsTab').addEventListener('click',() => setView('results'));
$('progressTab').addEventListener('click',() => setView('progress'));
$('studySearch').addEventListener('input',renderLibrary);
$('refreshLibrary').addEventListener('click',() => refreshStudies().catch(e => notify(e.message,'error')));
$('openFinished').addEventListener('click',() => lastJob?.study_id && selectStudy(lastJob.study_id));
async function init() {
  try {
    boot=await api('/api/bootstrap'); token=boot.token; studies=boot.studies;
    $('presetSelect').innerHTML+=boot.presets.map(p => `<option value="${esc(p.id)}">${esc(p.label)}</option>`).join('');
    const current=Number(boot.today.slice(0,4));
    $('startYear').value=current-3; $('endYear').value=current; $('startYear').max=current; $('endYear').max=current;
    $('asOfInput').value=boot.today; $('asOfInput').max=boot.today;
    const free=boot.model.endsWith(':free') || boot.model==='openrouter/free';
    $('useAIPlan').checked=!!boot.keys.OPENROUTER_API_KEY && free; $('useAIReport').checked=$('useAIPlan').checked;
    $('modelNote').textContent=`Model: ${boot.model}. ${free ? 'Đây là model miễn phí; số lượt gọi phụ thuộc hạn mức tài khoản.' : 'Để dùng AI miễn phí, đổi OPENROUTER_MODEL trong api/.env sang một model :free.'}`;
    $('keyStatus').innerHTML=[['SerpApi','SERPAPI_API_KEY'],['Tavily','TAVILY_API_KEY'],['OpenRouter','OPENROUTER_API_KEY']].map(([name,key]) => `<span class="${boot.keys[key] ? '' : 'missing'}">${boot.keys[key] ? '●' : '○'} ${name} · ${boot.keys[key] ? 'đã cấu hình' : 'chưa có key'}</span>`).join('')+'<span>Trạng thái key chưa kiểm tra với API.</span>';
    renderMonths(); renderLibrary();
    let stored; try {stored=localStorage.getItem('radar-selected-study');} catch {}
    const chosen=studies.find(s => s.id===stored && s.ready) || studies.find(s => s.id==='seasonal-gifts-us' && s.ready) || studies.find(s => s.ready);
    if (chosen) selectStudy(chosen.id);
    const active=boot.jobs.find(ongoing);
    if (active) {updateJob(active); watchJob(active.id);} else if (boot.jobs[0]) {
      const previous=boot.jobs[0]; updateJob(previous);
      if (previous.kind==='plan' && previous.status==='completed' && previous.result) {
        draft=previous.result.config; planning=previous.result.planning; setForm(draft); renderPlan(); setView('create');
      }
    }
  } catch (error) {notify('Không tải được workspace. Kiểm tra server local đang chạy.','error');}
}
init();

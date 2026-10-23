'use strict';
const payload = JSON.parse(document.getElementById('radarData').textContent);
const {data, analysis, config} = payload;
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const url = value => /^https?:\/\//i.test(value || '') ? esc(value) : '#';
const fmt = value => value == null ? '—' : new Intl.NumberFormat('en-US', {maximumFractionDigits:2}).format(value);
const dateText = value => /^\d{4}-\d{2}-\d{2}/.test(value || '') ? value.slice(0,10).split('-').reverse().join('/') : 'Chưa rõ ngày';
const fit = row => row?.historical_profile_pct_of_own_period_peak ?? row?.historical_profile_pct_of_own_q4_peak ?? null;
const months = data.history_months || config.months || [10,11,12];
const topN = config.top_n || 5;
const productByASIN = new Map(data.products.map(p => [p.asin,p]));
const familyByID = new Map(config.families.map(f => [f.id,f]));
const reviewCountText = asin => {
  const p=productByASIN.get(asin);
  return `${p?.full_reviews_collected ?? p?.customer_reviews_collected ?? 0} đầy đủ · ${p?.review_excerpts_collected ?? 0} trích đoạn`;
};
const statusNames = {historical_period_peak:'Thường được tìm nhiều nhất vào tháng này',historical_q4_peak:'Thường được tìm nhiều nhất vào tháng này',historical_build_up:'Thường tăng so với tháng trước',secondary_period:'Mức tìm kiếm còn tương đối cao',preparation_or_off_peak:'Mức tìm thấp hơn tháng cao điểm',insufficient_search_history:'Chưa đủ dữ liệu để xác định',no_supported_keyword:'Chưa có từ khóa phù hợp'};
const themeNames = {scent:'Mùi hương',packaging:'Đóng gói',size_or_quantity:'Size / số lượng',material_or_quality:'Vật liệu / chất lượng',value_for_money:'Giá / giá trị',gift_recipient_or_occasion:'Dịp / người nhận',skin_or_sensitivity:'Da / nhạy cảm',delivery:'Giao hàng',battery_or_power:'Pin / điện',assembly_or_instructions:'Lắp ráp',adhesion:'Độ bám',appearance_or_color:'Ngoại hình / màu'};
let month = months.includes(Number(data.as_of_date.slice(5,7))) ? Number(data.as_of_date.slice(5,7)) : months[0];
let niche = 'all', reviewASIN = 'all', showEveryReview = false;
if (new URLSearchParams(window.location.search).has('embed')) document.body.classList.add('embedded');
function belongs(asin) { return niche === 'all' || (productByASIN.get(asin)?.niche_ids || []).includes(niche); }
function topRows() { return analysis.monthly_top5.filter(r => r.month === month && belongs(r.asin)); }
function rankingRows() {
  const query = $('productSearch').value.trim().toLowerCase();
  return ($('showAll').checked ? analysis.product_month_opportunities : analysis.monthly_top5)
    .filter(r => r.month === month && belongs(r.asin) && (!query || (r.product_name+' '+r.asin).toLowerCase().includes(query)));
}
function renderRanking() {
  $('monthCaption').textContent = `SẢN PHẨM THÁNG ${month}`;
  document.querySelectorAll('[data-month]').forEach(b => b.setAttribute('aria-selected',String(Number(b.dataset.month) === month)));
  const top = topRows(), asins = new Set(top.map(r => r.asin));
  const completed = Math.max(0,...analysis.monthly_keyword_analysis.map(r => r.completed_year_count));
  $('metrics').innerHTML = [
    ['Sản phẩm đã lấy',data.products.filter(p => belongs(p.asin)).length,'Không đếm trùng mã ASIN'],
    [`Top ${topN} trong tháng`,top.length,`Tháng ${month} · nhóm đang chọn`],
    ['Nhận xét đầy đủ của Top',data.reviews.filter(r => asins.has(r.asin) && r.review_text_kind!=='excerpt').length,`${data.reviews.filter(r => asins.has(r.asin) && r.review_text_kind==='excerpt').length} trích đoạn được tính riêng`],
    ['Số năm phân tích (tối đa)',completed,'Mỗi từ khóa có thể có số năm khác nhau']
  ].map(([label,value,note]) => `<div class="metric"><span>${esc(label)}</span><strong>${value}</strong><small>${esc(note)}</small></div>`).join('');
  const snapshots=[...new Set(data.products.map(p => (p.observed_at_utc || '').slice(0,10)))].filter(Boolean).map(dateText).join(', ');
  $('rankNote').textContent = `Thông tin Amazon được lấy ngày ${snapshots || 'ghi ở từng sản phẩm'}. Xu hướng tìm kiếm được tính đến ${dateText(data.as_of_date)}. ${month > Number(data.as_of_date.slice(5,7)) ? `Tháng này trong năm ${data.as_of_date.slice(0,4)} chưa có dữ liệu, nên danh sách tham khảo xu hướng các năm trước. ` : ''}Bộ lọc nhóm chỉ thu gọn danh sách, không tính lại thứ hạng.`;
  const rows = rankingRows();
  $('productRows').innerHTML = rows.map(r => {
    const family = familyByID.get((r.timing_keyword_id || '').replace('K-',''));
    const rank = analysis.monthly_top5.find(t => t.month === month && t.asin === r.asin)?.rank_in_month;
    return `<tr><td><span class="rank-number">${rank ?? '—'}</span></td><td><button class="product-title detail-link" data-detail="${esc(r.asin)}">${esc(r.product_name)}</button><div class="product-meta">ASIN: ${esc(r.asin)} · ${fmt(r.rating_out_of_5)}/5 sao · <a href="${url(r.source_url)}" target="_blank" rel="noopener">Amazon ↗</a></div><span class="family-tag">${esc(family?.name_vi || r.product_group)}</span></td><td class="money">${r.price_usd == null ? '—' : '$'+fmt(r.price_usd)}</td><td><div class="badge-text">${esc(r.current_purchase_badge || 'Chưa có thông tin')}</div><div class="micro">Ghi nhận ${dateText(r.current_snapshot_at_utc)} · số Amazon hiển thị đã làm tròn</div></td><td><span class="fit-value">${fmt(fit(r))}/100</span><div class="fit-track"><span style="width:${Math.max(0,Math.min(100,fit(r) || 0))}%"></span></div><div class="micro">${esc(statusNames[r.timing_status])}</div></td><td><button class="review-link" data-review="${esc(r.asin)}">${reviewCountText(r.asin)} ↗</button></td></tr>`;
  }).join('');
  $('productEmpty').hidden = rows.length > 0;
  document.querySelectorAll('[data-review]').forEach(b => b.addEventListener('click',() => {
    reviewASIN = b.dataset.review; $('reviewProduct').value = reviewASIN; showEveryReview = false;
    renderReviews(); $('reviews').scrollIntoView({behavior:'smooth'});
  }));
  document.querySelectorAll('[data-detail]').forEach(b => b.addEventListener('click',() => showProduct(b.dataset.detail)));
}
function showProduct(asin) {
  const p = productByASIN.get(asin);
  if (!p) return;
  // A modal inside a tall iframe is centered outside the visible browser viewport.
  // Let the workbench own it; standalone reports retain their own native dialog.
  if (new URLSearchParams(window.location.search).has('embed') && window.parent !== window) {
    window.parent.postMessage({type:'market-analysis:product',product:p},window.location.origin);
    return;
  }
  const fields = [['Thương hiệu',p.brand],['Giá cả gói (USD)',p.price_usd],['Màu sắc',p.color],['Kích cỡ',p.size],['Kích thước',p.dimensions],['Chất liệu',p.material],['Mùi hương',p.scent],['Số món theo mô tả',p.listing_number_of_items],['Lượt mua Amazon hiển thị',p.bought_past_month_text],['Nhận xét đầy đủ',p.full_reviews_collected ?? p.customer_reviews_collected],['Trích đoạn nhận xét',p.review_excerpts_collected ?? 0]];
  $('productDetail').innerHTML = `<p class="eyebrow">ASIN: ${esc(asin)}</p><h2>${esc(p.product_name)}</h2><dl>${fields.map(([k,v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v ?? 'Chưa có thông tin')}</dd></div>`).join('')}</dl><h3>Mô tả từ trang sản phẩm</h3><p class="review-body">${esc(p.description || p.seller_features || 'Chưa có mô tả')}</p><p><a href="${url(p.source_url)}" target="_blank" rel="noopener">Xem sản phẩm trên Amazon ↗</a></p><p class="micro">Ngày lấy dữ liệu: ${dateText(p.observed_at_utc)}</p>`;
  if (!$('productDialog').open) $('productDialog').showModal();
}
function refreshKeywordOptions() {
  const families = config.families.filter(f => niche === 'all' || f.niche_id === niche);
  const previous = $('keywordSelect').value;
  $('keywordSelect').innerHTML = families.map(f => `<option value="K-${esc(f.id)}">${esc(f.name_vi)} · ${esc(f.keyword)}</option>`).join('');
  if (families.some(f => 'K-'+f.id === previous)) $('keywordSelect').value = previous;
}
function renderChart() {
  renderEvidence();
  const id = $('keywordSelect').value, year = $('yearSelect').value;
  const rows = data.trends.filter(r => r.keyword_id === id);
  const years = year === 'all' ? data.history_years : [Number(year)];
  const colors = ['#497d68','#c68139','#8c78a7','#4d8fab','#b66572','#849643','#7268ad','#607d8b'];
  const ceiling = Math.ceil(Math.max(1,...rows.filter(r => years.includes(r.year) && r.mean_interest_index != null).map(r => r.mean_interest_index))/10)*10;
  const x = m => months.length === 1 ? 310 : 60 + months.indexOf(m)*500/(months.length-1);
  const y = v => 220-v/ceiling*185;
  let svg = '<svg viewBox="0 0 620 265" xmlns="http://www.w3.org/2000/svg"><title>Chỉ số từ khóa theo tháng và năm đã chọn</title>';
  for (let i=0; i<=4; i++) {
    const v = ceiling*i/4;
    svg += `<line x1="52" x2="575" y1="${y(v)}" y2="${y(v)}" stroke="#e8eddf"/><text x="40" y="${y(v)+4}" text-anchor="end" fill="#8b9780" font-size="11">${fmt(v)}</text>`;
  }
  for (const m of months) svg += `<text x="${x(m)}" y="250" text-anchor="middle" fill="#829175" font-size="12">T${m}</text>`;
  for (const yy of years) {
    const color = colors[data.history_years.indexOf(yy)%colors.length];
    let previous = null;
    for (const m of months) {
      const point = rows.find(r => r.year === yy && r.month === m);
      if (point?.mean_interest_index == null) { previous = null; continue; }
      const current = [x(m),y(point.mean_interest_index)];
      if (previous) svg += `<line x1="${previous[0]}" y1="${previous[1]}" x2="${current[0]}" y2="${current[1]}" stroke="${color}" stroke-width="2.5"/>`;
      svg += `<circle cx="${current[0]}" cy="${current[1]}" r="4" fill="${color}"><title>${yy} T${m}: ${point.mean_interest_index} · ${esc(point.observation_status)}</title></circle>`;
      previous = current;
    }
  }
  $('trendChart').innerHTML = svg+'</svg>';
  $('chartLegend').innerHTML = years.map(yy => `<span style="--color:${colors[data.history_years.indexOf(yy)%colors.length]}">${yy}</span>`).join('');
  $('chartNote').innerHTML = `Google Trends thể hiện mức quan tâm tương đối đối với từ khóa này, không phải số lượt tìm cụ thể. Tháng chưa có dữ liệu được để trống; dấu * là tháng mới có một phần dữ liệu. <a href="${url(rows.find(r => r.source_url)?.source_url)}" target="_blank" rel="noopener">Xem trên Google Trends ↗</a>`;
  $('chartHeader').innerHTML = '<tr><th>Năm</th>'+months.map(m => `<th>T${m}</th>`).join('')+'</tr>';
  $('chartValues').innerHTML = years.map(yy => `<tr><td>${yy}</td>${months.map(m => {
    const r = rows.find(t => t.year === yy && t.month === m);
    return `<td>${r?.mean_interest_index == null ? 'Chưa có' : fmt(r.mean_interest_index)}${r?.observation_status === 'partial_month' ? ' *' : ''}</td>`;
  }).join('')}</tr>`).join('');
}
function renderEvidence() {
  const id=$('keywordSelect').value;
  const summary=(data.keyword_market_summary || []).find(r => r.keyword_id===id);
  const timing=analysis.monthly_keyword_analysis.find(r => r.keyword_id===id && r.month===month);
  $('evidenceSummary').textContent=summary ? `${summary.keyword} · Tháng ${month}: ${statusNames[timing?.timing_status] || 'Chưa đủ lịch sử'}. ${summary.products_collected} sản phẩm; ${summary.products_with_purchase_evidence} có nhãn mua; ${summary.full_review_texts} nhận xét đầy đủ và ${summary.review_excerpts} trích đoạn.` : 'Chưa có bảng đối chiếu. Chọn “Tính lại từ dữ liệu gốc” trên dashboard local để tạo bảng này từ nguồn đã lưu.';
  const rows=(data.keyword_product_evidence || []).filter(r => r.keyword_id===id && belongs(r.asin));
  $('evidenceRows').innerHTML=rows.map(r => `<tr><td><button class="product-title detail-link" data-evidence-detail="${esc(r.asin)}">${esc(r.product_name)}</button><div class="micro">ASIN ${esc(r.asin)} · <a href="${url(r.source_url)}" target="_blank" rel="noopener">Amazon ↗</a></div></td><td class="money">${r.price_usd == null ? '—' : '$'+fmt(r.price_usd)}</td><td><strong>${esc(r.purchase_badge || 'Chưa có nhãn mua')}</strong><div class="micro">${r.purchase_source_type==='product_listing' ? 'Trang sản phẩm' : r.purchase_source_type==='search_listing' ? 'Thẻ tìm kiếm Amazon' : 'Chưa có nguồn'} · ${dateText(r.purchase_observed_at_utc)}</div></td><td><button class="review-link" data-evidence-review="${esc(r.asin)}">${r.full_review_texts} đầy đủ ↗</button></td><td>${r.review_excerpts} trích đoạn</td></tr>`).join('') || '<tr><td colspan="5">Chưa thu được sản phẩm phù hợp với từ khóa này.</td></tr>';
  document.querySelectorAll('[data-evidence-detail]').forEach(b => b.addEventListener('click',() => showProduct(b.dataset.evidenceDetail)));
  document.querySelectorAll('[data-evidence-review]').forEach(b => b.addEventListener('click',() => {
    reviewASIN=b.dataset.evidenceReview; $('reviewProduct').value=reviewASIN; showEveryReview=false;
    $('reviewKind').value='all'; $('ratingFilter').value='all'; renderReviews(); $('reviews').scrollIntoView({behavior:'smooth'});
  }));
}
function renderHeatmap() {
  $('heatmap').style.gridTemplateColumns = `minmax(140px,1fr) repeat(${months.length},minmax(38px,1fr))`;
  let content = '<div></div>'+months.map(m => `<div class="heat-head">T${m}</div>`).join('');
  for (const f of config.families.filter(f => niche === 'all' || f.niche_id === niche)) {
    content += `<div class="heat-name">${esc(f.name_vi)}</div>`;
    for (const m of months) {
      const p = analysis.monthly_keyword_analysis.find(r => r.component_id === f.id && r.month === m);
      const value = p?.timing_supported ? fit(p) : null;
      content += `<button class="heat-cell${m === month ? ' active' : ''}" data-heat="${esc(f.id)}" data-heat-month="${m}" style="background:rgba(127,159,91,${value == null ? 0 : .08+value/100*.5})" title="${esc(statusNames[p?.timing_status] || 'Chưa có dữ liệu')}">${value == null ? '—' : Math.round(value)}</button>`;
    }
  }
  $('heatmap').innerHTML = content;
  document.querySelectorAll('[data-heat]').forEach(b => b.addEventListener('click',() => {
    month = Number(b.dataset.heatMonth); $('keywordSelect').value = 'K-'+b.dataset.heat; renderAll();
  }));
}
function renderReviews() {
  const visible = new Set(rankingRows().map(r => r.asin));
  let rows = data.reviews.filter(r => reviewASIN === 'all' ? visible.has(r.asin) : r.asin === reviewASIN);
  if ($('reviewKind').value!=='all') rows=rows.filter(r => (r.review_text_kind || 'full')===$('reviewKind').value);
  if ($('ratingFilter').value === 'low') rows = rows.filter(r => r.rating_out_of_5 != null && r.rating_out_of_5 <= 3);
  if ($('ratingFilter').value === 'high') rows = rows.filter(r => r.rating_out_of_5 >= 4);
  rows.sort((a,b) => (a.rating_out_of_5 ?? 6)-(b.rating_out_of_5 ?? 6) || (b.review_date || '').localeCompare(a.review_date || ''));
  const full=rows.filter(r => r.review_text_kind!=='excerpt').length;
  const dated=rows.filter(r => r.review_text_kind!=='excerpt' && r.review_date).length;
  const verified=rows.filter(r => r.review_text_kind!=='excerpt' && r.verified_purchase===true).length;
  $('reviewSummary').textContent = `${full} nhận xét đầy đủ và ${rows.length-full} trích đoạn của ${new Set(rows.map(r => r.asin)).size} sản phẩm. Trong số nhận xét đầy đủ: ${dated} có ngày đăng, ${verified} được Amazon xác nhận đã mua. Giữ nguyên tiếng Anh; trích đoạn thiếu sao không xuất hiện trong bộ lọc sao.`;
  const ids = new Set(rows.map(r => r.review_id)), counts = new Map();
  for (const item of data.customer_needs || []) {
    if (!ids.has(item.review_id)) continue;
    if (!counts.has(item.theme)) counts.set(item.theme,new Set());
    counts.get(item.theme).add(item.review_id);
  }
  $('themeTags').innerHTML = [...counts].sort((a,b) => b[1].size-a[1].size).slice(0,7).map(([theme,set]) => `<span>${esc(themeNames[theme] || theme)} · ${set.size}/${rows.length} nhận xét nhắc đến</span>`).join('');
  $('reviewCards').innerHTML = (showEveryReview ? rows : rows.slice(0,6)).map(r => `<article class="review-card"><div class="micro">${r.review_text_kind==='excerpt' ? 'Trích đoạn nhận xét' : 'Nhận xét đầy đủ'}</div><span class="review-rating">${r.rating_out_of_5==null ? 'Chưa có số sao' : fmt(r.rating_out_of_5)+'/5 sao'}</span><span class="review-date">${dateText(r.review_date)}</span><h3>${esc(r.review_title || 'Nhận xét')}</h3><div class="review-body">${esc(r.review_text.slice(0,400))}</div>${r.review_text.length > 400 ? `<details><summary>Đọc tiếp</summary><div class="review-body">${esc(r.review_text.slice(400))}</div></details>` : ''}<a class="review-source" href="${url(r.source_url)}" target="_blank" rel="noopener">ASIN ${esc(r.asin)} · Xem nguồn ↗</a><div class="micro">${r.verified_purchase ? 'Amazon xác nhận đã mua hàng' : 'Không có xác nhận đã mua hàng'}<br>${esc(r.variant_text || 'Chưa có thông tin phiên bản sản phẩm')}<br>${esc(r.reviewer_country_explicit || 'Chưa xác định quốc gia người nhận xét')}</div></article>`).join('') || '<div class="empty">Chưa lấy được nội dung nhận xét cho các sản phẩm đang chọn.</div>';
  $('moreReviews').hidden = showEveryReview || rows.length <= 6;
}
function renderAll() { renderRanking(); renderChart(); renderHeatmap(); renderReviews(); }
$('asOf').textContent = data.as_of_date.split('-').reverse().join(' / ');
$('studyCategory').textContent = payload.display_name || data.category;
$('studyScope').textContent = `Tháng ${months.join(', ')} / ${data.history_years.join(', ')}`;
$('rankingTitle').textContent = `Top ${topN} trong số sản phẩm đã lấy`;
$('methodTopTitle').textContent = `Cách chọn Top ${topN}`;
$('monthTabs').innerHTML = months.map(m => `<button type="button" role="tab" data-month="${m}">THÁNG ${m}</button>`).join('');
$('yearSelect').innerHTML += data.history_years.map(y => `<option>${y}</option>`).join('');
$('nicheFilter').innerHTML += config.niches.map(n => `<option value="${esc(n.id)}">${esc(n.name_vi)}</option>`).join('');
$('reviewProduct').innerHTML += data.products.map(p => `<option value="${esc(p.asin)}">${esc(p.asin)} · ${esc(p.product_name.slice(0,75))}</option>`).join('');
$('limitations').innerHTML = [
  'Google Trends dùng chỉ số tương đối. Không cộng hoặc so trực tiếp chỉ số của những từ khóa được lấy riêng để kết luận quy mô thị trường.',
  'Giá, số sao và lượt mua phản ánh trang Amazon ở ngày thu thập; chưa có lịch sử bán hàng từng tháng của mỗi sản phẩm.',
  'Nhận xét đã lấy chỉ là một phần nhận xét trên Amazon. Ngày đăng và tiếng Anh không xác nhận ngày mua hoặc quốc gia người mua.',
  'Tháng chưa xảy ra được để trống. Chỉ các năm đủ dữ liệu cho những tháng đã chọn mới được dùng để xác định xu hướng.'
].map(s => `<li>${esc(s)}</li>`).join('')+((data.source_errors || []).length ? '<li>Một số nguồn chưa lấy được dữ liệu. Xem báo cáo đầy đủ để kiểm tra phần còn thiếu.</li>' : '');
document.querySelectorAll('[data-month]').forEach(b => b.addEventListener('click',() => {
  month = Number(b.dataset.month); reviewASIN = 'all'; $('reviewProduct').value = 'all'; showEveryReview = false; renderAll();
}));
$('nicheFilter').addEventListener('change',() => { niche = $('nicheFilter').value; reviewASIN = 'all'; $('reviewProduct').value = 'all'; refreshKeywordOptions(); renderAll(); });
$('productSearch').addEventListener('input',() => {renderRanking(); renderReviews();});
$('showAll').addEventListener('change',() => {renderRanking(); renderReviews();});
$('keywordSelect').addEventListener('change',renderChart);
$('yearSelect').addEventListener('change',renderChart);
$('reviewProduct').addEventListener('change',() => {reviewASIN = $('reviewProduct').value; showEveryReview = false; renderReviews();});
$('ratingFilter').addEventListener('change',() => {showEveryReview = false; renderReviews();});
$('reviewKind').addEventListener('change',() => {showEveryReview = false; renderReviews();});
$('moreReviews').addEventListener('click',() => {showEveryReview = true; renderReviews();});
$('closeProduct').addEventListener('click',() => $('productDialog').close());
refreshKeywordOptions(); renderAll();
// Keep the embedded result in the same scrolling page as the workbench.
if (new URLSearchParams(window.location.search).has('embed') && window.parent!==window) {
  let lastHeight=0;
  const sendHeight=() => {
    const height=Math.ceil($('dashboardMain').getBoundingClientRect().height)+2;
    if (height>=300 && height!==lastHeight) {
      lastHeight=height;
      window.parent.postMessage({type:'market-analysis:height',height},window.location.origin);
    }
  };
  if (typeof ResizeObserver!=='undefined') new ResizeObserver(sendHeight).observe($('dashboardMain'));
  window.addEventListener('load',sendHeight);
  sendHeight();
}

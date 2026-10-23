// Execute production JS against a small DOM adapter. This is not visual/browser QA.
import fs from 'node:fs/promises';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const directories=process.argv.slice(2);
if (!directories.length) directories.push('data/seasonal-gifts-us');
const code=await fs.readFile('market_radar/assets/dashboard.js','utf8');
for (const directory of directories) {
  const html=await fs.readFile(path.join(directory,'dashboard.html'),'utf8');
  const serialized=html.match(/<script type="application\/json" id="radarData">([\s\S]*?)<\/script>/)[1];
  const payload=JSON.parse(serialized), months=payload.data.history_months;
  const elements=new Map(), generated=new Map();
  class Element {
    constructor(id){Object.assign(this,{id,value:'',checked:false,hidden:false,dataset:{},handlers:{},_html:'',textContent:'',style:{},classList:{add(){},toggle(){}}});}
    set innerHTML(value){
      this._html=value;
      if (value.includes('<option')) {const first=value.match(/<option(?: value="([^"]*)")?>([^<]*)/);if(first)this.value=first[1]??first[2];}
      const children=[];
      for (const tag of value.matchAll(/<(?:button|input)\b([^>]*)>/g)) {
        const child=new Element('generated');
        for (const attr of tag[1].matchAll(/data-([\w-]+)="([^"]*)"/g)) child.dataset[attr[1].replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=attr[2];
        children.push(child);
      }
      generated.set(this.id,children);
    }
    get innerHTML(){return this._html;}
    addEventListener(type,fn){this.handlers[type]=fn;}
    setAttribute(key,value){this[key]=value;}
    scrollIntoView(){}
    getBoundingClientRect(){return {height:4300};}
    showModal(){this.open=true;}
    close(){this.open=false;}
    fire(type){this.handlers[type]?.({target:this});}
  }
  for (const match of html.matchAll(/id="([^"]+)"/g)) elements.set(match[1],new Element(match[1]));
  const get=id=>elements.get(id);
  get('radarData').textContent=serialized;
  for (const id of ['yearSelect','ratingFilter','reviewProduct','nicheFilter','reviewKind']) get(id).innerHTML='<option value="all">All</option>';
  const document={body:new Element('body'),getElementById:id=>{
    assert.ok(elements.has(id),'Shell element exists: '+id);return get(id);
  },querySelectorAll:selector=>{
    const key=selector.match(/^\[data-([\w-]+)\]$/)?.[1]?.replace(/-([a-z])/g,(_,c)=>c.toUpperCase());
    return key ? [...generated.values()].flat().filter(e=>key in e.dataset) : [];
  }};
  const messages=[];
  const window={location:{search:'?embed=1',origin:'http://127.0.0.1:8765'},addEventListener(){},parent:{postMessage(message,origin){messages.push({message,origin});}}};
  const context=vm.createContext({document,window,URLSearchParams,Intl,console,Map,Set,Number,String,Math,JSON});
  vm.runInContext(code,context,{timeout:5000});
  assert.equal(messages[0].message.type,'market-analysis:height');
  assert.equal(messages[0].message.height,4302,'Embedded results report their content height to remove nested scrolling');
  const tabs=document.querySelectorAll('[data-month]');
  assert.deepEqual(tabs.map(t=>Number(t.dataset.month)),months);
  assert.equal((get('chartHeader').innerHTML.match(/<th>/g)||[]).length,months.length+1);
  assert.ok(get('studyCategory').textContent===(payload.display_name || payload.data.category));
  if(payload.data.keyword_product_evidence?.length){
    const target=payload.data.keyword_product_evidence.find(r=>r.purchase_source_type==='search_listing') || payload.data.keyword_product_evidence[0];
    get('keywordSelect').value=target.keyword_id;get('keywordSelect').fire('change');
    assert.match(get('evidenceRows').innerHTML,new RegExp(target.asin),'ASIN absent from Top 5 still appears in keyword-linked products');
    assert.ok(get('evidenceRows').innerHTML.includes(target.purchase_badge || 'Chưa có nhãn mua'));
    const button=document.querySelectorAll('[data-evidence-review]').find(e=>e.dataset.evidenceReview===target.asin);
    button.fire('click');assert.equal(get('reviewProduct').value,target.asin);
    get('reviewKind').value='excerpt';get('reviewKind').fire('change');
    assert.match(get('reviewSummary').textContent,/0 nhận xét đầy đủ/);
    if(payload.data.reviews.some(r=>r.asin===target.asin && r.review_text_kind==='excerpt')){
      assert.match(get('reviewCards').innerHTML,/Trích đoạn nhận xét/);
      assert.match(get('reviewCards').innerHTML,/Chưa có số sao/);
    }
    get('reviewKind').value='all';get('reviewKind').fire('change');
  }
  for (const tab of tabs){tab.fire('click');assert.match(get('monthCaption').textContent,new RegExp(tab.dataset.month));}
  get('showAll').checked=true;get('showAll').fire('change');
  assert.equal((get('productRows').innerHTML.match(/<tr>/g)||[]).length,payload.data.products.length);
  const detail=document.querySelectorAll('[data-detail]')[0];
  detail.fire('click');
  const productMessages=messages.filter(m=>m.message.type==='market-analysis:product');
  assert.equal(productMessages.length,1,'Embedded product opens through parent viewport, not the tall iframe');
  assert.equal(productMessages[0].message.product.asin,detail.dataset.detail);
  assert.equal(productMessages[0].origin,window.location.origin);
  assert.notEqual(get('productDialog').open,true,'Iframe must not display its own backdrop');
  window.parent=window; // Standalone HTML still has a usable detail dialog.
  detail.fire('click');assert.equal(get('productDialog').open,true);assert.match(get('productDetail').innerHTML,/ASIN/);
  get('closeProduct').fire('click');assert.equal(get('productDialog').open,false);
  get('productSearch').value='not-a-real-product';get('productSearch').fire('input');
  assert.equal(get('productRows').innerHTML,'');assert.equal(get('productEmpty').hidden,false);
  get('productSearch').value='';get('productSearch').fire('input');
  get('nicheFilter').value=payload.config.niches[0].id;get('nicheFilter').fire('change');
  get('ratingFilter').value='low';get('ratingFilter').fire('change');assert.match(get('reviewSummary').textContent,/nhận xét/);
  const currentYear=Number(payload.data.as_of_date.slice(0,4));
  if(payload.data.trends.some(r=>r.year===currentYear && r.observation_status==='not_yet_observed')){
    get('yearSelect').value=String(currentYear);get('yearSelect').fire('change');assert.match(get('chartValues').innerHTML,/Chưa có/);
  }
  const result={status:'logic_passed',checked_at_utc:new Date().toISOString(),months,
    checks:['dynamic month/year controls','chart columns and missing future months','catalog/search/niche/review filters','embedded content height message','embedded product message to parent viewport','standalone product dialog','real production JavaScript'],
    browser_visual_qa:'not_run: browser inventory empty; in-app browser unavailable',
    scope:'Executed production JavaScript with a minimal DOM adapter; does not verify browser layout'};
  await fs.writeFile(path.join(directory,'ui-validation.json'),JSON.stringify(result,null,2));
  console.log('Dashboard logic passed:',directory,'months',months.join(','));
}

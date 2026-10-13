
let DATA=[],ALL=[],map,SRCDATES={};
// ANCHOR = the (first) workplace: radius and rail fields are measured from it.
// ANCHOR2 = optional second commuter's workplace; null keeps the one-anchor behaviour.
// Deák tér: M1/M2/M3 are within the commute model's 1 km egress walk
let ANCHOR={name:'Budapest',lat:47.4977,lon:19.0544}, ANCHOR2=null, RADIUS=90;
// every string below comes from OSM or a user-editable upstream, and every one of them
// is interpolated into innerHTML. Escape at the point of interpolation, not at ingest.
const ESCMAP={'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
const esc=v=>v==null?'':String(v).replace(/[&<>"']/g,c=>ESCMAP[c]);

// localStorage can be blocked or hold anything from an older build: read defensively
const stored=(k,d)=>{ try{ return JSON.parse(localStorage.getItem(k))??d; }catch(e){ return d; } };
const store=(k,v)=>{ try{ localStorage.setItem(k,JSON.stringify(v)); }catch(e){} };
const okPt=a=>!!a&&typeof a.name==='string'&&num(a.lat)&&num(a.lon)
  &&a.lat>45.5&&a.lat<48.8&&a.lon>15.9&&a.lon<23.1;   // Hungary's bounding box
{ const w=stored('bl_work',[]);
  if(Array.isArray(w)){ if(okPt(w[0])) ANCHOR=w[0]; if(okPt(w[1])) ANCHOR2=w[1]; } }
if(stored('bl_kind')==='flat') UI.kind='flat';
const workNames=()=>ANCHOR2?`${ANCHOR.name} / ${ANCHOR2.name}`:ANCHOR.name;

// false once /api/anchor has failed or answered with nothing: without commute data
// every settlement drops out of scope, and "0 / 619 pass" is a lie about the filters.
let COMMUTE_OK=true;

const ANCH_D=[{},{}], ANCH_SEQ=[0,0];   // last /api/anchor answer per workplace
async function fetchAnchor(i,a){
  const seq=++ANCH_SEQ[i]; let d={};
  if(a) try{ const r=await fetch(`/api/anchor?lat=${a.lat}&lon=${a.lon}`);
    if(!r.ok) throw new Error('HTTP '+r.status);
    d=await r.json(); }
  catch(e){ console.error('anchor fetch failed',e); }
  if(seq===ANCH_SEQ[i]) ANCH_D[i]=d;     // a slower, older answer must not overwrite a newer one
}
function setWork(i,a){
  if(i===0) ANCHOR=a; else ANCHOR2=a;
  store('bl_work',[ANCHOR,ANCHOR2]);
  return loadAnchors([i]);
}
async function loadAnchors(which=[0,1]){
  const el=document.getElementById('anchor'), el2=document.getElementById('anchor2');
  if(el) el.value=ANCHOR.name;
  if(el2){ el2.value=ANCHOR2?ANCHOR2.name:''; document.getElementById('anchor2-x').hidden=!ANCHOR2; }
  // note: window.map is the <div id="map">, not the map object - use the local binding
  if(which.includes(0)&&typeof map!=='undefined'&&map&&map.loaded&&map.loaded())
    map.easeTo({center:[ANCHOR.lon,ANCHOR.lat],zoom:Math.max(7.2,9.6-Math.log2(RADIUS/20)),duration:900});
  await Promise.all(which.map(i=>fetchAnchor(i,[ANCHOR,ANCHOR2][i])));
  const [d,d2]=ANCH_D;
  COMMUTE_OK=Object.keys(d).length>0&&(!ANCHOR2||Object.keys(d2).length>0);
  for(const s of ALL){ const r=d[s.ksh];
    if(r) Object.assign(s,r); else { s.dist_km=null; s.commute_best_min=null; }
    s.commute1_min=r?.commute_best_min??null; s.commute2_min=null;
    // two commuters: rank on the WORSE of the two commutes, keep both for display.
    // One side unknown -> the pair is unknown, so the metric abstains.
    if(ANCHOR2){ const b=d2[s.ksh]?.commute_best_min;
      s.commute2_min=num(b)?b:null;
      s.commute_best_min=num(s.commute1_min)&&num(b)?Math.max(s.commute1_min,b):null; }
  }
  drawWork();
  applyScope();
}
const drawWork=()=>{ if(typeof map==='undefined'||!map?.getSource?.('work')) return;
  map.getSource('work').setData({type:'FeatureCollection',features:[ANCHOR,ANCHOR2].filter(Boolean)
    .map(a=>({type:'Feature',geometry:{type:'Point',coordinates:[a.lon,a.lat]},properties:{}}))}); };

function applyScope(){
  DATA=ALL.filter(s=>s.dist_km!=null&&s.dist_km<=RADIUS
    &&s.name!=='Budapest');   // the city-wide aggregate; its 23 districts rank on their own
  DATA.forEach(s=>s.ovoda_per_1k=s.ovoda_places&&s.pop_2022
    ?1000*s.ovoda_places/s.pop_2022:null);
  // formatted once per scope change instead of once per row per render (13ms/render)
  DATA.forEach(s=>s._pops=(s.pop_2022||0).toLocaleString('hu'));
  computeSimilarity(DATA);
  pct=percentiles(DATA);
  buildStats(DATA);
  const sub=document.getElementById('sub');
  if(sub) sub.textContent = !COMMUTE_OK
    ? t('no_commute','Commute data unavailable — /api/anchor did not answer.')
    : (LANG==='hu' ? HU.sub_fmt(DATA.length,RADIUS,ANCHOR.name)
                   : `${DATA.length} settlements within ${RADIUS} km of ${ANCHOR.name}`)
      +(ANCHOR2?` · ${t('work2','2nd workplace')}: ${ANCHOR2.name}`:'');
  if(map&&map.getSource('sett')) render();
}

let SEARCH='';
// accent-insensitive so "voroce" finds "Verőce"
const fold=t=>(t||'').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'');
// which hard filters a settlement fails, for the row tooltip
const failed=s=>FILTERS.filter(f=>f.on&&!f.f(s)).map(f=>t('f_'+f.k,f.n));

// Median + extremes of the current scope, so an eye-catching number can be judged
// against its peers instead of in a vacuum (+294% price growth looks alarming until
// you see the neighbours did +237%).
let STATS={};
const STAT_KEYS=['pop_trend_21y_pct','school_score_mean','school_vs_national',
  'price_m2','price_trend_pct','garden_score',
  'frost_risk','commute_best_min','crime_rate_county'];
// price stats follow UI.kind, so buildStats() must rerun when the kind switches
const STAT_GET={price_m2:r=>kf(r,'price_m2'), price_trend_pct:r=>kf(r,'price_trend_pct')};
function buildStats(rows){
  STATS={};
  for(const k of STAT_KEYS){ const g=STAT_GET[k]||(r=>r[k]);
    const v=rows.map(g).filter(x=>typeof x==='number'&&isFinite(x)).sort((a,b)=>a-b);
    if(v.length>8) STATS[k]={med:v[v.length>>1], lo:v[Math.floor(v.length*0.05)],
                             hi:v[Math.floor(v.length*0.95)], n:v.length};
  }
}
// returns a muted "median X" note, flagged when the value sits in the top/bottom 5%
function ctx(k,v,fmt=(x=>x)){
  const st=STATS[k]; if(!st||typeof v!=='number'||!isFinite(v)) return '';
  const mark = v>=st.hi ? ' ▲' : (v<=st.lo ? ' ▼' : '');
  return `<i class="ctx">${t('median','median')} ${fmt(st.med)}${mark}</i>`;
}

let MODE='score';   // 'score' | 'value'
const ROW_CAP=300;  // rows drawn per render; see the note in render()
const PROFILES={
 kertesz:{garden_score:3,frost_risk:2,frost_free_days:2,south_facing:1,precip_mm_yr:1,
   commute_best_min:2,house_price_m2:2,pm25_winter:1,pollution_nearest_km:1},
 gyerekes:{school_score_mean:3,school_beats_prediction:2,ovoda_per_1k:2,
   families_with_children_pct:2,pop_trend_21y_pct:2,commute_best_min:3,pm25_winter:2,
   house_price_m2:2,pollution_nearest_km:1},
 ingazo:{commute_best_min:3,house_price_m2:2,pop_trend_21y_pct:1,dwelling_comfort_pct:1,
   pm25_winter:1},
 olcso:{house_price_m2:3,commute_best_min:1,pop_trend_21y_pct:1,garden_score:1,
   dwelling_comfort_pct:1},
 termeszet:{landscape_sim:2,garden_score:2,pm25_winter:2,pollution_nearest_km:2,
   frost_risk:1,commute_best_min:1,house_price_m2:1},
};
// English names for the group and profile ids; the Hungarian ones live in lang.js
const NAMES_EN={g_csalad:'Family & school',g_ingatlan:'Property & price',g_kozlekedes:'Transport',
  g_kert:'Garden & landscape',g_kornyezet:'Environment & safety',p_kertesz:'Gardener',
  p_gyerekes:'Young family',p_ingazo:'Commuter',p_olcso:'On a budget',p_termeszet:'Close to nature'};
function applyProfile(id){
  const P=PROFILES[id]; if(!P) return;
  for(const m of METRICS) m.w = P[m.k] || 0;
  buildUI(); computeSimilarity(DATA); pct=percentiles(DATA); render();
  // buildUI() replaces the button that was just activated, so focus lands on <body>
  // and keyboard users lose their place. Put it back on the new instance.
  document.querySelector(`[data-p="${id}"]`)?.focus();
}
let LANDREF=null;   // ksh of the settlement whose landscape we are matching
// The Táj column and the "hidden better matches" warning are about the landscape
// RANKING, which only happens when the metric carries weight. A reference with the
// weight at zero changes nothing, so it must not add a column or raise a warning.
const landOn=()=>!!(LANDREF&&METRICS.find(m=>m.k==='landscape_sim')?.w);

// Landscape is not a scale - "more forest" is not better, it is a preference. So instead
// of asking for numbers, let the user point at a place they like and rank by similarity
// in landscape-feature space. z-scored so no single feature dominates.
const LAND_F=['lc_tree_pct','lc_crop_pct','lc_grass_pct','lc_built_pct','lc_water_pct',
              'local_relief_m','bigriver_km','lake_km'];
function computeSimilarity(rows){
  rows.forEach(r=>{r._sim=null; r._d=null;});
  if(!LANDREF) return;
  const ref=rows.find(r=>r.ksh===LANDREF)||ALL.find(r=>r.ksh===LANDREF);
  if(!ref) return;
  const st={};
  for(const f of LAND_F){
    const v=rows.map(r=>r[f]).filter(x=>typeof x==='number'&&isFinite(x));
    if(v.length<10){st[f]=null;continue;}
    const m=v.reduce((a,b)=>a+b,0)/v.length;
    const sd=Math.sqrt(v.reduce((a,b)=>a+(b-m)**2,0)/v.length)||1;
    st[f]={m,sd};
  }
  let max=0;
  for(const r of rows){
    let d=0,n=0;
    for(const f of LAND_F){
      if(!st[f]||typeof r[f]!=='number'||typeof ref[f]!=='number') continue;
      d+=((r[f]-ref[f])/st[f].sd)**2; n++;
    }
    if(!n) continue;
    r._d=Math.sqrt(d/n); if(r._d>max) max=r._d;
  }
  for(const r of rows) r._sim = r._d==null?null:Math.max(0,1-r._d/(max||1));
}

// --- price reliability: every place a price is shown also says how many sales it rests on
const lowTxTitle=s=>LANG==='hu'?HU.low_tx_t(kf(s,'tx')??null)
  :`Thin data: the price rests on ${kf(s,'tx')??'an unknown number of'} sales`;
const txHtml=s=>{ const n=kf(s,'tx');
  return (num(n)?`<span class="txn">· ${esc(LANG==='hu'?HU.tx_from(n):`from ${n} sales`)}</span>`:'')
    +(lowTx(s)?` <span class="lowtx" title="${esc(lowTxTitle(s))}">${esc(t('low_tx','thin data'))}</span>`:''); };

// --- comparison: 2-5 settlements side by side -------------------------------------------
const CMP_MAX=5;
let CMP=stored('bl_cmp',[]);
if(!Array.isArray(CMP)) CMP=[];
CMP=CMP.filter(x=>typeof x==='string').slice(0,CMP_MAX);   // unknown ksh are dropped on data load

const fx1=x=>Math.round(x*10)/10, sgn=x=>(x>0?'+':'')+x;
const NEAREST_SRC=[['landfill_km','r_landfill','Landfill'],['quarry_km','r_quarry','Quarry'],
  ['wwtp_km','r_wwtp','Sewage plant'],['works_km','r_works','Factory']];
// One entry per row: label, value (a number to rank on), dir (+1 higher is better, -1 lower
// is better, 0 = a preference or a count, never ranked or highlighted), fmt (text shown),
// note (muted second line). Adding a field = one line here.
const CMP_ROWS=[
 {l:()=>t('cmp_score','Score (current weights)'), v:s=>DATA.includes(s)?Math.round(s._s*100):null, dir:1},
 {l:()=>t('r_pop','Population'), v:s=>s.pop_2022, dir:0, fmt:x=>Math.round(x).toLocaleString('hu')},
 {l:()=>t('r_trend','21-year trend'), v:s=>s.pop_trend_21y_pct, dir:1, fmt:x=>sgn(Math.round(x))+' %'},
 {l:()=>t('cmp_commute','Commute'), v:s=>s.commute_best_min, dir:-1,
  fmt:(x,s)=>(num(s.commute2_min)?`${s.commute1_min} / ${s.commute2_min}`:x)+' '+t('min','min')},
 {l:()=>LANG==='hu'?HU.cmp_price(UI.size,UI.kind):`${UI.size} m² ${UI.kind} price`, v:costOf, dir:-1,
  fmt:x=>Math.round(x)+' M Ft', note:s=>`${kf(s,'price_m2')} eFt/m² (${kf(s,'price_year')??'?'})`, tx:true},
 {l:()=>t('cmp_school','School vs national'), v:s=>s.school_vs_national, dir:1, fmt:sgn},
 {l:()=>t('m_ovoda_per_1k','Óvoda places / 1k'), dir:1, fmt:fx1,
  v:s=>s.ovoda_places&&s.pop_2022?1000*s.ovoda_places/s.pop_2022:null},
 {l:()=>t('cmp_gp','Unfilled GP practices / 10k'), dir:-1, fmt:fx1,
  v:s=>s.pop_2022>0?1e4*(s.gp_vacant||0)/s.pop_2022:null},
 {l:()=>t('m_families_with_children_pct','Families with kids'), v:s=>s.families_with_children_pct, dir:1, fmt:x=>fx1(x)+' %'},
 {l:()=>t('m_unemployment_pct','Unemployment'), v:s=>s.unemployment_pct, dir:-1, fmt:x=>fx1(x)+' %'},
 {l:()=>t('m_dwelling_vacancy_pct','Dwelling vacancy'), v:s=>s.dwelling_vacancy_pct, dir:-1, fmt:x=>fx1(x)+' %'},
 {l:()=>t('r_pm25w','Winter PM2.5'), v:s=>s.pm25_winter, dir:-1, fmt:x=>fx1(x)+' µg/m³'},
 {l:()=>t('cmp_land','Forest / built-up'), v:s=>s.lc_tree_pct, dir:0,
  fmt:(x,s)=>`${Math.round(x)} / ${num(s.lc_built_pct)?Math.round(s.lc_built_pct):'—'} %`},
 {l:()=>t('r_garden','Garden score'), v:s=>s.garden_score, dir:1, fmt:x=>x+' / 100'},
 {l:()=>t('r_frost','Frost pocket'), v:s=>s.frost_risk, dir:-1, fmt:x=>x+' / 100'},
 // a count of flags: fewer is better, but "3rd of 400 with no flag" is not a rank
 {l:()=>t('cmp_flood','Flood / water'), dir:-1, rank:false,
  // no water layer at all (the sample dataset) is unknown, not "none"
  v:s=>s.in_floodway==null&&s.in_floodplain==null&&s.in_waterlogged==null?null
    :[s.in_floodway,s.in_floodplain,s.in_waterlogged].filter(Boolean).length,
  fmt:(x,s)=>x?[s.in_floodway&&t('sum_floodway','floodway'),s.in_floodplain&&t('sum_floodplain','floodplain basin'),
    s.in_waterlogged&&t('sum_wet','water-affected land')].filter(Boolean).join(', '):t('cmp_none','none')},
 {l:()=>t('cmp_poll','Nearest pollution source'), v:s=>s.pollution_nearest_km, dir:1, fmt:x=>fx1(x)+' km',
  note:s=>{ const n=NEAREST_SRC.filter(([k])=>num(s[k])).sort((a,b)=>s[a[0]]-s[b[0]])[0];
    return n?t(n[1],n[2]):''; }},
 {l:()=>t('s_summary','In short'), dir:0, rank:false, wide:true,
  v:s=>summarize(s,workNames(),DATA.includes(s)?RADIUS:null)||null},
 {l:()=>t('cmp_op','Opinions online'), dir:0, rank:false,
  v:s=>s.op_status==='ok'&&s.op_summary?t('cmp_op_ok','summary available')
    :s.op_status==='thin'?t('cmp_op_thin','too few opinions'):t('cmp_op_no','none')},
];

function renderCompare(){
  const cols=CMP.map(k=>ALL.find(s=>s.ksh===k)).filter(Boolean);
  // Simplification: ranks rescan DATA per row (20 x ~3k), fine on open; cache per row if rows grow tenfold
  const body=CMP_ROWS.map(row=>{
    const vals=cols.map(s=>row.v(s)), nums=vals.filter(num);
    const ranked=row.dir&&row.rank!==false;
    const pool=ranked?DATA.map(row.v).filter(num):null;
    // best = the extreme in the row's direction; no best when fewer than two have data or all tie
    const best=row.dir&&nums.length>1&&Math.min(...nums)!==Math.max(...nums)
      ?(row.dir>0?Math.max(...nums):Math.min(...nums)):null;
    return `<tr${row.wide?' class="wide"':''}><th scope="row">${esc(row.l())}</th>`+cols.map((s,i)=>{
      const v=vals[i];
      if(v==null||v==='') return `<td class="none">—</td>`;
      const isBest=best!==null&&v===best;
      const rank=ranked&&num(v)&&DATA.includes(s)
        ?1+pool.filter(x=>row.dir>0?x>v:x<v).length:null;
      const note=row.note?row.note(s):'';
      return `<td${isBest?' class="best"':''}>${esc(row.fmt?row.fmt(v,s):v)}`
        +(isBest?`<span class="sr"> (${esc(t('cmp_best','best'))})</span>`:'')
        +(rank?`<small class="rank"><span class="sr">${esc(t('cmp_rank','rank'))} </span>${rank}. / ${pool.length}</small>`:'')
        +(note||row.tx?`<small>${esc(note)}${row.tx?' '+txHtml(s):''}</small>`:'')+`</td>`;
    }).join('')+`</tr>`;
  }).join('');
  return `<div class="cmph"><button type="button" id="cmp-x">${esc(t('cmp_close','Close'))}</button>`
    +`<h2 id="cmp-h">${esc(t('cmp_title','Comparison'))}</h2>`
    +`<p class="co">${esc(LANG==='hu'?HU.cmp_scope(DATA.length,RADIUS,workNames())
      :`Ranks are within the current ${DATA.length} settlements (${RADIUS} km — ${workNames()}). Best value per row highlighted.`)}</p></div>`
    // focusable so a keyboard user can scroll it sideways at phone width
    +`<div class="cmpwrap" tabindex="0" role="region" aria-labelledby="cmp-h"><table class="cmpt">`
    +`<thead><tr><td></td>${cols.map(s=>`<th scope="col"><button type="button" class="cmprm" data-cmp-x="${esc(s.ksh)}"`
      +` aria-label="${esc(LANG==='hu'?HU.cmp_remove(s.name):`Remove ${s.name} from the comparison`)}">×</button>`
      +`${esc(s.name)}<small>${esc(s.megye||'')}${DATA.includes(s)?'':' · '+esc(t('cmp_out','not in the current ranking'))}</small></th>`).join('')}</tr></thead>`
    +`<tbody>${body}</tbody></table></div>`;
}
// selection changed: persist, then sync every control that shows it. Never re-render the
// table here - it would replace the checkbox the user is standing on and drop their focus.
function cmpSync(msg){
  store('bl_cmp',CMP);
  const bar=document.getElementById('cmpbar'); if(!bar) return;
  bar.hidden=!CMP.length&&!msg;
  document.getElementById('cmp-n').textContent=msg||(LANG==='hu'?HU.cmp_n(CMP.length)
    :`Selected for comparison: ${CMP.length} / ${CMP_MAX}`)+(CMP.length===1?' — '+t('cmp_need','pick at least one more'):'');
  document.getElementById('cmp-open').disabled=CMP.length<2;
  document.querySelectorAll('[data-cmp]').forEach(el=>{ const on=CMP.includes(el.dataset.cmp);
    if(el.type==='checkbox') el.checked=on; else el.setAttribute('aria-pressed',String(on)); });
}
function cmpToggle(ksh,on){
  const has=CMP.includes(ksh);
  if(on&&!has){ if(CMP.length>=CMP_MAX) return cmpSync(t('cmp_max','At most 5 settlements can be compared — remove one first.'));
    CMP.push(ksh); }
  if(!on) CMP=CMP.filter(x=>x!==ksh);
  cmpSync();
}
const cmpBtn=rec=>rec?`<button type="button" class="cmptog" data-cmp="${esc(rec.ksh)}" aria-pressed="${CMP.includes(rec.ksh)}">`
  +`${esc(t('cmp_add','Compare'))}</button>`:'';

function render(){
  DATA.forEach(s=>s._cost=costOf(s));
  DATA.forEach(s=>s._pass=passes(s));
  const kept=DATA.filter(s=>s._pass);
  DATA.forEach(s=>s._s=score(s));
  valueResidual(kept);
  const key=s=>MODE==='value'?(s._v??-1):s._s;
  kept.sort((a,b)=>key(b)-key(a));
  if(map.getSource('bounds')){
    const on=new Set(kept.map(s=>s.ksh));
    // clear every settlement, not just the in-scope ones: a smaller radius must
    // un-shade what it dropped
    for(const s of ALL) map.setFeatureState({source:'bounds',id:s.ksh},
      {s:on.has(s.ksh)?(key(s)<0?0:key(s)):0,
       on:on.has(s.ksh)&&!(MODE==='value'&&s._v==null)?1:0});
    void 0;
  }
  map.getSource('sett').setData({type:'FeatureCollection',features:kept.map(s=>({
    type:'Feature',geometry:{type:'Point',coordinates:[s.lon,s.lat]},
    properties:{...s,_s:key(s)<0?0:key(s),
      _r:Math.min(24,3+Math.sqrt(s.pop_2022||400)/9.5)}}))})
      ;
  const q=fold(SEARCH);
  const listed=(q?DATA.filter(s=>fold(s.name).includes(q)):DATA)
    .slice().sort((a,b)=>(b._pass-a._pass)||(key(b)-key(a)));
  // Simplification: 300 rows of DOM is the whole cost of a slider move at national scope
  // (~150ms measured). Nobody scrolls to rank 900; the count still reports the truth.
  const shown=listed.slice(0,ROW_CAP);
  const land=landOn();
  // share of the active weight a row actually has data for. Cheap because it only runs
  // over the rows we are about to draw, not all 3178.
  const act=METRICS.filter(m=>m.w), wtot=act.reduce((a,m)=>a+m.w,0);
  const coverage=s=>{ if(!wtot) return 1; let c=0;
    for(const m of act) if(pct[m.k](mval(m,s))!==null) c+=m.w;
    return c/wtot; };
  document.getElementById('count').innerHTML= !COMMUTE_OK
   ? `<span class="warn">${esc(t('no_commute','Commute data unavailable — /api/anchor did not answer.'))}</span>`
   : (LANG==='hu'?HU.pass(kept.length,DATA.length)
      :`<b>${kept.length}</b> of ${DATA.length} settlements pass`)
    +(q?` · <span style="color:var(--muted)">${listed.length} ${t('shown','shown')}</span>`:'')
    +(listed.length>shown.length?` · <span style="color:var(--muted)">${LANG==='hu'
        ?HU.capped(shown.length,listed.length)
        :`showing the first ${shown.length} of ${listed.length}`}</span>`:'')
    +(MODE==='value'?`<div class="hintline">${esc(t('v_hint',
        'Value for money = how much better the settlement is than its price suggests.'))}</div>`:'')
    +(()=>{ if(!land) return '';
      const best=Math.max(...kept.map(s=>s._sim??0), 0);
      const n=DATA.filter(s=>!s._pass&&(s._sim??0)>best).length;
      if(!n) return '';
      const nm=esc((ALL.find(s=>s.ksh===LANDREF)||{}).name||'');
      return `<div class="warnline">${LANG==='hu'?HU.hidden_better(n,nm)
        :`⚠ ${n} filtered-out settlements match ${nm}'s landscape more closely`}</div>`;})();
  const _t=document.getElementById('tbl'); if(_t) _t.classList.toggle('land',land);
  const _c8=document.getElementById('c8'); if(_c8) _c8.hidden=!land;
  document.getElementById('tbody').innerHTML=shown.map(s=>{
    // measured: at default weights this flags ~5% of rows (p5 of the coverage
    // distribution is 0.80), so it stays a signal rather than a decoration.
    const cov=coverage(s), thin=cov<0.8;
    return `
    <tr class="r${s._pass?'':' fail'}" data-ksh="${esc(s.ksh)}" data-lon="${s.lon}" data-lat="${s.lat}"
        title="${s._pass?'':esc(t('fails','fails: ')+failed(s).join(', '))}">
      <td><input type="checkbox" class="cmp" data-cmp="${esc(s.ksh)}"${CMP.includes(s.ksh)?' checked':''}
        aria-label="${esc(LANG==='hu'?HU.a_cmp(s.name):`Add ${s.name} to the comparison`)}"><button type="button" class="rowbtn"><span class="dot" style="background:${rampCss(key(s)<0?0:key(s))}"></span>${esc(s.name)}</button></td>
      <td${thin?` class="thin" title="${esc(LANG==='hu'?HU.lowcov(Math.round(100-cov*100))
          :`Thin data: ${Math.round(100-cov*100)}% of the active weight is missing here`)}"`:''}>${MODE==='value'
        ?(s._resid==null?'—':(s._resid>0?'+':'')+(s._resid*100).toFixed(0))
        :(s._s*100).toFixed(0)}${thin?'<i class="thinmark">·</i>':''}</td><td>${s.commute_best_min??''}</td>
      <td>${s._pops}</td>
      <td>${s.pop_trend_21y_pct==null?'':(s.pop_trend_21y_pct>0?'+':'')+s.pop_trend_21y_pct.toFixed(0)}</td>
      ${s._cost==null?'<td>—</td>':lowTx(s)
        // Simplification: ~half of all priced rows sit under LOW_TX, so the mark is a muted "~", not a warning
        ?`<td class="lowc" title="${esc(lowTxTitle(s))}"><i class="lowmark" aria-hidden="true">~</i>${s._cost.toFixed(0)}<span class="sr">, ${esc(t('low_tx','thin data'))}</span></td>`
        :`<td>${s._cost.toFixed(0)}</td>`}
      <td>${s.garden_score??'—'}</td>
      <td ${land?'':'hidden'}>${s._sim==null?'—':(s._sim*100).toFixed(0)}</td></tr>`;}).join('');
  document.querySelectorAll('#tbody tr').forEach(tr=>tr.onclick=e=>{
    if(e.target.closest('.cmp')) return;   // the compare checkbox is its own control
    map.flyTo({center:[+tr.dataset.lon,+tr.dataset.lat],zoom:11});
    // DATA, not kept: a row that fails a filter is listed, so it must open too
    const s=DATA.find(x=>x.ksh===tr.dataset.ksh);
    if(s){ const R=document.getElementById('report');
      // the table is hidden behind the report, so focus must not stay on the row button
      R.innerHTML=renderWhy(s); showPanel(true); document.getElementById('back')?.focus(); }
  });
}

const doy=d=>{if(d==null) return null;
  const x=new Date(2025,0,1); x.setDate(d);
  return x.toLocaleDateString(LANG==='hu'?'hu-HU':'en-GB',{month:'short',day:'numeric'});};
const kv=(k,v,bad)=>v==null||v===''?'':`<div class="kv${bad?' bad':''}">${k}<b>${v}</b></div>`;
// The two summaries that open every settlement panel. rec is the ALL record: commute and
// the op_* web-opinion fields live there, not in /api/plot's settlement subset.
function summaryHtml(rec){
  if(!rec) return '';
  const inScope=DATA.includes(rec), txt=summarize(rec,workNames(),inScope?RADIUS:null);
  // op_* is open-web text picked by an LLM: escape all of it, and only http(s) becomes a link
  const link=x=>{ let u=null; try{ u=new URL(x.u); }catch(e){}
    const lab=esc(x.t||(u?u.hostname:x.u));
    return u&&(u.protocol==='http:'||u.protocol==='https:')
      ?`<a href="${esc(u.href)}" target="_blank" rel="noopener noreferrer">${lab}</a>`:lab; };
  const src=Array.isArray(rec.op_sources)?rec.op_sources.filter(x=>x&&(x.t||x.u)):[];
  return (txt?`<section class="sum"><h2 class="sec">${t('s_summary','In short')}</h2><p>${esc(txt)}</p>`
    +(inScope?'':`<p class="opnote">${t('sum_out','Not in the current ranking, so it is not compared with the area.')}</p>`)+`</section>`:'')
   +(rec.op_status==='ok'&&rec.op_summary
     ?`<section class="sum"><h2 class="sec">${t('op_head','Opinions online')}</h2><p>${esc(rec.op_summary)}</p>`
      +(src.length?`<ul aria-label="${esc(t('op_src','Sources'))}">${src.map(x=>`<li>${link(x)}</li>`).join('')}</ul>`:'')
      +`<p class="opnote">${t('op_note','AI-generated summary of public web sources')}`
      +`${rec.op_date?' · '+esc(rec.op_date):''}</p></section>`
     :rec.op_status==='thin'?`<p class="sum opnote">${t('op_thin','Not enough public opinions found online.')}</p>`:'');
}
function renderReport(d,lat,lng){
  const head=(title,sub,acts='')=>`<div id="rhead"><button id="back">${t('back','← results')}</button>`
    +`<b>${title}</b><div class="co">${sub}</div>${acts}</div>`;
  if(d.error) return head(t('fail','Lookup failed'),'')+`<div class="note">${esc(d.error)}</div>`;
  const s=d.soil||{},tr=d.terrain||{},w=d.water||{},f=d.fibre,r=d.rail,st=d.settlement||{};
  // prices come from the ALL record: /api/plot's settlement subset has no flat_* fields
  const rec=st.name&&ALL.find(x=>x.name===st.name);   // names are unique across ALL
  // any clicked point can be a workplace; it is named after the settlement it falls in
  const wname=`${st.name||`${lat.toFixed(3)}, ${lng.toFixed(3)}`} (${t('pt','point')})`;
  const workBtn=(i,label)=>`<button type="button" class="act" data-work="${i}" data-lat="${lat}" data-lon="${lng}"`
    +` data-name="${esc(wname)}">${label}</button>`;
  const acts=`<div class="acts">${cmpBtn(rec)}${workBtn(0,t('work_here','Workplace here'))}`
    +`${workBtn(1,t('work2_here','2nd workplace here'))}<span class="actmsg" role="status"></span></div>`;
  // null = that layer is not loaded on the server (the sample dataset): kv() then skips the row
  const yn=v=>v==null?null:v?t('yes','YES — avoid'):t('no','no');
  return head(esc(st.name||'Plot'),
    `${lat.toFixed(5)}, ${lng.toFixed(5)} · ${esc(st.megye||'')} · ${t('centre','village centre')} ${esc(d.settlement_km)} ${t('km','km')}`,acts)
   +summaryHtml(rec)
   +`<div class="sec">${t('s_garden','Garden')}</div>`
   +kv(`${t('r_texture','Texture')}`
        +(t('tip_texture','')?` <button type="button" class="q" data-note="tip-texture" aria-expanded="false">?</button>`:''),
       s.texture?t('tex_'+s.texture,s.texture):null)
   +(t('tip_texture','')?`<div class="hintline nt" id="tip-texture" hidden>${t('tip_texture','')}</div>`:'')
   +kv(t('r_frac','Sand / silt / clay'),s.soil_sand_pct==null?null:
       `${s.soil_sand_pct} / ${s.soil_silt_pct} / ${s.soil_clay_pct} %`)
   +kv(t('r_ph','pH'),s.soil_ph)+kv(t('r_om','Organic matter'),s.soil_om_pct==null?null:s.soil_om_pct+' %')
   +kv(t('r_lime','Lime'),s.soil_lime_pct==null?null:s.soil_lime_pct+' %')
   +kv(t('r_garden','Garden score'),s.garden_score==null?null:s.garden_score+' / 100')
   +(s.texture==null&&s.soil_ph==null?`<div class="hintline nt">${t('s_garden_down','Soil data source unavailable — the rest of the report is unaffected.')}</div>`:'')
   +`<div class="sec">${t('s_terrain','Terrain')}</div>`
   +kv(t('r_elev','Elevation'),tr.elevation_m==null?null:tr.elevation_m+' m')
   +kv(t('r_slope','Slope'),tr.slope_deg==null?null:tr.slope_deg+'°')
   +kv(t('r_aspect','Aspect'),tr.aspect_deg==null?t('flat','flat'):tr.aspect_deg+'°')
   +kv(t('r_south','South-facing'),tr.south_facing)
   +kv(t('r_relief','Local relief'),tr.local_relief_m==null?null:tr.local_relief_m+' m')
   +kv(t('r_frost','Frost pocket'),tr.frost_risk==null?null:tr.frost_risk+' / 100',tr.frost_risk>=60)
   +(Object.values(w).some(v=>v!=null)?`<div class="sec">${t('s_water','Water')}</div>`:'')
   +kv(t('r_floodway','Floodway'),yn(w.floodway),w.floodway)
   +kv(t('r_floodplain','Floodplain basin'),yn(w.floodplain),w.floodplain)
   +kv(t('r_wet','Water-affected'),yn(w.waterlogged),w.waterlogged)
   +(f?`<div class="sec">${t('s_broadband','Broadband')}</div>`
     +kv(t('r_u100','Unserved within 100 m'),f.within_100m,f.within_100m>0)
     +kv(t('r_u500','Unserved within 500 m'),f.within_500m)
     +kv(t('r_unearest','Nearest unserved'),f.nearest_km+' km')
     +`<div class="note">${esc(f.address)}<br>${t('r_note',
       'NMHH survey lists addresses with no high-speed fixed line. Absence is not proof fibre is available.')}</div>`:'')
   +(r?`<div class="sec">${t('s_commute','Commute')}</div>`
     +kv(t('r_d2d','Door to desk'),r.door_to_desk+' '+t('min','min'))
     +kv(t('r_station','Station'),`${esc(r.station)} · ${esc(r.km)} km`)
     +kv(t('r_rail','Rail'),`${esc(r.rail_min)} ${t('min','min')} → ${esc(r.terminus)}`)
     +kv(t('r_trains','Morning trains'),r.trains_am):'')
   +(st.relief_class||st.lc_tree_pct!=null?`<div class="sec">${t('s_land','Landscape')}</div>`
     +kv(t('r_relief','Relief'),st.relief_class)
     +kv(t('r_tree','Forest'),st.lc_tree_pct!=null?st.lc_tree_pct+' %':null)
     +kv(t('r_crop','Arable'),st.lc_crop_pct!=null?st.lc_crop_pct+' %':null)
     +kv(t('r_grass','Grass'),st.lc_grass_pct!=null?st.lc_grass_pct+' %':null)
     +kv(t('r_built','Built-up'),st.lc_built_pct!=null?st.lc_built_pct+' %':null)
     +kv(t('r_lcwater','Water'),st.lc_water_pct?st.lc_water_pct+' %':null)
     +kv(t('r_bigriver','Major river'),st.bigriver_km!=null
        ?st.bigriver_km+' km'+(st.bigriver_name?' · '+esc(st.bigriver_name):''):null)
     +kv(t('r_lake','Lake'),st.lake_km!=null
        ?st.lake_km+' km'+(st.lake_name?' · '+esc(st.lake_name):''):null):'')
   +(st.pm25_annual?`<div class="sec">${t('s_env','Environment & climate')}</div>`
     +kv(t('r_pm25w','Winter PM2.5'),st.pm25_winter+' µg/m³',st.pm25_winter>=20)
     +kv(t('r_pm25a','Annual PM2.5'),st.pm25_annual+' µg/m³')
     +kv(t('r_no2','Annual NO₂'),st.no2_annual+' µg/m³')
     +kv(t('r_precip','Rainfall'),st.precip_mm_yr+' mm')
     +kv(t('r_raindays','Rain days'),st.rain_days_yr)
     +kv(t('r_wind','Wind (daily max avg)'),st.wind_kmh_mean+' km/h')
     +kv(t('r_lastfrost','Last spring frost'),doy(st.last_frost_doy))
     +kv(t('r_frostfree','Frost-free days'),st.frost_free_days)
     +kv(t('r_hotdays','Hot days (≥30 °C)'),st.hot_days_yr)
     +kv(t('r_pv','Solar yield (1 kWp)'),st.pv_kwh_kwp?st.pv_kwh_kwp+' kWh':null)
     +`<div class="note">${t('r_env_note',
       'Air is CAMS (~11 km); rain/wind/frost is NASA POWER (~50 km) — a regional signal, not street level. The local frost pocket is computed separately from terrain. WHO guideline: PM2.5 annual 5 µg/m³.')}</div>`:'')
   +(st.pollution_nearest_km!=null?`<div class="sec">${t('s_src','Point sources (OSM)')}</div>`
     +kv(t('r_landfill','Landfill'),st.landfill_km!=null?st.landfill_km+' km':null,st.landfill_km<2)
     +kv(t('r_quarry','Quarry'),st.quarry_km!=null?st.quarry_km+' km':null,st.quarry_km<2)
     +kv(t('r_wwtp','Sewage plant'),st.wwtp_km!=null?st.wwtp_km+' km':null,st.wwtp_km<2)
     +kv(t('r_works','Factory'),st.works_km!=null?st.works_km+' km':null,st.works_km<2)
     +kv(t('r_within3','Within 3 km'),st.pollution_sources_3km,st.pollution_sources_3km>=3)
     +`<div class="note">${t('r_src_note',
       'From OSM, measured from the village centre. NOT included: E-PRTR actual emission quantities and IED installations (incl. livestock farms), contaminated-land register. Asbestos: Hungary has no public register — it is a per-building question answered by survey.')}</div>`:'')
   +(st.crime_rate_county?`<div class="sec">${t('s_crime','Crime (county)')}</div>`
     +kv(t('r_crime_rate','Offences / 100k'),st.crime_rate_county+' ('+(st.crime_year||'')+')')
     +kv(t('r_crime_trend','change since 2015'),
         st.crime_trend_county==null?null:(st.crime_trend_county>0?'+':'')+st.crime_trend_county+'%')
     +`<div class="note">${t('r_crime_note',
       'County-level: settlement statistics sit behind a personal login, so every village shows its county figure.')}</div>`:'')
   +`<div class="sec">${t('s_settlement','Settlement')} — ${esc(st.name||'')}</div>`
   +kv(`${t('r_price','Price')} (${t('k_'+UI.kind,UI.kind)})`,rec&&num(kf(rec,'price_m2'))
       ?`${kf(rec,'price_m2')} eFt/m² (${esc(kf(rec,'price_year')??'?')}) ${txHtml(rec)}`:null)
   +kv(`${UI.size} m² ${t('r_cost_short','costs')}`,rec&&costOf(rec)!=null?Math.round(costOf(rec))+' M Ft':null)
   +kv(t('r_pop','Population'),st.pop_2022?Math.round(st.pop_2022).toLocaleString('hu'):null)
   +kv(t('r_trend','21-year trend'),st.pop_trend_21y_pct==null?null:
       (st.pop_trend_21y_pct>0?'+':'')+st.pop_trend_21y_pct+' %')
   +kv(t('r_school','School'),st.school_score_mean?`${st.school_score_mean} (${st.school_vs_national>0?'+':''}${st.school_vs_national})`:null)
   +kv(t('r_ovoda','Óvoda'),st.ovoda_sites
       ?`${st.ovoda_sites} ${t('site','site(s)')}, ${st.ovoda_places} ${t('places','places')}`:null)
   +kv(t('r_gp','GP practice'),st.gp_vacant
        ?`${t('unfilled','unfilled since')} ${st.gp_vacant_since||'?'}`:t('filled','filled'),st.gp_vacant>0);
}

function renderSources(){
  const L=LANG==='hu'?'hu':'en';
  return `<div id="rhead"><button id="back">${t('back','← results')}</button>`
   +`<b>${t('src_title','Data sources')}</b></div>`
   +`<div class="note">${t('src_intro',
     'Every layer comes from a public source. The caveats below matter: missing data is not good news.')}</div>`
   +SOURCES.map(x=>`<div class="src"><b>${x[L]}</b>`
     +`<div class="who">${x.who}</div><div class="meta">${x.meta}`
     +(SRCDATES[x.id]?` · <span class="fetched">${t('fetched','last fetched')} ${SRCDATES[x.id]}</span>`:'')
     +`</div>`
     +(x['warn_'+L]?`<div class="warn2">${x['warn_'+L]}</div>`:'')
     +`</div>`).join('')
   +`<div class="sec">${t('src_missing','Deliberately not included')}</div>`
   +MISSING.map(x=>`<div class="src"><b>${x[L]}</b>`
     +`<div class="who">${x['why_'+L]}</div></div>`).join('');
}

function renderWhy(s){
  const rows=[];let wsum=0;
  for(const m of METRICS){ if(!m.w) continue;
    const p=pct[m.k](mval(m,s));
    if(p!==null) wsum+=m.w;
    rows.push({m,p,v:mval(m,s)});
  }
  rows.forEach(r=>r.pts=r.p===null?null:100*r.m.w*r.p/wsum);
  rows.sort((a,b)=>(b.pts??-1)-(a.pts??-1));
  const fmtv=v=>v==null?'—':(Math.abs(v)>=1000?Math.round(v).toLocaleString('hu')
    :(Math.round(v*10)/10));
  return `<div id="rhead"><button id="back">${t('back','← results')}</button>`
   +`<b>${esc(s.name)}</b><div class="co">${t('why','Score breakdown')} · `
   +`${(s._s*100).toFixed(0)} / 100</div><div class="acts">${cmpBtn(s)}</div></div>`
   +summaryHtml(s)
   +rows.map(r=>{
      const label=esc(t('m_'+r.m.k,r.m.n));
      if(r.p===null) return `<div class="wrow"><div class="wtop"><b>${label}</b>`
        +`<span>—</span></div><div class="wmeta"><span>`
        +`${t('why_none','no data — abstains from the average')}</span>`
        +`<span>×${r.m.w}</span></div></div>`;
      // both commutes when there are two workplaces; the sales count behind a price
      const shown=r.m.k==='commute_best_min'&&num(s.commute2_min)?`${s.commute1_min} / ${s.commute2_min}`
        :fmtv(r.v)+(r.m.k==='house_price_m2'?' '+txHtml(s):'');
      return `<div class="wrow"><div class="wtop"><b>${label}</b>`
        +`<span>${shown}</span></div>`
        +`<div class="wbar"><i style="width:${(r.p*100).toFixed(0)}%;`
        +`background:var(${r.m.c})"></i></div>`
        +`<div class="wmeta"><span>${t('why_pct','percentile')} ${(r.p*100).toFixed(0)}`
        +` · ${t('why_w','weight')} ×${r.m.w}</span>`
        +`<span>+${r.pts.toFixed(1)} ${t('why_pts','pts')}</span></div></div>`;
    }).join('')
   +`<div class="note">${t('why_hint',
      'The score is a weighted mean of the enabled metrics. Missing data abstains rather than scoring zero.')}</div>`;
}

function applyLang(){
  document.documentElement.lang=LANG;
  document.getElementById('lang').textContent=LANG==='hu'?'EN':'HU';
  const set=(id,v)=>{const e=document.getElementById(id); if(e) e.textContent=v;};
  set('h-area',t('h_area','Area'));
  set('h-profiles',t('h_profiles','Profiles'));
  set('h-land',t('h_land','Landscape'));
  set('land-note',t('land_note',
    'Type a settlement whose landscape you like — the "Landscape similarity" weight then ranks places like it, on forest/arable/grass/built-up/water share, relief and distance to water.'));
  const lr=document.getElementById('landref');
  if(lr){ lr.placeholder=t('l_landref','Like…');
    lr.setAttribute('aria-label',t('a_landref','Reference settlement for landscape similarity')); }
  set('area-note',t('area_note',
    "The house's floor area. KSH divides the full purchase price by the house's floor "
    +"area, so the plot's value IS included in the total — but the plot's SIZE is not, "
    +"because the source does not publish it. For a large garden, treat it as a floor."));
  set('l-radius',t('l_radius','Radius'));
  set('l-anchor',t('l_anchor','Workplace')); set('l-anchor2',t('l_anchor2','2nd workplace (optional)'));
  const an=document.getElementById('anchor');
  if(an) an.setAttribute('aria-label',t('a_anchor','Workplace — radius and commute are measured from here'));
  const an2=document.getElementById('anchor2');
  if(an2) an2.setAttribute('aria-label',t('a_anchor2','Second workplace — with two, the longer commute is ranked'));
  document.getElementById('anchor2-x')?.setAttribute('aria-label',t('x_anchor2','Remove the second workplace'));
  set('k-house',t('k_house','House')); set('k-flat',t('k_flat','Flat'));
  document.getElementById('kind')?.setAttribute('aria-label',t('a_kind','Property type — prices are read for this'));
  set('cmp-open',t('cmp_open','Compare')); set('cmp-clear',t('cmp_clear','Clear selection'));
  cmpSync();
  const lp=document.getElementById('left'), rp=document.getElementById('right'),
        mp=document.getElementById('map');
  if(lp) lp.setAttribute('aria-label',t('a_left','Filters and weights'));
  if(rp) rp.setAttribute('aria-label',t('a_right','Ranking and report'));
  if(mp) mp.setAttribute('aria-label',t('a_map','Map'));
  set('h-budget',t('h_budget','Budget')); set('h-must',t('h_must','Must have'));
  set('h-weights',t('h_weights','Weights'));
  set('l-size',t('l_size','Floor area')); set('l-budget',t('l_budget','Max budget'));
  set('u-budget',t('u_budget','M Ft')); set('l-areas',t('l_areas','Shade settlement areas'));
  set('hint',t('hint','Click anywhere on the map for a plot report'));
  const val = MODE==='value';
  set('l-legend', val ? t('v_legend','Value for money (vs price)')
                      : t('l_legend','Composite score'));
  set('l-low', val ? t('v_low','overpriced') : t('low','low'));
  set('l-high', val ? t('v_high','good buy')  : t('high','high'));
  const cols=[['c1','Settlement'],['c2','Score'],['c3','min'],['c4','Pop'],
              ['c5','21y%'],['c6','M Ft'],['c7','Soil'],['c8','Land']];
  cols.forEach(([id,en])=>{ set(id,t(id,en));
    // the headers are abbreviated to fit 452px; the long form lives in the title
    const th=document.getElementById(id), full=t(id+'_t','');
    if(th&&full) th.title=full; });
  const c8=document.getElementById('c8'); if(c8) c8.hidden=!landOn();
  const tbl=document.getElementById('tbl'); if(tbl) tbl.classList.toggle('land',landOn());
  const set2=(id,v)=>{const e=document.getElementById(id); if(e) e.textContent=v;};
  set2('h-view',t('v_mode','View'));
  set2('v-s',t('v_score','Score')); set2('v-v',t('v_value','Value for money'));
  set2('c2', MODE==='value'?t('v_col','Value'):t('c2','Score'));
  const qi=document.getElementById('q');
  if(qi){ qi.placeholder=t('q_ph','Search by name…');
    qi.setAttribute('aria-label',t('a_q','Search the ranking by name')); }
  const sb=document.getElementById('srcbtn');
  if(sb) sb.textContent=t('srcbtn','Data sources');
  const areas=document.getElementById('areas');
  set('szhint', !(areas && areas.checked)
    ? t('circle_mode','Circle colour = score · size = population')
    : (val ? t('v_fill','Fill = value · circle = population')
           : t('fill_mode','Fill = score · circle = population')));
}

function buildUI(){
  document.getElementById('filters').innerHTML=FILTERS.map(f=>
    `<label class="chk"><input type="checkbox" data-f="${f.k}" ${f.on?'checked':''}>${t('f_'+f.k,f.n)}</label>`).join('');
  const GROUPS=['csalad','ingatlan','kozlekedes','kert','kornyezet'];
  const open=JSON.parse(localStorage.getItem('bl_groups')||'{"csalad":1}');
  const dirHint=t('dir_hint','flip direction (↑ more is better / ↓ less is better)');
  const rowHtml=m=>{
    const tip=t('tip_'+m.k,''), label=esc(t('m_'+m.k,m.n));
    // the ⓘ used to be a title-only tooltip: invisible to touch and to the keyboard.
    // Same .q / data-note / .hintline disclosure the rest of the panel already uses.
    return `<div class="row"><div class="lab">
       <b id="lb-${m.k}">${label}</b>
       <span>${tip?`<button type="button" class="q" data-note="tip-${m.k}" aria-expanded="false">?</button>`:''}
       <button type="button" class="dir" data-d="${m.k}" title="${esc(dirHint)}"
         aria-label="${label} ${m.dir>0?'↑':'↓'} — ${esc(dirHint)}">${m.dir>0?'↑':'↓'}</button>
       <span class="wt" id="w-${m.k}">${m.w?('×'+m.w):t('off','off')}</span></span>
     </div>
     <input type="range" min="0" max="${m.max||10}" step="1" value="${m.w}" data-m="${m.k}"
       aria-labelledby="lb-${m.k}" style="--accent:var(${m.c})">`
     +(tip?`<div class="hintline" id="tip-${m.k}" hidden>${tip}</div>`:'')+`</div>`;};
  document.getElementById('weights').innerHTML=GROUPS.map(g=>{
    const ms=METRICS.filter(m=>m.g===g);
    if(!ms.length) return '';
    const act=ms.filter(m=>m.w).length;
    // a <button>, not a <div>: collapsed groups hide 16 sliders, and a div header is
    // unreachable by keyboard, so those sliders were unreachable too.
    return `<div class="grp"><button type="button" class="grph" data-g="${g}"
        aria-expanded="${open[g]?'true':'false'}">
        <span>${open[g]?'▾':'▸'} ${t('g_'+g,NAMES_EN['g_'+g])}</span>
        <span class="n">${act}/${ms.length}</span></button>
      <div class="grpb" ${open[g]?'':'hidden'}>${ms.map(rowHtml).join('')}</div></div>`;
  }).join('');
  document.getElementById('profiles').innerHTML=
    ['kertesz','gyerekes','ingazo','olcso','termeszet']
      .map(id=>`<button data-p="${id}">${t('p_'+id,NAMES_EN['p_'+id])}</button>`).join('');
  // house size and budget: these live outside the weight groups, so they must be
  // rebound here every time buildUI() redraws the panel
  for(const [id,k] of [['size','size'],['budget','budget']]){
    const el=document.getElementById(id);
    if(!el) continue;
    el.value=UI[k];
    el.oninput=()=>{UI[k]=+el.value;
      document.getElementById('v-'+id).textContent=el.value; render();};
  }
  document.querySelectorAll('[data-p]').forEach(b=>b.onclick=()=>applyProfile(b.dataset.p));
  document.querySelectorAll('.grph').forEach(h=>h.onclick=()=>{
    const g=h.dataset.g; open[g]=!open[g];
    localStorage.setItem('bl_groups',JSON.stringify(open));
    h.querySelector('span').textContent=(open[g]?'▾ ':'▸ ')+t('g_'+g,NAMES_EN['g_'+g]);
    h.setAttribute('aria-expanded',open[g]?'true':'false');
    h.nextElementSibling.hidden=!open[g];
  });
  // .q buttons are bound once, on the document - the report panel renders its own
  // long after buildUI() has stopped running.
  document.querySelectorAll('[data-f]').forEach(el=>el.onchange=()=>{
    FILTERS.find(f=>f.k===el.dataset.f).on=el.checked; render();});
  document.querySelectorAll('[data-m]').forEach(el=>el.oninput=()=>{
    const m=METRICS.find(x=>x.k===el.dataset.m); m.w=+el.value;
    document.getElementById('w-'+m.k).textContent=m.w?('×'+m.w):t('off','off');
    render();});
  document.querySelectorAll('.dir').forEach(b=>b.onclick=()=>{
    const m=METRICS.find(x=>x.k===b.dataset.d); m.dir=-m.dir;
    b.textContent=m.dir>0?'↑':'↓';
    b.setAttribute('aria-label',b.getAttribute('aria-label').replace(/[↑↓]/,b.textContent));
    pct=percentiles(DATA); render();});
}

document.getElementById('count').textContent=t('loading','Loading…');
fetch('/data/out/source_dates.json').then(r=>r.json()).then(d=>{SRCDATES=d;}).catch(()=>{});
fetch('/data/out/app_data.json').then(r=>{
  if(!r.ok) throw new Error('HTTP '+r.status);
  return r.json();
}).catch(e=>{
  console.error('app_data load failed',e);
  const c=document.getElementById('count');
  if(c) c.innerHTML=`<span class="warn">${esc(t('data_fail',
    'Could not load the dataset. Is the server running? (tools/serve.py)'))}</span>`;
  return null;
}).then(async d=>{
  if(!d) return;   // load failed; the message is already in #count
  ALL=d;
  const known=new Set(ALL.map(s=>s.ksh)); CMP=CMP.filter(k=>known.has(k));
  document.getElementById('anchors').innerHTML=
    ALL.filter(s=>(s.pop_2022||0)>=800).map(s=>`<option value="${esc(s.name)}">`).join('');
  await loadAnchors();
  window.map=map=new maplibregl.Map({container:'map',style:'https://tiles.openfreemap.org/styles/dark',
    center:[19.1,47.45],zoom:8.2,attributionControl:{compact:true}});
  map.addControl(new maplibregl.NavigationControl({showCompass:false}),'bottom-right');
  map.on('load',()=>{
    map.addSource('bounds',{type:'geojson',data:'/data/out/boundaries_ring.geojson',
      promoteId:'ksh'});
    map.addLayer({id:'bounds-f',type:'fill',source:'bounds',paint:{
      'fill-color':['interpolate',['linear'],['coalesce',['feature-state','s'],0],
        0,'#7e1f81',0.2,'#aa2c7a',0.4,'#d33e68',0.6,'#f25a54',0.8,'#fe875a',1,'#feb578'],
      'fill-opacity':['case',['==',['coalesce',['feature-state','on'],0],1],0.55,0]}});
    map.addLayer({id:'bounds-l',type:'line',source:'bounds',paint:{
      'line-color':'#2a2a2a','line-width':0.5,
      'line-opacity':['case',['==',['coalesce',['feature-state','on'],0],1],0.9,0.15]}});
    map.addSource('sett',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
    map.addLayer({id:'sett-c',type:'circle',source:'sett',paint:{
      'circle-radius':['get','_r'],
      'circle-color':['interpolate',['linear'],['get','_s'],
        0,'#7e1f81',0.2,'#aa2c7a',0.4,'#d33e68',0.6,'#f25a54',0.8,'#fe875a',1,'#feb578'],
      'circle-opacity':0.78,'circle-stroke-width':0.6,'circle-stroke-color':'#0e0e0e'}});
    const SCORE_COLOR=['interpolate',['linear'],['get','_s'],
      0,'#7e1f81',0.2,'#aa2c7a',0.4,'#d33e68',0.6,'#f25a54',0.8,'#fe875a',1,'#feb578'];
    const setMode=on=>{
      const v=on?'visible':'none';
      map.setLayoutProperty('bounds-f','visibility',v);
      map.setLayoutProperty('bounds-l','visibility',v);
      map.setPaintProperty('sett-c','circle-color',on?'#0e0e0e':SCORE_COLOR);
      map.setPaintProperty('sett-c','circle-opacity',on?0.22:0.78);
      map.setPaintProperty('sett-c','circle-stroke-color',on?'#e9eff6':'#0e0e0e');
      map.setPaintProperty('sett-c','circle-stroke-width',on?0.9:0.6);
      map.setPaintProperty('sett-c','circle-stroke-opacity',on?0.38:1);
      // szhint is applyLang()'s to write - it is the only writer that knows about
      // value mode, and two writers disagreed about what the legend said.
    };
    document.getElementById('areas').onchange=e=>{setMode(e.target.checked); applyLang();};
    const vs=document.getElementById('v-s'), vv=document.getElementById('v-v');
    const setMode2=m=>{MODE=m;
      vs.classList.toggle('on',m==='score'); vs.setAttribute('aria-pressed',String(m==='score'));
      vv.classList.toggle('on',m==='value'); vv.setAttribute('aria-pressed',String(m==='value'));
      applyLang(); render();};
    vs.onclick=()=>setMode2('score'); vv.onclick=()=>setMode2('value');
    const kh=document.getElementById('k-house'), kl=document.getElementById('k-flat');
    const syncKind=()=>{ const h=UI.kind==='house';
      kh.classList.toggle('on',h); kh.setAttribute('aria-pressed',String(h));
      kl.classList.toggle('on',!h); kl.setAttribute('aria-pressed',String(!h)); };
    const setKind=k=>{ UI.kind=k; store('bl_kind',k); syncKind();
      // the price metric's percentiles and the price medians were built for the old kind
      pct=percentiles(DATA); buildStats(DATA); render(); };
    kh.onclick=()=>setKind('house'); kl.onclick=()=>setKind('flat');
    syncKind();
    const dlg=document.getElementById('cmp');
    const openCmp=()=>{ dlg.innerHTML=renderCompare(); if(!dlg.open) dlg.showModal();
      document.getElementById('cmp-x').focus(); };
    document.getElementById('cmp-open').onclick=openCmp;
    document.getElementById('cmp-clear').onclick=()=>{ CMP=[]; cmpSync(); };
    dlg.addEventListener('click',e=>{
      if(e.target===dlg||e.target.id==='cmp-x') return dlg.close();   // backdrop or Close
      const x=e.target.closest('[data-cmp-x]');
      if(x){ cmpToggle(x.dataset.cmpX,false); openCmp(); }             // re-render in place
    });
    document.getElementById('q').oninput=e=>{SEARCH=e.target.value; render();};
    document.getElementById('srcbtn').onclick=()=>{
      document.getElementById('report').innerHTML=renderSources(); showPanel(true);
    };
    document.getElementById('lang').onclick=()=>{
      LANG = LANG==='hu' ? 'en' : 'hu';
      localStorage.setItem(LANG_KEY,LANG);
      applyLang(); buildUI(); render();
    };
    const ai=document.getElementById('anchor'), ri=document.getElementById('radius');
    const aerr=document.getElementById('anchor-err');
    const sayAnchor=msg=>{ aerr.textContent=msg||''; aerr.hidden=!msg; };
    ai.addEventListener('change',()=>{
      const v=ai.value.trim(), hit=ALL.find(x=>x.name===v);
      if(hit){ sayAnchor(''); setWork(0,{name:hit.name,lat:hit.lat,lon:hit.lon}); }
      // snapping back to Budapest without a word looked like the app ignoring the user
      else { sayAnchor(v?(LANG==='hu'?HU.anchor_bad(v,ANCHOR.name)
              :`"${v}" is not in the settlement list — the workplace is still ${ANCHOR.name}.`):'');
        ai.value=ANCHOR.name; }
    });
    const a2=document.getElementById('anchor2');
    a2.addEventListener('change',()=>{
      const v=a2.value.trim(), hit=ALL.find(x=>x.name===v);
      if(!v){ sayAnchor(''); if(ANCHOR2) setWork(1,null); }
      else if(hit){ sayAnchor(''); setWork(1,{name:hit.name,lat:hit.lat,lon:hit.lon}); }
      else if(v!==ANCHOR2?.name){ sayAnchor(LANG==='hu'?HU.anchor2_bad(v)
          :`"${v}" is not in the settlement list — the second workplace is unchanged.`);
        a2.value=ANCHOR2?ANCHOR2.name:''; }
    });
    document.getElementById('anchor2-x').onclick=()=>{ sayAnchor(''); setWork(1,null); a2.focus(); };
    const lri=document.getElementById('landref');
    lri.addEventListener('change',()=>{
      const lv=lri.value.trim(), hit=ALL.find(x=>x.name===lv);
      LANDREF=hit?hit.ksh:null;
      if(!hit){ sayAnchor(lv?(LANG==='hu'?HU.landref_bad(lv)
          :`"${lv}" is not in the settlement list — the landscape reference is cleared.`):'');
        lri.value=''; } else sayAnchor('');
      const m=METRICS.find(x=>x.k==='landscape_sim');
      if(hit&&!m.w){ m.w=2; const el=document.querySelector('[data-m="landscape_sim"]');
        if(el){el.value=2; document.getElementById('w-landscape_sim').textContent='×2';} }
      computeSimilarity(DATA); pct=percentiles(DATA); render();
    });
    ri.oninput=()=>{RADIUS=+ri.value;
      document.getElementById('v-radius').textContent=ri.value; applyScope();};
    applyLang(); buildUI(); render(); setMode(true);
    const pop=new maplibregl.Popup({closeButton:false,offset:10});
    map.on('mouseenter','sett-c',e=>{map.getCanvas().style.cursor='pointer';
      const p=e.features[0].properties;
      const n=v=>{const x=+v; return isFinite(x)?x:null;};
      const r=(k,v,extra='')=>v==null||v===''?''
        :`<div>${k}<span>${v}</span>${extra}</div>`;
      const sig=(x,d=0)=>(x>0?'+':'')+x.toFixed(d);
      pop.setLngLat(e.lngLat).setHTML(`<div class="pop"><b>${esc(p.name)}</b>
        ${r(t('c2','Score'),(p._s*100).toFixed(0))}
        ${r(t('r_d2d','Commute'),p.commute_best_min!=null&&p.commute_best_min!==''
            ?(n(p.commute2_min)!=null?p.commute1_min+' / '+p.commute2_min:p.commute_best_min)+' '+t('min','min'):null,
            ctx('commute_best_min',n(p.commute_best_min),x=>x+' '+t('min','min')))}
        ${r(t('r_pop','Population'),n(p.pop_2022)?.toLocaleString('hu'))}
        ${r(t('r_trend','21-year trend'),n(p.pop_trend_21y_pct)!=null?sig(n(p.pop_trend_21y_pct),1)+'%':null,
            ctx('pop_trend_21y_pct',n(p.pop_trend_21y_pct),x=>sig(x,0)+'%'))}
        ${r(t('r_school','School'),n(p.school_score_mean),
            ctx('school_score_mean',n(p.school_score_mean)))}
        ${r(`${t('r_price','Price')} (${t('k_'+UI.kind,UI.kind)})`,n(kf(p,'price_m2'))
            ?kf(p,'price_m2')+' eFt/m² ('+kf(p,'price_year')+')':null,
            ctx('price_m2',n(kf(p,'price_m2')),x=>x+' eFt/m²')+(n(kf(p,'price_m2'))?txHtml(p):''))}
        ${r(UI.size+' m² '+t('r_cost_short','costs'),p._cost?p._cost.toFixed(0)+' M Ft':null,
            // cost is price x size, so the price median scales to the cost median exactly
            ctx('price_m2',n(kf(p,'price_m2')),x=>(x*UI.size/1000).toFixed(0)+' M Ft'))}
        ${r(t('r_pricetrend','10-year price rise'),n(kf(p,'price_trend_pct'))
            ?sig(n(kf(p,'price_trend_pct')))+'%':null,
            ctx('price_trend_pct',n(kf(p,'price_trend_pct')),x=>sig(x)+'%'))}
        ${r(t('r_texture','Soil'),p.soil_texture
            ?t('tex_'+p.soil_texture,p.soil_texture)+' · pH '+n(p.soil_ph).toFixed(1)
             +' · '+t('r_om','OM')+' '+n(p.soil_om_pct).toFixed(1)+'%':null)}
        ${r(t('r_garden','Garden score'),n(p.garden_score),
            ctx('garden_score',n(p.garden_score)))}
        ${r(t('r_elev','Elevation'),n(p.elevation_m)!=null
            ?p.elevation_m+' m ('+t('r_relief','relief')+' '+p.local_relief_m+' m)':null)}
        ${r(t('r_aspect','Aspect'),n(p.aspect_deg)!=null
            ?n(p.aspect_deg).toFixed(0)+'° · '+t('r_slope','slope')+' '+n(p.slope_deg).toFixed(1)+'°'
            :t('flat','flat'))}
        ${r(t('r_frost','Frost pocket'),n(p.frost_risk),ctx('frost_risk',n(p.frost_risk)))}
        ${r(t('r_ovoda','Óvoda'),n(p.ovoda_places)?p.ovoda_places+' '+t('places','places'):null)}
        ${p.in_floodway==='true'||p.in_floodway===true?`<div class="warn">${t('r_floodway','Floodway')}</div>`:''}
        ${p.in_floodplain==='true'||p.in_floodplain===true?`<div class="warn">${t('r_floodplain','Floodplain basin')}</div>`:''}
        ${p.gp_vacant>0?`<div class="warn">${t('r_gp','GP practice')}: ${t('unfilled','unfilled since')} ${p.gp_vacant_since||'?'}</div>`:''}
        </div>`).addTo(map);});
    map.on('mouseleave','sett-c',()=>{map.getCanvas().style.cursor='';pop.remove();});

    // --- plot report: click anywhere, sample that exact point ---
    map.addSource('work',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
    map.addLayer({id:'work-c',type:'circle',source:'work',paint:{   // --rail: the transport accent
      'circle-radius':5,'circle-color':'#f5c542','circle-stroke-width':2,'circle-stroke-color':'#0e0e0e'}});
    drawWork();
    map.addSource('pin',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
    map.addLayer({id:'pin-c',type:'circle',source:'pin',paint:{
      'circle-radius':7,'circle-color':'#fcfdbf','circle-opacity':0.25,
      'circle-stroke-width':1.5,'circle-stroke-color':'#fcfdbf'}});
    const R=document.getElementById('report'), C=document.getElementById('count'),
          TB=document.querySelector('#right table');
    const H2=document.getElementById('rhead2');
    // the report replaces the results, so the results' search box goes with them -
    // it used to float orphaned above the plot report
    const show=on=>{R.hidden=!on;H2.hidden=on;C.hidden=on;TB.hidden=on;};
    window.showPanel=show;
    document.addEventListener('click',e=>{if(e.target.id==='back'){show(false);
      map.getSource('pin').setData({type:'FeatureCollection',features:[]});}});
    const plotAt=async ({lng,lat})=>{
      map.getSource('pin').setData({type:'Feature',
        geometry:{type:'Point',coordinates:[lng,lat]},properties:{}});
      R.innerHTML=`<div id="rhead"><button id="back">${t('back','← results')}</button><b>${t('sampling','Sampling…')}</b>
        <div class="co">${lat.toFixed(5)}, ${lng.toFixed(5)}</div></div>`;
      show(true);
      let d;
      try{ d=await (await fetch(`/api/plot?lat=${lat}&lon=${lng}`)).json(); }
      catch(err){ d={error:String(err)}; }
      R.innerHTML=renderReport(d,lat,lng);
      document.getElementById('back')?.focus();
    };
    map.on('click',e=>plotAt(e.lngLat));
    // the plot report was mouse-only. The canvas is focusable and already pans with
    // the arrow keys, so Enter samples wherever the user has steered the centre.
    map.getCanvas().addEventListener('keydown',ev=>{
      if(ev.key==='Enter'&&!ev.repeat){ ev.preventDefault(); plotAt(map.getCenter()); }
    });
  });
});

// Compare toggles live in the table and in report headers, both re-rendered freely: delegate.
document.addEventListener('change',e=>{
  const c=e.target.closest&&e.target.closest('input.cmp');
  if(c) cmpToggle(c.dataset.cmp,c.checked);
});
document.addEventListener('click',e=>{
  const b=e.target.closest&&e.target.closest('button[data-cmp]');
  if(b) return cmpToggle(b.dataset.cmp,b.getAttribute('aria-pressed')!=='true');
  const w=e.target.closest&&e.target.closest('button[data-work]');
  if(!w) return;
  const pt={name:w.dataset.name,lat:+w.dataset.lat,lon:+w.dataset.lon};
  if(!okPt(pt)) return;
  setWork(+w.dataset.work,pt).then(()=>{
    const m=w.parentElement.querySelector('.actmsg'); if(m) m.textContent=t('work_set','Workplace set — the ranking is updated.'); });
});

// One disclosure handler for every .q in the document: the weight panel rebuilds them
// on each buildUI(), and the report panel renders its own after the fact.
document.addEventListener('click',e=>{
  const b=e.target.closest&&e.target.closest('.q');
  if(!b) return;
  e.preventDefault();
  const el=document.getElementById(b.dataset.note);
  if(!el) return;
  el.hidden=!el.hidden;
  b.setAttribute('aria-expanded',String(!el.hidden));
});

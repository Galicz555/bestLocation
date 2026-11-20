// Pure scoring and the text built from it (summarize, buyQuestions, buildPrompt): no DOM, no
// globals beyond METRICS/FILTERS/UI from config.js and t()/HU from lang.js. Kept separate so
// tools/test_score.mjs can run it headless.

// Percentile lookups for the current scope, rebuilt whenever the scope or a
// direction changes. Assigned by app.js; read by score().
let pct={};

const num=v=>typeof v==='number'&&isFinite(v);

const mval=(m,s)=>m.get?m.get(s):s[m.k];

// Property type: every price field exists as house_* and flat_* with the same meaning, so
// one switch (UI.kind) picks the family. kf(s,'price_m2') -> s.house_price_m2 / s.flat_price_m2.
const kf=(s,f)=>s[UI.kind+'_'+f];
const costOf=s=>{ const p=kf(s,'price_m2'); return num(p)&&p>0?p*UI.size/1000:null; };
// A price from fewer sales than this is shown with a "thin data" mark. A missing count on a
// present price is marked too: an unknown sample is not a reliable one.
const LOW_TX=10;
const lowTx=s=>num(kf(s,'price_m2'))&&!(kf(s,'tx')>=LOW_TX);

function percentiles(rows){ // rank-based: robust to the outliers min-max would flatten
  const out={};
  for(const m of METRICS){
    const vals=rows.map(r=>mval(m,r)).filter(num).sort((a,b)=>a-b);
    const n=vals.length;
    out[m.k]=v=>{ if(!num(v)||!n) return null;
      // Midrank: a tied block takes the AVERAGE of its ranks, not its lowest. Coarse metrics
      // are mostly ties — school_beats_prediction has 428 rows sharing one value out of 549 —
      // and lower-bound ranking scored that whole block 0.0, as if it were the worst rather
      // than the middle. Identical to lower-bound when every value is distinct.
      let lo=0,hi=n; while(lo<hi){const mid=(lo+hi)>>1; vals[mid]<v?lo=mid+1:hi=mid;}
      let up=lo; {let a=lo,b=n; while(a<b){const mid=(a+b)>>1; vals[mid]<=v?a=mid+1:b=mid;} up=a;}
      // One row, or a column with a single distinct value, carries no rank information.
      const p=n<2?0.5:((lo+up-1)/2)/(n-1); return m.dir>0?p:1-p; };
  }
  return out;
}
function score(s){
  let sum=0,wsum=0;
  for(const m of METRICS){ const w=m.w; if(!w) continue;
    const p=pct[m.k](mval(m,s)); if(p===null) continue; // missing -> abstains, never penalised
    sum+=w*p; wsum+=w; }
  return wsum?sum/wsum:0;
}
const passes=s=>FILTERS.every(f=>!f.on||f.f(s));


function valueResidual(rows){
  // Fit score = a + b·ln(price/m²) over the visible set, then rank each settlement by how
  // far ABOVE that line it sits. Positive residual = better than its price implies.
  rows.forEach(r=>{r._v=null; r._resid=null;});
  const pts=rows.filter(r=>kf(r,'price_m2')>0&&r._s!=null)
                .map(r=>({s:r, x:Math.log(kf(r,'price_m2')), y:r._s}));
  if(pts.length<12) return null;
  const n=pts.length;
  const mx=pts.reduce((a,p)=>a+p.x,0)/n, my=pts.reduce((a,p)=>a+p.y,0)/n;
  let sxy=0, sxx=0;
  for(const p of pts){ sxy+=(p.x-mx)*(p.y-my); sxx+=(p.x-mx)**2; }
  const b=sxx?sxy/sxx:0, a=my-b*mx;
  for(const p of pts) p.res=p.y-(a+b*p.x);
  pts.sort((u,v)=>u.res-v.res);
  pts.forEach((p,i)=>{ p.s._v=i/(n-1||1); p.s._resid=p.res; });
  return {a,b,n};
}

// Plain-text summary of one settlement, 1-3 sentences; the caller escapes it. Every clause
// reads its value first and abstains on a missing one, so thin data gives a shorter summary.
// radius = the scope the current pct was built over, or null when s is outside it (then the
// relative sentence is skipped: ranking a row against a scope it is not in is not a claim).
// Hungarian is phrased around suffixes that would need vowel harmony on a variable word.
function summarize(s,anchor,radius){
  const hu=LANG==='hu', out=[], and=hu?' és ':' and ';
  const list=a=>a.length<2?a.join(''):a.slice(0,-1).join(', ')+and+a[a.length-1];
  const sig=x=>(x>0?'+':'')+x;   // \u00a0/\u2011 below: keep "120 m²-es" and "63 M Ft" on one line
  const f=[];
  if(num(s.pop_2022)){ const n=Math.round(s.pop_2022).toLocaleString(hu?'hu':'en-GB'),
      tr=num(s.pop_trend_21y_pct)?sig(Math.round(s.pop_trend_21y_pct))+'%':null;
    f.push(hu?`${n} lakos${tr?` (21 év alatt ${tr})`:''}`:`${n} residents${tr?` (${tr} over 21 years)`:''}`); }
  // two workplaces: commute_best_min is already the worse of the two, so name both
  if(num(s.commute1_min)&&num(s.commute2_min)&&anchor)
    f.push(hu?`ingázás: ${Math.round(s.commute1_min)} / ${Math.round(s.commute2_min)}\u00a0perc (munkahelyek: ${anchor})`
      :`commutes of ${Math.round(s.commute1_min)} / ${Math.round(s.commute2_min)}\u00a0min (workplaces: ${anchor})`);
  else if(num(s.commute_best_min)&&anchor) f.push(hu?`${Math.round(s.commute_best_min)}\u00a0perc ingázás (központ: ${anchor})`
    :`a ${Math.round(s.commute_best_min)}\u00a0min commute to ${anchor}`);
  const cost=costOf(s);
  if(cost!=null){ const flat=UI.kind==='flat', yr=kf(s,'price_year'), tx=kf(s,'tx'),
      y=[num(yr)&&yr, num(tx)&&(hu?`${tx} eladásból`:`from ${tx} sales`),
         lowTx(s)&&t('low_tx','thin data')].filter(Boolean).join(', ');
    f.push((hu?`${UI.size}\u00a0m²\u2011es ${flat?'lakás':'ház'} kb. ${Math.round(cost)}\u00a0M\u00a0Ft`
      :`a ${UI.size}\u00a0m² ${flat?'flat':'house'} about ${Math.round(cost)}\u00a0M\u00a0Ft`)+(y?` (${y})`:'')); }
  if(num(s.school_vs_national)){ const v=s.school_vs_national, a=Math.abs(v);
    f.push(a<5?t('sum_school0','school results around the national average')
      :hu?`iskolai eredmény az országos átlagnál ${a} ponttal ${v>0?'jobb':'gyengébb'}`
         :`school results ${a} points ${v>0?'above':'below'} the national average`); }
  if(f.length){ const x=f.join(', '); out.push(x[0].toUpperCase()+x.slice(1)+'.'); }

  if(radius!=null){
    // only enabled metrics: the summary explains the user's own ranking, not every column
    const r=METRICS.filter(m=>m.w&&m.hi).map(m=>({m,p:pct[m.k](mval(m,s))})).filter(x=>x.p!==null);
    const phr=({m,p})=>(p>.5)===(m.dir>0)?t('hi_'+m.k,m.hi):t('lo_'+m.k,m.lo);
    const str=r.filter(x=>x.p>=.8).sort((a,b)=>b.m.w*b.p-a.m.w*a.p).slice(0,3),
          weak=r.filter(x=>x.p<=.2).sort((a,b)=>b.m.w*(1-b.p)-a.m.w*(1-a.p)).slice(0,2);
    const g=(a,one,many,e1,eN)=>a.length?`${a.length>1?t(many,eN):t(one,e1)} ${list(a.map(phr))}`:'';
    const parts=[g(str,'sum_s1','sum_sN','its strength is','its strengths are'),
                 g(weak,'sum_w1','sum_wN','its weakness is','its weaknesses are')].filter(Boolean);
    const lead=hu?HU.sum_rel(radius):`Compared with settlements within ${radius} km,`;
    if(parts.length) out.push(`${lead} ${parts.join('; ')}.`);
    // Simplification: "not standout" needs a few ranked metrics to mean anything; 3 is a judgement call
    else if(r.length>=3) out.push(`${lead} ${t('sum_mid','it does not stand out on any enabled criterion')}.`);
  }

  const w=[s.in_floodway&&t('sum_floodway','floodway'), s.in_floodplain&&t('sum_floodplain','floodplain basin'),
    s.in_waterlogged&&t('sum_wet','water-affected land'), num(s.frost_risk)&&s.frost_risk>=60&&t('sum_frost','frost pocket'),
    // same rule as the 'gp' filter, so the summary never warns about a row the filter lets through
    FILTERS.find(f=>f.k==='gp')?.f(s)===false&&t('sum_gp','many unfilled GP practices (more than 1 per 10k people)')].filter(Boolean);
  if(w.length) out.push(`${t('sum_flags','Watch out:')} ${list(w)}.`);
  return out.join(' ');
}

// Polluting point sources by distance field: [field, label key, English label]
const NEAREST_SRC=[['landfill_km','r_landfill','Landfill'],['quarry_km','r_quarry','Quarry'],
  ['wwtp_km','r_wwtp','Sewage plant'],['works_km','r_works','Factory']];

// "Ask before you buy": questions for the seller, the council or the neighbours. here = raised
// by this row's own values, each abstaining on a missing one; always = the blind spots every
// settlement shares (what no source here covers). Plain text; the caller escapes it.
function buyQuestions(s){
  const hu=LANG==='hu', here=[];
  const flood=[s.in_floodway&&t('sum_floodway','floodway'), s.in_floodplain&&t('sum_floodplain','floodplain basin'),
    s.in_waterlogged&&t('sum_wet','water-affected land')].filter(Boolean).join(', ');
  if(flood) here.push(hu?HU.ask_flood(flood):`Flood flag at the settlement centre (${flood}). Ask the seller and the neighbours whether water has reached the plot or the cellar, and click the plot on the map: the flag is for the centre.`);
  if(num(s.frost_risk)&&s.frost_risk>=60) here.push(hu?HU.ask_frost(s.frost_risk)
    :`The settlement centre is a frost pocket (${s.frost_risk} / 100). Ask the neighbours how late the spring frosts run, and click the plot on the map: a slope or a hill can differ.`);
  // same rule as the 'gp' filter and the summary: one empty practice in a large town is not a flag
  if(FILTERS.find(f=>f.k==='gp')?.f(s)===false) here.push(hu?HU.ask_gp(s.gp_vacant,s.gp_vacant_since)
    :`${s.gp_vacant>1?s.gp_vacant+' GP practices are':'A GP practice is'} unfilled${s.gp_vacant_since?` (since ${s.gp_vacant_since})`:''}. Ask the council who stands in, when they see patients, and where the nearest paediatrician is.`);
  if(s.ovoda_sites===0) here.push(t('ask_ovoda','There is no óvoda here. Ask the council which óvoda takes children from here, and how they get there.'));
  if(s.primary_sites===0) here.push(t('ask_school0','There is no primary school here. Ask which school the address belongs to, and whether a school bus runs.'));
  else if(s.primary_sites>0&&!num(s.school_score_mean))
    here.push(t('ask_score','The school has no competency-test result. Ask the school for its year 6 and year 8 results (FIT report).'));
  if(costOf(s)==null) here.push(hu?HU.ask_noprice(UI.kind)
    :`No ${UI.kind==='flat'?'flat':'house'} price from actual sales. Listing prices are asking prices: ask the agent for recent sale prices, or get a valuation.`);
  else {
    if(lowTx(s)){ const n=num(kf(s,'tx'))?kf(s,'tx'):null;
      here.push(hu?HU.ask_lowtx(n):`The price rests on ${n??'an unknown number of'} sales, so it is uncertain. Ask the agent for prices recently achieved nearby.`); }
    // same rule as the 'priced' filter, so the two never disagree about what is recent
    if(FILTERS.find(f=>f.k==='priced')?.f(s)===false){ const y=kf(s,'price_year')??'?';
      here.push(hu?HU.ask_oldprice(y):`The latest transaction price is from ${y}. Prices may have moved since: ask about recent sales.`); }
  }
  // 2 km is the distance the plot report marks red
  const near=NEAREST_SRC.filter(([k])=>num(s[k])&&s[k]<2).map(([k,l,e])=>`${t(l,e)} ${s[k]} km`).join(', ');
  if(near) here.push(hu?HU.ask_src(near):`Within 2 km of the settlement centre: ${near}. Ask the neighbours about smell, noise, dust and lorry traffic.`);
  if(num(s.pm25_winter)&&s.pm25_winter>=20) here.push(hu?HU.ask_air(s.pm25_winter)
    :`Winter air is dusty (PM2.5: ${s.pm25_winter} µg/m³), mostly from home heating. Ask how the neighbours heat their homes.`);
  // Tradeoff: -10% over 21 years is a judgement call for "shrinking enough to lose services"
  if(num(s.pop_trend_21y_pct)&&s.pop_trend_21y_pct<=-10){ const p=Math.round(-s.pop_trend_21y_pct);
    here.push(hu?HU.ask_shrink(p):`The population shrank ${p}% in 21 years. Ask the council whether the shop, the post office, the school and the bus will stay.`); }
  const always=[
    t('ask_zoning','Is the plot inside the built-up area, and what do the local building rules allow on it? Ask for the land register extract and the map copy; the council explains the building rules.'),
    t('ask_crime','Crime figures are county level only. Ask the local police officer and the neighbours about burglaries and safety.'),
    t('ask_commute','The commute is timed from the settlement centre, without waiting, and Volánbusz is not included. Try the trip from the actual address at the morning peak.'),
    t('ask_net','Broadband data only lists where fast fixed lines are MISSING. Ask the providers about the actual address.'),
    t('ask_radon','There is no radon or noise map for the settlement. Get a radon test for a house with a cellar, and visit at different times of day (main road, railway, aircraft).')];
  return {here,always};
}

// The text the "ask a chatbot" button hands over: our criteria, each settlement's facts, its
// news lines with links and its open questions, plus rules that keep the answer tied to them.
// ctx = {anchor, radius, inScope(s), news: {ksh: [{d, s, u}]}}. Plain text in the UI language.
function buildPrompt(rows,ctx){
  const hu=LANG==='hu', L=[];
  const line=(label,v)=>{ if(v!=null&&v!=='') L.push(`- ${label}: ${v}`); };
  const sig=x=>(x>0?'+':'')+x, r1=x=>Math.round(x*10)/10;
  L.push(t('pr_intro','We plan to move and are looking at the settlements below. The data comes from the bestLocation app, built from public official sources (KSH census and property register, Oktatási Hivatal competency tests, MÁV and BKK timetables, OKFŐ GP practices, water authority, CAMS air quality, OpenStreetMap).'),
    '', t('pr_rules','Please:'),
    '- '+t('pr_rule1','Work from this data first. Mark anything you add from elsewhere (your own knowledge or a web search) separately, with its source.'),
    '- '+t('pr_rule2','Where there is no data, say so; do not estimate.'),
    '- '+t('pr_rule3','The news lines are AI-written one-sentence summaries: when a claim rests on one, give its link.'),
    '- '+t('pr_rule4','The open questions cannot be answered from the data: do not make up answers, tell us whom to ask instead.'),
    '', t('pr_ours','What matters to us:'));
  line(t('pr_work','Workplace'),ctx.anchor);
  line(t('pr_budget','Budget'),`${UI.budget} M Ft, ${UI.size} m² ${t('k_'+UI.kind,UI.kind).toLowerCase()}`);
  line(t('pr_weights','Weights (0–10)'),METRICS.filter(m=>m.w).sort((a,b)=>b.w-a.w)
    .map(m=>`${t('m_'+m.k,m.n)} ×${m.w}`).join(', '));
  line(t('pr_filters','Must-haves'),FILTERS.filter(f=>f.on).map(f=>t('f_'+f.k,f.n)).join(', '));
  for(const s of rows){
    const inScope=ctx.inScope(s);
    L.push('',`## ${s.name}${s.megye?` (${s.megye})`:''}`);
    if(inScope&&num(s._s)) line(t('pr_score','Score with our weights'),`${Math.round(s._s*100)} / 100`);
    line(t('s_summary','In short'),summarize(s,ctx.anchor,inScope?ctx.radius:null));
    line(t('r_school','School'),num(s.school_score_mean)?s.school_score_mean
      +(num(s.school_vs_national)?` (${t('pr_vs','vs national')} ${sig(s.school_vs_national)})`:''):null);
    line(t('r_ovoda','Óvoda'),num(s.ovoda_sites)?(hu?`${s.ovoda_sites} telephely, ${s.ovoda_places??'?'} férőhely`
      :`${s.ovoda_sites} site(s), ${s.ovoda_places??'?'} places`):null);
    line(t('pr_primary','Primary schools'),num(s.primary_sites)?s.primary_sites:null);
    line(t('r_gp','GP practice'),s.gp_vacant>0?(hu?`betöltetlen${s.gp_vacant_since?` (${s.gp_vacant_since} óta)`:''}`
      :`unfilled${s.gp_vacant_since?` since ${s.gp_vacant_since}`:''}`):num(s.gp_vacant)?t('filled','filled'):null);
    line(t('m_families_with_children_pct','Families with kids'),num(s.families_with_children_pct)?r1(s.families_with_children_pct)+' %':null);
    line(t('m_unemployment_pct','Unemployment'),num(s.unemployment_pct)?r1(s.unemployment_pct)+' %':null);
    line(t('r_garden','Garden score'),num(s.garden_score)?s.garden_score+' / 100':null);
    line(t('r_frost','Frost pocket'),num(s.frost_risk)?s.frost_risk+' / 100':null);
    line(t('r_pm25w','Winter PM2.5'),num(s.pm25_winter)?s.pm25_winter+' µg/m³':null);
    const src=NEAREST_SRC.filter(([k])=>num(s[k])).sort((a,b)=>s[a[0]]-s[b[0]])[0];
    line(t('cmp_poll','Nearest pollution source'),src?`${t(src[1],src[2])} ${s[src[0]]} km`:null);
    line(`${t('s_crime','Crime (county)')}, ${t('r_crime_rate','offences / 100k')}`,
      num(s.crime_rate_county)?`${s.crime_rate_county} (${s.crime_year??'?'})`:null);
    if(s.op_status==='ok'&&s.op_summary) line(t('pr_op','Opinions online (AI summary of web sources)'),s.op_summary);
    const news=(ctx.news[s.ksh]||[]).slice(0,8);
    if(news.length) L.push('- '+t('pr_news','News (AI-written one-sentence summaries, check the link):'),
      ...news.map(x=>`  - ${x.d}: ${x.s} ${x.u}`));
    const {here}=buyQuestions(s);
    if(here.length) L.push('- '+t('pr_open','Open questions the data raises:'),...here.map(q=>'  - '+q));
  }
  L.push('',t('pr_always','What the app cannot see for any settlement:'),...buyQuestions({}).always.map(q=>'- '+q),
    '',rows.length>1?t('pr_qn','My question: compare these settlements against what matters to us, and tell us what to check in person before we decide.')
      :t('pr_q1','My question: what should we know about this settlement against what matters to us, and what should we check in person before we decide?'));
  return L.join('\n');
}

// --- public demo: in-browser stand-ins for /api/anchor and /api/plot ---------------------
const haversineKm=(la1,lo1,la2,lo2)=>{ const p=Math.PI/180,
  h=Math.sin((la2-la1)*p/2)**2+Math.cos(la1*p)*Math.cos(la2*p)*Math.sin((lo2-lo1)*p/2)**2;
  return 2*6371.0088*Math.asin(Math.sqrt(h)); };
// Same model and constants as commute.road_only() in tools/commute.py: change both together.
const ROAD_KMH=55, ROAD_OVERHEAD_MIN=20;
function roadOnly(a,rows){
  const out={};
  for(const s of rows){ if(!num(s.lat)) continue;
    const d=haversineKm(a.lat,a.lon,s.lat,s.lon), road=Math.round(d/ROAD_KMH*60+ROAD_OVERHEAD_MIN);
    out[s.ksh]={dist_km:Math.round(d*10)/10,drive_min_est:road,commute_min:null,rail_station:null,
      rail_station_km:null,rail_min:null,rail_trains_am:0,rail_terminus:null,transit_min:null,
      transit_stop:null,transit_walk_km:null,transit_line:null,commute_best_min:road,commute_mode:'road'}; }
  return out;
}
// Ray casting over a GeoJSON Polygon's rings (outer ring first, then holes).
function pointInPolygon(lon,lat,rings){
  const inRing=r=>{ let c=false;
    for(let i=0,j=r.length-1;i<r.length;j=i++){ const [xi,yi]=r[i],[xj,yj]=r[j];
      if((yi>lat)!==(yj>lat)&&lon<(xj-xi)*(lat-yi)/(yj-yi)+xi) c=!c; }
    return c; };
  return inRing(rings[0])&&!rings.slice(1).some(inRing);
}

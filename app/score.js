// Pure scoring: no DOM, no globals beyond METRICS/FILTERS/UI from config.js (and t()/HU
// from lang.js for summarize()). Kept separate so tools/test_score.mjs can run it headless.

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

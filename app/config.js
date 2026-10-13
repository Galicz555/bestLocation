// Score ramp: magma truncated to [0.25,1] so the lowest score still clears the background.
const RAMP=[[126,31,129],[170,44,122],[211,62,104],[242,90,84],[254,135,90],[254,181,120]];
const rampCss=t=>{const x=Math.max(0,Math.min(1,t))*(RAMP.length-1),i=Math.floor(x),f=x-i,
  a=RAMP[i],b=RAMP[Math.min(i+1,RAMP.length-1)];
  return `rgb(${a.map((v,k)=>Math.round(v+(b[k]-v)*f)).join(',')})`};

// hi/lo: how the summary phrases a standout RAW value (high/low), not good/bad — so a
// flipped direction still describes the settlement truthfully. No hi/lo = never summarised.
const METRICS=[
 {k:'pop_trend_21y_pct',   n:'Population growth',      w:2, dir:1,  c:'--amen', g:'csalad', hi:'stronger population growth', lo:'weaker population growth or decline'},
 {k:'school_score_mean',   n:'School score',           w:2, dir:1,  c:'--edu', g:'csalad', hi:'better school results', lo:'weaker school results'},
 {k:'school_beats_prediction',n:'School beats expectation',w:1, dir:1, c:'--edu', g:'csalad', hi:'more schools beating expectations', lo:'fewer schools beating expectations'},
 {k:'families_with_children_pct',n:'Families with kids',w:1,dir:1,  c:'--amen', g:'csalad', hi:'more families with children', lo:'fewer families with children'},
 {k:'ovoda_per_1k',        n:'Óvoda places / 1k',      w:1, dir:1,  c:'--edu', g:'csalad', hi:'more óvoda places', lo:'fewer óvoda places'},
 {k:'dwelling_comfort_pct',n:'Dwelling comfort',       w:1, dir:1,  c:'--soil', g:'ingatlan', hi:'better-equipped homes', lo:'less-equipped homes'},
 {k:'unemployment_pct',    n:'Unemployment',           w:1, dir:-1, c:'--hazard', g:'ingatlan', hi:'higher unemployment', lo:'lower unemployment'},
 {k:'dwelling_vacancy_pct',n:'Dwelling vacancy',       w:1, dir:-1, c:'--hazard', g:'ingatlan', hi:'more empty homes', lo:'fewer empty homes'},
 {k:'commute_best_min',   n:'Commute to work',    w:3, dir:-1, c:'--rail', g:'kozlekedes', hi:'a longer commute', lo:'a shorter commute'},
 // the id stays house_price_m2 (profiles and strings key on it); the value follows UI.kind
 {k:'house_price_m2',      n:'House price (cheaper)',  w:2, dir:-1, c:'--hazard', g:'ingatlan', hi:'pricier housing', lo:'cheaper housing',
  get:s=>kf(s,'price_m2')},
 {k:'garden_score',        n:'Soil for growing',       w:2, dir:1,  c:'--soil', g:'kert', hi:'better soil', lo:'poorer soil'},
 {k:'frost_risk',          n:'Frost pocket (lower)',   w:1, dir:-1, c:'--health', g:'kert', hi:'more frost-prone ground', lo:'less frost-prone ground'},
 {k:'south_facing',        n:'South-facing ground',    w:0, dir:1,  c:'--rail', g:'kert', hi:'more south-facing ground', lo:'less south-facing ground'},
 {k:'crime_rate_county',   n:'Crime (county)',         w:0, dir:-1, c:'--hazard', g:'kornyezet', hi:'higher county crime', lo:'lower county crime'},
 {k:'pm25_winter',         n:'Winter PM2.5',           w:1, dir:-1, c:'--health', g:'kornyezet', hi:'more polluted winter air', lo:'cleaner winter air'},
 {k:'frost_free_days',     n:'Frost-free days',        w:0, dir:1,  c:'--soil', g:'kert', hi:'a longer frost-free season', lo:'a shorter frost-free season'},
 {k:'pv_kwh_kwp',          n:'Solar yield',            w:0, dir:1,  c:'--rail', g:'kert', hi:'higher solar yield', lo:'lower solar yield'},
 {k:'precip_mm_yr',        n:'Rainfall',               w:0, dir:1,  c:'--health', g:'kert', hi:'more rainfall', lo:'less rainfall'},
 {k:'pollution_nearest_km',n:'Distance to a source',   w:1, dir:1,  c:'--hazard', g:'kornyezet', hi:'pollution sources farther away', lo:'a pollution source closer by'},
 {k:'landscape_sim',      n:'Landscape similarity',   w:0, dir:1,  c:'--soil',
  get:s=>s._sim, g:'kert', max:10, hi:'landscape closer to the reference', lo:'landscape less like the reference'},
];
const FILTERS=[
 {k:'ovoda',   n:'Óvoda in the settlement', on:true,  f:s=>s.ovoda_sites>0},
 {k:'school',  n:'Primary school here',     on:true,  f:s=>s.primary_sites>0},
 // a rate, not "none at all": a count grows with size, and failed 22 of 23 Budapest districts
 {k:'gp',      n:'At most 1 unfilled GP practice per 10k', on:true,
  f:s=>!s.gp_vacant||(s.pop_2022>0&&1e4*s.gp_vacant/s.pop_2022<=1)},
 {k:'growing', n:'Population not shrinking',on:false, f:s=>(s.pop_trend_21y_pct??-99)>0},
 {k:'pop1500', n:'At least 1500 people',    on:false, f:s=>(s.pop_2022||0)>=1500},
 // kf/costOf/LOW_TX live in score.js; these closures only run after it has loaded
 {k:'budget',  n:'Fits the budget',          on:true,  f:s=>{const c=costOf(s); return c!=null&&c<=UI.budget;}},
 {k:'priced',  n:'Has a recent price (2023+)',on:false,f:s=>(kf(s,'price_year')||0)>=2023},
 {k:'reliable',n:'Reliable price (≥10 sales)',on:false,f:s=>(kf(s,'tx')||0)>=LOW_TX},
 {k:'flood',   n:'Not in a floodplain',      on:true,  f:s=>!s.in_floodplain&&!s.in_floodway},
 {k:'belviz',  n:'Not water-affected land',  on:false, f:s=>!s.in_waterlogged},
 // missing frost data must NOT pass a filter labelled "not a frost pocket" - terrain is
 // nationwide since build_all runs it with --all, but a failed tile still leaves a gap.
 // Same convention as cmt/growing: absent data fails the filter.
 {k:'frost',   n:'Not a frost pocket',       on:false, f:s=>(s.frost_risk??999)<60},
 {k:'rail',    n:'Direct train to Budapest', on:false, f:s=>!!s.commute_min},
 {k:'cmt',     n:'Commute under 75 min',     on:false, f:s=>(s.commute_best_min??999)<=75},
];
// kind: 'house' | 'flat' — which price family (house_* / flat_*) every price reads
const UI={size:120,budget:100,kind:'house'};

import { useState, useEffect, useCallback } from "react";

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const ROOM_TYPES = ["Standard Double","Superior Double","Family Room","Suite","Sea View Double"];
const BOARD_TYPES = ["Self Catering","Bed & Breakfast","Half Board","Full Board","All Inclusive"];
const AIRPORTS = [
  {code:"LBA",name:"Leeds Bradford"},{code:"MAN",name:"Manchester"},{code:"EMA",name:"East Midlands"},
  {code:"BHX",name:"Birmingham"},{code:"EDI",name:"Edinburgh"},{code:"GLA",name:"Glasgow"},
  {code:"NCL",name:"Newcastle"},{code:"STN",name:"London Stansted"},{code:"BFS",name:"Belfast"},
  {code:"BRS",name:"Bristol"},{code:"LGW",name:"London Gatwick"},{code:"LTN",name:"London Luton"},
  {code:"LPL",name:"Liverpool"},{code:"BOH",name:"Bournemouth"},
];
const DURATIONS = [3,5,7,10,14];
const SAMPLE_HOTELS = [
  {name:"Sunwing Alcudia Beach",destination:"Majorca, Spain",stars:4,rating:4.3},
  {name:"Hotel Flamingo Oasis",destination:"Benidorm, Spain",stars:4,rating:4.1},
  {name:"Zafiro Palace Alcudia",destination:"Majorca, Spain",stars:5,rating:4.7},
  {name:"Olympic Lagoon Resort",destination:"Paphos, Cyprus",stars:5,rating:4.5},
  {name:"Hotel Riu Palace Jandia",destination:"Fuerteventura, Canaries",stars:4,rating:4.2},
  {name:"Aqua Fantasy Aquapark",destination:"Kusadasi, Turkey",stars:5,rating:4.4},
  {name:"Mitsis Rinela Beach Resort",destination:"Crete, Greece",stars:5,rating:4.3},
  {name:"Rixos Premium Bodrum",destination:"Bodrum, Turkey",stars:5,rating:4.8},
];

function generateDemoData(hotel,airport,duration,board){
  const seed=(hotel+airport+duration+board).split("").reduce((a,c)=>a+c.charCodeAt(0),0);
  const rng=i=>{const x=Math.sin(seed+i)*10000;return x-Math.floor(x)};
  const bp=400+rng(1)*600,sm=[.7,.65,.75,.85,1,1.25,1.5,1.55,1.2,.9,.7,.65];
  const dm=duration<=3?.5:duration<=5?.7:duration<=7?1:duration<=10?1.35:1.7;
  const bm=BOARD_TYPES.indexOf(board)*.12+.85;
  const rm={"Standard Double":1,"Superior Double":1.2,"Sea View Double":1.35,"Family Room":1.45,"Suite":1.9};
  const months=[],now=new Date();
  for(let i=0;i<12;i++){const mi=(now.getMonth()+i)%12,yr=now.getFullYear()+(now.getMonth()+i>=12?1:0);
    const rooms={};let ch=Infinity,mx=0;
    ROOM_TYPES.forEach((rt,ri)=>{const p=Math.round(bp*sm[mi]*dm*bm*rm[rt]*(.95+rng(i*10+ri)*.1));
      const av=rng(i*100+ri)>.15;rooms[rt]={price:p,available:av,perNight:Math.round(p/duration)};
      if(p<ch)ch=p;if(p>mx)mx=p});
    months.push({month:MONTHS[mi],year:yr,rooms,cheapest:ch,mostExpensive:mx,
      avgPrice:Math.round(Object.values(rooms).reduce((a,r)=>a+r.price,0)/ROOM_TYPES.length),
      availability:Object.values(rooms).filter(r=>r.available).length+"/"+ROOM_TYPES.length})}
  return months}

function Stars({count}){return <span style={{color:"#f0a500",letterSpacing:2,fontSize:14}}>{"★".repeat(count||0)}{"☆".repeat(5-(count||0))}</span>}
function MiniBar({value,max,color}){return <div style={{width:"100%",height:6,background:"rgba(255,255,255,0.06)",borderRadius:3}}><div style={{width:`${(value/(max||1))*100}%`,height:"100%",background:color,borderRadius:3,transition:"width 0.5s ease"}}/></div>}
function Dot({on}){return <span style={{display:"inline-block",width:8,height:8,borderRadius:"50%",background:on?"#2ecc71":"#e74c3c",marginRight:6,boxShadow:`0 0 6px ${on?"rgba(46,204,113,0.5)":"rgba(231,76,60,0.5)"}`}}/>}

function PriceChart({data,selectedRoom}){
  const [hover,setHover]=useState(null);
  const prices=data.map(m=>m.rooms[selectedRoom]?.price||0);
  const max=Math.max(...prices),min=Math.min(...prices.filter(p=>p>0));
  const range=max-min||1;
  // Layout constants
  const padL=40,padR=12,padT=20,padB=32,W=500,H=200;
  const chartW=W-padL-padR, chartH=H-padT-padB;
  const gx=i=>padL+(i/(prices.length-1))*chartW;
  const gy=p=>padT+chartH-((p-min)/range)*chartH;
  // Y-axis ticks
  const yTicks=5;
  const ySteps=Array.from({length:yTicks},(_,i)=>min+range*(i/(yTicks-1)));

  return <div style={{position:"relative",width:"100%",marginTop:8}} onMouseLeave={()=>setHover(null)}>
    <svg viewBox={`0 0 ${W} ${H}`} style={{width:"100%",height:"auto",display:"block"}} preserveAspectRatio="xMidYMid meet">
      <defs>
        <linearGradient id="ag" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#f0a500" stopOpacity="0.25"/><stop offset="100%" stopColor="#f0a500" stopOpacity="0.02"/></linearGradient>
      </defs>

      {/* Grid lines + Y labels */}
      {ySteps.map((v,i)=>{const y=gy(v);return <g key={i}>
        <line x1={padL} y1={y} x2={W-padR} y2={y} stroke="rgba(255,255,255,0.06)" strokeWidth="1"/>
        <text x={padL-6} y={y+4} fill="rgba(255,255,255,0.35)" fontSize="11" textAnchor="end" fontFamily="'DM Sans',sans-serif">£{Math.round(v)}</text>
      </g>})}

      {/* Area fill */}
      <polygon points={[
        ...prices.map((p,i)=>`${gx(i)},${gy(p)}`),
        `${gx(prices.length-1)},${padT+chartH}`,
        `${gx(0)},${padT+chartH}`
      ].join(" ")} fill="url(#ag)"/>

      {/* Line */}
      <polyline points={prices.map((p,i)=>`${gx(i)},${gy(p)}`).join(" ")} fill="none" stroke="#f0a500" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>

      {/* Data points + month labels */}
      {prices.map((p,i)=>{const x=gx(i),y=gy(p);return <g key={i}>
        {/* Tick line */}
        <line x1={x} y1={padT+chartH} x2={x} y2={padT+chartH+4} stroke="rgba(255,255,255,0.15)" strokeWidth="1"/>
        {/* Month label */}
        <text x={x} y={padT+chartH+18} fill="rgba(255,255,255,0.5)" fontSize="11" textAnchor="middle" fontFamily="'DM Sans',sans-serif">{data[i].month}</text>
        {/* Hover zone */}
        <rect x={x-chartW/prices.length/2} y={padT} width={chartW/prices.length} height={chartH} fill="transparent" onMouseEnter={()=>setHover(i)} style={{cursor:"crosshair"}}/>
        {/* Dot */}
        <circle cx={x} cy={y} r={hover===i?5:3} fill={hover===i?"#f0a500":"#1a1a2e"} stroke="#f0a500" strokeWidth={hover===i?2.5:1.5} style={{transition:"r 0.15s"}}/>
        {/* Price tooltip on hover */}
        {hover===i&&<><rect x={x-24} y={y-26} width={48} height={20} rx={4} fill="#f0a500"/>
          <text x={x} y={y-12} fill="#0d0d1a" fontSize="11" fontWeight="700" textAnchor="middle" fontFamily="'DM Sans',sans-serif">£{p}</text>
          {/* Vertical guide line */}
          <line x1={x} y1={y+5} x2={x} y2={padT+chartH} stroke="#f0a500" strokeWidth="1" strokeDasharray="3,3" opacity="0.4"/>
        </>}
      </g>})}
    </svg>
  </div>}

export default function Dashboard(){
  const [mode,setMode]=useState("demo");
  const [liveData,setLiveData]=useState(null); // parsed pricing_data.json
  const [liveStatus,setLiveStatus]=useState("loading"); // loading | ok | none
  const [query,setQuery]=useState("");
  const [sugg,setSugg]=useState([]);
  const [hotel,setHotel]=useState(null);
  const [apt,setApt]=useState("MAN");
  const [dur,setDur]=useState(7);
  const [board,setBoard]=useState("Half Board");
  const [selRoom,setSelRoom]=useState("Standard Double");
  const [data,setData]=useState(null);
  const [rTypes,setRTypes]=useState(ROOM_TYPES);
  const [hm,setHm]=useState(null);
  const [anim,setAnim]=useState(false);

  // On mount, try to load pricing_data.json (written by the scraper)
  useEffect(()=>{
    fetch(`${import.meta.env.BASE_URL}pricing_data.json`)
      .then(r=>{if(!r.ok)throw new Error();return r.json()})
      .then(d=>{
        if(d.hotels?.length){setLiveData(d);setLiveStatus("ok");setMode("live")}
        else setLiveStatus("none")
      })
      .catch(()=>setLiveStatus("none"))
  },[]);

  // Build hotel list from live data (new format with months + room_types)
  const liveHotels=(liveData?.hotels||[]).map(h=>({
    name:h.name,destination:h.destination,stars:h.stars,rating:h.rating,
    _months:h.months,_roomTypes:h.room_types
  }));

  useEffect(()=>{if(query.length<2){setSugg([]);return}
    const q=query.toLowerCase();
    if(mode==="live"&&liveHotels.length){
      const lf=liveHotels.filter(h=>h.name.toLowerCase().includes(q));
      setSugg(lf.length?lf:SAMPLE_HOTELS.filter(h=>h.name.toLowerCase().includes(q)));
    } else setSugg(SAMPLE_HOTELS.filter(h=>h.name.toLowerCase().includes(q)))
  },[query,mode,liveData]);

  const buildLiveMonths=(h,ap,d)=>{
    // New format: hotel has months[] with real per-month per-room data
    // Only show months the scraper actually found prices for
    if(!h._months||!h._months.length)return null;
    const rt=h._roomTypes||ROOM_TYPES;
    if(!rt.length)return null;

    const months=h._months.map(m=>{
      const rooms={};let ch=Infinity,mx=0;
      rt.forEach(r=>{
        const rd=m.rooms[r];
        if(rd&&rd.price_pp>0){
          rooms[r]={price:Math.round(rd.price_pp),available:true,perNight:Math.round(rd.price_pp/d)};
          if(rd.price_pp<ch)ch=rd.price_pp;
          if(rd.price_pp>mx)mx=rd.price_pp;
        }else{
          rooms[r]={price:0,available:false,perNight:0};
        }
      });
      const label=m.month_label||m.month_key||"";
      const parts=label.split(" ");
      return{month:parts[0]||"",year:parseInt(parts[1])||2026,rooms,
        cheapest:ch===Infinity?0:Math.round(ch),mostExpensive:Math.round(mx),
        avgPrice:Math.round(Object.values(rooms).filter(r=>r.price>0).reduce((a,r)=>a+r.price,0)/Math.max(Object.values(rooms).filter(r=>r.price>0).length,1)),
        availability:Object.values(rooms).filter(r=>r.available).length+"/"+rt.length};
    });

    // Filter out months where nothing is available
    const validMonths=months.filter(m=>m.cheapest>0);
    if(!validMonths.length)return null;

    return{months:validMonths,roomTypes:rt};
  };

  const load=useCallback((h,ap,d,b)=>{setAnim(false);setTimeout(()=>{
    if(mode==="live"&&h._months){
      const result=buildLiveMonths(h,ap,d);
      if(result){setData(result.months);setRTypes(result.roomTypes);
        if(!result.roomTypes.includes(selRoom)&&result.roomTypes.length)setSelRoom(result.roomTypes[0])}
      else{setData(generateDemoData(h.name,ap,d,b));setRTypes(ROOM_TYPES)}
    }else{setData(generateDemoData(h.name,ap,d,b));setRTypes(ROOM_TYPES)}
    setAnim(true)},100)},[mode,selRoom]);

  const pick=h=>{setHotel(h);setQuery(h.name);setSugg([]);load(h,apt,dur,board)};
  useEffect(()=>{if(hotel)load(hotel,apt,dur,board)},[apt,dur,board,hotel,load]);

  const oMin=data?Math.min(...data.map(m=>m.cheapest).filter(v=>v>0)):0;
  const oMax=data?Math.max(...data.map(m=>m.mostExpensive)):0;
  const oAvg=data?Math.round(data.reduce((a,m)=>a+m.avgPrice,0)/data.length):0;
  const cM=data?data.filter(m=>m.cheapest>0).reduce((b,m)=>m.cheapest<b.cheapest?m:b,{cheapest:Infinity}):null;
  const bv=cM?.month?`${cM.month} ${cM.year}`:"";
  const cs={bg:"#0d0d1a",card:"#151528",acc:"#f0a500",ad:"rgba(240,165,0,0.15)",tx:"#e8e8f0",td:"rgba(232,232,240,0.5)",bdr:"rgba(255,255,255,0.06)",grn:"#2ecc71",red:"#e74c3c"};
  const inp={width:"100%",padding:"10px 14px",background:"rgba(255,255,255,0.04)",border:`1px solid ${cs.bdr}`,borderRadius:8,color:cs.tx,fontSize:14,outline:"none",boxSizing:"border-box",appearance:"none"};
  const lbl={fontSize:11,color:cs.td,textTransform:"uppercase",letterSpacing:1,display:"block",marginBottom:6};

  return(
    <div style={{minHeight:"100vh",background:cs.bg,color:cs.tx,fontFamily:"'DM Sans','Segoe UI',sans-serif",padding:"24px 20px"}}>
      <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Playfair+Display:wght@700&display=swap" rel="stylesheet"/>
      <style>{`*{margin:0;box-sizing:border-box}body{margin:0;background:#0d0d1a} @keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}`}</style>

      {/* HEADER */}
      <div style={{maxWidth:1280,margin:"0 auto",marginBottom:28}}>
        <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",flexWrap:"wrap",gap:12}}>
          <div style={{display:"flex",alignItems:"center",gap:14}}>
            <div style={{background:cs.acc,color:"#0d0d1a",fontWeight:700,fontSize:18,padding:"6px 14px",borderRadius:6,letterSpacing:"-.5px"}}>jet2</div>
            <h1 style={{fontFamily:"'Playfair Display',serif",fontSize:28,fontWeight:700,margin:0,letterSpacing:"-.5px"}}>Trip Pricing Dashboard</h1>
          </div>
          <div style={{display:"flex",alignItems:"center",gap:12}}>
            <div style={{display:"flex",background:"rgba(255,255,255,0.04)",borderRadius:8,border:`1px solid ${cs.bdr}`,overflow:"hidden"}}>
              {["demo","live"].map(m=><button key={m} onClick={()=>setMode(m)} style={{padding:"6px 16px",fontSize:12,fontWeight:600,fontFamily:"'DM Sans'",background:mode===m?cs.acc:"transparent",color:mode===m?"#0d0d1a":cs.td,border:"none",cursor:"pointer",textTransform:"uppercase",letterSpacing:.5}}>{m}</button>)}
            </div>
            {mode==="live"&&<div style={{display:"flex",alignItems:"center",fontSize:11,color:liveStatus==="ok"?cs.grn:cs.red}}><Dot on={liveStatus==="ok"}/>{liveStatus==="ok"?`${liveData?.total_prices||0} prices scraped`:liveStatus==="loading"?"Loading...":"No scraped data"}</div>}
          </div>
        </div>
        <p style={{color:cs.td,fontSize:13,margin:"4px 0 0"}}>{mode==="demo"?"Demo mode — simulated pricing data":`Live data — last scraped ${liveData?.scraped_at?new Date(liveData.scraped_at).toLocaleString("en-GB"):""}`}</p>
      </div>

      <div style={{maxWidth:1280,margin:"0 auto"}}>
        {/* FILTERS */}
        <div style={{background:cs.card,borderRadius:14,padding:"20px 24px",border:`1px solid ${cs.bdr}`,marginBottom:20}}>
          <div style={{display:"flex",flexWrap:"wrap",gap:16,alignItems:"flex-end"}}>
            <div style={{flex:"1 1 280px",position:"relative"}}>
              <label style={lbl}>Hotel Name</label>
              <input value={query} onChange={e=>{setQuery(e.target.value);setHotel(null);setData(null)}} placeholder="Start typing a hotel name..." style={inp} onFocus={e=>e.target.style.borderColor=cs.acc} onBlur={e=>e.target.style.borderColor=cs.bdr}/>
              {sugg.length>0&&<div style={{position:"absolute",top:"100%",left:0,right:0,zIndex:10,background:"#1e1e38",borderRadius:8,marginTop:4,border:`1px solid ${cs.bdr}`,overflow:"hidden",boxShadow:"0 12px 40px rgba(0,0,0,.5)",maxHeight:300,overflowY:"auto"}}>
                {sugg.map((h,i)=><div key={i} onClick={()=>pick(h)} style={{padding:"10px 14px",cursor:"pointer",borderBottom:`1px solid ${cs.bdr}`}} onMouseEnter={e=>e.currentTarget.style.background="rgba(240,165,0,0.08)"} onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                  <div style={{fontWeight:600,fontSize:13}}>{h.name}</div>
                  <div style={{fontSize:11,color:cs.td,marginTop:2}}>{h.destination} • <Stars count={h.stars}/> • {h.rating}/5</div></div>)}
              </div>}
            </div>
            <div style={{flex:"0 1 180px"}}><label style={lbl}>Airport</label><select value={apt} onChange={e=>setApt(e.target.value)} style={inp}>{AIRPORTS.map(a=><option key={a.code} value={a.code} style={{background:"#1e1e38"}}>{a.name}</option>)}</select></div>
            <div style={{flex:"0 1 120px"}}><label style={lbl}>Nights</label><select value={dur} onChange={e=>setDur(+e.target.value)} style={inp}>{DURATIONS.map(d=><option key={d} value={d} style={{background:"#1e1e38"}}>{d} nights</option>)}</select></div>
            <div style={{flex:"0 1 170px"}}><label style={lbl}>Board Basis</label><select value={board} onChange={e=>setBoard(e.target.value)} style={inp}>{BOARD_TYPES.map(b=><option key={b} value={b} style={{background:"#1e1e38"}}>{b}</option>)}</select></div>
          </div>
        </div>

        {/* EMPTY STATE */}
        {!data&&<div style={{textAlign:"center",padding:"80px 20px",color:cs.td}}>
          <div style={{fontSize:48,marginBottom:16,opacity:.3}}>✈</div>
          <div style={{fontSize:16,fontWeight:500}}>Search for a hotel to view pricing</div>
          <div style={{fontSize:13,marginTop:8}}>{mode==="demo"?'Try "Sunwing", "Flamingo", or "Zafiro"':'Search your database or switch to Demo mode'}</div>
        </div>}

        {/* MAIN DASHBOARD */}
        {data&&hotel&&<div style={{animation:anim?"fadeUp .4s ease forwards":"none",opacity:anim?1:0}}>
          {/* Hotel bar */}
          <div style={{background:cs.card,borderRadius:14,padding:"16px 24px",border:`1px solid ${cs.bdr}`,marginBottom:20,display:"flex",justifyContent:"space-between",alignItems:"center",flexWrap:"wrap",gap:12}}>
            <div><h2 style={{margin:0,fontSize:20,fontWeight:700,fontFamily:"'Playfair Display',serif"}}>{hotel.name}</h2>
              <div style={{fontSize:13,color:cs.td,marginTop:4}}>{hotel.destination} • <Stars count={hotel.stars}/> • {hotel.rating}/5</div></div>
            <div style={{display:"flex",gap:8,flexWrap:"wrap"}}>
              {[AIRPORTS.find(a=>a.code===apt)?.name||apt,`${dur}N`,board].map((t,i)=><span key={i} style={{background:cs.ad,color:cs.acc,padding:"4px 10px",borderRadius:6,fontSize:12,fontWeight:600}}>{t}</span>)}
              {mode==="live"&&<span style={{background:"rgba(46,204,113,.15)",color:cs.grn,padding:"4px 10px",borderRadius:6,fontSize:12,fontWeight:600}}>LIVE</span>}
            </div>
          </div>

          {/* KPIs */}
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(180px,1fr))",gap:14,marginBottom:20}}>
            {[{l:"Cheapest",v:`£${oMin||0}`,sb:"All rooms & months",i:"▼",c:cs.grn},{l:"Most Expensive",v:`£${oMax||0}`,sb:"Peak / suite",i:"▲",c:cs.red},{l:"12-Mo Average",v:`£${oAvg||0}`,sb:"All rooms mean",i:"◆",c:cs.acc},{l:"Best Value",v:bv||"—",sb:cM?.cheapest&&cM.cheapest<Infinity?`From £${cM.cheapest}pp`:"",i:"★",c:cs.acc},{l:"Spread",v:`£${(oMax||0)-(oMin||0)}`,sb:"Max−Min",i:"↔",c:"#8e8ef0"}].map((k,i)=>
              <div key={i} style={{background:cs.card,borderRadius:12,padding:"18px 20px",border:`1px solid ${cs.bdr}`}}>
                <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:8}}>
                  <span style={{fontSize:11,color:cs.td,textTransform:"uppercase",letterSpacing:.8}}>{k.l}</span>
                  <span style={{color:k.c,fontSize:14}}>{k.i}</span></div>
                <div style={{fontSize:24,fontWeight:700,letterSpacing:"-.5px"}}>{k.v}</div>
                <div style={{fontSize:11,color:cs.td,marginTop:4}}>{k.sb}</div></div>)}
          </div>

          {/* Room tabs */}
          <div style={{marginBottom:20,display:"flex",gap:8,flexWrap:"wrap"}}>
            {rTypes.map(rt=><button key={rt} onClick={()=>setSelRoom(rt)} style={{background:selRoom===rt?cs.acc:"rgba(255,255,255,.04)",color:selRoom===rt?"#0d0d1a":cs.td,border:`1px solid ${selRoom===rt?cs.acc:cs.bdr}`,borderRadius:8,padding:"8px 16px",fontSize:12,fontWeight:600,cursor:"pointer",fontFamily:"'DM Sans'"}}>{rt}</button>)}
          </div>

          {/* Chart + Per-night */}
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(340px,1fr))",gap:14,marginBottom:20}}>
            <div style={{background:cs.card,borderRadius:14,padding:"20px 24px",border:`1px solid ${cs.bdr}`}}>
              <div style={{fontSize:11,color:cs.td,textTransform:"uppercase",letterSpacing:1,marginBottom:2}}>Price Trend — {selRoom}</div>
              <PriceChart data={data} selectedRoom={selRoom}/></div>
            <div style={{background:cs.card,borderRadius:14,padding:"20px 24px",border:`1px solid ${cs.bdr}`}}>
              <div style={{fontSize:11,color:cs.td,textTransform:"uppercase",letterSpacing:1,marginBottom:14}}>Per-Night — {selRoom}</div>
              <div style={{display:"flex",flexDirection:"column",gap:8}}>
                {data.map((m,i)=>{const rm=m.rooms[selRoom];const mx=Math.max(...data.map(m2=>m2.rooms[selRoom]?.perNight||0));return(
                  <div key={i} style={{display:"flex",alignItems:"center",gap:10}}>
                    <span style={{fontSize:11,color:cs.td,width:30,textAlign:"right"}}>{m.month}</span>
                    <div style={{flex:1}}><MiniBar value={rm?.perNight||0} max={mx} color={rm?.available?cs.acc:cs.red}/></div>
                    <span style={{fontSize:12,fontWeight:600,width:50,textAlign:"right"}}>{rm?.available?`£${rm.perNight}`:<span style={{color:cs.red,fontSize:10}}>N/A</span>}</span></div>)})}</div></div>
          </div>

          {/* Full pricing grid */}
          <div style={{background:cs.card,borderRadius:14,border:`1px solid ${cs.bdr}`,overflow:"hidden"}}>
            <div style={{padding:"16px 24px",borderBottom:`1px solid ${cs.bdr}`}}>
              <span style={{fontSize:11,color:cs.td,textTransform:"uppercase",letterSpacing:1}}>Complete Pricing Grid — Per Person</span></div>
            <div style={{overflowX:"auto"}}>
              <table style={{width:"100%",borderCollapse:"collapse",fontSize:13}}>
                <thead><tr>
                  <th style={{padding:"12px 16px",textAlign:"left",color:cs.td,fontWeight:600,fontSize:11,textTransform:"uppercase",position:"sticky",left:0,background:cs.card,borderBottom:`1px solid ${cs.bdr}`,zIndex:1}}>Room Type</th>
                  {data.map((m,i)=><th key={i} style={{padding:"12px 10px",textAlign:"center",fontWeight:600,fontSize:11,textTransform:"uppercase",color:hm===i?cs.acc:cs.td,borderBottom:`1px solid ${cs.bdr}`,cursor:"pointer"}} onMouseEnter={()=>setHm(i)} onMouseLeave={()=>setHm(null)}>{m.month}<br/><span style={{fontSize:10,opacity:.6}}>{m.year}</span></th>)}
                </tr></thead>
                <tbody>
                  {rTypes.map(rt=><tr key={rt} style={{background:selRoom===rt?"rgba(240,165,0,.04)":"transparent",cursor:"pointer"}} onClick={()=>setSelRoom(rt)}>
                    <td style={{padding:"10px 16px",fontWeight:selRoom===rt?700:500,color:selRoom===rt?cs.acc:cs.tx,whiteSpace:"nowrap",position:"sticky",left:0,background:selRoom===rt?"rgba(240,165,0,.04)":cs.card,borderBottom:`1px solid ${cs.bdr}`,fontSize:12,zIndex:1}}>{rt}</td>
                    {data.map((m,mi)=>{const rm=m.rooms[rt];return <td key={mi} style={{padding:"10px",textAlign:"center",borderBottom:`1px solid ${cs.bdr}`,background:hm===mi?"rgba(255,255,255,.02)":"transparent"}}>
                      {rm?.available?<span style={{fontWeight:600,color:rm.price===oMin?cs.grn:rm.price===oMax?cs.red:cs.tx}}>£{rm.price}</span>:<span style={{color:"rgba(255,255,255,.15)",fontSize:11}}>Sold Out</span>}</td>})}
                  </tr>)}
                  <tr style={{background:"rgba(46,204,113,.04)"}}>
                    <td style={{padding:"10px 16px",fontWeight:700,color:cs.grn,fontSize:12,position:"sticky",left:0,background:cs.card,borderBottom:`1px solid ${cs.bdr}`,zIndex:1}}>▼ Cheapest</td>
                    {data.map((m,i)=><td key={i} style={{padding:"10px",textAlign:"center",fontWeight:700,color:cs.grn,borderBottom:`1px solid ${cs.bdr}`,fontSize:13}}>£{m.cheapest||"—"}</td>)}
                  </tr>
                </tbody>
              </table></div>
          </div>

          <div style={{textAlign:"center",padding:"20px 0",color:cs.td,fontSize:11}}>
            {mode==="demo"?"Simulated data • Switch to Live and connect API for real prices":"Scraped from jet2holidays.com"}<br/>
            Per person, 2 adults sharing • {dur} nights {board} from {AIRPORTS.find(a=>a.code===apt)?.name}</div>
        </div>}
      </div>
    </div>)}

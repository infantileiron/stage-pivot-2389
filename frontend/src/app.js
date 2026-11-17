import {api,post} from './api/client.js';
import {state} from './stores/session.js';
import {routes,page} from './router/index.js';
import {values,feedback} from './hooks/form.js';
import {esc} from './utils/html.js';
import * as settlements from './pages/settlements.js';
import * as layout from './pages/layout.js';
import * as pivot from './pages/pivot.js';
import * as reviews from './pages/reviews.js';
import * as contracts from './pages/contracts.js';

const root=document.querySelector('#app');
const pages=[settlements,layout,pivot,reviews,contracts];

async function load(){
  [state.settlements,state.pivots,state.reviews,state.contracts]=await Promise.all(['/settlements','/pivots','/reviews','/contracts'].map(x=>api(x)));
  state.selected=state.pivots.find(r=>r.id===state.selected?.id)||state.pivots[0]||null;
  const keep=state.selectedContract?.id;
  state.selectedContract=state.contracts.find(c=>c.id===keep)||state.contracts[0]||null;
}

function login(){root.innerHTML=`<div class="login"><section class="cover"><div class="eyebrow">YUN MU / SETTLEMENT PROGRAMME 012</div><h1>散场之后，<br>每一笔都有回声。</h1><p>云幕剧院 · 场次结算节目单<br>明细 → 透视 → 冻结下钻 → 差异签核 → 合同分成<br>三处场馆 / 180场演出 / 分币守恒</p></section><section><div class="eyebrow">STAGE PIVOT</div><h2>登录结算节目单</h2><form id="login"><label>工作邮箱<input name="email" type="email" value="analyst@demo.local" required></label><label>密码<input name="password" type="password" value="Demo123!" required></label><button class="primary">进入场次结算</button></form><p id="error" class="error"></p><p>admin / analyst / viewer @demo.local<br>密码：Demo123!</p></section></div>`;document.querySelector('form').onsubmit=e=>{e.preventDefault();run(async()=>{let d=await post('/auth/login',values(e.target));localStorage.setItem('token',d.token);state.user=d.user;await load();render()})}}

function render(){
  const n=Math.min(routes.length-1,Math.max(0,page()));
  root.innerHTML=`<header><div class="brand">云幕 / 场次结算节目单 <span class="eyebrow">STAGE PIVOT</span></div><div>${esc(state.user.email)} · ${esc(state.user.role)} <button id="logout">退出</button></div></header><div class="layout"><nav>${routes.map((r,i)=>`<button data-nav="${i}" class="${i===n?'active':''}">0${i+1} ${r}</button>`).join('')}<span class="eyebrow">THEATRE ACCOUNTS / 2026</span></nav><main><div class="intro"><div><div class="eyebrow">SETTLEMENT PROGRAMME / 0${n+1}</div><h1>${routes[n]}</h1><p>让票款、退款与渠道费回到具体场次。每份透视保留原始明细；合同按场分成、抵扣预付后形成应付，差异由财务负责人签核。</p></div><span class="tag">3 场馆 / 散场结算</span></div><p id="error" class="error"></p>${pages[n].render()}</main></div>`;
  bind();
  if(state.user.role==='viewer')document.querySelectorAll('form button,#draft-review,#calc-contract').forEach(b=>{b.disabled=true;b.textContent='观察员只读'});
}

async function run(fn){try{await fn()}catch(e){feedback(e.message)}}

function bind(){
  document.querySelectorAll('[data-nav]').forEach(b=>b.onclick=()=>location.hash=b.dataset.nav);
  document.querySelector('#logout').onclick=()=>{localStorage.removeItem('token');state.user=null;login()};
  for(let [id,path] of [['settlement','/settlements'],['pivot','/pivots'],['review','/reviews']]){
    const f=document.querySelector('#'+id);if(!f)continue;
    f.onsubmit=e=>{e.preventDefault();run(async()=>{let d=values(f);for(let k of ['gross_cents','refund_cents','fee_cents','seats','checked','pivot_id','expected_cents'])if(k in d)d[k]=Number(d[k]);let record=d.record_id;delete d.record_id;let created=record?await api(path+'/'+record,{method:'PUT',body:JSON.stringify(d)}):await post(path,d);if(id==='pivot'){state.selected=created;state.drill=null;state.chosen=null}await load();if(id==='pivot'&&location.hash!=='#2')location.hash='2';else render()})};
  }
  document.querySelectorAll('[data-pivot]').forEach(b=>b.onclick=()=>run(async()=>{state.selected=await api('/pivots/'+b.dataset.pivot);state.drill=null;state.chosen=null;if(location.hash!=='#2')location.hash='2';else render()}));
  document.querySelectorAll('[data-drill-row]').forEach(b=>b.onclick=()=>run(async()=>{state.drill=await api('/pivots/'+state.selected.id+'/drill?'+new URLSearchParams({row_key:b.dataset.drillRow,col_key:b.dataset.drillCol}));render();document.querySelector('#draft-review')?.scrollIntoView({block:'center'})}));
  const draft=document.querySelector('#draft-review');if(draft)draft.onclick=()=>{state.chosen=state.drill.cell;location.hash='3'};
  document.querySelectorAll('[data-approve]').forEach(b=>b.onclick=()=>run(async()=>{await post('/reviews/'+b.dataset.approve+'/approve',{});await load();render()}));
  const refresh=document.querySelector('#refresh');if(refresh)refresh.onclick=()=>run(async()=>{await load();render()});
  const download=document.querySelector('#download');if(download)download.onclick=()=>run(async()=>{let d=await api('/pivots/'+state.selected.id+'/export');let u=URL.createObjectURL(new Blob([JSON.stringify(d,null,2)],{type:'application/json'}));let a=document.createElement('a');a.href=u;a.download='stage-pivot-'+d.id+'.json';a.click();URL.revokeObjectURL(u)});

  document.querySelectorAll('[data-contract]').forEach(b=>b.onclick=async()=>{state.selectedContract=state.contracts.find(c=>c.id===Number(b.dataset.contract))||null;render()});
  document.querySelectorAll('[data-retry]').forEach(b=>b.onclick=()=>run(async()=>{await post('/share-runs/'+b.dataset.retry+'/retry',{});await load();render()}));
  const calc=document.querySelector('#calc-contract');if(calc)calc.onclick=()=>run(async()=>{await post('/contracts/'+state.selectedContract.id+'/calculate',{});await load();render();poll()});
  const dlContract=document.querySelector('#download-contract');if(dlContract)dlContract.onclick=()=>run(async()=>{let d=await api('/contracts/'+state.selectedContract.id+'/export');let u=URL.createObjectURL(new Blob([JSON.stringify(d,null,2)],{type:'application/json'}));let a=document.createElement('a');a.href=u;a.download='contract-'+d.code+'.json';a.click();URL.revokeObjectURL(u)});
  const receipt=document.querySelector('#receipt');if(receipt)receipt.onsubmit=e=>{e.preventDefault();run(async()=>{let d=values(receipt);d.amount_cents=Number(d.amount_cents);let r=await post('/contracts/'+state.selectedContract.id+'/receipts',d);await load();render();feedback(r.created?'回执已登记':'回执已存在，幂等返回，未重复付款')})};
  const contract=document.querySelector('#contract');
  if(contract)contract.onsubmit=e=>{e.preventDefault();run(async()=>{let d=values(contract);d.ratio_bp=Number(d.ratio_bp);d.advance_cents=Number(d.advance_cents);let c=await post('/contracts',d);await load();state.selectedContract=state.contracts.find(x=>x.id===c.id)||state.contracts[0];render()})};
  const contractEdit=document.querySelector('#contract-edit');
  if(contractEdit)contractEdit.onsubmit=e=>{e.preventDefault();run(async()=>{let d=values(contractEdit);d.ratio_bp=Number(d.ratio_bp);d.advance_cents=Number(d.advance_cents);await api('/contracts/'+state.selectedContract.id,{method:'PUT',body:JSON.stringify(d)});await load();render()})};
  poll();
}

let timer=null;
function poll(){
  clearTimeout(timer);
  const open=(state.contracts||[]).some(c=>(c.runs||[]).some(r=>r.state==='pending'||r.state==='running'));
  if(open&&page()===4)timer=setTimeout(()=>run(async()=>{await load();render()}),2500);
}

window.onhashchange=()=>{if(state.user){render();window.scrollTo(0,0)}};
if(localStorage.getItem('token'))run(async()=>{try{state.user=await api('/me');await load();render()}catch(e){localStorage.removeItem('token');login();feedback(e.message)}});else login();

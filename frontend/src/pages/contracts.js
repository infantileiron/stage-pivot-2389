import {state} from '../stores/session.js';
import {esc} from '../utils/html.js';
import {badge} from '../components/common/status.js';
import {table} from '../components/common/table.js';
import {field,select} from '../components/common/fields.js';
import {VENUES} from '../constants/enums.js';
import {money} from '../utils/format.js';

const stateLabel={pending:'待计算',running:'计算中',published:'已发布',failed:'失败',stale:'已过期'};
const runRows=runs=>(runs||[]).slice(0,5).map(r=>[`#${r.id}`,stateLabel[r.state]||r.state,`v${r.contract_version}`,r.attempts,r.error||'—',r.published||r.finished||r.created]);

function contractPick(){
 return state.contracts.map(x=>`<button class="study" data-contract="${x.id}">#${x.id} ${esc(x.code)} ${esc(x.name)} ${badge(x.needs_recalc?'待重算':'已对齐')} · ${esc(x.producer)}
 <small>分成 ${money(x.earned_cents)} / 抵预付 ${money(x.published_advance_cents)} / 应付 ${money(x.payable_cents)}${x.credit_cents?` / 待抵 ${money(x.credit_cents)}`:''}${x.recovery_cents?` / 追偿 ${money(x.recovery_cents)}`:''}</small></button>`).join('')||'<p>尚无演出合同。</p>';
}

function detail(){
 const c=state.selectedContract;if(!c)return '<p class="notice">选择一份合同查看逐场分成、预付款抵扣与付款回执。</p>';
 const run=(c.runs||[]).find(r=>r.id===c.current_run_id)||(c.runs||[])[0];
 const result=run?.state==='published'?run.result:null;
 const allocations=result?.allocations||[];
 return `<h3>#${c.id} ${esc(c.name)} ${badge(c.status)} ${c.needs_recalc?badge('待重算'):''}</h3>
 <p>制作方：${esc(c.producer)} · 演出：${esc(c.play)} · 场馆：${esc(c.venue||'全部场馆')} · ${esc(c.start_day)} 至 ${esc(c.end_day)}</p>
 <p>分成比例 ${(c.ratio_bp/100).toFixed(2)}% · 预付款 ${money(c.advance_cents)} 元 · 条款版本 v${c.version}${c.published_at?` · 最近发布 ${esc(c.published_at)}`:''}</p>
 <div class="metrics"><div><strong>${money(c.earned_cents)}</strong>累计分成 / 元</div><div><strong>${money(c.published_advance_cents)}</strong>已抵预付</div><div><strong>${money(c.paid_cents)}</strong>已确认付款</div><div><strong>${money(c.payable_cents)}</strong>当前应付</div><div><strong>${money(c.credit_cents)}</strong>后续抵扣</div><div><strong>${money(c.recovery_cents)}</strong>${c.status==='ended'?'结束追偿':'未结追偿'}</div></div>
 <p class="notice">每场分成=净结算×比例向下取整到分；比例合计的累计尾差全部留在末场，保证逐场分成合计等于总额。先抵预付款再形成应付；已确认回执永久保留，多付转为后续抵扣；合同结束后仍未收回的预付与多付单列追偿。</p>
 <h3>逐场分成${result?` · 末场尾差 ${money(result.residual_cents)} 元`:''}</h3>${allocations.length?table(['场','场次','日期','场馆','净结算 ¥','基础分成 ¥','尾差 ¥','分成 ¥'],allocations.map(a=>[a.sequence,a.code,a.day,a.venue,money(a.net_cents),money(a.base_share_cents),money(a.residual_cents),money(a.share_cents)])):'<p>尚无已发布计算。</p>'}
 <h3>计算任务</h3>${table(['任务','状态','条款版本','尝试','失败原因','时间'],runRows(c.runs))}
 <h3>付款回执</h3>${table(['编号','金额 ¥','付款日','状态','登记人','登记时间'],(c.receipts||[]).map(r=>[r.receipt_no,money(r.amount_cents),r.paid_day,r.status,r.created_by,r.created]))}`;
}

function receiptForm(c){
 return `<h3>登记付款回执</h3><form id="receipt"><label>回执编号<input name="receipt_no" required maxlength="100" placeholder="银行流水唯一编号"></label>${field('金额 / 分','amount_cents','number','required min=1 step=1')}${field('付款日期','paid_day','date','required value="2026-11-17"')}<label>备注<textarea name="note" rows="3" maxlength="2000"></textarea></label><p>同号同额重试幂等，不重复支付；同号异额或异合同拒绝；付款不得超过最新应付 ${money(c.payable_cents)} 元。</p><button class="primary">登记回执</button></form>`;
}

function editForm(c){
 return `<h3>修改合同条款</h3><form id="contract-edit"><p>#${c.id} · ${esc(c.code)} · 当前 v${c.version}</p>
 ${field('合同名称','name','text',`required maxlength="100" value="${esc(c.name)}"`)}
 ${field('制作方','producer','text',`required maxlength="100" value="${esc(c.producer)}"`)}
 ${field('演出名称','play','text',`required maxlength="60" value="${esc(c.play)}"`)}
 ${select('场馆范围','venue',[['','全部场馆'],...VENUES.map(x=>[x,x])],c.venue)}
 ${field('起始日期','start_day','date',`required value="${esc(c.start_day)}"`)}
 ${field('结束日期','end_day','date',`required value="${esc(c.end_day)}"`)}
 ${field('分成比例 / 基点','ratio_bp','number',`required min=0 max=10000 value=${Number(c.ratio_bp)}`)}
 ${field('预付款 / 分','advance_cents','number',`required min=0 step=1 value=${Number(c.advance_cents)}`)}
 <label>合同状态<select name="status"><option value="active" ${c.status==='active'?'selected':''}>履约中</option><option value="ended" ${c.status==='ended'?'selected':''}>已结束</option></select></label>
 <p>修改比例、预付、范围或日期会提升条款版本并要求重算；旧计算结果发布时会被判定过期。</p>
 <button class="primary">保存条款</button></form>`;
}

export function render(){
 const c=state.selectedContract;
 return `<div class="split"><section class="panel">
 <h2>合同、分成与付款回执</h2><p class="notice">合同定义制作方、演出、场馆、日期范围、分成比例（基点）与预付款。计算提交时冻结场次快照；退款或改期会自动把受影响合同标记为待重算，已确认付款保留并转为后续抵扣。</p>
 ${detail()}
 </section><aside class="side">
 <h2>合同分成</h2>${contractPick()}
 ${c?`<div class="result-head"><h3>#${c.id} ${esc(c.code)}</h3><div><button id="calc-contract">${c.current_run_id?'重新计算':'计算分成'}</button> <button id="download-contract" ${c.current_run_id?'':'disabled'}>下载依据</button></div></div>
 ${c.needs_recalc?'<p class="notice">场次或合同条款已变化。请重新计算；发布时若发现快照过期将拒绝覆盖现有应付。</p>':''}
 ${(c.runs||[]).filter(r=>r.state==='failed').map(r=>`<p>#${r.id} 失败：${esc(r.error||'未知原因')} <button data-retry="${r.id}">续跑</button></p>`).join('')}
 ${c.current_run_id?receiptForm(c):'<p class="notice">合同尚未发布分成结果，暂不能登记付款。</p>'}
 ${editForm(c)}`:`<p>选择合同后可计算、登记回执或下载依据。</p>`}
 <h3>新建合同</h3>
 <form id="contract">${field('合同编号','code','text','required maxlength="60"')}${field('合同名称','name','text','required maxlength="100"')}${field('制作方','producer','text','required maxlength="100"')}${field('演出名称','play','text','required maxlength="60"')}${select('场馆范围','venue',[['','全部场馆'],...VENUES.map(x=>[x,x])])}${field('起始日期','start_day','date','required value="2026-09-01"')}${field('结束日期','end_day','date','required value="2026-10-31"')}${field('分成比例 / 基点（10000=100%）','ratio_bp','number','required min=0 max=10000 value=3000')}${field('预付款 / 分','advance_cents','number','required min=0 step=1 value=0')}<p>同一演出、日期与场馆范围不得重叠。</p><button class="primary">创建合同</button></form>
 </aside></div>`;
}

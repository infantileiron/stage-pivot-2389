import {esc} from '../../utils/html.js';
export const field=(label,name,type='text',extra='')=>`<label>${label}<input name=${name} type=${type} ${extra}></label>`;export const select=(label,name,options,current)=>`<label>${label}<select name=${name}>${options.map(([v,t])=>`<option value="${esc(v)}" ${String(v)===String(current??'')?'selected':''}>${esc(t)}</option>`).join('')}</select></label>`;

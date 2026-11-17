import os,json
import redis
from fastapi import APIRouter,Depends,HTTPException,Response
from sqlalchemy.exc import IntegrityError
from src.config.database import db
from src.models.entities import User,Settlement,Pivot,Review,Audit,Contract,ShareRun,PaymentReceipt
from src.schemas.business import Login,SettlementInput,PivotInput,ReviewInput,ReviewEdit,ContractInput,ContractEdit,ReceiptInput
from src.middlewares.auth import current,editor,admin
from src.utils.security import verify,token
from src.services.business import audit,dump
from src.services.settlements import save
from src.services.analysis import key
from src.services import shares
from src.controllers.business import ensure_pivot,ensure_review,cell
router=APIRouter()
@router.post('/auth/login')
def login(data:Login,s=Depends(db)):
 u=s.query(User).filter_by(email=data.email).first()
 if not u or not verify(data.password,u.password):raise HTTPException(401,'账号或密码错误')
 return {'token':token(u),'user':dump(u)}
@router.get('/me')
def me(u=Depends(current)):return dump(u)
@router.get('/settlements')
def settlements(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Settlement).order_by(Settlement.id).all()]
@router.post('/settlements')
def create(data:SettlementInput,u=Depends(editor),s=Depends(db)):
 r=save(s,data);audit(s,u,'录入结算 '+r['code']);return r
@router.put('/settlements/{i}')
def edit(i:int,data:SettlementInput,u=Depends(editor),s=Depends(db)):
 r=save(s,data,i);audit(s,u,'修订结算 '+str(i));return r
@router.get('/pivots')
def pivots(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Pivot).order_by(Pivot.id.desc()).all()]
@router.post('/pivots')
def submit(data:PivotInput,u=Depends(editor),s=Depends(db)):
 rows=[dump(r) for r in s.query(Settlement).order_by(Settlement.id).all()]
 r=Pivot(**data.model_dump(),result={'snapshot':rows});s.add(r);s.commit()
 try:redis.Redis.from_url(os.environ['REDIS_URL']).rpush('stage:pivots',r.id)
 except redis.RedisError:r.state='failed';r.error='队列暂不可用，请恢复后新建透视';s.commit();raise HTTPException(503,r.error)
 audit(s,u,'提交透视 '+str(r.id));return dump(r)
@router.get('/pivots/{i}')
def detail(i:int,u=Depends(current),s=Depends(db)):return dump(ensure_pivot(s,i))
@router.get('/pivots/{i}/drill')
def drill(i:int,row_key:str,col_key:str,u=Depends(current),s=Depends(db)):
 r,c=cell(s,i,row_key,col_key)
 return {'cell':c,'rows':[x for x in r.result['snapshot'] if key(x,r.row_dim)==row_key and key(x,r.col_dim)==col_key]}
@router.get('/pivots/{i}/export')
def export(i:int,u=Depends(current),s=Depends(db)):
 r=ensure_pivot(s,i)
 if r.state!='done':raise HTTPException(409,'仅成功透视可以导出')
 return Response(json.dumps(dump(r),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="stage-pivot-{i}.json"'})
@router.get('/reviews')
def reviews(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Review).order_by(Review.id.desc()).all()]
@router.post('/reviews')
def review(data:ReviewInput,u=Depends(editor),s=Depends(db)):
 run,c=cell(s,data.pivot_id,data.row_key,data.col_key)
 r=Review(**data.model_dump(),book_cents=c['net_cents'],difference_cents=data.expected_cents-c['net_cents']);s.add(r);s.commit();audit(s,u,'起草差异复核 '+str(r.id));return dump(r)
@router.put('/reviews/{i}')
def edit_review(i:int,data:ReviewEdit,u=Depends(editor),s=Depends(db)):
 r=ensure_review(s,i)
 if r.status!='draft':raise HTTPException(409,'已签核复核单不可覆盖，请新建复核')
 r.expected_cents=data.expected_cents;r.difference_cents=data.expected_cents-r.book_cents;r.note=data.note;s.commit();audit(s,u,'修改差异复核 '+str(i));return dump(r)
@router.post('/reviews/{i}/approve')
def approve(i:int,u=Depends(admin),s=Depends(db)):
 r=ensure_review(s,i)
 if r.status!='draft':raise HTTPException(409,'已签核复核单不可重复签核')
 r.status='approved';s.commit();audit(s,u,'签核差异复核 '+str(i));return dump(r)
@router.get('/audits')
def audits(u=Depends(admin),s=Depends(db)):return [dump(r) for r in s.query(Audit).order_by(Audit.id.desc()).limit(100)]


def ensure_contract(s,i):
 r=s.get(Contract,i)
 if not r:raise HTTPException(404,'演出合同不存在')
 return r

def run_out(run,full=False):
 out=dump(run)
 out.pop('snapshot',None)
 if not full:
  out.pop('result',None)
 return out

def contract_out(s,c,with_runs=True):
 out=dump(c)
 out['ended']=shares.contract_ended(c)
 if with_runs:
  runs=s.query(ShareRun).filter(ShareRun.contract_id==c.id).order_by(ShareRun.id.desc()).limit(5).all()
  if c.current_run_id and all(r.id!=c.current_run_id for r in runs):
   current=s.get(ShareRun,c.current_run_id)
   if current:runs.append(current)
  out['runs']=[run_out(r,full=(r.id==c.current_run_id or r.state=='failed')) for r in runs]
  receipts=s.query(PaymentReceipt).filter(PaymentReceipt.contract_id==c.id).order_by(PaymentReceipt.id.desc()).all()
  out['receipts']=[dump(r) for r in receipts]
 out['ledger']=shares.ledger(c,c.earned_cents or 0,c.paid_cents or 0)
 return out

@router.get('/contracts')
def contracts(u=Depends(current),s=Depends(db)):
 return [contract_out(s,c) for c in s.query(Contract).order_by(Contract.id.desc()).all()]

@router.post('/contracts')
def create_contract(data:ContractInput,u=Depends(editor),s=Depends(db)):
 payload=data.model_dump();payload['start_day']=payload['start_day'].isoformat();payload['end_day']=payload['end_day'].isoformat()
 if s.query(Contract).filter(Contract.code==payload['code']).first():raise HTTPException(409,'合同编号重复，一份合同仅一条记录')
 shares.contract_overlap(s,payload)
 c=Contract(**payload,version=1,needs_recalc=1,created=shares.now(),updated=shares.now())
 s.add(c)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'合同编号重复，一份合同仅一条记录')
 audit(s,u,'新建演出合同 '+c.code)
 return contract_out(s,c)

@router.put('/contracts/{i}')
def edit_contract(i:int,data:ContractEdit,u=Depends(editor),s=Depends(db)):
 c=ensure_contract(s,i)
 payload=data.model_dump();payload['start_day']=payload['start_day'].isoformat();payload['end_day']=payload['end_day'].isoformat()
 shares.contract_overlap(s,payload,exclude_id=c.id)
 frozen=(c.ratio_bp,c.advance_cents,c.play,c.venue,c.start_day,c.end_day,c.status)
 for k,v in payload.items():setattr(c,k,v)
 new=(c.ratio_bp,c.advance_cents,c.play,c.venue,c.start_day,c.end_day,c.status)
 if frozen!=new:
  c.version=(c.version or 1)+1
  c.needs_recalc=1
 c.updated=shares.now()
 s.commit()
 audit(s,u,'修订演出合同 '+c.code)
 return contract_out(s,c)

@router.post('/contracts/{i}/calculate')
def calculate_contract(i:int,u=Depends(editor),s=Depends(db)):
 c=ensure_contract(s,i)
 shares.reconcile_open_slots(s)
 run=shares.create_run(s,c,u.email)
 try:shares.enqueue_run(run,s)
 except HTTPException:audit(s,u,'提交合同分成（排队失败） '+c.code);raise
 audit(s,u,'提交合同分成计算 '+c.code)
 return run_out(run)

@router.get('/contracts/{i}/runs')
def contract_runs(i:int,u=Depends(current),s=Depends(db)):
 ensure_contract(s,i)
 return [run_out(r) for r in s.query(ShareRun).filter(ShareRun.contract_id==i).order_by(ShareRun.id.desc()).all()]

@router.get('/share-runs')
def share_runs(u=Depends(current),s=Depends(db)):
 return [run_out(r) for r in s.query(ShareRun).order_by(ShareRun.id.desc()).limit(100).all()]

@router.get('/share-runs/{i}')
def share_run(i:int,u=Depends(current),s=Depends(db)):
 r=s.get(ShareRun,i)
 if not r:raise HTTPException(404,'计算任务不存在')
 return dump(r)

@router.post('/share-runs/{i}/retry')
def retry_run(i:int,u=Depends(editor),s=Depends(db)):
 # 续跑沿用原始冻结快照；若快照已过期，发布时会判定 stale 而拒绝覆盖。
 run,old=shares.create_retry(s,i,u.email)
 c=ensure_contract(s,run.contract_id)
 try:shares.enqueue_run(run,s)
 except HTTPException:audit(s,u,'续跑合同分成（排队失败） '+c.code);raise
 audit(s,u,f'续跑合同分成计算 #{old.id} → #{run.id}')
 return run_out(run)

@router.get('/contracts/{i}/export')
def export_contract(i:int,u=Depends(current),s=Depends(db)):
 c=ensure_contract(s,i)
 if not c.current_run_id:raise HTTPException(409,'合同尚未发布分成结果')
 run=s.get(ShareRun,c.current_run_id)
 payload=contract_out(s,c);payload['published_run']=dump(run)
 return Response(json.dumps(payload,ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="contract-{c.code}.json"'})

@router.get('/contracts/{i}/receipts')
def contract_receipts(i:int,u=Depends(current),s=Depends(db)):
 ensure_contract(s,i)
 return [dump(r) for r in s.query(PaymentReceipt).filter(PaymentReceipt.contract_id==i).order_by(PaymentReceipt.id).all()]

@router.post('/contracts/{i}/receipts')
def add_receipt(i:int,data:ReceiptInput,u=Depends(editor),s=Depends(db)):
 c=ensure_contract(s,i)
 row,created=shares.register_receipt(s,c,data,u.email)
 audit(s,u,('登记付款回执 ' if created else '重复回执幂等返回 ')+data.receipt_no)
 return {**row,'created':created}

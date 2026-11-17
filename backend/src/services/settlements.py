from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from src.models.entities import Settlement
from src.services.business import dump
from src.services import shares


def save(s,data,i=None):
 r=s.get(Settlement,i) if i else Settlement()
 if not r:raise HTTPException(404,'结算场次不存在')
 before=shares.settlement_row(r) if r.id else None
 d=data.model_dump();d['day']=d['day'].isoformat()
 for k,v in d.items():setattr(r,k,v)
 s.add(r)
 try:s.flush()
 except IntegrityError:s.rollback();raise HTTPException(409,'场次编号重复，一场次仅一条结算')
 after=shares.settlement_row(r)
 try:
  if shares.share_relevant_changed(before,after):shares.mark_affected(s,before,after)
  s.commit()
 except IntegrityError:
  s.rollback();raise HTTPException(409,'场次编号重复，一场次仅一条结算')
 return dump(r)

from sqlalchemy import Column,Integer,BigInteger,String,JSON,Text,ForeignKey,Index
from src.config.database import Base


class User(Base):
    __tablename__='users'
    id=Column(Integer,primary_key=True)
    email=Column(String(100),unique=True,nullable=False)
    password=Column(String(200))
    role=Column(String(20))


class Settlement(Base):
    __tablename__='settlements'
    id=Column(Integer,primary_key=True)
    code=Column(String(60),unique=True,nullable=False)
    day=Column(String(10))
    venue=Column(String(40))
    play=Column(String(60))
    channel=Column(String(30))
    gross_cents=Column(BigInteger)
    refund_cents=Column(BigInteger)
    fee_cents=Column(BigInteger)
    seats=Column(Integer)
    checked=Column(Integer)


class Pivot(Base):
    __tablename__='pivots'
    id=Column(Integer,primary_key=True)
    name=Column(String(100))
    row_dim=Column(String(30))
    col_dim=Column(String(30))
    state=Column(String(20),default='queued')
    result=Column(JSON,nullable=True)
    error=Column(Text,default='')


class Review(Base):
    __tablename__='reviews'
    id=Column(Integer,primary_key=True)
    pivot_id=Column(Integer,ForeignKey('pivots.id'))
    row_key=Column(String(100))
    col_key=Column(String(100))
    book_cents=Column(BigInteger)
    expected_cents=Column(BigInteger)
    difference_cents=Column(BigInteger)
    note=Column(Text)
    status=Column(String(20),default='draft')


class Audit(Base):
    __tablename__='audits'
    id=Column(Integer,primary_key=True)
    actor=Column(String(100))
    action=Column(String(200))
    created=Column(String(40))


class Contract(Base):
    """演出合同：约定制作方分成比例、预付款及合同覆盖的场次范围。"""
    __tablename__='contracts'
    id=Column(Integer,primary_key=True)
    code=Column(String(60),unique=True,nullable=False)
    name=Column(String(100),nullable=False)
    producer=Column(String(100),nullable=False)
    play=Column(String(60),nullable=False)
    # 空字符串表示合同覆盖全部场馆
    venue=Column(String(40),nullable=True)
    start_day=Column(String(10),nullable=False)
    end_day=Column(String(10),nullable=False)
    ratio_bp=Column(Integer,nullable=False,default=0)
    advance_cents=Column(BigInteger,nullable=False,default=0)
    status=Column(String(20),default='active')
    version=Column(Integer,default=1)
    needs_recalc=Column(Integer,default=1)
    # 以下字段是最近一次“已发布”计算的账本，由发布事务原子切换
    current_run_id=Column(Integer,nullable=True)
    # 0/1 守护位：条件更新保证同一合同同时最多一个未完成任务。
    open_run=Column(Integer,default=0,nullable=False)
    earned_cents=Column(BigInteger,default=0)
    published_advance_cents=Column(BigInteger,default=0)
    paid_cents=Column(BigInteger,default=0)
    payable_cents=Column(BigInteger,default=0)
    credit_cents=Column(BigInteger,default=0)
    recovery_cents=Column(BigInteger,default=0)
    settlement_fingerprint=Column(String(64),nullable=True)
    published_at=Column(String(40),nullable=True)
    created=Column(String(40))
    updated=Column(String(40))


class ShareRun(Base):
    """合同分成计算任务。pending→running→published；失败可续跑，过期结果不得覆盖。"""
    __tablename__='share_runs'
    __table_args__ = (
        Index('ix_share_runs_contract', 'contract_id', 'state'),
    )
    id=Column(Integer,primary_key=True)
    contract_id=Column(Integer,ForeignKey('contracts.id'),nullable=False)
    state=Column(String(20),default='pending')
    snapshot=Column(JSON,nullable=True)
    result=Column(JSON,nullable=True)
    error=Column(Text,default='')
    attempts=Column(Integer,default=0)
    contract_version=Column(Integer)
    settlement_fingerprint=Column(String(64))
    retry_of=Column(Integer,nullable=True)
    created_by=Column(String(100))
    created=Column(String(40))
    started=Column(String(40),nullable=True)
    finished=Column(String(40),nullable=True)
    published=Column(String(40),nullable=True)


class PaymentReceipt(Base):
    __table_args__ = (
        Index('ix_receipts_contract', 'contract_id', 'status'),
    )
    """付款回执：编号全局唯一；同号同额重试幂等，同号异额拒绝。"""
    __tablename__='payment_receipts'
    id=Column(Integer,primary_key=True)
    contract_id=Column(Integer,ForeignKey('contracts.id'),nullable=False)
    receipt_no=Column(String(100),unique=True,nullable=False)
    amount_cents=Column(BigInteger,nullable=False)
    paid_day=Column(String(10),nullable=False)
    note=Column(Text,default='')
    status=Column(String(20),default='confirmed')
    run_id=Column(Integer,nullable=True)
    payable_before_cents=Column(BigInteger,default=0)
    payable_after_cents=Column(BigInteger,default=0)
    created_by=Column(String(100))
    created=Column(String(40))

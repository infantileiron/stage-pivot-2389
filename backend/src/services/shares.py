"""演出合同分成、预付款抵扣与付款回执。

核心口径：
- 每场分成 = 该场净结算 × 合同比例，逐场向下取整到分；
- 比例总计的累计尾差全部留在末场，保证 Σ逐场分成 = floor(Σ净结算×比例)；
- 先抵扣合同预付款，再形成应付；已确认回执永久保留；
- 重算发布在单事务内原子切换应付与已抵扣预付款；
- 计算提交时冻结场次快照与指纹，发布时若合同版本或场次指纹已变化则判定过期并拒绝覆盖。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException

from src.models.entities import Contract, PaymentReceipt, Settlement, ShareRun
from src.services.business import dump

BPS = 10_000
RUN_OPEN_STATES = ('pending', 'running')
RECEIPT_CONFIRMED = 'confirmed'


def now():
    return datetime.now(timezone.utc).isoformat()


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def settlement_row(r: Settlement):
    gross = _int(r.gross_cents)
    refund = _int(r.refund_cents)
    fee = _int(r.fee_cents)
    return {
        'id': r.id,
        'code': r.code,
        'day': r.day,
        'venue': r.venue,
        'play': r.play,
        'gross_cents': gross,
        'refund_cents': refund,
        'fee_cents': fee,
        'seats': _int(r.seats),
        'checked': _int(r.checked),
        'net_cents': gross - refund - fee,
    }


def covered(contract: Contract, row) -> bool:
    """场次是否落入合同范围：演出、场馆（空=全部）与业务日期都匹配。"""
    if row.get('play') != contract.play:
        return False
    venue = contract.venue or ''
    if venue and row.get('venue') != venue:
        return False
    day = row.get('day') or ''
    return (contract.start_day or '') <= day <= (contract.end_day or '')


def contract_rows(s, contract: Contract):
    q = s.query(Settlement).filter(Settlement.play == contract.play)
    if contract.venue:
        q = q.filter(Settlement.venue == contract.venue)
    q = q.filter(Settlement.day >= contract.start_day, Settlement.day <= contract.end_day)
    return q.order_by(Settlement.day, Settlement.id).all()


def fingerprint(rows) -> str:
    payload = [
        {
            'id': r['id'],
            'code': r['code'],
            'day': r['day'],
            'venue': r['venue'],
            'play': r['play'],
            'gross_cents': r['gross_cents'],
            'refund_cents': r['refund_cents'],
            'fee_cents': r['fee_cents'],
            'seats': r['seats'],
            'checked': r['checked'],
        }
        for r in rows
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    ).hexdigest()


def contract_ended(contract: Contract) -> bool:
    """合同结束以显式状态为准，避免仅因日期经过而把在履约合同判成追偿。"""
    return contract.status == 'ended'


def calculate(snapshot: dict) -> dict:
    """纯函数：按冻结快照逐场计算分成，尾差留在末场。"""
    rows = list(snapshot.get('settlements') or [])
    ratio = _int(snapshot.get('ratio_bp'))
    total_net = sum(_int(r.get('net_cents')) for r in rows)
    target = total_net * ratio // BPS
    allocations = []
    allocated = 0
    for index, row in enumerate(rows):
        net = _int(row.get('net_cents'))
        base = net * ratio // BPS
        allocated += base
        allocations.append({
            'sequence': index + 1,
            'settlement_id': row.get('id'),
            'code': row.get('code'),
            'day': row.get('day'),
            'venue': row.get('venue'),
            'play': row.get('play'),
            'net_cents': net,
            'ratio_bp': ratio,
            'base_share_cents': base,
            'residual_cents': 0,
            'share_cents': base,
        })
    residual = target - allocated
    if allocations:
        last = allocations[-1]
        last['residual_cents'] = residual
        last['share_cents'] = last['base_share_cents'] + residual
    return {
        'ratio_bp': ratio,
        'session_count': len(allocations),
        'total_net_cents': total_net,
        'earned_cents': target,
        'residual_cents': residual,
        'allocations': allocations,
        'fingerprint': snapshot.get('fingerprint'),
        'calculated_at': now(),
    }


def ledger(contract: Contract, earned_cents: int, paid_cents: int) -> dict:
    """预付款抵扣 → 应付；多付转为后续抵扣；合同结束后未收回款单列追偿。"""
    advance = max(_int(contract.advance_cents), 0)
    earned = max(_int(earned_cents), 0)
    paid = max(_int(paid_cents), 0)
    advance_applied = min(advance, earned)
    gross_payable = earned - advance_applied
    payable = max(gross_payable - paid, 0)
    overpaid = max(paid - gross_payable, 0)
    unrecovered_advance = advance - advance_applied
    ended = contract_ended(contract)
    if ended:
        credit = 0
        recovery = unrecovered_advance + overpaid
    else:
        credit = overpaid
        recovery = 0
    return {
        'advance_cents': advance,
        'advance_applied_cents': advance_applied,
        'unrecovered_advance_cents': unrecovered_advance,
        'earned_cents': earned,
        'gross_payable_cents': gross_payable,
        'paid_cents': paid,
        'payable_cents': payable,
        'credit_cents': credit,
        'recovery_cents': recovery,
        'contract_ended': ended,
    }


def confirmed_receipts(s, contract_id: int):
    return (
        s.query(PaymentReceipt)
        .filter(PaymentReceipt.contract_id == contract_id,
                PaymentReceipt.status == RECEIPT_CONFIRMED)
        .order_by(PaymentReceipt.id)
        .all()
    )


def snapshot_for(s, contract: Contract) -> dict:
    rows = [settlement_row(r) for r in contract_rows(s, contract)]
    return {
        'contract_id': contract.id,
        'contract_code': contract.code,
        'name': contract.name,
        'producer': contract.producer,
        'play': contract.play,
        'venue': contract.venue,
        'start_day': contract.start_day,
        'end_day': contract.end_day,
        'ratio_bp': _int(contract.ratio_bp),
        'advance_cents': _int(contract.advance_cents),
        'contract_version': _int(contract.version),
        'fingerprint': fingerprint(rows),
        'settlements': rows,
        'frozen_at': now(),
    }


def _release_open_slot(s, contract_id: int) -> None:
    s.query(Contract).filter(Contract.id == contract_id).update(
        {Contract.open_run: 0}, synchronize_session=False
    )


def reconcile_open_slots(s) -> int:
    """清理守护位：没有未完成任务却仍被占用的合同（进程中断遗留）。"""
    stuck = [
        c.id
        for c in s.query(Contract).filter(Contract.open_run == 1).all()
        if not s.query(ShareRun).filter(
            ShareRun.contract_id == c.id, ShareRun.state.in_(RUN_OPEN_STATES)
        ).first()
    ]
    for cid in stuck:
        s.query(Contract).filter(Contract.id == cid).update(
            {Contract.open_run: 0}, synchronize_session=False
        )
    s.commit()
    return len(stuck)


def _claim_open_slot(s, contract_id: int) -> bool:
    """条件更新抢占“未完成任务”位，与任务插入同事务提交。

    MySQL 下行锁串行化并发提交；SQLite 下写事务整体串行。抢不到即为已有任务进行中。
    """
    won = (
        s.query(Contract)
        .filter(Contract.id == contract_id, Contract.open_run == 0)
        .update({Contract.open_run: 1}, synchronize_session=False)
    )
    return bool(won)


def create_run(s, contract: Contract, actor: str) -> ShareRun:
    contract_id = contract.id
    if not _claim_open_slot(s, contract_id):
        s.rollback()
        raise HTTPException(409, '该合同已有计算任务进行中，请稍后刷新')
    try:
        contract = s.get(Contract, contract_id)
        s.refresh(contract)
        snap = snapshot_for(s, contract)
        run = ShareRun(
            contract_id=contract.id,
            state='pending',
            snapshot=snap,
            error='',
            attempts=0,
            contract_version=_int(contract.version),
            settlement_fingerprint=snap['fingerprint'],
            created_by=actor,
            created=now(),
        )
        contract.updated = now()
        s.add(run)
        s.commit()
    except Exception:
        s.rollback()
        raise
    return run


def create_retry(s, run_id: int, actor: str) -> tuple[ShareRun, ShareRun]:
    """失败任务续跑：沿用原快照新建任务，先抢占守护位防并发重复排队。"""
    old = s.get(ShareRun, run_id)
    if not old:
        raise HTTPException(404, '计算任务不存在')
    if old.state != 'failed':
        raise HTTPException(409, '仅失败任务可以续跑')
    if not _claim_open_slot(s, old.contract_id):
        s.rollback()
        raise HTTPException(409, '该合同已有计算任务进行中，请稍后刷新')
    try:
        run = ShareRun(
            contract_id=old.contract_id,
            state='pending',
            snapshot=old.snapshot,
            error='',
            attempts=0,
            contract_version=old.contract_version,
            settlement_fingerprint=old.settlement_fingerprint,
            retry_of=old.id,
            created_by=actor,
            created=now(),
        )
        s.add(run)
        s.commit()
    except Exception:
        s.rollback()
        raise
    return run, old


def enqueue_run(run: ShareRun, s) -> None:
    """把待算任务放入 Redis；队列不可用时任务保留为失败，可续跑。"""
    import redis

    try:
        redis.Redis.from_url(os.environ['REDIS_URL']).rpush('stage:share_runs', run.id)
    except redis.RedisError as exc:
        run.state = 'failed'
        run.error = '队列暂不可用，请恢复后重试计算'
        run.finished = now()
        _release_open_slot(s, run.contract_id)
        s.commit()
        raise HTTPException(503, run.error) from exc


SHARE_FIELDS = ('day', 'venue', 'play', 'net_cents', 'seats', 'checked')


def share_relevant_changed(before: dict | None, after: dict | None) -> bool:
    """只有影响归属、净额或快照指纹的修订才需要重算合同。"""
    if before is None or after is None:
        return True
    return any(before.get(k) != after.get(k) for k in SHARE_FIELDS)


def mark_affected(s, before: dict | None, after: dict | None):
    """场次新增/修订后，把旧范围与新范围内命中的合同标记为待重算。"""
    probes = [x for x in (before, after) if x]
    if not probes:
        return []
    marked = []
    for contract in s.query(Contract).order_by(Contract.id).with_for_update().all():
        if any(covered(contract, row) for row in probes):
            contract.needs_recalc = 1
            contract.updated = now()
            marked.append(contract.code)
    return marked


def publish(s, run: ShareRun, calc: dict) -> None:
    """在单事务内校验新鲜度并原子切换合同账本。"""
    contract = (
        s.query(Contract)
        .filter(Contract.id == run.contract_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if not contract:
        run.state = 'failed'
        run.error = '合同不存在，计算无法发布'
        run.finished = now()
        s.commit()
        return

    current_fp = fingerprint([settlement_row(r) for r in contract_rows(s, contract)])
    reason = ''
    if _int(contract.version) != _int(run.contract_version):
        reason = '合同条款已变更，本次计算结果过期，请重新计算'
    elif current_fp != run.settlement_fingerprint:
        reason = '场次明细或范围已变更，本次计算结果过期，请重新计算'
    elif contract.current_run_id and _int(run.id) <= _int(contract.current_run_id):
        reason = '已有更新的计算结果发布，本次结果不得覆盖'

    if reason:
        run.state = 'stale'
        run.error = reason
        run.result = {**calc, 'stale': True, 'reason': reason}
        run.finished = now()
        contract.open_run = 0
        s.commit()
        _write_artifact(run)
        return

    receipts = (
        s.query(PaymentReceipt)
        .filter(PaymentReceipt.contract_id == contract.id,
                PaymentReceipt.status == RECEIPT_CONFIRMED)
        .order_by(PaymentReceipt.id)
        .with_for_update()
        .all()
    )
    paid = sum(_int(r.amount_cents) for r in receipts)
    # 条款版本在上方已校验；预付款、合同状态与计算快照一致。
    book = ledger(contract, calc.get('earned_cents', 0), paid)
    published_at = now()
    result = {
        **calc,
        'ledger': book,
        'receipts': [dump(r) for r in receipts],
        'contract_code': contract.code,
        'contract_name': contract.name,
        'published_at': published_at,
        'stale': False,
    }

    contract.current_run_id = run.id
    contract.earned_cents = book['earned_cents']
    contract.published_advance_cents = book['advance_applied_cents']
    contract.paid_cents = book['paid_cents']
    contract.payable_cents = book['payable_cents']
    contract.credit_cents = book['credit_cents']
    contract.recovery_cents = book['recovery_cents']
    contract.settlement_fingerprint = run.settlement_fingerprint
    contract.published_at = published_at
    contract.needs_recalc = 0
    contract.open_run = 0
    contract.updated = published_at

    run.state = 'published'
    run.result = result
    run.error = ''
    run.finished = published_at
    run.published = published_at
    s.commit()
    _write_artifact(run)


def _write_artifact(run: ShareRun) -> None:
    try:
        folder = Path(os.environ.get('ARTIFACTS_DIR', '/artifacts'))
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f'share-run-{run.id}.json').write_text(
            json.dumps(run.result, ensure_ascii=False, indent=2), encoding='utf-8'
        )
    except OSError:
        # 证据仍保存在数据库，文件卷缺失不阻断发布。
        pass


def process_run(run_id: int) -> None:
    """worker 可重入执行：pending→running→published；异常→failed 可续跑。"""
    from src.config.database import Session

    with Session() as s:
        run = s.get(ShareRun, run_id)
        # 只执行 pending：worker 启动时会把中断的 running 任务重置为 pending 再入队。
        # 同一任务若在队列里重复出现，第二次会因状态已变更而跳过。
        if not run or run.state != 'pending':
            return
        contract = s.get(Contract, run.contract_id)
        if not contract:
            run.state = 'failed'
            run.error = '合同不存在'
            run.finished = now()
            s.commit()
            return
        run.state = 'running'
        run.attempts = _int(run.attempts) + 1
        run.started = run.started or now()
        s.commit()
        try:
            calc = calculate(run.snapshot or {})
            publish(s, run, calc)
        except Exception as exc:  # 保留失败原因，允许新建任务续跑
            s.rollback()
            run = s.get(ShareRun, run_id)
            if run and run.state not in ('published', 'stale'):
                run.state = 'failed'
                run.error = str(exc)[:2000]
                run.finished = now()
                _release_open_slot(s, run.contract_id)
                s.commit()


def register_receipt(s, contract: Contract, data, actor: str):
    """登记付款回执。编号唯一：同号同额幂等，同号异额/异合同拒绝。"""
    receipt_no = data.receipt_no
    amount = _int(data.amount_cents)
    existing = s.query(PaymentReceipt).filter(PaymentReceipt.receipt_no == receipt_no).first()
    if existing:
        if existing.contract_id != contract.id or _int(existing.amount_cents) != amount:
            raise HTTPException(409, '回执编号已存在，且金额或合同不一致')
        return dump(existing), False

    # 锁住合同行，避免与发布事务交错读写应付/已付。
    contract = (
        s.query(Contract)
        .filter(Contract.id == contract.id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    if not contract.current_run_id:
        raise HTTPException(409, '合同尚未发布分成结果，无法登记付款')

    payable_before = max(_int(contract.payable_cents), 0)
    if amount > payable_before:
        raise HTTPException(409, f'付款金额超过最新应付余额 {payable_before} 分')

    paid_after = _int(contract.paid_cents) + amount
    book = ledger(contract, contract.earned_cents, paid_after)

    receipt = PaymentReceipt(
        contract_id=contract.id,
        receipt_no=receipt_no,
        amount_cents=amount,
        paid_day=data.paid_day.isoformat(),
        note=data.note or '',
        status=RECEIPT_CONFIRMED,
        run_id=contract.current_run_id,
        payable_before_cents=payable_before,
        payable_after_cents=book['payable_cents'],
        created_by=actor,
        created=now(),
    )
    s.add(receipt)
    contract.paid_cents = book['paid_cents']
    contract.payable_cents = book['payable_cents']
    contract.credit_cents = book['credit_cents']
    contract.recovery_cents = book['recovery_cents']
    contract.updated = now()
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        existing = s.query(PaymentReceipt).filter(PaymentReceipt.receipt_no == receipt_no).first()
        if existing and existing.contract_id == contract.id and _int(existing.amount_cents) == amount:
            return dump(existing), False
        raise HTTPException(409, '回执编号已存在，且金额或合同不一致')
    return dump(receipt), True


def contract_overlap(s, data, exclude_id=None):
    """同一演出、同场馆范围、日期相交的合同会让场次重复归属，必须拒绝。"""
    for other in s.query(Contract).all():
        if exclude_id and other.id == exclude_id:
            continue
        if other.play != data['play']:
            continue
        venue_overlap = not other.venue or not data.get('venue') or other.venue == data.get('venue')
        date_overlap = data['start_day'] <= other.end_day and other.start_day <= data['end_day']
        if venue_overlap and date_overlap:
            raise HTTPException(422, f'合同场次范围与 {other.code} 重叠，请先调整覆盖范围')

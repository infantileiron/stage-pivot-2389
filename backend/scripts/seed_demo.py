import random
from datetime import date, timedelta
from src.config.database import Base, engine, Session
from src.models.entities import User, Settlement, Contract
from src.services import shares
from src.utils.security import hash_password
from src.constants.enums import VENUES, CHANNELS


DEMO_CONTRACTS = [
    dict(code='HT-YM-A', name='秋季巡演分成合同', producer='渡口制作社', play='渡口来信',
         venue='', start_day='2026-09-01', end_day='2026-11-15', ratio_bp=2800, advance_cents=3000000),
    dict(code='HT-YM-B', name='大剧场驻演分成合同', producer='星河演艺', play='星河漫游',
         venue='云幕大剧场', start_day='2026-09-01', end_day='2026-11-15', ratio_bp=3200, advance_cents=1200000),
    dict(code='HT-YM-C', name='小剧场联合制作合同', producer='一间书房工作室', play='一间书房',
         venue='河畔小剧场', start_day='2026-09-01', end_day='2026-11-15', ratio_bp=2500, advance_cents=500000),
]


def seed():
    Base.metadata.create_all(engine)
    rng = random.Random(3112)
    with Session() as s:
        for role in ('admin', 'analyst', 'viewer'):
            email = role + '@demo.local'
            if not s.query(User).filter_by(email=email).first():
                s.add(User(email=email, role=role, password=hash_password('Demo123!')))
        for i in range(180):
            code = f'YM-{i + 1:03}'
            seats = [800, 240, 120][i % 3]
            checked = rng.randint(seats // 2, seats)
            gross = checked * rng.choice([8000, 12000, 18000])
            refund = rng.randint(0, checked // 10) * 8000
            fee = int((gross - refund) * [0, .07, .03][i % 3])
            if not s.query(Settlement).filter_by(code=code).first():
                s.add(Settlement(code=code, day=(date(2026, 9, 1) + timedelta(days=i // 3)).isoformat(),
                                 venue=VENUES[i % 3], play=['渡口来信', '星河漫游', '一间书房', '冬日序曲'][i % 4],
                                 channel=CHANNELS[(i // 3) % 3], gross_cents=gross, refund_cents=refund,
                                 fee_cents=fee, seats=seats, checked=checked))
        s.commit()
        for item in DEMO_CONTRACTS:
            if s.query(Contract).filter_by(code=item['code']).first():
                continue
            c = Contract(**item, status='active', version=1, needs_recalc=1,
                         created=shares.now(), updated=shares.now())
            s.add(c)
            s.commit()
            run = shares.create_run(s, c, 'seed@demo.local')
            shares.process_run(run.id)
        print({'users': s.query(User).count(), 'settlements': s.query(Settlement).count(),
               'contracts': s.query(Contract).count()})


if __name__ == '__main__':
    seed()

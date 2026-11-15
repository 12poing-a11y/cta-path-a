import json,collections,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
snap=json.loads((ROOT/"archive/snapshots/bt_input_20261113_d246813d911a.json").read_text())
f=json.loads((ROOT/"historical_backtest_latest.json").read_text())
bars=snap['bars']
idx={c:{b['date']:i for i,b in enumerate(h)} for c,h in bars.items()}
gap_days=0;roll_mix=0;affected=set();lost=[]
for k,t in enumerate(f['closed_pnls']):
    if t.get('fill_price_basis')!='contract': continue
    c=t['code'];h=bars[c];i0=idx[c][t['entry_date']];i1=idx[c][t['date']]
    for i in range(i0,i1+1):
        b=h[i]
        if b.get('contract_close') is None: gap_days+=1;affected.add(k)
        elif b.get('contract')!=t.get('fill_contract'): roll_mix+=1;affected.add(k)
print('contract trades',sum(1 for t in f['closed_pnls'] if t.get('fill_price_basis')=='contract'),'gap bar-days',gap_days,'roll-mix bar-days',roll_mix,'trades affected',len(affected))
for k in sorted(affected):
    t=f['closed_pnls'][k]; c=t['code'];h=bars[c]
    seg=h[idx[c][t['entry_date']]:idx[c][t['date']]+1]
    print(' ',t['code'],t['direction'],t['entry_date'],'->',t['date'],t['reason'],t['R'],t['fill_contract'],[ (b['date'][5:],b.get('contract'),b.get('contract_close') is not None, b.get('basis_rel')) for b in seg][:8])
# hold length / same-day
print('same-day', f['same_day_exit_n'],'/',f['closed_trades'])
# lookahead: member dates vs bars
alld=sorted({b['date'] for h in bars.values() for b in h})
last=alld[-1]
fut=[(c,d) for c,m in snap['member'].items() for d in m if d>last]
print('last bar',last,'member future-dated keys',len(fut), fut[:5])
# check member lag: value at d equals raw at prior date? need raw seats files
md=sorted({d for m in snap['member'].values() for d in m}); print('member date range',md[0],md[-1],len(md))
# DCE seat coverage
dce=['M','Y','P','C','CS','JD','EG','EB','V','L','PP','I','J','JM','LH','A','B','PG']
for c in dce:
    if c in snap['member']: print(' seats',c,len(snap['member'][c]),end=';')
print()
for c in snap['member']: 
    pass
print({c:len(m) for c,m in snap['member'].items()})

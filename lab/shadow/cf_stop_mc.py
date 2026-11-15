import json,re,random,statistics
from pathlib import Path
t=Path(__file__).with_name("cf2701_sina_daily_20261115.txt").read_text()
rows=json.loads(t[t.index('(')+1:t.rindex(')')])
b=[{k:float(r[k]) for k in 'ohlcs'}|{'d':r['d'],'v':float(r['v'])} for r in rows]
b=[x for x in b if x['v']>0]
last=b[-1]; print('bars',len(b),b[0]['d'],'->',last['d'],'last close',last['c'],'settle',last['s'])
def atr(n=14):
    tr=[max(x['h']-x['l'],abs(x['h']-p['c']),abs(x['l']-p['c'])) for p,x in zip(b[-n-1:-1],b[-n:])]
    return sum(tr)/n
A14=atr(); print('ATR14',round(A14,1))
S0=last['c']
for lv in (15300,15200): print(lv,'dist',S0-lv,'=',round((S0-lv)/A14,2),'ATR')
res={}
for win in (60,120):
    hist=b[-win-1:]
    pairs=[(x['c']/p['c'],x['l']/p['c'],x['v']) for p,x in zip(hist[:-1],hist[1:])]
    random.seed(7); N=20000; mins=[]; hit={15300:0,15200:0}; closes=[]
    for _ in range(N):
        px=S0; mn=1e9
        for _ in range(5):
            r,l,_v=random.choice(pairs); mn=min(mn,px*l); px*=r
        mins.append(mn); closes.append(px)
        for lv in hit:
            if mn<=lv: hit[lv]+=1
    mins.sort(); closes.sort()
    res[win]={"p10_low":round(mins[N//10]),"p5_low":round(mins[N//20]),"p50_low":round(mins[N//2]),"touch15300":round(hit[15300]/N,3),"touch15200":round(hit[15200]/N,3),"close5d_p10":round(closes[N//10]),"close5d_p90":round(closes[9*N//10])}
    print('bootstrap win',win,res[win])
# 5-day historical actual drawdown from close (empirical)
dd=[min(x['l'] for x in b[i+1:i+6])/b[i]['c']-1 for i in range(len(b)-130,len(b)-5)]
dd.sort(); print('empirical 5d min-low/close p10',round(dd[len(dd)//10]*100,2),'% ->',round(S0*(1+dd[len(dd)//10])))
# ATR band
print('S0-1ATR',round(S0-A14),'S0-1.5ATR',round(S0-1.5*A14),'S0-2ATR',round(S0-2*A14))
vol=[x['v'] for x in b[-20:]]; print('vol20 mean',round(statistics.mean(vol)),'last',last['v'])
Path(__file__).with_name("cf_stop_mc_result.json").write_text(json.dumps({"S0":S0,"date":last['d'],"ATR14":A14,"bootstrap":res,"emp_p10_5d":dd[len(dd)//10]},ensure_ascii=False,indent=1))
# drift-neutral variant: remove mean log return
import math
out2={}
for win in (60,120):
    hist=b[-win-1:]
    pairs=[(x['c']/p['c'],x['l']/p['c']) for p,x in zip(hist[:-1],hist[1:])]
    mu=statistics.mean(math.log(r) for r,_ in pairs)
    pairs=[(r/math.exp(mu),l/math.exp(mu)) for r,l in pairs]
    random.seed(11); N=20000; mins=[]; h3=h2=0
    for _ in range(N):
        px=S0; mn=1e9
        for _ in range(5):
            r,l=random.choice(pairs); mn=min(mn,px*l); px*=r
        mins.append(mn); h3+=mn<=15300; h2+=mn<=15200
    mins.sort(); out2[win]={"daily_mu_pct":round(mu*100,3),"p10_low":round(mins[N//10]),"touch15300":round(h3/N,3),"touch15200":round(h2/N,3)}
    print('drift-neutral',win,out2[win])
d=json.loads(Path(__file__).with_name("cf_stop_mc_result.json").read_text()); d["drift_neutral"]=out2
Path(__file__).with_name("cf_stop_mc_result.json").write_text(json.dumps(d,ensure_ascii=False,indent=1))

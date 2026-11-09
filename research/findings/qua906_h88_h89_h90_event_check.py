import yfinance as yf, pandas as pd, numpy as np
t=["SPY","QQQ","IWM","DIA","XLF","XLK","XLE","XLV","MDY"]
d=yf.download(t,start="2000-01-01",end="2025-01-01",auto_adjust=True,progress=False,group_by="ticker")
def stats(r):
    r=pd.Series(r).dropna(); return len(r), round(r.mean()*1e4,1), round(r.mean()/r.std()*np.sqrt(len(r)),2) if len(r)>2 else None
# H88
tr88=[];tr90=[]
for s in ["SPY","QQQ","IWM","DIA","XLF","XLK","XLE","XLV"]:
    x=d[s].dropna(); pl=x.Low.shift(); pc=x.Close.shift()
    tr=pd.concat([x.High-x.Low,(x.High-pc).abs(),(x.Low-pc).abs()],axis=1).max(axis=1); atr=tr.rolling(14).mean().shift()
    sma=x.Close.rolling(200).mean().shift()
    sig=(x.Open<pl-0.25*atr)&(x.Close>pl)&(pc>sma)
    ret=(x.Close.shift(-1)/x.Close-1)[sig]
    tr88.append(ret)
all88=pd.concat(tr88).sort_index(); print("H88 events",len(all88),"per-yr/ETF",round(len(all88)/8/25,1),"IS2000-19",len(all88[:"2019"]),"next-day mean bp",round(all88.mean()*1e4,1),"t",round(all88.mean()/all88.std()*np.sqrt(len(all88)),2))
# H90
for s in ["SPY","QQQ","IWM","DIA","MDY","XLF"]:
    x=d[s].dropna(); c=x.Close
    mon=x.index.dayofweek==0
    sig=mon&(c/c.shift(1)-1<=-0.005)&(c<c.rolling(5).mean())&(c>c.rolling(200).mean())
    tr90.append((c.shift(-1)/c-1)[sig])
a=pd.concat(tr90).sort_index(); print("H90 events",len(a),"IS<=2019",len(a[:"2019"]),"mean bp",round(a.mean()*1e4,1),"t",round(a.mean()/a.std()*np.sqrt(len(a)),2))
spyd=a.groupby(level=0).mean(); print("H90 distinct dates",len(spyd),"per yr",round(len(spyd)/25,1),"date-level mean bp",round(spyd.mean()*1e4,1),"t",round(spyd.mean()/spyd.std()*np.sqrt(len(spyd)),2))
d88=all88.groupby(level=0).mean(); print("H88 distinct dates",len(d88),"date-level t",round(d88.mean()/d88.std()*np.sqrt(len(d88)),2))
# H89 SPY
c=d["SPY"].Close.dropna(); r=c.pct_change()
inw=pd.Series(False,index=c.index)
for y in range(2000,2025):
    for m1,m2 in [(2,3),(5,6),(8,9),(11,12)]:
        a_=pd.Timestamp(y,m1,5); b_=pd.Timestamp(y,m2,15)
        inw[(c.index>=a_)&(c.index<=b_)]=True
sm=c.rolling(200).mean().shift()>0
f=(c.shift()>c.rolling(200).mean().shift())
print("H89 SPY ann ret in-window %",round(r[inw].mean()*252*100,1),"out-window",round(r[~inw].mean()*252*100,1),"windows",25*4,"in-window Sharpe",round(r[inw].mean()/r[inw].std()*np.sqrt(252),2),"out",round(r[~inw].mean()/r[~inw].std()*np.sqrt(252),2))

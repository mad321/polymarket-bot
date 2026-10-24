import json, math, collections, sys, os
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import os; os.environ["ENABLE_MONITOR"]="0"; os.environ["JOURNAL"]="0"
import strict_strategy as st
R=json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "market.json")))
lgs=sorted({r["league"] for r in R})
def feats(r):
    p=min(max(r["price"],.01),.99)
    return [1.0, math.log(p/(1-p)), r["side"]=="home", st.is_elite(r["team"]), math.log1p(r["volume"])/10] + [r["league"]==l for l in lgs[1:]]
def fit(X,y,l2=1.0):
    w=np.zeros(X.shape[1])
    for _ in range(50):
        p=1/(1+np.exp(-X@w)); g=X.T@(p-y)+l2*w; H=(X.T*(p*(1-p)))@X+l2*np.eye(len(w)); w-=np.linalg.solve(H,g)
    return w
def ll(X,y,w):
    p=np.clip(1/(1+np.exp(-X@w)),1e-6,1-1e-6); return float(np.mean(y*np.log(p)+(1-y)*np.log(1-p)))
R.sort(key=lambda r:r["start"]); cut=int(len(R)*0.7)
tr,te=R[:cut],R[cut:]
X=np.array([feats(r) for r in tr],float); y=np.array([r["won"] for r in tr]); Xt=np.array([feats(r) for r in te],float); yt=np.array([r["won"] for r in te])
w=fit(X,y)
pm=np.clip(np.array([r["price"] for r in te]),1e-6,1-1e-6)
print("train", len(tr), "test", len(te), "test period from", te[0]["start"][:10])
print("log-loss market price :", round(float(np.mean(yt*np.log(pm)+(1-yt)*np.log(1-pm))),4))
print("log-loss model        :", round(ll(Xt,yt,w),4))
print("brier market / model  :", round(float(np.mean((pm-yt)**2)),4), round(float(np.mean((1/(1+np.exp(-Xt@w))-yt)**2)),4))
names=["const","logit(price)","home","elite","log volume"]+["lg_"+l for l in lgs[1:]]
for n,v in zip(names,w): print(f"  {n:14} {v:+.3f}")
# pick-of-the-day rules on the 3.x range
def roi(r):
    p=r["price"]; return r["won"]/(p+r["fee"]*p*(1-p))-1
S=[r for r in R if .55<=r["price"]<=.72 and st.is_elite(r["team"]) and r["volume"]>=15000]
byday=collections.defaultdict(list)
for r in S: byday[r["start"][:10]].append(r)
rules={"max volume":lambda v:max(v,key=lambda r:r["volume"]),"lowest price":lambda v:min(v,key=lambda r:r["price"]),
       "highest price":lambda v:max(v,key=lambda r:r["price"]),"home first, max vol":lambda v:max(v,key=lambda r:(r["side"]=="home",r["volume"])),
       "model edge (test only)":None}
for name,f in rules.items():
    if f is None:
        days=collections.defaultdict(list)
        for r in te:
            if .55<=r["price"]<=.72 and st.is_elite(r["team"]) and r["volume"]>=15000: days[r["start"][:10]].append(r)
        picks=[]
        for v in days.values():
            sc=[(1/(1+math.exp(-float(np.array(feats(r))@w)))-r["price"],r) for r in v]
            picks.append(max(sc,key=lambda x:x[0])[1])
    else: picks=[f(v) for v in byday.values()]
    rs=[roi(r) for r in picks]; m=sum(rs)/len(rs); sd=math.sqrt(sum((x-m)**2 for x in rs)/(len(rs)-1))
    print(f"pick: {name:24} n={len(picks):3} won {sum(r['won'] for r in picks)/len(picks)*100:5.1f}% price {sum(r['price'] for r in picks)/len(picks)*100:5.1f}% ROI {m*100:+6.1f}% ±{1.96*sd/math.sqrt(len(rs))*100:.1f}")

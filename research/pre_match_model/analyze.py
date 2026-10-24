import json, math, sys, collections, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import os; os.environ["ENABLE_MONITOR"]="0"; os.environ["JOURNAL"]="0"
import strict_strategy as st
R=json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "market.json")))
for r in R: r["elite"]=st.is_elite(r["team"]); r["home"]=r["side"]=="home"
def roi(r):  # per $1 staked, buying at price with the taker fee, held to the end
    p=r["price"]; cost=p+r["fee"]*p*(1-p); return r["won"]/cost-1
def line(xs,label):
    n=len(xs)
    if n==0: return
    exp=sum(x["price"] for x in xs); act=sum(x["won"] for x in xs)
    se=math.sqrt(sum(x["price"]*(1-x["price"]) for x in xs)); z=(act-exp)/se
    rs=[roi(x) for x in xs]; m=sum(rs)/n; sd=math.sqrt(sum((v-m)**2 for v in rs)/max(1,n-1))
    print(f"{label:34} n={n:4}  price {exp/n*100:5.1f}%  won {act/n*100:5.1f}%  z={z:+5.2f}  ROI {m*100:+6.1f}% ±{1.96*sd/math.sqrt(n)*100:4.1f}")
print("== calibration, all teams 15-60 min before kickoff")
for lo,hi in [(0,.2),(.2,.35),(.35,.5),(.5,.55),(.55,.62),(.62,.72),(.72,.85),(.85,1)]:
    line([r for r in R if lo<=r["price"]<hi], f"price {lo:.2f}-{hi:.2f}")
B=[r for r in R if .55<=r["price"]<=.72]
print("== the 3.x range 55-72c")
line(B,"all")
line([r for r in B if r["home"]],"home"); line([r for r in B if not r["home"]],"away")
line([r for r in B if r["elite"]],"elite list"); line([r for r in B if not r["elite"]],"not elite")
line([r for r in B if r["volume"]>=15000],"volume >= 15k"); line([r for r in B if r["volume"]<15000],"volume < 15k")
for lg in sorted({r["league"] for r in B}): line([r for r in B if r["league"]==lg], "league "+lg)
S=[r for r in B if r["elite"] and r["volume"]>=15000]
line(S,"3.0 rule (elite, 15k+)")
line([r for r in S if r["home"]],"3.0 rule, home only")
# 3.1: one pick a day, highest volume
byday=collections.defaultdict(list)
for r in S: byday[r["start"][:10]].append(r)
line([max(v,key=lambda r:r["volume"]) for v in byday.values()],"3.1 pick of the day (max volume)")

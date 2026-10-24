# Market-wide dataset: every finished match of the watched leagues, each team's
# Yes price 15-60 min before kickoff (CLOB price history) and whether it won.
import sys, os, json, time, datetime as dt, concurrent.futures as cf
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.environ["ENABLE_MONITOR"]="0"; os.environ["JOURNAL"]="0"
import requests, match_strategy as ms
G="https://gamma-api.polymarket.com"; C="https://clob.polymarket.com"
S=requests.Session()
since=sys.argv[1] if len(sys.argv)>1 else "2025-08-01"
games=[]
for code,(sid,_) in ms.LEAGUES.items():
    off=0
    while True:
        r=S.get(f"{G}/events", params={"series_id":sid,"closed":"true","limit":100,"offset":off,
                 "end_date_min":since+"T00:00:00Z"}, timeout=30); r.raise_for_status(); ev=r.json()
        for e in ev:
            g=ms.parse_game(e, code)
            if not g: continue
            outs={}
            for m in e["markets"]:
                if m.get("sportsMarketType")!="moneyline": continue
                try:
                    toks=json.loads(m["clobTokenIds"]); pr=[float(x) for x in json.loads(m["outcomePrices"])]
                except Exception: continue
                outs[str(toks[0])]=pr[0]
            g["outcome"]={s["token_id"]:outs.get(s["token_id"]) for s in g["sides"].values()}
            g["draw"]=[v for k,v in outs.items() if k not in g["outcome"]]
            games.append(g)
        if len(ev)<100: break
        off+=100
    print(code, len(games), flush=True)
def hist(token, start):
    t=int(start.timestamp())
    for _ in range(3):
        try:
            r=S.get(f"{C}/prices-history", params={"market":token,"startTs":t-3*3600,"endTs":t,"fidelity":5}, timeout=30)
            if r.status_code==429: time.sleep(2); continue
            r.raise_for_status(); return r.json().get("history") or []
        except Exception: time.sleep(1)
    return None
jobs=[(g,side,s) for g in games for side,s in g["sides"].items()]
def run(j):
    g,side,s=j; h=hist(s["token_id"], g["start"])
    return (g["slug"],side,h)
res={}
with cf.ThreadPoolExecutor(12) as ex:
    for i,(slug,side,h) in enumerate(ex.map(run, jobs)):
        res[(slug,side)]=h
        if i%500==0: print("hist", i, len(jobs), flush=True)
rows=[]
for g in games:
    for side,s in g["sides"].items():
        h=res.get((g["slug"],side)) or []
        t0=g["start"].timestamp()
        pts=[(p["t"],p["p"]) for p in h if t0-3600<=p["t"]<=t0-15*60]
        y=g["outcome"].get(s["token_id"])
        if not pts or y not in (0.0,1.0): continue
        price=pts[-1][1]
        rows.append({"slug":g["slug"],"league":g["league"],"team":s["team"],"side":side,"price":price,
                     "won":y,"volume":g["volume"],"start":g["start"].isoformat(),"fee":s["fee_rate"]})
json.dump(rows, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "market.json"),"w"))
print("games", len(games), "rows", len(rows))

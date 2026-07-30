# -*- coding: utf-8 -*-
"""
SOX 공포·탐욕 지수 데이터 갱신 스크립트 (GitHub Actions에서 매일 실행)
- Yahoo Finance에서 SOX 구성종목·보조 시세를 받아 7개 지표를 계산하고
  template.html에 데이터를 주입해 index.html을 생성한다.
- 산출 방식: 각 지표를 최근 252거래일 분포 대비 백분위(0~100)로 점수화 후 동일가중 평균.
"""
import json, sys, time
import numpy as np
import pandas as pd
import requests
import yfinance as yf

# SOX 구성종목 (변경 시 이 목록만 수정: https://www.nasdaq.com/docs/SOX 참고)
CONSTITUENTS = ["AMD","ADI","AMAT","ARM","ASML","ALAB","AVGO","COHR","CRDO","ENTG",
                "GFS","INTC","KLAC","LRCX","MTSI","MRVL","MCHP","MU","MPWR","NVMI",
                "NVDA","NXPI","ON","QRVO","QCOM","RMBS","SWKS","TSM","TER","TXN"]
AUX = ["^SOX","^VXN","IEF","SOXL","SOXS","USD"]

def fetch(tickers, tries=3):
    for a in range(tries):
        try:
            px = yf.download(tickers, period="12y", auto_adjust=False, progress=False, threads=True)
            if px["Adj Close"].dropna(how="all").shape[0] > 500:
                return px
        except Exception as e:
            print("fetch retry", a+1, e, file=sys.stderr)
        time.sleep(20)
    raise SystemExit("Yahoo fetch failed")

px = fetch(CONSTITUENTS + AUX)
adj, rawc, vol = px["Adj Close"], px["Close"], px["Volume"]

sox = adj["^SOX"].dropna()
idx = sox.index
cons_adj = adj[CONSTITUENTS].reindex(idx)
cons_vol = vol[CONSTITUENTS].reindex(idx)

# 52주 신고가/신저가 (±0.1% 허용), 상장 126일 미만 종목 제외
valid = cons_adj.notna().cumsum() >= 126
roll_max = cons_adj.rolling(252, min_periods=1).max()
roll_min = cons_adj.rolling(252, min_periods=1).min()
at_hi = (cons_adj >= roll_max * 0.999) & valid
at_lo = (cons_adj <= roll_min * 1.001) & valid
nHi, nLo, nValid = at_hi.sum(axis=1), at_lo.sum(axis=1), valid.sum(axis=1)

# 상승/하락 거래량
chg = cons_adj.diff()
advV = cons_vol.where((chg > 0) & valid).sum(axis=1)
decV = cons_vol.where((chg < 0) & valid).sum(axis=1)

# SOXL/SOXS 달러 거래대금 (원시 종가 × 거래량)
soxlDV = (rawc["SOXL"] * vol["SOXL"]).reindex(idx)
soxsDV = (rawc["SOXS"] * vol["SOXS"]).reindex(idx)
vxn = adj["^VXN"].reindex(idx).ffill()
ief = adj["IEF"].reindex(idx).ffill()

# FRED 하이일드 스프레드 (무료 CSV는 최근 3년만 제공)
r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2", timeout=30)
rows = [l.split(",") for l in r.text.strip().splitlines()[1:]]
oas = pd.Series({pd.to_datetime(d): float(v) for d, v in rows if v not in (".", "")}).sort_index()
oas = oas.reindex(idx, method="ffill")

# ---- 7개 지표 ----
ind = pd.DataFrame(index=idx)
ind["momentum"] = sox / sox.rolling(125).mean() - 1
net_hi = (nHi - nLo) / nValid.replace(0, np.nan)
ind["strength"] = net_hi.rolling(10, min_periods=5).mean()
netfrac = (advV - decV) / (advV + decV).replace(0, np.nan)
ind["breadth"] = netfrac.ewm(span=19, min_periods=10).mean() - netfrac.ewm(span=39, min_periods=20).mean()
ind["levered"] = np.log(soxlDV.replace(0, np.nan) / soxsDV.replace(0, np.nan)).rolling(5, min_periods=3).mean()
ind["vol"] = -(vxn / vxn.rolling(50).mean() - 1)
ind["safehaven"] = sox.pct_change(20) - ief.pct_change(20)
ind["junk"] = -oas.rolling(5, min_periods=1).mean()

# ---- 252일 롤링 백분위 점수 ----
def roll_pct(s, window=252, minp=126):
    def pct(x):
        cur = x[-1]
        arr = x[~np.isnan(x)]
        if len(arr) < minp or np.isnan(cur):
            return np.nan
        return 100.0 * (arr < cur).sum() / (len(arr) - 1 if len(arr) > 1 else 1)
    return s.rolling(window, min_periods=minp).apply(pct, raw=True)

scores = pd.DataFrame(index=ind.index)
for c in ind.columns:
    scores[c] = roll_pct(ind[c], minp=60 if c == "junk" else 126)
scores["composite"] = scores.mean(axis=1, skipna=True).where(scores.notna().sum(axis=1) >= 5)

out = scores.join(sox.rename("sox"))
out = out[out.composite.notna()].round(1)   # 종합지수가 계산되는 전 구간 표시
cur = out.composite.iloc[-1]
assert 0 <= cur <= 100 and len(out) > 1500, "sanity check failed"

# ---- 백테스트 (SOX / USD 2x / SOXL 3x) ----
c = out.composite
px_bt = {"sox": out.sox,
         "usd": adj["USD"].reindex(out.index),
         "soxl": adj["SOXL"].reindex(out.index)}
zones = [("극단적 공포", c < 25), ("공포", (c >= 25) & (c < 45)), ("중립", (c >= 45) & (c < 55)),
         ("탐욕", (c >= 55) & (c < 75)), ("극단적 탐욕", c >= 75), ("전체", c.notna())]
bt = []
for name, mask in zones:
    row = {"zone": name}
    fwd20 = px_bt["sox"].shift(-20) / px_bt["sox"] - 1
    v20 = fwd20[mask].dropna()
    fwd60s = px_bt["sox"].shift(-60) / px_bt["sox"] - 1
    v60s = fwd60s[mask].dropna()
    row["n"] = int(len(v60s))
    row["sox20"] = round(100 * v20.mean(), 1) if len(v20) else None
    row["sox60"] = round(100 * v60s.mean(), 1) if len(v60s) else None
    row["win60"] = round(100 * (v60s > 0).mean(), 0) if len(v60s) else None
    for k in ["usd", "soxl"]:
        fwd = px_bt[k].shift(-60) / px_bt[k] - 1
        v = fwd[mask].dropna()
        row[k + "60"] = round(100 * v.mean(), 1) if len(v) else None
    bt.append(row)

# ---- index.html 생성 ----
data = {"dates": [d.strftime("%Y-%m-%d") for d in out.index],
        "comp": [None if pd.isna(v) else round(v, 1) for v in out.composite],
        "sox": [round(v, 1) for v in out.sox]}
usd_px = adj["USD"].reindex(out.index)
soxl_px = adj["SOXL"].reindex(out.index)
data["usd"] = [None if pd.isna(v) else round(v, 2) for v in usd_px]
data["soxl"] = [None if pd.isna(v) else round(v, 2) for v in soxl_px]
for k in ["momentum","strength","breadth","levered","vol","safehaven","junk"]:
    data[k] = [None if pd.isna(v) else round(v, 1) for v in out[k]]

tpl = open("template.html", encoding="utf-8").read()
html = (tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False))
           .replace("__BT__", json.dumps(bt, ensure_ascii=False))
           .replace("__LASTDATE__", out.index[-1].strftime("%Y.%m.%d")))
open("index.html", "w", encoding="utf-8").write(html)

sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           '  <url><loc>https://kjb-canvas.github.io/sox-fear-greed/</loc>'
           f'<lastmod>{out.index[-1].strftime("%Y-%m-%d")}</lastmod>'
           '<changefreq>daily</changefreq></url>\n</urlset>\n')
open("sitemap.xml", "w", encoding="utf-8").write(sitemap)
print("OK", out.index[-1].date(), "composite:", cur)

# -*- coding: utf-8 -*-
"""
공포·탐욕 지수 시리즈 데이터 갱신 스크립트 (GitHub Actions에서 매일 실행)
- 4개 지수(sox / nasdaq / kospi / kosdaq)를 설정(CONFIGS) 기반으로 계산해
  각 하위 폴더의 index.html과 루트 허브(index.html), sitemap.xml을 생성한다.
- 산출 방식: 각 지표를 최근 252거래일 분포 대비 백분위(0~100)로 점수화 후 동일가중 평균.
- 실행: python update_data.py --markets us|kr|all
"""
import argparse, json, os, sys, time
import numpy as np
import pandas as pd
import requests
import yfinance as yf

BASE_URL = "https://kjb-canvas.github.io/sox-fear-greed"

# SOX 구성종목 (변경 시 수정: https://www.nasdaq.com/docs/SOX)
SOX_CONS = ["AMD","ADI","AMAT","ARM","ASML","ALAB","AVGO","COHR","CRDO","ENTG",
            "GFS","INTC","KLAC","LRCX","MTSI","MRVL","MCHP","MU","MPWR","NVMI",
            "NVDA","NXPI","ON","QRVO","QCOM","RMBS","SWKS","TSM","TER","TXN"]

# 나스닥100 예비 목록 (위키피디아 수집 실패 시 사용, 2026-07 기준)
NDX_FALLBACK = ["ADBE","AMD","ABNB","ALNY","GOOGL","GOOG","AMZN","AEP","AMGN","ADI","AAPL","AMAT",
    "APP","ARM","ASML","ADSK","ADP","AXON","BKR","BKNG","AVGO","CDNS","CHTR","CTAS","CSCO","CCEP",
    "CTSH","CMCSA","CEG","CPRT","CSGP","COST","CRWD","CSX","DDOG","DXCM","FANG","DASH","EA","EXC",
    "FAST","FER","FTNT","GEHC","GILD","HON","IDXX","INSM","INTC","INTU","ISRG","KDP","KLAC","KHC",
    "LRCX","LIN","MAR","MRVL","MELI","META","MCHP","MU","MSFT","MSTR","MDLZ","MPWR","MNST","NFLX",
    "NVDA","NXPI","ORLY","ODFL","PCAR","PLTR","PANW","PAYX","PYPL","PDD","PEP","QCOM","REGN","ROP",
    "ROST","SNDK","STX","SHOP","SBUX","SNPS","TMUS","TTWO","TSLA","TXN","TRI","VRSK","VRTX","WMT",
    "WBD","WDC","WDAY","XEL","ZS"]


def get_ndx_constituents():
    """위키피디아에서 나스닥100 목록 수집, 실패 시 예비 목록."""
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/Nasdaq-100")
        for t in tables:
            cols = [str(c).lower() for c in t.columns]
            if any("ticker" in c or "symbol" in c for c in cols) and len(t) > 80:
                col = t.columns[[i for i, c in enumerate(cols) if "ticker" in c or "symbol" in c][0]]
                syms = [str(s).strip().replace(".", "-") for s in t[col] if str(s).strip()]
                if len(syms) >= 90:
                    return syms[:110]
    except Exception as e:
        print("NDX wiki fail:", e, file=sys.stderr)
    return NDX_FALLBACK


def get_krx_constituents(index_code, suffix, cache_file):
    """pykrx로 KRX 지수 구성종목 수집(KOSPI200=1028, KOSDAQ150=2203). 실패 시 캐시."""
    try:
        from pykrx import stock
        codes = stock.get_index_portfolio_deposit_file(index_code)
        if codes is not None and len(codes) >= 100:
            syms = [c + suffix for c in codes]
            json.dump(syms, open(cache_file, "w"))
            return syms
    except Exception as e:
        print("pykrx fail:", index_code, e, file=sys.stderr)
    if os.path.exists(cache_file):
        return json.load(open(cache_file))
    raise RuntimeError(f"no constituents for {index_code} (pykrx failed, no cache)")


CONFIGS = {
    "sox": dict(
        name="SOX 반도체", h1="필라델피아 반도체지수(SOX) 공포·탐욕 지수",
        index="^SOX", index_label="SOX",
        constituents=lambda: SOX_CONS, n_cons_label="30",
        lev_pair=("SOXL", "SOXS"), lev_label="SOXL(3배 롱)/SOXS(3배 숏)",
        vol_src=("ticker", "^VXN"), vol_label="VXN(나스닥100 변동성지수) vs 50일 이동평균 · SOX 전용 VIX 부재로 대체",
        safe="IEF", safe_label="미국채 ETF(IEF)", junk=True,
        charts=[("^SOX", "SOX 지수", 0), ("USD", "USD — ProShares Ultra Semiconductors 2배", 2),
                ("SOXL", "SOXL — Direxion Semiconductor Bull 3배", 2)],
        title="SOX 공포탐욕지수 — 필라델피아 반도체지수 Fear & Greed Index",
        desc="필라델피아 반도체지수(SOX) 전용 공포탐욕지수. CNN 방법론을 반도체 섹터에 맞게 적용해 7개 심리 지표를 0~100으로 산출. SOXL 등 레버리지 ETF 백테스트 제공, 매일 자동 갱신.",
        keywords="SOX, 공포탐욕지수, 반도체지수, 필라델피아 반도체, SOXL, 반도체 ETF",
    ),
    "nasdaq": dict(
        name="나스닥100", h1="나스닥100 공포·탐욕 지수",
        index="^NDX", index_label="NDX",
        constituents=get_ndx_constituents, n_cons_label="100",
        lev_pair=("TQQQ", "SQQQ"), lev_label="TQQQ(3배 롱)/SQQQ(3배 숏)",
        vol_src=("ticker", "^VXN"), vol_label="VXN(나스닥100 변동성지수) vs 50일 이동평균",
        safe="IEF", safe_label="미국채 ETF(IEF)", junk=True,
        charts=[("^NDX", "나스닥100 지수", 0), ("QLD", "QLD — ProShares Ultra QQQ 2배", 2),
                ("TQQQ", "TQQQ — ProShares UltraPro QQQ 3배", 2)],
        title="나스닥 공포탐욕지수 — 나스닥100 Fear & Greed Index",
        desc="나스닥100 전용 공포탐욕지수. CNN 방법론을 나스닥100에 적용해 7개 심리 지표를 0~100으로 산출. TQQQ 등 레버리지 ETF 백테스트 제공, 매일 자동 갱신.",
        keywords="나스닥 공포탐욕지수, 나스닥100, QQQ, TQQQ, Fear and Greed",
    ),
    "kospi": dict(
        name="코스피", h1="코스피 공포·탐욕 지수",
        index="^KS11", index_label="KOSPI",
        constituents=lambda: get_krx_constituents("1028", ".KS", "kospi/constituents.json"),
        n_cons_label="KOSPI200",
        lev_pair=("122630.KS", "252670.KS"), lev_label="KODEX 레버리지/KODEX 200선물인버스2X",
        vol_src=("realized", None), vol_label="20일 실현변동성 vs 50일 이동평균 · VKOSPI 무료 데이터 부재로 대체",
        safe="148070.KS", safe_label="KOSEF 국고채10년 ETF", junk=False,
        charts=[("^KS11", "코스피 지수", 0), ("122630.KS", "KODEX 레버리지 2배", 0)],
        title="코스피 공포탐욕지수 — KOSPI Fear & Greed Index",
        desc="코스피 전용 공포탐욕지수. CNN 방법론을 KOSPI200 구성종목에 적용해 6개 심리 지표를 0~100으로 산출. KODEX 레버리지 백테스트 제공, 매일 자동 갱신.",
        keywords="코스피 공포탐욕지수, KOSPI, 코스피 투자심리, KODEX 레버리지",
    ),
    "kosdaq": dict(
        name="코스닥", h1="코스닥 공포·탐욕 지수",
        index="^KQ11", index_label="KOSDAQ",
        constituents=lambda: get_krx_constituents("2203", ".KQ", "kosdaq/constituents.json"),
        n_cons_label="KOSDAQ150",
        lev_pair=("233740.KS", "251340.KS"), lev_label="KODEX 코스닥150레버리지/선물인버스",
        vol_src=("realized", None), vol_label="20일 실현변동성 vs 50일 이동평균 · 전용 변동성지수 부재로 대체",
        safe="148070.KS", safe_label="KOSEF 국고채10년 ETF", junk=False,
        charts=[("^KQ11", "코스닥 지수", 0), ("233740.KS", "KODEX 코스닥150레버리지 2배", 0)],
        title="코스닥 공포탐욕지수 — KOSDAQ Fear & Greed Index",
        desc="코스닥 전용 공포탐욕지수. CNN 방법론을 KOSDAQ150 구성종목에 적용해 6개 심리 지표를 0~100으로 산출. 매일 자동 갱신.",
        keywords="코스닥 공포탐욕지수, KOSDAQ, 코스닥 투자심리",
    ),
}

TILE_DEFS = dict(
    momentum=("주가 모멘텀", "지수 vs 125일 이동평균"),
    strength=("주가 강도", "52주 신고가·신저가 비중"),
    breadth=("주가 폭", "상승·하락 거래량 (McClellan)"),
    levered=("레버리지 수급", "레버리지/인버스 거래대금"),
    vol=("변동성", "변동성 vs 50일 평균 (역방향)"),
    safehaven=("안전자산 수요", "지수 - 국채 20일 수익률"),
    junk=("정크본드 수요", "하이일드 스프레드 (역방향)"),
)

ZONES = [(25, "극단적 공포"), (45, "공포"), (55, "중립"), (75, "탐욕"), (101, "극단적 탐욕")]


def zone_of(v):
    for th, name in ZONES:
        if v < th:
            return name
    return ""


def fetch_prices(tickers, tries=3):
    for a in range(tries):
        try:
            px = yf.download(tickers, period="12y", auto_adjust=False, progress=False, threads=True)
            if px["Adj Close"].dropna(how="all").shape[0] > 500:
                return px
        except Exception as e:
            print("fetch retry", a + 1, e, file=sys.stderr)
        time.sleep(20)
    raise RuntimeError("price fetch failed")


def roll_pct(s, window=252, minp=126):
    def pct(x):
        cur = x[-1]
        arr = x[~np.isnan(x)]
        if len(arr) < minp or np.isnan(cur):
            return np.nan
        return 100.0 * (arr < cur).sum() / (len(arr) - 1 if len(arr) > 1 else 1)
    return s.rolling(window, min_periods=minp).apply(pct, raw=True)


def get_oas(idx):
    r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2", timeout=30)
    rows = [l.split(",") for l in r.text.strip().splitlines()[1:]]
    oas = pd.Series({pd.to_datetime(d): float(v) for d, v in rows if v not in (".", "")}).sort_index()
    return oas.reindex(idx, method="ffill")


def build_market(key):
    cfg = CONFIGS[key]
    cons = cfg["constituents"]()
    chart_ticks = [c[0] for c in cfg["charts"]]
    aux = list({cfg["index"], *cfg["lev_pair"], cfg["safe"], *chart_ticks})
    if cfg["vol_src"][0] == "ticker":
        aux.append(cfg["vol_src"][1])
    px = fetch_prices(list(dict.fromkeys(cons + aux)))
    adj, rawc, vol = px["Adj Close"], px["Close"], px["Volume"]

    base = adj[cfg["index"]].dropna()
    idx = base.index
    cons_in = [c for c in cons if c in adj.columns]
    cons_adj = adj[cons_in].reindex(idx)
    cons_vol = vol[cons_in].reindex(idx)

    # 52주 신고가/신저가 (0.1% 허용), 상장 126일 미만 제외
    valid = cons_adj.notna().cumsum() >= 126
    roll_max = cons_adj.rolling(252, min_periods=1).max()
    roll_min = cons_adj.rolling(252, min_periods=1).min()
    at_hi = (cons_adj >= roll_max * 0.999) & valid
    at_lo = (cons_adj <= roll_min * 1.001) & valid
    nHi, nLo, nValid = at_hi.sum(axis=1), at_lo.sum(axis=1), valid.sum(axis=1)

    chg = cons_adj.diff()
    advV = cons_vol.where((chg > 0) & valid).sum(axis=1)
    decV = cons_vol.where((chg < 0) & valid).sum(axis=1)

    levL, levS = cfg["lev_pair"]
    levLDV = (rawc[levL] * vol[levL]).reindex(idx)
    levSDV = (rawc[levS] * vol[levS]).reindex(idx)
    safe = adj[cfg["safe"]].reindex(idx).ffill()

    ind = pd.DataFrame(index=idx)
    ind["momentum"] = base / base.rolling(125).mean() - 1
    net_hi = (nHi - nLo) / nValid.replace(0, np.nan)
    ind["strength"] = net_hi.rolling(10, min_periods=5).mean()
    netfrac = (advV - decV) / (advV + decV).replace(0, np.nan)
    ind["breadth"] = netfrac.ewm(span=19, min_periods=10).mean() - netfrac.ewm(span=39, min_periods=20).mean()
    ind["levered"] = np.log(levLDV.replace(0, np.nan) / levSDV.replace(0, np.nan)).rolling(5, min_periods=3).mean()
    if cfg["vol_src"][0] == "ticker":
        vser = adj[cfg["vol_src"][1]].reindex(idx).ffill()
    else:
        vser = base.pct_change().rolling(20).std()
    ind["vol"] = -(vser / vser.rolling(50).mean() - 1)
    ind["safehaven"] = base.pct_change(20) - safe.pct_change(20)
    if cfg["junk"]:
        ind["junk"] = -get_oas(idx).rolling(5, min_periods=1).mean()

    n_ind = len(ind.columns)
    scores = pd.DataFrame(index=ind.index)
    for c in ind.columns:
        scores[c] = roll_pct(ind[c], minp=60 if c == "junk" else 126)
    min_needed = n_ind - 1 if n_ind >= 6 else n_ind
    scores["composite"] = scores.mean(axis=1, skipna=True).where(scores.notna().sum(axis=1) >= min_needed)

    out = scores.join(base.rename("base"))
    out = out[out.composite.notna()].round(1)
    cur = out.composite.iloc[-1]
    assert 0 <= cur <= 100 and len(out) > 1000, f"{key}: sanity check failed (n={len(out)})"

    # ---- 페이지 데이터 ----
    data = {"dates": [d.strftime("%Y-%m-%d") for d in out.index],
            "comp": [None if pd.isna(v) else round(v, 1) for v in out.composite],
            "px": []}
    for tick, label, dp in cfg["charts"]:
        ser = adj[tick].reindex(out.index)
        data["px"].append([None if pd.isna(v) else round(float(v), dp if dp > 0 else 1) for v in ser])
    for k in ind.columns:
        data[k] = [None if pd.isna(v) else round(v, 1) for v in out[k]]

    js_cfg = {
        "key": key, "indexLabel": cfg["index_label"],
        "charts": [{"label": lb, "dp": dp} for _, lb, dp in cfg["charts"]],
        "tiles": [[k, TILE_DEFS[k][0], TILE_DEFS[k][1]] for k in ind.columns],
    }

    method_items = [
        f"주가 모멘텀 — 지수 vs 125일 이동평균 이탈률",
        f"주가 강도 — 구성종목({cfg['n_cons_label']}) 중 52주 신고가·신저가 종목 비중(순비중, 10일 평활)",
        f"주가 폭 — 구성종목 상승/하락 거래량 순비중의 McClellan 오실레이터(19/39 EMA)",
        f"레버리지 수급 — {cfg['lev_label']} 거래대금 비율(5일 평균) · 풋/콜 비율 대체",
        f"변동성 — {cfg['vol_label']}",
        f"안전자산 수요 — 최근 20거래일 지수 수익률 - {cfg['safe_label']} 수익률",
    ]
    if cfg["junk"]:
        method_items.append("정크본드 수요 — 하이일드 스프레드(ICE BofA HY OAS, 5일 평균) 역방향")
    method_html = "\n".join(f"      <li><b>{m.split(' — ')[0]}</b> — {m.split(' — ')[1]}</li>" for m in method_items)

    notes = ("데이터: Yahoo Finance(수정주가), FRED(BAMLH0A0HYM2). " if cfg["junk"] else "데이터: Yahoo Finance(수정주가). ")
    notes += f"기준일 {out.index[-1].strftime('%Y.%m.%d')}.<br>유의: "
    if cfg["junk"]:
        notes += "정크본드 지표는 데이터 제공 한계(FRED 3년)로 과거 구간에서 제외됨. "
    else:
        notes += "한국 하이일드 스프레드는 무료 데이터가 없어 정크본드 지표 없이 6개 지표로 산출함. "
    notes += ("상장 1년 미만 종목은 강도·폭 계산에서 제외. 1년 백분위 방식은 장기 강세장에서 조정이 실제보다 "
              "극단적 공포로 표시되는 경향과 극단값 포화 특성이 있음. CNN 원 방법론의 세부 공식은 비공개라 수치를 "
              "직접 비교할 수 없음. 본 지표는 참고용이며 투자 판단의 근거가 아님.")

    nav = nav_html(key)
    tpl = open("template.html", encoding="utf-8").read()
    html = (tpl.replace("__TITLE__", cfg["title"])
               .replace("__METADESC__", cfg["desc"])
               .replace("__KEYWORDS__", cfg["keywords"])
               .replace("__CANONICAL__", f"{BASE_URL}/{key}/")
               .replace("__H1__", cfg["h1"])
               .replace("__NAV__", nav)
               .replace("__METHODLIST__", method_html)
               .replace("__NOTES__", notes)
               .replace("__NIND__", str(n_ind))
               .replace("__CFG__", json.dumps(js_cfg, ensure_ascii=False))
               .replace("__DATA__", json.dumps(data, ensure_ascii=False))
               .replace("__LASTDATE__", out.index[-1].strftime("%Y.%m.%d")))
    os.makedirs(key, exist_ok=True)
    open(f"{key}/index.html", "w", encoding="utf-8").write(html)

    prev = out.composite.iloc[-2] if len(out) > 1 else cur
    summary = {"key": key, "name": cfg["name"], "value": round(float(cur), 1), "zone": zone_of(cur),
               "prev": round(float(prev), 1), "date": out.index[-1].strftime("%Y.%m.%d")}
    json.dump(summary, open(f"{key}/summary.json", "w"), ensure_ascii=False)
    print(f"{key} OK {summary['date']} composite={cur}")
    return summary


def nav_html(active):
    items = [("../", "홈", "hub"), ("../sox/", "SOX 반도체", "sox"), ("../nasdaq/", "나스닥100", "nasdaq"),
             ("../kospi/", "코스피", "kospi"), ("../kosdaq/", "코스닥", "kosdaq")]
    return "".join(f'<a href="{h}" class="{"on" if k == active else ""}">{t}</a>' for h, t, k in items)


def build_hub():
    sums = []
    for k in CONFIGS:
        p = f"{k}/summary.json"
        if os.path.exists(p):
            sums.append(json.load(open(p)))
    if not sums:
        return
    tpl = open("hub_template.html", encoding="utf-8").read()
    html = tpl.replace("__SUMS__", json.dumps(sums, ensure_ascii=False))
    open("index.html", "w", encoding="utf-8").write(html)

    today = max(s["date"] for s in sums).replace(".", "-")
    urls = [f"{BASE_URL}/"] + [f"{BASE_URL}/{k}/" for k in CONFIGS if os.path.exists(f"{k}/summary.json")]
    body = "".join(f"  <url><loc>{u}</loc><lastmod>{today}</lastmod><changefreq>daily</changefreq></url>\n" for u in urls)
    open("sitemap.xml", "w", encoding="utf-8").write(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + body + "</urlset>\n")
    print("hub OK:", [s["key"] for s in sums])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--markets", default="all", choices=["us", "kr", "all"])
    args = ap.parse_args()
    targets = {"us": ["sox", "nasdaq"], "kr": ["kospi", "kosdaq"], "all": list(CONFIGS)}[args.markets]
    failed = []
    for k in targets:
        try:
            build_market(k)
        except Exception as e:
            failed.append(k)
            print(f"{k} FAILED: {e}", file=sys.stderr)
    build_hub()
    if failed and len(failed) == len(targets):
        sys.exit(1)  # 전부 실패했을 때만 실패 처리 (부분 실패는 다음 실행에서 재시도)

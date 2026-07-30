# -*- coding: utf-8 -*-
"""
공포·탐욕 지수 시리즈 데이터 갱신 스크립트 (GitHub Actions에서 매일 실행)
- 5개 지수(sox / nasdaq / spx / kospi / kosdaq) 페이지 + 허브 + 비교 페이지 + OG 이미지 + sitemap 생성
- 텔레그램 알림(선택): 환경변수 TG_TOKEN / TG_CHAT 설정 시 구간 변경 알림 발송
- 실행: python update_data.py --markets us|kr|all
"""
import argparse, json, os, sys, time
import numpy as np
import pandas as pd
import requests
import yfinance as yf

BASE_URL = "https://kjb-canvas.github.io/sox-fear-greed"
GUIDES = [
    ("guide-how-to-read.html", "공포탐욕지수 읽는 법"),
    ("guide-leverage-etf.html", "레버리지 ETF와 변동성 드래그"),
    ("guide-contrarian.html", "역발상 투자와 백테스트 해석"),
]

SOX_CONS = ["AMD","ADI","AMAT","ARM","ASML","ALAB","AVGO","COHR","CRDO","ENTG",
            "GFS","INTC","KLAC","LRCX","MTSI","MRVL","MCHP","MU","MPWR","NVMI",
            "NVDA","NXPI","ON","QRVO","QCOM","RMBS","SWKS","TSM","TER","TXN"]

NDX_FALLBACK = ["ADBE","AMD","ABNB","ALNY","GOOGL","GOOG","AMZN","AEP","AMGN","ADI","AAPL","AMAT",
    "APP","ARM","ASML","ADSK","ADP","AXON","BKR","BKNG","AVGO","CDNS","CHTR","CTAS","CSCO","CCEP",
    "CTSH","CMCSA","CEG","CPRT","CSGP","COST","CRWD","CSX","DDOG","DXCM","FANG","DASH","EA","EXC",
    "FAST","FER","FTNT","GEHC","GILD","HON","IDXX","INSM","INTC","INTU","ISRG","KDP","KLAC","KHC",
    "LRCX","LIN","MAR","MRVL","MELI","META","MCHP","MU","MSFT","MSTR","MDLZ","MPWR","MNST","NFLX",
    "NVDA","NXPI","ORLY","ODFL","PCAR","PLTR","PANW","PAYX","PYPL","PDD","PEP","QCOM","REGN","ROP",
    "ROST","SNDK","STX","SHOP","SBUX","SNPS","TMUS","TTWO","TSLA","TXN","TRI","VRSK","VRTX","WMT",
    "WBD","WDC","WDAY","XEL","ZS"]


def wiki_tickers(url, min_n):
    tables = pd.read_html(url)
    for t in tables:
        cols = [str(c).lower() for c in t.columns]
        if any("ticker" in c or "symbol" in c for c in cols) and len(t) >= min_n:
            col = t.columns[[i for i, c in enumerate(cols) if "ticker" in c or "symbol" in c][0]]
            syms = [str(s).strip().replace(".", "-") for s in t[col] if str(s).strip() and str(s) != "nan"]
            if len(syms) >= min_n:
                return syms
    return None


def get_ndx_constituents():
    try:
        syms = wiki_tickers("https://en.wikipedia.org/wiki/Nasdaq-100", 90)
        if syms:
            return syms[:110]
    except Exception as e:
        print("NDX wiki fail:", e, file=sys.stderr)
    return NDX_FALLBACK


def get_spx_constituents():
    cache = "spx/constituents.json"
    try:
        syms = wiki_tickers("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", 450)
        if syms:
            os.makedirs("spx", exist_ok=True)
            json.dump(syms[:510], open(cache, "w"))
            return syms[:510]
    except Exception as e:
        print("SPX wiki fail:", e, file=sys.stderr)
    if os.path.exists(cache):
        return json.load(open(cache))
    raise RuntimeError("S&P500 list unavailable")


def get_krx_constituents(index_code, suffix, cache_file):
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
    raise RuntimeError(f"no constituents for {index_code}")


CONFIGS = {
    "sox": dict(
        name="SOX 반도체", h1="필라델피아 반도체지수(SOX) 공포·탐욕 지수",
        index="^SOX", index_label="SOX",
        constituents=lambda: SOX_CONS, n_cons_label="30종목",
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
        constituents=get_ndx_constituents, n_cons_label="100종목",
        lev_pair=("TQQQ", "SQQQ"), lev_label="TQQQ(3배 롱)/SQQQ(3배 숏)",
        vol_src=("ticker", "^VXN"), vol_label="VXN(나스닥100 변동성지수) vs 50일 이동평균",
        safe="IEF", safe_label="미국채 ETF(IEF)", junk=True,
        charts=[("^NDX", "나스닥100 지수", 0), ("QLD", "QLD — ProShares Ultra QQQ 2배", 2),
                ("TQQQ", "TQQQ — ProShares UltraPro QQQ 3배", 2)],
        title="나스닥 공포탐욕지수 — 나스닥100 Fear & Greed Index",
        desc="나스닥100 전용 공포탐욕지수. CNN 방법론을 나스닥100에 적용해 7개 심리 지표를 0~100으로 산출. TQQQ 등 레버리지 ETF 백테스트 제공, 매일 자동 갱신.",
        keywords="나스닥 공포탐욕지수, 나스닥100, QQQ, TQQQ, Fear and Greed",
    ),
    "spx": dict(
        name="S&P500", h1="S&P500 공포·탐욕 지수",
        index="^GSPC", index_label="S&P500",
        constituents=get_spx_constituents, n_cons_label="약 500종목",
        lev_pair=("UPRO", "SPXU"), lev_label="UPRO(3배 롱)/SPXU(3배 숏)",
        vol_src=("ticker", "^VIX"), vol_label="VIX vs 50일 이동평균",
        safe="IEF", safe_label="미국채 ETF(IEF)", junk=True, cnn=True,
        charts=[("^GSPC", "S&P500 지수", 0), ("SSO", "SSO — ProShares Ultra S&P500 2배", 2),
                ("UPRO", "UPRO — ProShares UltraPro S&P500 3배", 2)],
        title="S&P500 공포탐욕지수 — CNN Fear & Greed 실측 비교",
        desc="S&P500 공포탐욕지수를 CNN과 같은 철학으로 자체 산출하고, CNN 실측값과 매일 나란히 비교. 방법론 재현 검증과 레버리지 ETF 백테스트 제공.",
        keywords="공포탐욕지수, CNN Fear and Greed, S&P500, 투자심리, UPRO",
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
NAV_ITEMS = [("../", "홈", "hub"), ("../sox/", "SOX 반도체", "sox"), ("../nasdaq/", "나스닥100", "nasdaq"),
             ("../spx/", "S&P500", "spx"), ("../kospi/", "코스피", "kospi"), ("../kosdaq/", "코스닥", "kosdaq"),
             ("../compare/", "비교", "compare")]


def zone_of(v):
    for th, name in ZONES:
        if v < th:
            return name
    return ""


def nav_html(active):
    return "".join(f'<a href="{h}" class="{"on" if k == active else ""}">{t}</a>' for h, t, k in NAV_ITEMS)


def telegram(text):
    tok, chat = os.environ.get("TG_TOKEN"), os.environ.get("TG_CHAT")
    if not tok or not chat:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      data={"chat_id": chat, "text": text}, timeout=15)
    except Exception as e:
        print("telegram fail:", e, file=sys.stderr)


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


def get_cnn_series():
    """CNN Fear & Greed 실측 히스토리(약 1년). 실패 시 None."""
    try:
        r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        j = r.json()
        pts = j["fear_and_greed_historical"]["data"]
        return {pd.to_datetime(p["x"], unit="ms").strftime("%Y-%m-%d"): round(float(p["y"]), 1) for p in pts}
    except Exception as e:
        print("cnn fetch fail:", e, file=sys.stderr)
    try:
        df = pd.read_csv("https://raw.githubusercontent.com/whit3rabbit/fear-greed-data/main/fear-greed.csv")
        return {str(d)[:10]: round(float(v), 1) for d, v in zip(df["Date"], df["Fear Greed"]) if pd.notna(v)}
    except Exception as e:
        print("cnn mirror fail:", e, file=sys.stderr)
        return None


def gen_og(path, title, value, zone, date):
    """1200x630 OG 이미지 생성 (Pillow)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import math
        W, H = 1200, 630
        img = Image.new("RGB", (W, H), "#fcfcfb")
        d = ImageDraw.Draw(img)
        def font(sz, bold=True):
            for p in ["/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf" if bold else "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
                if os.path.exists(p):
                    return ImageFont.truetype(p, sz)
            return ImageFont.load_default()
        cols = ["#d03b3b", "#e34948", "#c3c2b7", "#5598e7", "#2a78d6"]
        bounds = [0, 25, 45, 55, 75, 100]
        cx, cy, r1, r2 = 330, 430, 150, 210
        for i in range(5):
            a0 = 180 + bounds[i] * 1.8 + (0.8 if i else 0)
            a1 = 180 + bounds[i + 1] * 1.8 - (0.8 if i < 4 else 0)
            d.arc([cx - r2, cy - r2, cx + r2, cy + r2], a0, a1, fill=cols[i], width=r2 - r1)
        ang = math.radians(180 + value * 1.8)
        nx, ny = cx + (r1 - 12) * math.cos(ang), cy + (r1 - 12) * math.sin(ang)
        d.line([cx, cy, nx, ny], fill="#0b0b0b", width=8)
        d.ellipse([cx - 12, cy - 12, cx + 12, cy + 12], fill="#0b0b0b")
        vcol = cols[0] if value < 25 else cols[1] if value < 45 else "#898781" if value < 55 else cols[3] if value < 75 else cols[4]
        d.text((60, 60), title, font=font(46), fill="#0b0b0b")
        d.text((60, 125), "Fear & Greed Index · " + date, font=font(26), fill="#898781")
        d.text((620, 230), f"{value:.0f}", font=font(170), fill=vcol)
        d.text((625, 430), zone, font=font(56), fill=vcol)
        img.save(path)
        return True
    except Exception as e:
        print("og gen fail:", path, e, file=sys.stderr)
        return False


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

    data = {"dates": [d.strftime("%Y-%m-%d") for d in out.index],
            "comp": [None if pd.isna(v) else round(v, 1) for v in out.composite],
            "px": []}
    for tick, label, dp in cfg["charts"]:
        ser = adj[tick].reindex(out.index)
        data["px"].append([None if pd.isna(v) else round(float(v), dp if dp > 0 else 1) for v in ser])
    for k in ind.columns:
        data[k] = [None if pd.isna(v) else round(v, 1) for v in out[k]]

    cnn_note = ""
    if cfg.get("cnn"):
        cnn = get_cnn_series()
        if cnn:
            data["cnn"] = [cnn.get(d) for d in data["dates"]]
            last_cnn = next((v for v in reversed(data["cnn"]) if v is not None), None)
            if last_cnn is not None:
                cnn_note = (f" CNN 실측 최신값은 {last_cnn:.0f}이며, CNN은 S&P500·NYSE 전체 시장 기준의 "
                            "다른 세부 공식을 쓰므로 수치 차이는 자연스러움.")

    js_cfg = {
        "key": key, "indexLabel": cfg["index_label"],
        "charts": [{"label": lb, "dp": dp} for _, lb, dp in cfg["charts"]],
        "tiles": [[k, TILE_DEFS[k][0], TILE_DEFS[k][1]] for k in ind.columns],
        "cnn": bool(data.get("cnn")),
    }

    method_items = [
        "주가 모멘텀 — 지수 vs 125일 이동평균 이탈률",
        f"주가 강도 — 구성종목({cfg['n_cons_label']}) 중 52주 신고가·신저가 종목 비중(순비중, 10일 평활)",
        "주가 폭 — 구성종목 상승/하락 거래량 순비중의 McClellan 오실레이터(19/39 EMA)",
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
        notes += ("한국 하이일드 스프레드는 무료 데이터가 없어 정크본드 지표 없이 6개 지표로 산출함. "
                  "구성종목은 KRX 공식 목록 또는 시가총액 상위 근사 목록(주기적 갱신)을 사용함. ")
    notes += ("상장 1년 미만 종목은 강도·폭 계산에서 제외. 1년 백분위 방식은 장기 강세장에서 조정이 실제보다 "
              "극단적 공포로 표시되는 경향과 극단값 포화 특성이 있음. CNN 원 방법론의 세부 공식은 비공개라 수치를 "
              "직접 비교할 수 없음." + cnn_note + " 본 지표는 참고용이며 투자 판단의 근거가 아님.")

    os.makedirs(key, exist_ok=True)
    date_str = out.index[-1].strftime("%Y.%m.%d")
    og_ok = gen_og(f"{key}/og.png", cfg["name"] + " 공포탐욕지수", float(cur), zone_of(cur), date_str)

    tpl = open("template.html", encoding="utf-8").read()
    html = (tpl.replace("__TITLE__", cfg["title"])
               .replace("__METADESC__", cfg["desc"])
               .replace("__KEYWORDS__", cfg["keywords"])
               .replace("__CANONICAL__", f"{BASE_URL}/{key}/")
               .replace("__OGIMG__", f"{BASE_URL}/{key}/og.png" if og_ok else f"{BASE_URL}/og.png")
               .replace("__H1__", cfg["h1"])
               .replace("__NAV__", nav_html(key))
               .replace("__METHODLIST__", method_html)
               .replace("__NOTES__", notes)
               .replace("__NIND__", str(n_ind))
               .replace("__CFG__", json.dumps(js_cfg, ensure_ascii=False))
               .replace("__DATA__", json.dumps(data, ensure_ascii=False))
               .replace("__LASTDATE__", date_str))
    open(f"{key}/index.html", "w", encoding="utf-8").write(html)

    # 비교 페이지용 시계열 (최근 3.2년)
    comp_slim = {"dates": data["dates"][-800:], "comp": data["comp"][-800:]}
    json.dump(comp_slim, open(f"{key}/series.json", "w"))

    prev = out.composite.iloc[-2] if len(out) > 1 else cur
    old_zone = None
    if os.path.exists(f"{key}/summary.json"):
        try:
            old_zone = json.load(open(f"{key}/summary.json")).get("zone")
        except Exception:
            pass
    summary = {"key": key, "name": cfg["name"], "value": round(float(cur), 1), "zone": zone_of(cur),
               "prev": round(float(prev), 1), "date": date_str}
    json.dump(summary, open(f"{key}/summary.json", "w"), ensure_ascii=False)
    print(f"{key} OK {date_str} composite={cur}")

    if old_zone and old_zone != summary["zone"]:
        return summary, f"[{cfg['name']}] {old_zone} -> {summary['zone']} ({summary['prev']} -> {summary['value']})"
    return summary, None


def build_compare():
    series = {}
    for k in CONFIGS:
        p = f"{k}/series.json"
        if os.path.exists(p):
            series[k] = json.load(open(p))
    if len(series) < 2:
        return
    names = {k: CONFIGS[k]["name"] for k in series}
    tpl = open("compare_template.html", encoding="utf-8").read()
    html = (tpl.replace("__NAV__", nav_html("compare"))
               .replace("__SERIES__", json.dumps(series, ensure_ascii=False))
               .replace("__NAMES__", json.dumps(names, ensure_ascii=False)))
    os.makedirs("compare", exist_ok=True)
    open("compare/index.html", "w", encoding="utf-8").write(html)
    print("compare OK:", list(series))


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
    # 허브 OG: 대표 지수(첫 번째) 기준
    s0 = sums[0]
    gen_og("og.png", "공포탐욕지수 시리즈", s0["value"], s0["name"] + " " + s0["zone"], s0["date"])

    today = max(s["date"] for s in sums).replace(".", "-")
    urls = [f"{BASE_URL}/"] + [f"{BASE_URL}/{k}/" for k in CONFIGS if os.path.exists(f"{k}/summary.json")]
    if os.path.exists("compare/index.html"):
        urls.append(f"{BASE_URL}/compare/")
    for g, _ in GUIDES:
        if os.path.exists(g):
            urls.append(f"{BASE_URL}/{g}")
    body = "".join(f"  <url><loc>{u}</loc><lastmod>{today}</lastmod><changefreq>daily</changefreq></url>\n" for u in urls)
    open("sitemap.xml", "w", encoding="utf-8").write(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + body + "</urlset>\n")
    print("hub OK:", [s["key"] for s in sums])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--markets", default="all", choices=["us", "kr", "all"])
    args = ap.parse_args()
    targets = {"us": ["sox", "nasdaq", "spx"], "kr": ["kospi", "kosdaq"], "all": list(CONFIGS)}[args.markets]
    failed, alerts = [], []
    for k in targets:
        try:
            _, alert = build_market(k)
            if alert:
                alerts.append(alert)
        except Exception as e:
            failed.append(k)
            print(f"{k} FAILED: {e}", file=sys.stderr)
    build_compare()
    build_hub()
    if alerts:
        telegram("공포탐욕지수 구간 변경\n" + "\n".join(alerts) + f"\n{BASE_URL}/")
    if failed:
        telegram("공포탐욕지수 갱신 실패: " + ", ".join(failed))
    if failed and len(failed) == len(targets):
        sys.exit(1)

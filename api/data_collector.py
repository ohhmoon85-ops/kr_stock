"""
시장 데이터 수집 모듈 - Yahoo Finance API 직접 호출 버전
yfinance 대신 requests로 직접 호출하여 Vercel 환경 호환성 확보
"""

import requests
import pandas as pd
import time
from datetime import datetime, timezone, timedelta
import logging

KST = timezone(timedelta(hours=9))
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

US_INDICES = {
    "S&P500":           "^GSPC",
    "NASDAQ":           "^IXIC",
    "필라델피아 반도체": "^SOX",
    "다우존스":         "^DJI",
    "VIX(공포지수)":    "^VIX",
    "금(Gold)":         "GC=F",
    "달러인덱스(DXY)":  "DX-Y.NYB",
}

KR_STOCKS = {
    "삼성전자":           "005930.KS",
    "SK하이닉스":         "000660.KS",
    "DB하이텍":           "000990.KS",
    "리노공업":           "058470.KS",
    "LG에너지솔루션":     "373220.KS",
    "삼성SDI":            "006400.KS",
    "에코프로비엠":       "247540.KQ",
    "포스코퓨처엠":       "003670.KS",
    "삼성바이오로직스":   "207940.KS",
    "셀트리온":           "068270.KS",
    "유한양행":           "000100.KS",
    "HLB":                "028300.KQ",
    "NAVER":              "035420.KS",
    "카카오":             "035720.KS",
    "크래프톤":           "259960.KS",
    "현대차":             "005380.KS",
    "기아":               "000270.KS",
    "현대모비스":         "012330.KS",
    "KB금융":             "105560.KS",
    "신한지주":           "055550.KS",
    "하나금융지주":       "086790.KS",
    "LG화학":             "051910.KS",
    "한화솔루션":         "009830.KS",
    "한화에어로스페이스": "012450.KS",
    "LIG넥스원":          "079550.KS",
    "현대로템":           "064350.KS",
    "HD현대중공업":       "329180.KS",
    "삼성중공업":         "010140.KS",
    "한화오션":           "042660.KS",
}

KR_INDICES = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11"}

GEO_RISK_KEYWORDS = [
    "nuclear", "invasion", "missile", "World War",
    "North Korea", "Iran attack", "Ukraine war",
    "military strike", "armed conflict",
]

TIME_LIMIT = 50.0


# ── Yahoo Finance API 직접 호출 ───────────────────────────────────────────────

def _fetch_yahoo(ticker: str, range_: str = "3mo") -> dict:
    """Yahoo Finance Chart API 직접 호출"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"interval": "1d", "range": range_}
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        resp.raise_for_status()
        result = resp.json()["chart"]["result"]
        if not result:
            return {}
        r = result[0]
        closes  = r["indicators"]["quote"][0].get("close", [])
        volumes = r["indicators"]["quote"][0].get("volume", [])
        # None 제거
        closes  = [c for c in closes  if c is not None]
        volumes = [v for v in volumes if v is not None]
        return {"closes": closes, "volumes": volumes}
    except Exception as e:
        logger.debug(f"  {ticker} fetch 실패: {e}")
        return {}


# ── 기술적 지표 계산 ──────────────────────────────────────────────────────────

def _calc_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return None
    s = pd.Series(closes)
    delta = s.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta).clip(lower=0).rolling(period).mean()
    rs    = gain / loss
    rsi   = 100 - (100 / (1 + rs))
    val   = rsi.iloc[-1]
    return round(float(val), 1) if not pd.isna(val) else None


def _calc_macd(closes: list) -> dict:
    if len(closes) < 26:
        return {}
    s      = pd.Series(closes)
    ema12  = s.ewm(span=12, adjust=False).mean()
    ema26  = s.ewm(span=26, adjust=False).mean()
    macd   = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist   = macd - signal
    return {
        "macd":      round(float(macd.iloc[-1]),   0),
        "signal":    round(float(signal.iloc[-1]), 0),
        "histogram": round(float(hist.iloc[-1]),   0),
    }


def _calc_ma(closes: list) -> dict:
    s    = pd.Series(closes)
    ma5  = s.rolling(5).mean().iloc[-1]
    ma20 = s.rolling(20).mean().iloc[-1]
    ma60 = s.rolling(60).mean().iloc[-1] if len(closes) >= 60 else None
    r = {
        "ma5":  round(float(ma5),  0) if not pd.isna(ma5)  else None,
        "ma20": round(float(ma20), 0) if not pd.isna(ma20) else None,
        "ma60": round(float(ma60), 0) if (ma60 is not None and not pd.isna(ma60)) else None,
    }
    if all(v is not None for v in r.values()):
        r["golden_align"] = r["ma5"] > r["ma20"] > r["ma60"]
    else:
        r["golden_align"] = None
    return r


def _calc_stoch_rsi(closes: list, period: int = 14) -> float:
    """Stochastic RSI - RSI보다 민감한 과매수/과매도 판단"""
    if len(closes) < period * 2:
        return None
    s = pd.Series(closes)
    delta = s.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta).clip(lower=0).rolling(period).mean()
    rs    = gain / loss
    rsi   = 100 - (100 / (1 + rs))
    rsi_min = rsi.rolling(period).min()
    rsi_max = rsi.rolling(period).max()
    stoch_rsi = (rsi - rsi_min) / (rsi_max - rsi_min)
    val = stoch_rsi.iloc[-1]
    return round(float(val) * 100, 1) if not pd.isna(val) else None


def _calc_atr(closes: list, period: int = 14) -> float:
    """ATR (Average True Range) - 변동성 측정"""
    if len(closes) < period + 1:
        return None
    s  = pd.Series(closes)
    tr = s.diff().abs()  # 간소화 버전 (고가/저가 없을 때)
    atr = tr.rolling(period).mean().iloc[-1]
    return round(float(atr), 0) if not pd.isna(atr) else None


def _calc_obv(closes: list, volumes: list) -> str:
    """OBV (On-Balance Volume) - 거래량 기반 추세 확인"""
    if len(closes) < 5 or len(volumes) < 5:
        return None
    s_close = pd.Series(closes)
    s_vol   = pd.Series(volumes)
    obv = (s_vol * s_close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))).cumsum()
    # 최근 5일 추세
    recent = obv.iloc[-5:]
    trend  = "상승" if recent.iloc[-1] > recent.iloc[0] else "하락"
    return trend


def _calc_volume_ratio(volumes: list, period: int = 20) -> float:
    """거래량 비율 - 평균 대비 오늘 거래량 (급등 신호)"""
    if len(volumes) < period + 1:
        return None
    avg = pd.Series(volumes[:-1]).rolling(period).mean().iloc[-1]
    if avg == 0:
        return None
    ratio = volumes[-1] / avg
    return round(float(ratio), 2)


def _calc_bollinger(closes: list, period: int = 20) -> dict:
    if len(closes) < period:
        return {}
    s     = pd.Series(closes)
    ma    = s.rolling(period).mean()
    std   = s.rolling(period).std()
    upper = (ma + 2 * std).iloc[-1]
    lower = (ma - 2 * std).iloc[-1]
    mid   = ma.iloc[-1]
    if pd.isna(upper) or pd.isna(lower):
        return {}
    width = float(upper) - float(lower)
    pos   = round((closes[-1] - float(lower)) / width, 2) if width > 0 else 0.5
    return {
        "upper":         round(float(upper), 0),
        "middle":        round(float(mid),   0),
        "lower":         round(float(lower), 0),
        "band_position": pos,
    }


# ── 데이터 수집 ───────────────────────────────────────────────────────────────

def collect_us_indices() -> dict:
    result = {}
    for name, ticker in US_INDICES.items():
        data = _fetch_yahoo(ticker, range_="5d")
        closes = data.get("closes", [])
        if len(closes) < 2:
            continue
        change = (closes[-1] - closes[-2]) / closes[-2] * 100
        result[name] = {
            "close":      round(closes[-1], 2),
            "change_pct": round(change,     2),
        }
    logger.info(f"  미 증시 {len(result)}/{len(US_INDICES)}개 수집")
    return result


def collect_kr_indices() -> dict:
    result = {}
    for name, ticker in KR_INDICES.items():
        data = _fetch_yahoo(ticker, range_="5d")
        closes = data.get("closes", [])
        if len(closes) < 2:
            continue
        change = (closes[-1] - closes[-2]) / closes[-2] * 100
        result[name] = {
            "close":      round(closes[-1], 2),
            "change_pct": round(change,     2),
        }
    return result


def collect_kr_stocks(start_time: float) -> dict:
    result = {}
    for name, ticker in KR_STOCKS.items():
        if time.time() - start_time > TIME_LIMIT:
            logger.warning(f"⏱ 타임아웃 가드 발동 ({len(result)}개 처리 후 중단)")
            break
        data   = _fetch_yahoo(ticker, range_="3mo")
        closes = data.get("closes", [])
        volumes = data.get("volumes", [])
        if len(closes) < 26:
            continue
        last  = closes[-1]
        prev  = closes[-2]
        result[name] = {
            "ticker":     ticker,
            "close":      round(last, 0),
            "prev_close": round(prev, 0),
            "change_pct": round((last - prev) / prev * 100, 2),
            "volume":     int(volumes[-1]) if volumes else 0,
            "rsi":          _calc_rsi(closes),
            "stoch_rsi":    _calc_stoch_rsi(closes),
            "macd":         _calc_macd(closes),
            "ma":           _calc_ma(closes),
            "bollinger":    _calc_bollinger(closes),
            "atr":          _calc_atr(closes),
            "obv_trend":    _calc_obv(closes, volumes),
            "volume_ratio": _calc_volume_ratio(volumes),
        }

    # 모멘텀 점수 → 상위 15개
    def score(item):
        rsi    = item[1].get("rsi") or 50
        hist_v = (item[1].get("macd") or {}).get("histogram", 0)
        ma     = item[1].get("ma") or {}
        vol    = item[1].get("volume", 0)
        return (
            (1 if 40 <= rsi <= 65 else 0)
            + (1 if hist_v > 0 else 0)
            + (1 if ma.get("golden_align") else 0),
            vol,
        )

    top15 = dict(sorted(result.items(), key=score, reverse=True)[:15])
    logger.info(f"  한국 종목: {len(result)}개 수집 → 상위 {len(top15)}개 선별")
    return top15


def collect_geopolitical_news() -> dict:
    try:
        import feedparser
        url  = "https://news.google.com/rss/search?q=war+crisis+geopolitical+risk+economy&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        headlines  = []
        risk_count = 0
        for entry in feed.entries[:10]:
            title = entry.get("title", "")
            if not title:
                continue
            headlines.append(title)
            if any(kw.lower() in title.lower() for kw in GEO_RISK_KEYWORDS):
                risk_count += 1
        level = "높음" if risk_count >= 3 else "보통" if risk_count >= 1 else "낮음"
        return {"headlines": headlines[:5], "risk_count": risk_count, "risk_level": level}
    except Exception as e:
        logger.warning(f"지정학 뉴스 수집 실패: {e}")
        return {"headlines": [], "risk_count": 0, "risk_level": "알 수 없음"}


# ── 프롬프트 포맷터 ────────────────────────────────────────────────────────────

def format_market_data_for_prompt(market_data: dict) -> str:
    lines = [f"[분석 기준일: {datetime.now(KST).strftime('%Y년 %m월 %d일')}]"]

    # 실제 수집 가격 명시 (GPT 가격 날조 방지)
    kr_stocks = market_data.get("kr_stocks", {})
    if kr_stocks:
        lines.append("\n⚠️ 아래는 실제 수집된 종가입니다. 진입가는 반드시 이 가격을 사용하세요:")
        for name, info in kr_stocks.items():
            lines.append(f"  {name}: {int(info['close']):,}원")

    # 지정학적 리스크
    geo = market_data.get("geo_risk", {})
    lines.append(f"\n### 지정학적 리스크")
    lines.append(f"- 위험도: {geo.get('risk_level','알 수 없음')} (위험 키워드 {geo.get('risk_count',0)}건)")
    for h in geo.get("headlines", []):
        lines.append(f"  - {h}")

    # 미 증시
    lines.append("\n### 전일 미 증시 지수")
    us = market_data.get("us_indices", {})
    if us:
        for name, info in us.items():
            sign = "+" if info["change_pct"] >= 0 else ""
            lines.append(f"- {name}: {info['close']:,.2f} ({sign}{info['change_pct']:.2f}%)")
    else:
        lines.append("- 데이터 수집 실패")

    # 한국 지수
    lines.append("\n### 한국 증시 지수")
    for name, info in market_data.get("kr_indices", {}).items():
        sign = "+" if info["change_pct"] >= 0 else ""
        lines.append(f"- {name}: {info['close']:,.2f} ({sign}{info['change_pct']:.2f}%)")

    # 한국 종목 기술적 지표
    lines.append("\n### 한국 주요 종목 (기술적 지표)")
    lines.append("종목명 | 종가(원) | 등락률 | RSI | StochRSI | MACD히스토 | MA정배열 | 볼린저위치 | ATR | OBV추세 | 거래량비율")
    lines.append("---|---|---|---|---|---|---|---|---|---|---")
    for name, info in kr_stocks.items():
        sign      = "+" if info["change_pct"] >= 0 else ""
        rsi       = info.get("rsi") or "-"
        stoch_rsi = info.get("stoch_rsi") or "-"
        hist_v    = (info.get("macd") or {}).get("histogram", "-")
        ma        = info.get("ma") or {}
        golden    = "정배열✓" if ma.get("golden_align") else ("역배열✗" if ma.get("golden_align") is False else "-")
        bb        = info.get("bollinger") or {}
        bb_pos    = bb.get("band_position", "-")
        atr       = info.get("atr") or "-"
        obv       = info.get("obv_trend") or "-"
        vol_ratio = info.get("volume_ratio") or "-"
        lines.append(
            f"{name} | {int(info['close']):,} | {sign}{info['change_pct']:.2f}%"
            f" | {rsi} | {stoch_rsi} | {hist_v} | {golden} | {bb_pos}"
            f" | {atr} | {obv} | {vol_ratio}"
        )

    return "\n".join(lines)


# ── 메인 수집 함수 ─────────────────────────────────────────────────────────────

def collect_market_data() -> dict:
    start_time = time.time()

    logger.info("① 지정학적 리스크 뉴스 수집...")
    geo_risk = collect_geopolitical_news()
    logger.info(f"   완료 ({time.time()-start_time:.1f}s)")

    logger.info("② 미 증시 지수 수집...")
    us_indices = collect_us_indices()
    logger.info(f"   완료 ({time.time()-start_time:.1f}s)")

    logger.info("③ 한국 지수 수집...")
    kr_indices = collect_kr_indices()
    logger.info(f"   완료 ({time.time()-start_time:.1f}s)")

    logger.info("④ 한국 종목 수집 + 기술적 지표...")
    kr_stocks = collect_kr_stocks(start_time)
    logger.info(f"   완료 ({time.time()-start_time:.1f}s)")

    market_data = {
        "geo_risk":     geo_risk,
        "us_indices":   us_indices,
        "kr_indices":   kr_indices,
        "kr_stocks":    kr_stocks,
        "collected_at": datetime.now(KST).isoformat(),
        "elapsed_sec":  round(time.time() - start_time, 1),
    }
    market_data["prompt_text"] = format_market_data_for_prompt(market_data)
    logger.info(f"전체 데이터 수집 완료: {market_data['elapsed_sec']}초")
    return market_data

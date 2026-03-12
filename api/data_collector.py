"""
시장 데이터 수집 모듈
- 미 증시: S&P500, NASDAQ, 필라델피아 반도체, 금, 달러인덱스
- 한국 증시: RSI/MACD/MA/볼린저밴드 + 뉴스
- 지정학적 리스크: Google News RSS 헤드라인 분석
"""

import yfinance as yf
import pandas as pd
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

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
    # 반도체
    "삼성전자":           "005930.KS",
    "SK하이닉스":         "000660.KS",
    "DB하이텍":           "000990.KS",
    "리노공업":           "058470.KS",
    # 2차전지
    "LG에너지솔루션":     "373220.KS",
    "삼성SDI":            "006400.KS",
    "에코프로비엠":       "247540.KQ",
    "포스코퓨처엠":       "003670.KS",
    # 바이오
    "삼성바이오로직스":   "207940.KS",
    "셀트리온":           "068270.KS",
    "유한양행":           "000100.KS",
    "HLB":                "028300.KQ",
    # IT/플랫폼
    "NAVER":              "035420.KS",
    "카카오":             "035720.KS",
    "크래프톤":           "259960.KS",
    # 자동차
    "현대차":             "005380.KS",
    "기아":               "000270.KS",
    "현대모비스":         "012330.KS",
    # 금융
    "KB금융":             "105560.KS",
    "신한지주":           "055550.KS",
    "하나금융지주":       "086790.KS",
    # 에너지/화학
    "LG화학":             "051910.KS",
    "한화솔루션":         "009830.KS",
    # 방산
    "한화에어로스페이스": "012450.KS",
    "LIG넥스원":          "079550.KS",
    "현대로템":           "064350.KS",
    # 조선
    "HD현대중공업":       "329180.KS",
    "삼성중공업":         "010140.KS",
    "한화오션":           "042660.KS",
}

KR_INDICES = {
    "KOSPI":  "^KS11",
    "KOSDAQ": "^KQ11",
}

# 지정학적 리스크 키워드
GEO_RISK_KEYWORDS = [
    "war", "nuclear", "military", "invasion", "missile", "attack",
    "sanctions", "crisis", "conflict", "Iran", "North Korea",
    "Ukraine", "Russia", "rate hike", "emergency", "collapse",
    "recession", "crash", "tariff", "trade war",
]


# ── 기술적 지표 계산 ──────────────────────────────────────────────────────────

def _calc_rsi(closes: pd.Series, period: int = 14) -> float:
    delta    = closes.diff()
    gains    = delta.clip(lower=0)
    losses   = (-delta).clip(lower=0)
    avg_gain = gains.rolling(period).mean()
    avg_loss = losses.rolling(period).mean()
    rs  = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return round(float(val), 1) if not pd.isna(val) else None


def _calc_macd(closes: pd.Series) -> dict:
    ema12  = closes.ewm(span=12, adjust=False).mean()
    ema26  = closes.ewm(span=26, adjust=False).mean()
    macd   = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist   = macd - signal
    return {
        "macd":      round(float(macd.iloc[-1]), 0),
        "signal":    round(float(signal.iloc[-1]), 0),
        "histogram": round(float(hist.iloc[-1]), 0),
    }


def _calc_ma(closes: pd.Series) -> dict:
    """이동평균선 + 정배열 여부"""
    ma5  = closes.rolling(5).mean().iloc[-1]
    ma20 = closes.rolling(20).mean().iloc[-1]
    ma60 = closes.rolling(60).mean().iloc[-1] if len(closes) >= 60 else None

    result = {
        "ma5":  round(float(ma5),  0) if not pd.isna(ma5)  else None,
        "ma20": round(float(ma20), 0) if not pd.isna(ma20) else None,
        "ma60": round(float(ma60), 0) if (ma60 is not None and not pd.isna(ma60)) else None,
    }
    # 정배열: MA5 > MA20 > MA60
    if all(v is not None for v in result.values()):
        result["golden_align"] = result["ma5"] > result["ma20"] > result["ma60"]
    else:
        result["golden_align"] = None
    return result


def _calc_bollinger(closes: pd.Series, period: int = 20) -> dict:
    """볼린저 밴드 (20일 기준)"""
    ma    = closes.rolling(period).mean()
    std   = closes.rolling(period).std()
    upper = (ma + 2 * std).iloc[-1]
    lower = (ma - 2 * std).iloc[-1]
    mid   = ma.iloc[-1]

    if pd.isna(upper) or pd.isna(lower):
        return {"upper": None, "middle": None, "lower": None, "band_position": None}

    width = float(upper) - float(lower)
    last  = float(closes.iloc[-1])
    pos   = round((last - float(lower)) / width, 2) if width > 0 else 0.5
    return {
        "upper":         round(float(upper), 0),
        "middle":        round(float(mid),   0),
        "lower":         round(float(lower), 0),
        "band_position": pos,   # 0=하단 / 0.5=중간 / 1=상단
    }


# ── 개별 데이터 수집 ──────────────────────────────────────────────────────────

def _get_price_and_technicals(ticker: str) -> dict:
    """가격 + RSI/MACD/MA/볼린저 수집 (60일 데이터)"""
    try:
        tk   = yf.Ticker(ticker)
        hist = tk.history(period="60d")
        if hist.empty or len(hist) < 26:
            return {}

        closes     = hist["Close"]
        last_close = float(closes.iloc[-1])
        prev_close = float(closes.iloc[-2])
        change_pct = (last_close - prev_close) / prev_close * 100

        info = {
            "close":      round(last_close, 0),
            "prev_close": round(prev_close, 0),
            "change_pct": round(change_pct, 2),
            "volume":     int(hist["Volume"].iloc[-1]),
            "high":       round(float(hist["High"].iloc[-1]), 0),
            "low":        round(float(hist["Low"].iloc[-1]),  0),
            "rsi":        _calc_rsi(closes),
            "macd":       _calc_macd(closes),
            "ma":         _calc_ma(closes),
            "bollinger":  _calc_bollinger(closes),
        }

        try:
            mc = tk.fast_info.market_cap
            info["market_cap"] = int(mc) if mc else None
        except Exception:
            info["market_cap"] = None

        return info
    except Exception as e:
        logger.warning(f"티커 {ticker} 기본 조회 실패: {e}")
        return {}


def _get_news(ticker: str, max_items: int = 2) -> list:
    """최근 뉴스 수집"""
    try:
        raw     = yf.Ticker(ticker).news[:max_items]
        results = []
        for n in raw:
            if "content" in n:
                title = n["content"].get("title", "")
                pub   = n["content"].get("provider", {}).get("displayName", "")
            else:
                title = n.get("title", "")
                pub   = n.get("publisher", "")
            if title:
                results.append({"title": title, "publisher": pub})
        return results
    except Exception:
        return []


# ── 지정학적 리스크 수집 ──────────────────────────────────────────────────────

def collect_geopolitical_news() -> dict:
    """Google News RSS에서 지정학적 리스크 헤드라인 수집 및 위험도 평가"""
    try:
        import feedparser
        url  = "https://news.google.com/rss/search?q=war+crisis+geopolitical+risk&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)

        headlines   = []
        risk_count  = 0
        for entry in feed.entries[:8]:
            title = entry.get("title", "")
            if not title:
                continue
            headlines.append(title)
            tl = title.lower()
            if any(kw.lower() in tl for kw in GEO_RISK_KEYWORDS):
                risk_count += 1

        level = "높음" if risk_count >= 4 else "보통" if risk_count >= 2 else "낮음"
        logger.info(f"  지정학적 뉴스: {len(headlines)}건 수집, 위험 키워드 {risk_count}건 → {level}")
        return {"headlines": headlines[:5], "risk_count": risk_count, "risk_level": level}

    except Exception as e:
        logger.warning(f"지정학적 뉴스 수집 실패: {e}")
        return {"headlines": [], "risk_count": 0, "risk_level": "알 수 없음"}


# ── 수집 메인 함수 ─────────────────────────────────────────────────────────────

def collect_us_indices() -> dict:
    result = {}
    for name, ticker in US_INDICES.items():
        try:
            tk   = yf.Ticker(ticker)
            hist = tk.history(period="5d")
            if hist.empty or len(hist) < 2:
                continue
            closes = hist["Close"]
            change = (float(closes.iloc[-1]) - float(closes.iloc[-2])) / float(closes.iloc[-2]) * 100
            result[name] = {
                "close":      round(float(closes.iloc[-1]), 2),
                "change_pct": round(change, 2),
            }
            logger.info(f"  {name}: {result[name]['close']} ({change:+.2f}%)")
        except Exception as e:
            logger.warning(f"  {name} 조회 실패: {e}")
    return result


def collect_kr_indices() -> dict:
    result = {}
    for name, ticker in KR_INDICES.items():
        try:
            tk   = yf.Ticker(ticker)
            hist = tk.history(period="5d")
            if hist.empty or len(hist) < 2:
                continue
            closes = hist["Close"]
            change = (float(closes.iloc[-1]) - float(closes.iloc[-2])) / float(closes.iloc[-2]) * 100
            result[name] = {
                "close":      round(float(closes.iloc[-1]), 2),
                "change_pct": round(change, 2),
            }
        except Exception as e:
            logger.warning(f"  {name} 조회 실패: {e}")
    return result


def collect_kr_stocks() -> dict:
    """
    1단계: 전 종목 가격+기술적 지표 수집
    2단계: RSI/MACD 모멘텀 점수로 상위 15개 선별
    3단계: 선별 종목에 뉴스 추가
    """
    raw = {}
    for name, ticker in KR_STOCKS.items():
        info = _get_price_and_technicals(ticker)
        if info:
            raw[name] = {**info, "ticker": ticker}

    def score(item):
        rsi  = item[1].get("rsi") or 50
        hist = (item[1].get("macd") or {}).get("histogram", 0)
        vol  = item[1].get("volume", 0)
        ma   = item[1].get("ma") or {}
        rsi_ok    = 1 if 40 <= rsi <= 65 else 0
        macd_ok   = 1 if hist > 0 else 0
        golden_ok = 1 if ma.get("golden_align") else 0
        return (rsi_ok + macd_ok + golden_ok, vol)

    top15 = dict(sorted(raw.items(), key=score, reverse=True)[:15])

    for name, info in top15.items():
        top15[name]["news"] = _get_news(info["ticker"])

    logger.info(f"  한국 종목 최종 선별: {len(top15)}개")
    return top15


# ── 프롬프트 포맷터 ────────────────────────────────────────────────────────────

def format_market_data_for_prompt(market_data: dict) -> str:
    lines = []
    today = datetime.now().strftime("%Y년 %m월 %d일")
    lines.append(f"[분석 기준일: {today}]")

    # ── 지정학적 리스크 ──
    geo = market_data.get("geo_risk", {})
    lines.append(f"\n### 지정학적 리스크")
    lines.append(f"- 위험도: {geo.get('risk_level', '알 수 없음')} (위험 키워드 {geo.get('risk_count', 0)}건)")
    for h in geo.get("headlines", []):
        lines.append(f"  - {h}")

    # ── 미 증시 ──
    lines.append("\n### 전일 미 증시 지수 (금·달러 포함)")
    for name, info in market_data.get("us_indices", {}).items():
        sign = "+" if info["change_pct"] >= 0 else ""
        lines.append(f"- {name}: {info['close']:,.2f} ({sign}{info['change_pct']:.2f}%)")

    # ── 한국 지수 ──
    lines.append("\n### 한국 증시 지수")
    for name, info in market_data.get("kr_indices", {}).items():
        sign = "+" if info["change_pct"] >= 0 else ""
        lines.append(f"- {name}: {info['close']:,.2f} ({sign}{info['change_pct']:.2f}%)")

    # ── 한국 종목 ──
    lines.append("\n### 한국 주요 종목 (RSI·MACD·MA·볼린저)")
    lines.append("종목명 | 종가 | 등락률 | RSI | MACD히스토 | MA정배열 | 볼린저위치 | 시가총액(조)")
    lines.append("---|---|---|---|---|---|---|---")
    for name, info in market_data.get("kr_stocks", {}).items():
        sign   = "+" if info["change_pct"] >= 0 else ""
        rsi    = info.get("rsi") or "-"
        hist   = (info.get("macd") or {}).get("histogram", "-")
        ma     = info.get("ma") or {}
        golden = "정배열✓" if ma.get("golden_align") else ("역배열✗" if ma.get("golden_align") is False else "-")
        bb     = info.get("bollinger") or {}
        bb_pos = f"{bb.get('band_position', '-')}" if bb.get("band_position") is not None else "-"
        mc     = info.get("market_cap")
        mc_str = f"{mc/1e12:.1f}조" if mc else "-"
        lines.append(
            f"{name} | {info['close']:,} | {sign}{info['change_pct']:.2f}% "
            f"| {rsi} | {hist} | {golden} | {bb_pos} | {mc_str}"
        )

    # ── MA 상세 ──
    lines.append("\n### 이동평균선 상세 (MA5 / MA20 / MA60)")
    for name, info in market_data.get("kr_stocks", {}).items():
        ma = info.get("ma") or {}
        if any(ma.get(k) for k in ("ma5", "ma20", "ma60")):
            lines.append(
                f"- {name}: MA5={ma.get('ma5','-'):,}  MA20={ma.get('ma20','-'):,}  MA60={ma.get('ma60','-') or '-'}"
            )

    # ── 볼린저 밴드 상세 ──
    lines.append("\n### 볼린저 밴드 상세 (상단/중간/하단)")
    for name, info in market_data.get("kr_stocks", {}).items():
        bb = info.get("bollinger") or {}
        if bb.get("upper"):
            lines.append(
                f"- {name}: 상단={bb['upper']:,}  중간={bb['middle']:,}  하단={bb['lower']:,}"
                f"  (현재위치={bb.get('band_position','-')})"
            )

    # ── 뉴스 ──
    lines.append("\n### 종목별 최근 뉴스")
    for name, info in market_data.get("kr_stocks", {}).items():
        news_list = info.get("news", [])
        if news_list:
            lines.append(f"**{name}**")
            for n in news_list:
                lines.append(f"  - [{n['publisher']}] {n['title']}")

    return "\n".join(lines)


def collect_market_data() -> dict:
    logger.info("지정학적 리스크 뉴스 수집...")
    geo_risk = collect_geopolitical_news()

    logger.info("미 증시 지수 수집 (금·달러 포함)...")
    us_indices = collect_us_indices()

    logger.info("한국 지수 수집...")
    kr_indices = collect_kr_indices()

    logger.info("한국 종목 수집 (RSI/MACD/MA/볼린저/뉴스)...")
    kr_stocks = collect_kr_stocks()

    market_data = {
        "geo_risk":     geo_risk,
        "us_indices":   us_indices,
        "kr_indices":   kr_indices,
        "kr_stocks":    kr_stocks,
        "collected_at": datetime.now().isoformat(),
    }
    market_data["prompt_text"] = format_market_data_for_prompt(market_data)
    return market_data

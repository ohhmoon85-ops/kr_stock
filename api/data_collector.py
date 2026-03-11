"""
시장 데이터 수집 모듈
- 미 증시: S&P500, NASDAQ, 필라델피아 반도체
- 한국 증시: RSI/MACD + 시가총액 필터 + PER/PBR + 뉴스
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

MIN_MARKET_CAP = 1_000_000_000_000  # 1조원


# ── 기술적 지표 계산 ──────────────────────────────────────────────────────────

def _calc_rsi(closes: pd.Series, period: int = 14) -> float:
    delta = closes.diff()
    gains = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)
    avg_gain = gains.rolling(period).mean()
    avg_loss = losses.rolling(period).mean()
    rs = avg_gain / avg_loss
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


# ── 개별 데이터 수집 ──────────────────────────────────────────────────────────

def _get_price_and_technicals(ticker: str) -> dict:
    """가격 + RSI/MACD + 시가총액 수집 (60일 데이터)"""
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
            "low":        round(float(hist["Low"].iloc[-1]), 0),
            "rsi":        _calc_rsi(closes),
            "macd":       _calc_macd(closes),
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


def _get_fundamentals(ticker: str) -> dict:
    """PER/PBR 수집 (상위 종목에만 호출)"""
    try:
        info = yf.Ticker(ticker).info
        return {
            "per": round(info.get("trailingPE") or 0, 1) or None,
            "pbr": round(info.get("priceToBook") or 0, 2) or None,
            "eps": round(info.get("trailingEps") or 0, 0) or None,
        }
    except Exception as e:
        logger.warning(f"티커 {ticker} PER/PBR 조회 실패: {e}")
        return {"per": None, "pbr": None, "eps": None}


def _get_news(ticker: str, max_items: int = 2) -> list:
    """최근 뉴스 수집"""
    try:
        raw = yf.Ticker(ticker).news[:max_items]
        results = []
        for n in raw:
            # yfinance 버전에 따라 구조가 다름
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
    2단계: 시가총액 1조+ 필터
    3단계: RSI/MACD 모멘텀 점수로 상위 15개 선별
    4단계: 선별된 종목에만 PER/PBR + 뉴스 추가 수집
    """
    # 1단계
    raw = {}
    for name, ticker in KR_STOCKS.items():
        info = _get_price_and_technicals(ticker)
        if info:
            raw[name] = {**info, "ticker": ticker}

    # 2단계: 시가총액 필터
    filtered = {
        n: v for n, v in raw.items()
        if v.get("market_cap") is None or v["market_cap"] >= MIN_MARKET_CAP
    }

    # 3단계: 모멘텀 점수 정렬 → 상위 15개
    def score(item):
        rsi  = item[1].get("rsi") or 50
        hist = (item[1].get("macd") or {}).get("histogram", 0)
        vol  = item[1].get("volume", 0)
        rsi_ok   = 1 if 40 <= rsi <= 65 else 0
        macd_ok  = 1 if hist > 0 else 0
        return (rsi_ok + macd_ok, vol)

    top15 = dict(sorted(filtered.items(), key=score, reverse=True)[:15])

    # 4단계: 상위 15개에만 PER/PBR + 뉴스 추가
    for name, info in top15.items():
        ticker = info["ticker"]
        fund   = _get_fundamentals(ticker)
        news   = _get_news(ticker)
        top15[name].update(fund)
        top15[name]["news"] = news

    logger.info(f"  한국 종목 최종 선별: {len(top15)}개 (시가총액·모멘텀 필터 적용)")
    return top15


# ── 프롬프트 포맷터 ────────────────────────────────────────────────────────────

def format_market_data_for_prompt(market_data: dict) -> str:
    lines = []
    today = datetime.now().strftime("%Y년 %m월 %d일")
    lines.append(f"[분석 기준일: {today}]")

    # 미 증시
    lines.append("\n### 전일 미 증시 지수")
    for name, info in market_data.get("us_indices", {}).items():
        sign = "+" if info["change_pct"] >= 0 else ""
        lines.append(f"- {name}: {info['close']:,.2f} ({sign}{info['change_pct']:.2f}%)")

    # 한국 지수
    lines.append("\n### 한국 증시 지수")
    for name, info in market_data.get("kr_indices", {}).items():
        sign = "+" if info["change_pct"] >= 0 else ""
        lines.append(f"- {name}: {info['close']:,.2f} ({sign}{info['change_pct']:.2f}%)")

    # 한국 종목 (기술적 지표 + 펀더멘털)
    lines.append("\n### 한국 주요 종목 (시가총액 1조+ | RSI·MACD·PER·PBR 포함)")
    lines.append("종목명 | 종가 | 등락률 | RSI | MACD히스토 | PER | PBR | 시가총액(조)")
    lines.append("---|---|---|---|---|---|---|---")
    for name, info in market_data.get("kr_stocks", {}).items():
        sign   = "+" if info["change_pct"] >= 0 else ""
        rsi    = info.get("rsi") or "-"
        hist   = (info.get("macd") or {}).get("histogram", "-")
        per    = info.get("per") or "-"
        pbr    = info.get("pbr") or "-"
        mc     = info.get("market_cap")
        mc_str = f"{mc/1e12:.1f}조" if mc else "-"
        lines.append(
            f"{name} | {info['close']:,} | {sign}{info['change_pct']:.2f}% "
            f"| {rsi} | {hist} | {per} | {pbr} | {mc_str}"
        )

    # 뉴스
    lines.append("\n### 종목별 최근 뉴스")
    for name, info in market_data.get("kr_stocks", {}).items():
        news_list = info.get("news", [])
        if news_list:
            lines.append(f"**{name}**")
            for n in news_list:
                lines.append(f"  - [{n['publisher']}] {n['title']}")

    return "\n".join(lines)


def collect_market_data() -> dict:
    logger.info("미 증시 지수 수집...")
    us_indices = collect_us_indices()

    logger.info("한국 지수 수집...")
    kr_indices = collect_kr_indices()

    logger.info("한국 종목 수집 (RSI/MACD/PER/PBR/뉴스)...")
    kr_stocks = collect_kr_stocks()

    market_data = {
        "us_indices":   us_indices,
        "kr_indices":   kr_indices,
        "kr_stocks":    kr_stocks,
        "collected_at": datetime.now().isoformat(),
    }
    market_data["prompt_text"] = format_market_data_for_prompt(market_data)
    return market_data

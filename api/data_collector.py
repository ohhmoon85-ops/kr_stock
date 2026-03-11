"""
시장 데이터 수집 모듈
- 미 증시: S&P500, NASDAQ, 필라델피아 반도체
- 한국 증시: KOSPI, KOSDAQ 상위 종목 + RSI/MACD + 시가총액 필터
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
    "카카오게임즈":       "293490.KQ",
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
    "롯데케미칼":         "011170.KS",
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

# 시가총액 최소 기준: 1조원 (단위: KRW)
MIN_MARKET_CAP = 1_000_000_000_000


def _calc_rsi(closes: pd.Series, period: int = 14) -> float:
    """RSI(상대강도지수) 계산. 30 이하 과매도, 70 이상 과매수"""
    delta = closes.diff()
    gains = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)
    avg_gain = gains.rolling(period).mean()
    avg_loss = losses.rolling(period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return round(float(val), 1) if not pd.isna(val) else None


def _calc_macd(closes: pd.Series):
    """MACD 계산. macd > signal 이면 상승 모멘텀"""
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return {
        "macd":      round(float(macd.iloc[-1]), 0),
        "signal":    round(float(signal.iloc[-1]), 0),
        "histogram": round(float(hist.iloc[-1]), 0),
    }


def _get_price_info(ticker: str, include_technicals: bool = False) -> dict:
    """단일 티커 가격 정보 + 기술적 지표 반환"""
    try:
        tk = yf.Ticker(ticker)
        period = "60d" if include_technicals else "5d"
        hist = tk.history(period=period)
        if hist.empty or len(hist) < (26 if include_technicals else 2):
            return {}

        closes = hist["Close"]
        prev_close = closes.iloc[-2]
        last_close = closes.iloc[-1]
        change_pct = (last_close - prev_close) / prev_close * 100
        volume = hist["Volume"].iloc[-1]

        info = {
            "close":      round(float(last_close), 0),
            "prev_close": round(float(prev_close), 0),
            "change_pct": round(float(change_pct), 2),
            "volume":     int(volume),
            "high":       round(float(hist["High"].iloc[-1]), 0),
            "low":        round(float(hist["Low"].iloc[-1]), 0),
        }

        if include_technicals:
            info["rsi"]  = _calc_rsi(closes)
            info["macd"] = _calc_macd(closes)

            # 시가총액 (fast_info 사용 - 추가 API 호출 없음)
            try:
                mc = tk.fast_info.market_cap
                info["market_cap"] = int(mc) if mc else None
            except Exception:
                info["market_cap"] = None

        return info
    except Exception as e:
        logger.warning(f"티커 {ticker} 조회 실패: {e}")
        return {}


def collect_us_indices() -> dict:
    result = {}
    for name, ticker in US_INDICES.items():
        info = _get_price_info(ticker)
        if info:
            result[name] = info
            logger.info(f"  {name}: {info['close']} ({info['change_pct']:+.2f}%)")
    return result


def collect_kr_indices() -> dict:
    result = {}
    for name, ticker in KR_INDICES.items():
        info = _get_price_info(ticker)
        if info:
            result[name] = info
            logger.info(f"  {name}: {info['close']} ({info['change_pct']:+.2f}%)")
    return result


def collect_kr_stocks() -> dict:
    """한국 주요 종목 수집 + RSI/MACD + 시가총액 1조원 이상 필터"""
    result = {}
    for name, ticker in KR_STOCKS.items():
        info = _get_price_info(ticker, include_technicals=True)
        if not info:
            continue

        # 시가총액 1조원 미만 제외
        mc = info.get("market_cap")
        if mc and mc < MIN_MARKET_CAP:
            logger.info(f"  {name} 시가총액 미달 제외 ({mc/1e12:.1f}조)")
            continue

        result[name] = {**info, "ticker": ticker}

    # RSI 40~65 구간(적정 모멘텀) 우선 정렬, 그 외 거래량 순
    def score(item):
        rsi = item[1].get("rsi") or 50
        vol = item[1].get("volume", 0)
        macd_hist = (item[1].get("macd") or {}).get("histogram", 0)
        # RSI 40~65: 과매수/과매도 아닌 모멘텀 구간에 높은 점수
        rsi_score = 1 if 40 <= rsi <= 65 else 0
        # MACD 히스토그램 양수면 상승 모멘텀
        macd_score = 1 if macd_hist > 0 else 0
        return (rsi_score + macd_score, vol)

    sorted_stocks = sorted(result.items(), key=score, reverse=True)
    top_stocks = dict(sorted_stocks[:25])
    logger.info(f"  한국 종목 최종 선별: {len(top_stocks)}개 (시가총액 1조+ 필터 적용)")
    return top_stocks


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

    # 한국 종목 (RSI/MACD 포함)
    lines.append("\n### 한국 주요 종목 (시가총액 1조원 이상, 기술적 지표 포함)")
    lines.append("종목명 | 종가 | 등락률 | RSI | MACD히스토그램 | 거래량 | 시가총액(조)")
    lines.append("---|---|---|---|---|---|---")
    for name, info in market_data.get("kr_stocks", {}).items():
        sign = "+" if info["change_pct"] >= 0 else ""
        rsi  = info.get("rsi") or "-"
        macd = info.get("macd") or {}
        hist = macd.get("histogram", "-")
        mc   = info.get("market_cap")
        mc_str = f"{mc/1e12:.1f}조" if mc else "-"
        lines.append(
            f"{name} | {info['close']:,} | {sign}{info['change_pct']:.2f}% "
            f"| {rsi} | {hist} | {info['volume']:,} | {mc_str}"
        )

    return "\n".join(lines)


def collect_market_data() -> dict:
    logger.info("미 증시 지수 수집...")
    us_indices = collect_us_indices()

    logger.info("한국 지수 수집...")
    kr_indices = collect_kr_indices()

    logger.info("한국 종목 수집 (RSI/MACD/시가총액)...")
    kr_stocks = collect_kr_stocks()

    market_data = {
        "us_indices":   us_indices,
        "kr_indices":   kr_indices,
        "kr_stocks":    kr_stocks,
        "collected_at": datetime.now().isoformat(),
    }
    market_data["prompt_text"] = format_market_data_for_prompt(market_data)
    return market_data

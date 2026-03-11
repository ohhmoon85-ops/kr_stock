"""
시장 데이터 수집 모듈
- 미 증시: S&P500, NASDAQ, 필라델피아 반도체
- 한국 증시: KOSPI, KOSDAQ 상위 종목
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# ── 미 증시 주요 지수 티커 ──────────────────────────────────────────────────
US_INDICES = {
    "S&P500":           "^GSPC",
    "NASDAQ":           "^IXIC",
    "필라델피아 반도체": "^SOX",
    "다우존스":         "^DJI",
    "VIX(공포지수)":    "^VIX",
}

# ── 한국 주요 종목 (섹터별 대표주) ─────────────────────────────────────────
KR_STOCKS = {
    # 반도체
    "삼성전자":    "005930.KS",
    "SK하이닉스":  "000660.KS",
    "DB하이텍":    "000990.KS",
    "리노공업":    "058470.KS",
    # 2차전지
    "LG에너지솔루션": "373220.KS",
    "삼성SDI":    "006400.KS",
    "에코프로비엠": "247540.KQ",
    "포스코퓨처엠": "003670.KS",
    # 바이오/헬스케어
    "삼성바이오로직스": "207940.KS",
    "셀트리온":    "068270.KS",
    "유한양행":    "000100.KS",
    "HLB":        "028300.KQ",
    # IT/플랫폼
    "NAVER":      "035420.KS",
    "카카오":     "035720.KS",
    "크래프톤":   "259960.KS",
    "카카오게임즈": "293490.KQ",
    # 자동차
    "현대차":     "005380.KS",
    "기아":       "000270.KS",
    "현대모비스": "012330.KS",
    # 금융
    "KB금융":     "105560.KS",
    "신한지주":   "055550.KS",
    "하나금융지주": "086790.KS",
    # 에너지/화학
    "LG화학":     "051910.KS",
    "롯데케미칼": "011170.KS",
    "한화솔루션": "009830.KS",
    # 방산/우주
    "한화에어로스페이스": "012450.KS",
    "LIG넥스원":  "079550.KS",
    "현대로템":   "064350.KS",
    # 조선
    "HD현대중공업": "329180.KS",
    "삼성중공업": "010140.KS",
    "한화오션":   "042660.KS",
}

# ── KOSPI / KOSDAQ 지수 ────────────────────────────────────────────────────
KR_INDICES = {
    "KOSPI":  "^KS11",
    "KOSDAQ": "^KQ11",
}


def _get_price_info(ticker: str, period: str = "5d") -> dict:
    """단일 티커의 가격 정보 반환"""
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period=period)
        if hist.empty or len(hist) < 2:
            return {}

        prev_close = hist["Close"].iloc[-2]
        last_close = hist["Close"].iloc[-1]
        change_pct = (last_close - prev_close) / prev_close * 100
        volume = hist["Volume"].iloc[-1]

        return {
            "close":      round(float(last_close), 2),
            "prev_close": round(float(prev_close), 2),
            "change_pct": round(float(change_pct), 2),
            "volume":     int(volume),
            "high":       round(float(hist["High"].iloc[-1]), 2),
            "low":        round(float(hist["Low"].iloc[-1]), 2),
        }
    except Exception as e:
        logger.warning(f"티커 {ticker} 조회 실패: {e}")
        return {}


def collect_us_indices() -> dict:
    """미 증시 주요 지수 수집"""
    result = {}
    for name, ticker in US_INDICES.items():
        info = _get_price_info(ticker)
        if info:
            result[name] = info
            logger.info(f"  {name}: {info['close']} ({info['change_pct']:+.2f}%)")
    return result


def collect_kr_indices() -> dict:
    """한국 지수 수집"""
    result = {}
    for name, ticker in KR_INDICES.items():
        info = _get_price_info(ticker)
        if info:
            result[name] = info
            logger.info(f"  {name}: {info['close']} ({info['change_pct']:+.2f}%)")
    return result


def collect_kr_stocks() -> dict:
    """한국 주요 종목 데이터 수집 (상위 종목 필터링)"""
    result = {}
    for name, ticker in KR_STOCKS.items():
        info = _get_price_info(ticker)
        if info:
            result[name] = {**info, "ticker": ticker}

    # 거래량 기준 정렬 후 상위 30개 반환 (토큰 절약)
    sorted_stocks = sorted(result.items(), key=lambda x: x[1].get("volume", 0), reverse=True)
    top_stocks = dict(sorted_stocks[:30])
    logger.info(f"  한국 종목 수집 완료: {len(top_stocks)}개")
    return top_stocks


def format_market_data_for_prompt(market_data: dict) -> str:
    """수집된 데이터를 LLM 프롬프트용 텍스트로 변환"""
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

    # 한국 종목
    lines.append("\n### 한국 주요 종목 (거래량 상위, 전일 종가 기준)")
    lines.append("종목명 | 종가 | 등락률 | 고가 | 저가 | 거래량")
    lines.append("---|---|---|---|---|---")
    for name, info in market_data.get("kr_stocks", {}).items():
        sign = "+" if info["change_pct"] >= 0 else ""
        vol_str = f"{info['volume']:,}"
        lines.append(
            f"{name} | {info['close']:,} | {sign}{info['change_pct']:.2f}% "
            f"| {info['high']:,} | {info['low']:,} | {vol_str}"
        )

    return "\n".join(lines)


def collect_market_data() -> dict:
    """전체 시장 데이터 수집 메인 함수"""
    logger.info("미 증시 지수 수집...")
    us_indices = collect_us_indices()

    logger.info("한국 지수 수집...")
    kr_indices = collect_kr_indices()

    logger.info("한국 종목 수집...")
    kr_stocks = collect_kr_stocks()

    market_data = {
        "us_indices": us_indices,
        "kr_indices": kr_indices,
        "kr_stocks":  kr_stocks,
        "collected_at": datetime.now().isoformat(),
    }

    market_data["prompt_text"] = format_market_data_for_prompt(market_data)
    return market_data

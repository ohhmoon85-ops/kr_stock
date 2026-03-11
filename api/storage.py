"""
GitHub 저장소 기반 영구 데이터 저장소
추천 종목 이력을 data/weekly_picks.json 파일에 저장
"""

import os
import json
import base64
import logging
import requests
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

REPO      = "ohhmoon85-ops/kr_stock"
FILE_PATH = "data/weekly_picks.json"
API_BASE  = "https://api.github.com"


def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN 환경 변수가 필요합니다.")
    return {
        "Authorization":        f"Bearer {token}",
        "Accept":               "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _fetch_file() -> tuple:
    """GitHub에서 현재 파일 로드. (content_dict, sha) 반환"""
    url  = f"{API_BASE}/repos/{REPO}/contents/{FILE_PATH}"
    resp = requests.get(url, headers=_headers(), timeout=10)
    if resp.status_code == 404:
        return {"history": []}, None
    resp.raise_for_status()
    data    = resp.json()
    decoded = json.loads(base64.b64decode(data["content"]).decode("utf-8"))
    return decoded, data["sha"]


def save_weekly_picks(picks: list) -> None:
    """
    이번 주 추천 종목을 GitHub에 저장.
    picks: [{"name":..., "ticker":..., "entry_price":...,
              "target_price":..., "stop_price":...}, ...]
    """
    if not picks:
        logger.warning("저장할 추천 종목이 없습니다.")
        return

    current, sha = _fetch_file()
    history = current.get("history", [])

    history.append({
        "date":  datetime.now().strftime("%Y-%m-%d"),
        "picks": picks,
    })
    history = history[-2:]            # 이번 주 + 지난 주 2건만 보관
    current["history"] = history

    encoded = base64.b64encode(
        json.dumps(current, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("utf-8")

    payload = {
        "message": f"chore: 주간 추천 종목 저장 {history[-1]['date']}",
        "content": encoded,
    }
    if sha:
        payload["sha"] = sha

    url  = f"{API_BASE}/repos/{REPO}/contents/{FILE_PATH}"
    resp = requests.put(url, json=payload, headers=_headers(), timeout=15)
    resp.raise_for_status()
    logger.info(f"추천 종목 저장 완료: {len(picks)}개")


def load_last_week_picks() -> dict | None:
    """
    약 7일 전(5~9일 허용) 추천 종목 반환.
    없으면 None.
    """
    try:
        current, _ = _fetch_file()
        history    = current.get("history", [])
        now        = datetime.now()

        for entry in reversed(history):
            entry_date = datetime.strptime(entry["date"], "%Y-%m-%d")
            diff_days  = (now - entry_date).days
            if 5 <= diff_days <= 9:
                logger.info(f"지난주 데이터 발견: {entry['date']} ({diff_days}일 전)")
                return entry

        logger.info("평가 가능한 지난주 데이터 없음")
        return None
    except Exception as e:
        logger.error(f"지난주 데이터 로드 실패: {e}")
        return None

"""
텔레그램 메시지 전송 모듈
- 긴 메시지 자동 분할 (텔레그램 4096자 제한)
- Markdown V2 포맷 지원
"""

import os
import requests
import logging

logger = logging.getLogger(__name__)

TELEGRAM_MAX_LENGTH = 4000  # 안전 마진 포함 (실제 제한: 4096)


def _split_message(text: str, max_length: int = TELEGRAM_MAX_LENGTH) -> list[str]:
    """긴 메시지를 텔레그램 제한에 맞게 분할"""
    if len(text) <= max_length:
        return [text]

    parts = []
    while text:
        if len(text) <= max_length:
            parts.append(text)
            break
        # 마지막 줄바꿈 기준으로 자르기
        split_at = text.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = max_length
        parts.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return parts


def send_telegram_message(text: str) -> bool:
    """텔레그램 채널/채팅방으로 메시지 전송"""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id   = os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 환경 변수가 설정되지 않았습니다."
        )

    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    parts   = _split_message(text)

    for i, part in enumerate(parts, 1):
        payload = {
            "chat_id":    chat_id,
            "text":       part,
            "parse_mode": "Markdown",
            # 링크 미리보기 비활성화 (깔끔한 메시지)
            "disable_web_page_preview": True,
        }

        response = requests.post(api_url, json=payload, timeout=30)

        if not response.ok:
            logger.error(
                f"텔레그램 전송 실패 (파트 {i}/{len(parts)}): "
                f"{response.status_code} - {response.text}"
            )
            # Markdown 파싱 오류 시 plain text로 재시도
            if response.status_code == 400:
                payload["parse_mode"] = None
                payload.pop("parse_mode")
                response = requests.post(api_url, json=payload, timeout=30)
                if not response.ok:
                    raise RuntimeError(f"텔레그램 전송 최종 실패: {response.text}")
        else:
            logger.info(f"텔레그램 전송 성공 (파트 {i}/{len(parts)})")

    return True

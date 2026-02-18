import os
import json
import time
import requests
from typing import List, Dict, Any

BIZINFO_API_URL = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
SEEN_PATH = "seen.json"

# 1) 키워드(요청 + 유사어)
KEYWORDS = [
    "전북", "전라북도", "충남", "충청남도", "천안", "천안시",
    "융자", "대출", "자금", "자금지원", "정책자금", "보증", "이차보전",
    "지원", "지원사업", "사업", "수출", "수출지원", "해외진출", "바우처", "수출바우처"
]

# 2) Bizinfo 해시태그(1차 필터)
HASHTAGS = ["전북", "충남", "수출"]


def load_seen() -> set:
    if not os.path.exists(SEEN_PATH):
        return set()
    try:
        with open(SEEN_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(seen: set):
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(list(seen)), f, ensure_ascii=False, indent=2)


def normalize_items(data: Any) -> List[Dict]:
    """
    Bizinfo API JSON 응답 표준화:
    - data가 list -> [{...},{...}] 형태면 그대로
    - data가 dict ->
        - jsonArray가 list 인 경우: 그 list가 곧 공고 리스트
        - jsonArray가 dict 인 경우: jsonArray.item 에 공고 리스트가 있음
    """

    # 1) data 자체가 list인 경우
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]

    # 2) data가 dict인 경우
    if isinstance(data, dict):
        json_array = data.get("jsonArray", None)

        # ✅ 이번에 나온 케이스: jsonArray가 list
        if isinstance(json_array, list):
            return [x for x in json_array if isinstance(x, dict)]

        # ✅ 다른 케이스: jsonArray가 dict이고 그 안에 item이 있음
        if isinstance(json_array, dict):
            items = json_array.get("item", [])
            if isinstance(items, dict):
                return [items]
            if isinstance(items, list):
                return [x for x in items if isinstance(x, dict)]
            return []

        return []

    return []


def fetch_bizinfo_items(crtfc_key: str, search_cnt: int = 200) -> List[Dict]:
    params = {
        "crtfcKey": crtfc_key,
        "dataType": "json",
        "searchCnt": str(search_cnt),
        "hashtags": ",".join(HASHTAGS),
    }

    r = requests.get(BIZINFO_API_URL, params=params, timeout=30)
    r.raise_for_status()

    data = r.json()

    # ✅ 에러/비정상 응답 판별을 위해 초반 일부만 출력(문제 있을 때만)
    items = normalize_items(data)
    if not items:
        # items가 비어있다면, 원인을 보기 위해 응답 형태를 출력
        preview = str(data)
        if len(preview) > 500:
            preview = preview[:500] + " ..."
        print("DEBUG: Bizinfo 응답이 공고 리스트로 파싱되지 않았습니다.")
        print("DEBUG: type(data) =", type(data))
        print("DEBUG: preview =", preview)

    return items


def matches_keywords(item: Dict) -> bool:
    text = " ".join([
        str(item.get("title", "")),
        str(item.get("description", "")),
        str(item.get("author", "")),
        str(item.get("excInsttNm", "")),
        str(item.get("hashTags", "")),
        str(item.get("reqstDt", "")),
        str(item.get("link", "")),
    ])
    return any(k in text for k in KEYWORDS)


def telegram_send(bot_token: str, chat_id: str, message: str):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }
    r = requests.post(url, data=payload, timeout=30)
    r.raise_for_status()


def format_message(item: Dict) -> str:
    title = item.get("title") or item.get("pblancNm") or "(제목 없음)"

    link = item.get("link", "")
    reqst = item.get("reqstDt", "")
    author = item.get("author", "")
    tags = item.get("hashTags", "")

    return (
        "📌 [기업마당 신규 지원사업 알림]\n"
        f"• 제목: {title}\n"
        f"• 소관: {author}\n"
        f"• 신청기간: {reqst}\n"
        f"• 해시태그: {tags}\n"
        f"• 링크: {link}"
    )


def main():
    crtfc_key = os.environ.get("BIZINFO_CRTFC_KEY", "").strip()
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not crtfc_key or not bot_token or not chat_id:
        raise SystemExit(
            "환경변수(BIZINFO_CRTFC_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)가 비어있습니다.\n"
            "CMD에서 아래로 확인하세요:\n"
            "echo %BIZINFO_CRTFC_KEY%\n"
            "echo %TELEGRAM_BOT_TOKEN%\n"
            "echo %TELEGRAM_CHAT_ID%\n"
        )

    seen = load_seen()
    items = fetch_bizinfo_items(crtfc_key, search_cnt=200)

    # 파싱이 안 됐으면 여기서 종료
    if not items:
        print("공고 리스트를 가져오지 못했습니다. 위 DEBUG 내용을 확인하세요.")
        return

    new_hits = []
    for it in items:
        seq = str(it.get("seq") or it.get("pblancId") or it.get("link") or "")
        if not seq:
            continue
        if seq in seen:
            continue
        if matches_keywords(it):
            new_hits.append((seq, it))

    if not new_hits:
        print("신규 조건 일치 공고 없음")
        return

    sent = 0
    for seq, it in new_hits[:30]:
        telegram_send(bot_token, chat_id, format_message(it))
        seen.add(seq)
        sent += 1
        time.sleep(0.5)

    save_seen(seen)
    print(f"발송 완료: {sent}건")


if __name__ == "__main__":
    main()

import os
import json
import time
import hashlib
import requests
from typing import List, Dict, Any
from bs4 import BeautifulSoup

# K-Startup 공고 목록 (모집중)
KSTARTUP_URLS = [
    "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do",
    # 필요하면 마감공고도 추가 가능
    # "https://www.k-startup.go.kr/web/contents/bizpbanc-finished.do",
]

SEEN_PATH = "seen_kstartup.json"

# 키워드(요청 + 유사어 + 지역 확장)
KEYWORDS = [
    # 지역
    "전북", "전라북도", "전주시", "익산시", "군산", "김제", "완주",
    "충남", "충청남도", "천안", "천안시", "아산", "당진",
    # 자금/지원
    "융자", "대출", "자금", "자금지원", "정책자금", "보증", "이차보전",
    "지원", "지원사업", "사업화", "실증", "실증사업", "실증지원",
    "과제", "R&D", "R&D사업", "연구개발", "기술개발",
    # 수출/해외
    "수출", "수출지원", "해외진출", "바우처", "수출바우처", "글로벌", "해외",
]

# 텔레그램
def telegram_send(bot_token: str, chat_id: str, message: str):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "disable_web_page_preview": True}
    r = requests.post(url, data=payload, timeout=30)
    r.raise_for_status()

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

def norm(s: str) -> str:
    return (s or "").strip()

def contains_keywords(text: str) -> bool:
    t = text or ""
    return any(k in t for k in KEYWORDS)

def make_id(title: str, link: str) -> str:
    raw = f"{title}|{link}".encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()

def fetch_kstartup_items() -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; bizinfo-alert/1.0)"
    }

    for url in KSTARTUP_URLS:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # K-Startup 페이지는 구조가 바뀔 수 있어서 "링크+제목" 중심으로 최대한 안전하게 수집
        # 공고 링크 후보: a 태그 중 'bizpbanc' 관련 또는 제목처럼 보이는 것
        for a in soup.select("a"):
            title = norm(a.get_text(" ", strip=True))
            href = a.get("href") or ""
            if not title or len(title) < 6:
                continue

            # 링크 정규화
            if href.startswith("/"):
                link = "https://www.k-startup.go.kr" + href
            elif href.startswith("http"):
                link = href
            else:
                # onclick 기반 등은 제외 (필요 시 나중에 보완)
                continue

            # 너무 광범위하게 잡히면 노이즈가 생기므로, 키워드 필터를 통과하는 것만 보관
            blob = f"{title} {link}"
            if contains_keywords(blob):
                items.append({"title": title, "link": link})

    # 중복 제거 (title+link 기준)
    uniq = {}
    for it in items:
        key = make_id(it["title"], it["link"])
        uniq[key] = it
    return list(uniq.values())

def format_message(it: Dict[str, str]) -> str:
    return "\n".join([
        "🚀 [K-Startup 신규 공고 알림]",
        f"• 제목: {it.get('title','')}",
        f"• 링크: {it.get('link','')}",
    ])

def main():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not bot_token or not chat_id:
        raise SystemExit("환경변수(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)가 비어있습니다.")

    seen = load_seen()
    items = fetch_kstartup_items()

    new_hits = []
    for it in items:
        sid = make_id(it.get("title",""), it.get("link",""))
        if sid in seen:
            continue
        new_hits.append((sid, it))

    if not new_hits:
        print("K-Startup: 신규 조건 일치 공고 없음")
        return

    # 너무 많으면 상위 30개만 발송
    for sid, it in new_hits[:30]:
        telegram_send(bot_token, chat_id, format_message(it))
        seen.add(sid)
        time.sleep(0.6)

    save_seen(seen)
    print(f"K-Startup: 발송 완료 {min(len(new_hits), 30)}건")

if __name__ == "__main__":
    main()

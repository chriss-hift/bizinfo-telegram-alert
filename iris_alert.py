import os
import re
import time
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup


IRIS_LIST_URL = "https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do"


def telegram_send(bot_token: str, chat_id: str, message: str):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }
    r = requests.post(url, data=payload, timeout=30)
    r.raise_for_status()


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; IRISAlertBot/1.0)",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text


def extract_receiving_items(html: str, limit: int = 30) -> List[Dict]:
    """
    IRIS '사업공고' 페이지에서 '접수중' 공고를 텍스트 패턴 기반으로 추출합니다.
    페이지 구조가 바뀌어도 비교적 버티도록 HTML을 텍스트로 변환 후 파싱합니다.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    # '#### 접수중' 이후 영역을 우선 사용 (페이지에 실제로 표시됨) :contentReference[oaicite:1]{index=1}
    # 혹시 표기 방식이 달라도 '접수중' 헤더를 기준으로 최대한 안정적으로 슬라이스
    idx = text.find("#### 접수중")
    if idx == -1:
        # 대체: '접수중' 단어 자체 기준 (덜 정확)
        idx = text.find("접수중")
    if idx != -1:
        text = text[idx:]

    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    items: List[Dict] = []
    i = 0

    # 패턴 예시(페이지에 실제 표기): 
    # "농림축산식품부 > 농림식품기술기획평가원"
    # "2026년도 ... 공고"
    # "공고번호 : ... 공고일자 :2026-02-13 공고상태 : 공고접수중 ..."
    ministry_pattern = re.compile(r".+\s>\s.+")
    date_pattern = re.compile(r"공고일자\s*:\s*(\d{4}-\d{2}-\d{2})")
    status_pattern = re.compile(r"공고상태\s*:\s*([^\s]+)")

    while i < len(lines) and len(items) < limit:
        ln = lines[i]

        # 기관 라인
        if ministry_pattern.fullmatch(ln):
            org = ln
            title = None
            meta = None

            # 다음 유효 라인에서 제목 탐색
            j = i + 1
            while j < len(lines):
                if lines[j].startswith("공고번호"):
                    meta = lines[j]
                    break
                # '접수중' 같은 단독 라벨은 스킵
                if lines[j] in ("접수중", "마감", "접수예정"):
                    j += 1
                    continue
                # 제목 후보
                if title is None:
                    title = lines[j]
                j += 1

            pub_date = None
            status = None
            if meta:
                m = date_pattern.search(meta)
                if m:
                    pub_date = m.group(1)
                s = status_pattern.search(meta)
                if s:
                    status = s.group(1)

            # '접수중'만 수집 (공고상태가 공고접수중 등으로 들어옴) :contentReference[oaicite:2]{index=2}
            if title and (status is None or "접수중" in status):
                items.append({
                    "org": org,
                    "title": title,
                    "pub_date": pub_date or "",
                    "status": status or "",
                    "link": IRIS_LIST_URL,  # 상세링크가 구조적으로 다를 수 있어 기본은 리스트 URL
                })

            i = j if j > i else i + 1
        else:
            i += 1

    return items


def build_message(items: List[Dict], max_items: int = 10) -> str:
    if not items:
        return "📌 [IRIS 접수중 공고] 오늘 신규/접수중 항목을 찾지 못했습니다."

    lines = ["📌 [IRIS 접수중 공고 요약]", f"총 {len(items)}건 (표시 {min(len(items), max_items)}건)"]
    for idx, it in enumerate(items[:max_items], 1):
        lines.append(
            f"\n{idx}. {it.get('title','(제목 없음)')}\n"
            f"   - 기관: {it.get('org','')}\n"
            f"   - 공고일자: {it.get('pub_date','')}\n"
            f"   - 링크: {it.get('link','')}"
        )
    return "\n".join(lines)


def main():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not bot_token or not chat_id:
        raise SystemExit("환경변수(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)가 비어있습니다. GitHub Secrets를 확인하세요.")

    html = fetch_html(IRIS_LIST_URL)
    items = extract_receiving_items(html, limit=40)

    # 접수중 요약 1메시지로 발송(폭탄 방지)
    msg = build_message(items, max_items=12)
    telegram_send(bot_token, chat_id, msg)
    time.sleep(0.2)


if __name__ == "__main__":
    main()

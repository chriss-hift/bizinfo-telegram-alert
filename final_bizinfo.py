import os
import json
import time
import requests
from typing import List, Dict, Any

BIZINFO_API_URL = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
SEEN_PATH = "seen.json"

# 1) 키워드(최종 필터) - 너무 넓으면 폭탄이 나서, 아래 matches_keywords는 "완화"로 유지하고
#    실제 전송은 classify_item()으로 카테고리화 + 요약 전송으로 운영합니다.
KEYWORDS = [
    "전북", "전라북도", "전북특별자치도",
    "충남", "충청남도", "천안", "천안시",
    "융자", "대출", "자금", "자금지원", "정책자금", "보증", "이차보전",
    "수출", "수출지원", "해외진출", "바우처", "수출바우처",
    "과제", "R&D", "r&d", "연구개발", "지원사업", "사업화", "실증", "PoC", "테스트베드", "검증"
]

# 2) Bizinfo 해시태그(1차 필터) - 너무 좁으면 놓치고, 너무 넓으면 많아집니다.
#    운영하면서 필요하면 조정하세요.
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
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]

    if isinstance(data, dict):
        json_array = data.get("jsonArray", None)

        if isinstance(json_array, list):
            return [x for x in json_array if isinstance(x, dict)]

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

    items = normalize_items(data)
    if not items:
        preview = str(data)
        if len(preview) > 500:
            preview = preview[:500] + " ..."
        print("DEBUG: Bizinfo 응답이 공고 리스트로 파싱되지 않았습니다.")
        print("DEBUG: type(data) =", type(data))
        print("DEBUG: preview =", preview)

    return items


def matches_keywords(item: Dict) -> bool:
    """
    1차 완화 필터: 여기서 너무 빡세게 걸면 놓칠 수 있어서,
    '대략 관련 가능성'만 통과시키고, 실제는 classify_item()로 카테고리 분류 후 전송합니다.
    """
    text = " ".join([
        str(item.get("title", "")),
        str(item.get("pblancNm", "")),
        str(item.get("description", "")),
        str(item.get("author", "")),
        str(item.get("excInsttNm", "")),
        str(item.get("hashTags", "")),
        str(item.get("reqstDt", "")),
        str(item.get("link", "")),
    ])
    return any(k in text for k in KEYWORDS)


def classify_item(item: Dict) -> str:
    """
    카테고리 분류:
    - 수출
    - 융자·자금
    - R&D·사업화(과제/실증/지원사업 포함)
    - 전북(전북특별자치도 포함, 전 시·군)
    - 충남·천안(요청 범위: 충남/천안/천안시)
    기타는 None 반환 (전송하지 않음)
    """
    text = " ".join([
        str(item.get("title", "")),
        str(item.get("pblancNm", "")),
        str(item.get("description", "")),
        str(item.get("hashTags", "")),
        str(item.get("hashtags", "")),
        str(item.get("reqstDt", "")),
        str(item.get("link", "")),
    ])

    JEONBUK_TERMS = [
        "전북", "전라북도", "전북특별자치도",
        "전주시", "군산시", "익산시", "정읍시", "남원시", "김제시",
        "완주군", "진안군", "무주군", "장수군", "임실군", "순창군",
        "고창군", "부안군"
    ]

    # 충남은 아직 "충남/충청남도/천안" 중심 (원하면 충남 전 시·군도 확장 가능)
    CHUNGNAM_TERMS = ["충남", "충청남도", "천안", "천안시"]

    FIN_TERMS = ["융자", "대출", "정책자금", "보증", "이차보전", "자금", "자금지원", "운전자금", "시설자금"]
    EXPORT_TERMS = ["수출", "해외진출", "수출지원", "수출바우처", "바우처", "해외마케팅", "해외전시", "무역", "통상"]
    RND_TERMS = ["과제", "R&D", "r&d", "연구개발", "지원사업", "사업화", "실증", "PoC", "poc", "테스트베드", "검증", "시범", "데모"]

    is_exp = any(k in text for k in EXPORT_TERMS)
    is_fin = any(k in text for k in FIN_TERMS)
    is_rnd = any(k in text for k in RND_TERMS)
    is_jb = any(k in text for k in JEONBUK_TERMS)
    is_cn = any(k in text for k in CHUNGNAM_TERMS)

    # 우선순위: 목적형(수출/금융/R&D) → 지역
    if is_exp:
        return "수출"
    if is_fin:
        return "융자·자금"
    if is_rnd:
        return "R&D·사업화"
    if is_jb:
        return "전북"
    if is_cn:
        return "충남·천안"

    return None


def telegram_send(bot_token: str, chat_id: str, message: str):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }
    r = requests.post(url, data=payload, timeout=30)
    r.raise_for_status()


def build_category_message(category: str, items: List[Dict], max_items: int = 10) -> str:
    """
    카테고리별 '요약 1메시지' 생성: 폭탄 방지 핵심
    """
    def _title(it: Dict) -> str:
        return it.get("title") or it.get("pblancNm") or "(제목 없음)"

    def _link(it: Dict) -> str:
        return it.get("link") or it.get("pblancUrl") or ""

    def _period(it: Dict) -> str:
        return it.get("reqstDt") or it.get("reqstBeginEndDe") or ""

    lines = [
        f"📌 [기업마당 신규 알림 | {category}]",
        f"총 {len(items)}건 (표시 {min(len(items), max_items)}건)"
    ]

    for i, it in enumerate(items[:max_items], 1):
        lines.append(f"\n{i}. {_title(it)}\n   - 신청: {_period(it)}\n   - {_link(it)}")

    return "\n".join(lines)


def main():
    crtfc_key = os.environ.get("BIZINFO_CRTFC_KEY", "").strip()
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not crtfc_key or not bot_token or not chat_id:
        raise SystemExit(
            "환경변수(BIZINFO_CRTFC_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)가 비어있습니다.\n"
            "GitHub Actions Secrets에 3개 모두 있는지 확인하세요.\n"
        )

    seen = load_seen()
    items = fetch_bizinfo_items(crtfc_key, search_cnt=200)

    if not items:
        print("공고 리스트를 가져오지 못했습니다. 위 DEBUG 내용을 확인하세요.")
        return

    # 신규 + 1차 필터 통과만 추림
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

    # ✅ 폭주 방지: 하루 처리 상한 (원하면 30/100 등으로 변경)
    top = new_hits[:60]

    # ✅ 카테고리별로 묶기
    grouped: Dict[str, List[Dict]] = {}
    seq_by_cat: Dict[str, List[str]] = {}

    for seq, it in top:
        cat = classify_item(it)
        if not cat:
            continue
        grouped.setdefault(cat, []).append(it)
        seq_by_cat.setdefault(cat, []).append(seq)

    # 카테고리별로 아무것도 없으면 종료(=키워드는 잡혔는데 분류 기준엔 안 맞는 경우)
    if not grouped:
        print("신규 공고는 있으나 지정한 카테고리(수출/융자/R&D/전북/충남)에 해당 없음")
        # 그래도 중복 폭주를 막으려면 seen 처리할지 선택인데,
        # 여기선 '알림 안 보낸 건'은 다시 뜰 수 있게 seen 처리 안 함.
        return

    # ✅ 발송 순서 고정
    order = ["수출", "융자·자금", "R&D·사업화", "전북", "충남·천안"]

    sent_msgs = 0
    for cat in order:
        if cat not in grouped:
            continue
        msg = build_category_message(cat, grouped[cat], max_items=10)
        telegram_send(bot_token, chat_id, msg)
        sent_msgs += 1
        time.sleep(0.8)

        # ✅ 발송한 것만 seen 처리
        for seq in seq_by_cat.get(cat, []):
            seen.add(seq)

    save_seen(seen)
    print(f"카테고리 요약 발송 완료: {sent_msgs}개 메시지")


if __name__ == "__main__":
    main()

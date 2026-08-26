아래 코드를 `app.py`의 기존 내용 전체를 지우고 그대로 붙여넣으세요.

```python
import html
import io
import json
import os
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


st.set_page_config(
    page_title="AI 기반 보험 트렌드 인텔리전스",
    page_icon="📈",
    layout="wide",
)

NAVER_CLIENT_ID = str(st.secrets.get("NAVER_CLIENT_ID", "")).strip()
NAVER_CLIENT_SECRET = str(st.secrets.get("NAVER_CLIENT_SECRET", "")).strip()
GEMINI_API_KEY = str(st.secrets.get("GEMINI_API_KEY", "")).strip()

NAVER_URL = "https://openapi.naver.com/v1/search/news.json"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/"
    "v1beta/models/gemini-3.6-flash:generateContent"
)

KOREAN_FONT_PATH = r"C:\Windows\Fonts\malgun.ttf"
KOREAN_BOLD_FONT_PATH = r"C:\Windows\Fonts\malgunbd.ttf"

TARGET_PRESS_CONFIG = {
    "한국보험신문": {
        "type": "보험 전문지",
        "domains": ["insweek.co.kr"],
        "query": '"한국보험신문" 보험',
    },
    "보험매일": {
        "type": "보험 전문지",
        "domains": ["fins.co.kr"],
        "query": '"보험매일" 보험',
    },
    "보험신문": {
        "type": "보험 전문지",
        "domains": ["bohumnews.com"],
        "query": '"보험신문" 보험',
    },
    "대한금융신문": {
        "type": "금융 전문지",
        "domains": ["kbanker.co.kr"],
        "query": '"대한금융신문" 보험',
    },
    "CEO스코어데일리": {
        "type": "기업·경영 전문지",
        "domains": ["ceoscoredaily.com"],
        "query": '"CEO스코어데일리" 보험',
    },
    "매일경제": {
        "type": "경제지",
        "domains": ["mk.co.kr"],
        "query": '"매일경제" 보험',
    },
    "한국경제": {
        "type": "경제지",
        "domains": ["hankyung.com"],
        "query": '"한국경제" 보험',
    },
    "머니투데이": {
        "type": "경제지",
        "domains": ["mt.co.kr"],
        "query": '"머니투데이" 보험',
    },
    "서울경제": {
        "type": "경제지",
        "domains": ["sedaily.com"],
        "query": '"서울경제" 보험',
    },
    "연합뉴스": {
        "type": "종합지",
        "domains": ["yna.co.kr", "yonhapnewstv.co.kr"],
        "query": '"연합뉴스" 보험',
    },
}


def add_error(message):
    st.session_state.setdefault("api_errors", [])

    if message not in st.session_state["api_errors"]:
        st.session_state["api_errors"].append(message)


def clean_html(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def normalize_title(title):
    title = re.sub(r"\[.*?\]|\(.*?\)", "", title or "")
    title = re.sub(r"[^\w\s]", " ", title.lower())

    return set(title.split())


def is_duplicate_article(tokens, previous_tokens):
    for previous in previous_tokens:
        if not tokens or not previous:
            continue

        similarity = len(tokens & previous) / len(tokens | previous)

        if similarity >= 0.55:
            return True

    return False


def is_insurance_industry_article(title, description):
    """
    보험회사·보험상품·보험산업과 직접 연관된 기사만 통과시킵니다.
    국민건강보험 등 공적 건강보험 중심 기사는 제외합니다.
    """
    text = f"{title} {description}".lower()

    insurance_terms = [
        "보험사",
        "보험회사",
        "보험업",
        "보험업계",
        "생명보험",
        "손해보험",
        "보험상품",
        "보험료",
        "보험금",
        "보험계약",
        "보험설계사",
        "보험대리점",
        "ga",
        "실손보험",
        "자동차보험",
        "운전자보험",
        "암보험",
        "펫보험",
        "치아보험",
        "여행자보험",
        "보장성보험",
        "저축성보험",
        "변액보험",
        "연금보험",
        "재보험",
        "ifrs17",
        "csm",
        "k-ics",
    ]

    public_health_terms = [
        "국민건강보험공단",
        "건강보험심사평가원",
        "건강보험료 부과",
        "건강보험 재정",
        "건보료",
        "의료보험",
    ]

    has_insurance_term = any(term in text for term in insurance_terms)
    is_public_health_topic = any(term in text for term in public_health_terms)

    return has_insurance_term and not is_public_health_topic


@st.cache_resource
def register_korean_pdf_font():
    try:
        pdfmetrics.registerFont(
            TTFont("MalgunGothic", KOREAN_FONT_PATH)
        )
        pdfmetrics.registerFont(
            TTFont("MalgunGothic-Bold", KOREAN_BOLD_FONT_PATH)
        )

        return "MalgunGothic", "MalgunGothic-Bold"

    except Exception as error:
        add_error(f"PDF 한글 폰트 등록 실패: {error}")

        return "Helvetica", "Helvetica-Bold"


def fallback_score(title, description, published_at):
    text = f"{title} {description}".lower()

    industry = 23 if any(word in text for word in [
        "ifrs17", "csm", "k-ics", "지급여력", "자본확충"
    ]) else 18 if any(word in text for word in [
        "손해율", "언더라이팅", "수익성"
    ]) else 10

    policy = 18 if any(word in text for word in [
        "금감원", "금융위", "금융감독원", "감독규정", "시행령"
    ]) else 13 if any(word in text for word in [
        "제도개편", "개선안", "공청회"
    ]) else 5

    consumer = 18 if any(word in text for word in [
        "실손", "비급여", "보험료", "약관", "지급기준"
    ]) else 13 if any(word in text for word in [
        "펫보험", "유병자", "고령", "치매"
    ]) else 5

    market = 17 if any(word in text for word in [
        "점유율", "가격경쟁", "ga", "제3보험"
    ]) else 12 if any(word in text for word in [
        "신상품", "특약", "담보"
    ]) else 6

    days = max(0, (datetime.now() - published_at).days)
    timeliness = 14 if days <= 1 else 11 if days <= 3 else 8 if days <= 5 else 4

    return {
        "article_importance_score": industry + policy + consumer + market + timeliness,
        "industry_score": industry,
        "policy_score": policy,
        "consumer_score": consumer,
        "market_score": market,
        "timeliness_score": timeliness,
        "importance_reason": "Gemini API 연결 실패 시 적용되는 규칙 기반 보조 평가입니다.",
        "eval_mode": "Fallback",
    }


def gemini_json(prompt):
    if not GEMINI_API_KEY:
        add_error("Gemini API 키가 설정되지 않았습니다.")

        return None

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt,
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
        },
    }

    try:
        response = requests.post(
            GEMINI_URL,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": GEMINI_API_KEY,
            },
            json=payload,
            timeout=45,
        )

        response.raise_for_status()

        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]

        return json.loads(text)

    except requests.RequestException as error:
        detail = (
            error.response.text[:500]
            if error.response is not None
            else str(error)
        )

        add_error(f"Gemini: {detail}")

    except (KeyError, IndexError, ValueError) as error:
        add_error(f"Gemini 응답 형식 오류: {error}")

    return None


def evaluate_articles_with_gemini(articles):
    if not articles:
        return []

    article_text = "\n\n".join(
        (
            f"기사 #{index}\n"
            f"제목: {article['기사제목']}\n"
            f"요약: {article['기사내용']}\n"
            f"언론사: {article['언론사']}"
        )
        for index, article in enumerate(articles, 1)
    )

    prompt = f"""
당신은 대한민국 보험산업 분석가입니다.

아래 보험 기사만 근거로 중요도를 평가하세요.

{article_text}

반드시 JSON 형식만 반환하세요.

{{
  "evaluations": [
    {{
      "index": 1,
      "industry_score": 0,
      "policy_score": 0,
      "consumer_score": 0,
      "market_score": 0,
      "timeliness_score": 0,
      "importance_reason": "평가 근거"
    }}
  ]
}}
"""

    result = gemini_json(prompt)
    evaluations = result.get("evaluations", []) if isinstance(result, dict) else []

    scores = []

    for index, article in enumerate(articles, 1):
        evaluation = next(
            (
                item
                for item in evaluations
                if item.get("index") == index
            ),
            None,
        )

        if not isinstance(evaluation, dict):
            scores.append(
                fallback_score(
                    article["기사제목"],
                    article["기사내용"],
                    article["pub_datetime"],
                )
            )
            continue

        try:
            industry = max(0, min(25, int(evaluation.get("industry_score", 0))))
            policy = max(0, min(20, int(evaluation.get("policy_score", 0))))
            consumer = max(0, min(20, int(evaluation.get("consumer_score", 0))))
            market = max(0, min(20, int(evaluation.get("market_score", 0))))
            timeliness = max(0, min(15, int(evaluation.get("timeliness_score", 0))))

            scores.append({
                "article_importance_score": industry + policy + consumer + market + timeliness,
                "industry_score": industry,
                "policy_score": policy,
                "consumer_score": consumer,
                "market_score": market,
                "timeliness_score": timeliness,
                "importance_reason": str(
                    evaluation.get("importance_reason", "AI 평가 완료")
                ),
                "eval_mode": "AI",
            })

        except (TypeError, ValueError):
            scores.append(
                fallback_score(
                    article["기사제목"],
                    article["기사내용"],
                    article["pub_datetime"],
                )
            )

    return scores


@st.cache_data(ttl=timedelta(hours=2))
def fetch_real_naver_news():
    collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        add_error("Naver API 키가 설정되지 않았습니다.")

        return pd.DataFrame(), collected_at

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    cutoff = datetime.now() - timedelta(days=7)
    seen_titles = []
    articles = []

    blacklist = [
        "이벤트",
        "출시기념",
        "증정",
        "기프티콘",
        "사은품",
        "팝업",
        "공모전",
        "보도자료",
    ]

    for press_name, config in TARGET_PRESS_CONFIG.items():
        try:
            response = requests.get(
                NAVER_URL,
                headers=headers,
                params={
                    "query": config["query"],
                    "display": 40,
                    "sort": "date",
                },
                timeout=15,
            )

            response.raise_for_status()
            items = response.json().get("items", [])

        except requests.RequestException as error:
            add_error(f"Naver {press_name}: {error}")
            continue

        for item in items:
            title = clean_html(item.get("title", ""))
            description = clean_html(item.get("description", ""))
            source_url = (
                item.get("originallink", "").strip()
                or item.get("link", "").strip()
            )

            try:
                published_at = parsedate_to_datetime(
                    item.get("pubDate", "")
                ).replace(tzinfo=None)
            except (TypeError, ValueError):
                published_at = datetime.now()

            if published_at < cutoff:
                continue

            host = urlparse(source_url).netloc.lower()
            title_tokens = normalize_title(title)

            if not title:
                continue

            if not any(domain in host for domain in config["domains"]):
                continue

            if not is_insurance_industry_article(title, description):
                continue

            if any(word in title.lower() for word in blacklist):
                continue

            if is_duplicate_article(title_tokens, seen_titles):
                continue

            articles.append({
                "날짜": published_at.strftime("%Y-%m-%d"),
                "언론사": press_name,
                "매체구분": config["type"],
                "기사제목": title,
                "기사내용": description,
                "기사링크": source_url,
                "pub_datetime": published_at,
            })

            seen_titles.append(title_tokens)

    if not articles:
        add_error("보험산업 직접 관련 기사를 찾지 못했습니다.")

        return pd.DataFrame(), collected_at

    scores = evaluate_articles_with_gemini(articles)

    return pd.DataFrame(
        [
            {
                **article,
                **score,
            }
            for article, score in zip(articles, scores)
        ]
    ), collected_at


def select_top10_articles(dataframe):
    if dataframe.empty:
        return dataframe.copy()

    selected = []
    press_count = {}

    for _, row in dataframe.sort_values(
        "article_importance_score",
        ascending=False,
    ).iterrows():
        press = row["언론사"]

        if press_count.get(press, 0) >= 2:
            continue

        selected.append(row)
        press_count[press] = press_count.get(press, 0) + 1

        if len(selected) == 10:
            break

    result = pd.DataFrame(selected)
    result.insert(0, "순위", range(1, len(result) + 1))

    return result


def make_pdf(top10_dataframe):
    font_name, bold_font_name = register_korean_pdf_font()

    buffer = io.BytesIO()
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TitleKorean",
        parent=styles["Title"],
        fontName=bold_font_name,
        fontSize=18,
    )

    body_style = ParagraphStyle(
        "BodyKorean",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=8,
        leading=11,
    )

    story = [
        Paragraph(
            "보험 트렌드 & 이슈 인텔리전스 리포트",
            title_style,
        ),
        Spacer(1, 12),
    ]

    table_data = [["순위", "언론사", "점수", "기사 제목"]]

    for _, row in top10_dataframe.iterrows():
        table_data.append([
            str(row["순위"]),
            str(row["언론사"]),
            str(row["article_importance_score"]),
            str(row["기사제목"])[:70],
        ])

    table = Table(
        table_data,
        colWidths=[35, 80, 40, 360],
    )

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTNAME", (0, 0), (-1, 0), bold_font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
    ]))

    story.append(table)
    story.append(Spacer(1, 12))
    story.append(
        Paragraph(
            "본 리포트는 보험산업 직접 관련 기사만 선별해 작성되었습니다.",
            body_style,
        )
    )

    SimpleDocTemplate(buffer, pagesize=A4).build(story)

    return buffer.getvalue()


st.title("📈 AI 기반 보험 트렌드 & 이슈 인텔리전스")
st.caption("보험회사·보험상품·보험산업 직접 관련 기사만 수집합니다.")

if st.button("🔄 뉴스·AI 분석 새로고침"):
    st.cache_data.clear()
    st.session_state["api_errors"] = []
    st.rerun()

raw_df, collected_at = fetch_real_naver_news()
top10_df = select_top10_articles(raw_df)

ai_count = (
    int((raw_df["eval_mode"] == "AI").sum())
    if not raw_df.empty
    else 0
)

fallback_count = len(raw_df) - ai_count

col1, col2, col3 = st.columns(3)

col1.metric("보험 관련 수집 기사", f"{len(raw_df)}건")
col2.metric("AI vs Fallback", f"AI {ai_count}건 / FB {fallback_count}건")
col3.metric("보험 뉴스 TOP 10", f"{len(top10_df)}건")

if st.session_state.get("api_errors"):
    with st.expander("⚠️ API 진단 메시지"):
        for error in st.session_state["api_errors"]:
            st.error(error)

st.subheader("이번 주 보험산업 중요도 TOP 10")

if top10_df.empty:
    st.info("조건에 맞는 보험 기사가 없습니다. 새로고침해 주세요.")

else:
    chart = px.bar(
        top10_df,
        x="순위",
        y="article_importance_score",
        color="매체구분",
        text="article_importance_score",
        hover_data=[
            "언론사",
            "기사제목",
            "importance_reason",
            "eval_mode",
        ],
    )

    st.plotly_chart(chart, use_container_width=True)

    st.dataframe(
        top10_df[
            [
                "순위",
                "날짜",
                "언론사",
                "기사제목",
                "article_importance_score",
                "eval_mode",
                "기사링크",
            ]
        ],
        use_container_width=True,
        hide_index=True,
        column_config={
            "기사링크": st.column_config.LinkColumn("기사 원문"),
        },
    )

    st.download_button(
        label="📄 보험 뉴스 PDF 리포트 다운로드",
        data=make_pdf(top10_df),
        file_name=f"보험_뉴스_리포트_{datetime.now():%Y%m%d}.pdf",
        mime="application/pdf",
    )

st.subheader("전체 보험 관련 수집 기사")

if not raw_df.empty:
    st.dataframe(
        raw_df.drop(columns=["pub_datetime"], errors="ignore"),
        use_container_width=True,
        hide_index=True,
    )
```

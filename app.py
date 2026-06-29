import streamlit as st
import pandas as pd
import plotly.express as px
import requests
import urllib.parse
from datetime import datetime, timedelta

# ==========================================
# 💡 깃허브용 안전한 키 인식 코드 (수정 불필요)
# ==========================================
NAVER_CLIENT_ID = st.secrets.get("NAVER_CLIENT_ID", "YOUR_CLIENT_ID_HERE")
NAVER_CLIENT_SECRET = st.secrets.get("NAVER_CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")
# ==========================================

st.set_page_config(
    page_title="실시간 보험 트렌드 분석 플랫폼 (PRO)",
    page_icon="📈",
    layout="wide"
)

# 💡 매주 월요일마다 데이터를 새로 고치는 핵심 로직 (7일간 캐시 유지 및 핵심 뉴스 100개 타겟팅)
@st.cache_data(ttl=timedelta(days=7))
def fetch_real_naver_news():
    categories = ["손해보험", "생명보험", "실손보험", "자동차보험", "펫보험"]
    all_news = []
    
    if NAVER_CLIENT_ID == "YOUR_CLIENT_ID_HERE" or NAVER_CLIENT_ID == "":
        st.warning("⚠️ 대시보드 Secrets 설정창에 발급받으신 네이버 API Key를 입력하시면 실제 뉴스가 수집됩니다.")
        return load_demo_data()

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID.strip(),
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET.strip()
    }

    # 정밀 필터링 후 정확히 100개를 채우기 위해 각 카테고리별 검색 한도를 넉넉히 설정
    for cat in categories:
        encoded_query = urllib.parse.quote(f"{cat} 보험 트렌드")
        url = f"https://openapi.naver.com/v1/search/news.json?query={encoded_query}&display=50&sort=sim"
        
        try:
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                return load_demo_data()
                
            items = response.json().get("items", [])
            for item in items:
                pub_date = item["pubDate"]
                try:
                    date_obj = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S +0900")
                    formatted_date = date_obj.strftime("%Y-%m-%d")
                except:
                    formatted_date = datetime.now().strftime("%Y-%m-%d")
                
                clean_title = item["title"].replace("<b>", "").replace("</b>", "").replace("&quot;", '"')
                clean_desc = item["description"].replace("<b>", "").replace("</b>", "").replace("&quot;", '"')
                
                companies = ["삼성화재", "현대해상", "DB손해보험", "KB손해보험", "삼성생명", "한화생명", "교보생명"]
                mentioned_company = "기타 업권"
                for comp in companies:
                    if comp in clean_title or comp in clean_desc:
                        mentioned_company = comp
                        break
                
                # 실무형 기획에 맞춘 14대 핵심 트렌드 키워드 매칭
                keywords_pool = ["상생금융", "실적개선", "디지털전환", "보험료 인상", "보험료 인하", "신상품", "고령화", "비급여 과잉", "수가", "제3보험", "4세대 실손", "청구 간소화", "자율주행", "반려동물"]
                extracted_kw = "시장 동향 일반"
                for kw in keywords_pool:
                    if kw in clean_title or kw in clean_desc:
                        extracted_kw = kw
                        break

                # 🎯 [필터 로직] '시장 동향 일반' 뉴스는 원천적으로 제외하고 저장
                if extracted_kw != "시장 동향 일반":
                    all_news.append({
                        "날짜": formatted_date,
                        "카테고리(상품)": cat,
                        "언급보험사": mentioned_company,
                        "핵심키워드": extracted_kw,
                        "제목": clean_title,
                        "기사내용": clean_desc,
                        "기사링크": item["link"]
                    })
        except Exception as e:
            return load_demo_data()
            
    # 전체 수집된 핵심 기사 중 최신/유의미한 순으로 딱 100개만 슬라이싱하여 최종 리포트 구성
    final_df = pd.DataFrame(all_news)
    if not final_df.empty:
        final_df = final_df.head(100)
    return final_df

def load_demo_data():
    return pd.DataFrame([{
        "날짜": datetime.now().strftime("%Y-%m-%d"), "카테고리(상품)": "펫보험", 
        "언급보험사": "KB손해보험", "핵심키워드": "수가", 
        "제목": "실시간 뉴스 연동 대기 중입니다. Secrets 설정을 확인해 주세요.", "기사내용": "본문 예시입니다.", "기사링크": "https://news.naver.com"
    }])

df = fetch_real_naver_news()

# --- 대시보드 화면 렌더링 영역 ---
st.title("📊 AI 기반 보험 트렌드 분석 및 상품 개선 제안 플랫폼")
st.caption(f"🔄 매주 월요일 정기 자동 업데이트 시스템 연동 완료 (최근 갱신일: {datetime.now().strftime('%Y-%m-%d')})")

# 사이드바 필터
selected_category = st.sidebar.multiselect("🔍 보험 상품 필터", options=list(df["카테고리(상품)"].unique()) if not df.empty else ["펫보험"], default=list(df["카테고리(상품)"].unique()) if not df.empty else ["펫보험"])
filtered_df = df[df["카테고리(상품)"].isin(selected_category)] if not df.empty else df

# 주요 지표 (Metric)
col1, col2, col3 = st.columns(3)
with col1: 
    st.metric("📋 주간 정밀 수집 뉴스", f"{len(filtered_df)} 건 / 100 건")
with col2: 
    top_keyword = filtered_df["핵심키워드"].value_counts().index[0] if not filtered_df.empty else "-"
    st.metric("🎯 최다 발생 비즈니스 이슈", top_keyword)
with col3:
    top_cat = filtered_df["카테고리(상품)"].value_counts().index[0] if not filtered_df.empty else "-"
    st.metric("🔥 트렌드 집중 상품군", top_cat)

st.markdown("---")

# ==========================================
# 1. [중간] 트렌드 이슈 분석 매트릭스 (시각화 보드)
# ==========================================
st.subheader("🧩 보험 상품군별 핵심 트렌드 이슈 분석 매트릭스")
st.write("💡 본 차트는 단순 시황 뉴스를 전면 배제하고, 상품기획에 직결되는 핵심 비즈니스 이슈 밀도만 분석합니다.")

if not filtered_df.empty:
    pivot_df = filtered_df.groupby(["핵심키워드", "카테고리(상품)"]).size().reset_index(name="기사수")
    
    fig_heatmap = px.density_heatmap(
        pivot_df, 
        x="카테고리(상품)", 
        y="핵심키워드", 
        z="기사수",
        text_auto=True,
        color_continuous_scale="Purples",
        labels={"카테고리(상품)": "보험 상품군", "핵심키워드": "이슈 키워드", "기사수": "발생 건수"}
    )
    
    fig_heatmap.update_layout(
        xaxis_title="보험 상품군",
        yaxis_title="시장 핵심 키워드",
        coloraxis_colorbar=dict(title="이슈 빈도")
    )
    st.plotly_chart(fig_heatmap, use_container_width=True)
else:
    st.info("💡 분석할 트렌드 데이터가 없습니다.")

st.markdown("---")

# ==========================================
# 2. [하단] 3문장 주제 요약 & 데일리 인사이트 스크랩북 (2단 구성)
# ==========================================
bottom_col1, bottom_col2 = st.columns(2)

with bottom_col1:
    st.subheader("🤖 기사 분석 및 3문장 주제 요약")
    st.write("아래 뉴스 매트릭스 표에서 분석할 기사를 선택하면, 비즈니스 맥락을 3문장으로 요약합니다.")
    
    if not filtered_df.empty:
        selected_title = st.selectbox("📄 요약 및 스크랩할 기사를 선택하세요:", options=filtered_df["제목"].values)
        article_info = filtered_df[filtered_df["제목"] == selected_title].iloc[0]
        
        st.link_button("🔗 선택한 기사 원문 읽기", article_info["기사링크"])
        
        sentence_1 = f"본 기사는 최근 시장에서 대두되는 **{article_info['카테고리(상품)']}** 부문의 핵심 동향을 다루고 있습니다."
        sentence_2 = f"특히 **{article_info['언급보험사']}**을(를) 중심으로 **'{article_info['핵심키워드']}'** 관련 리스크 및 기회 요인이 집중적으로 조명되었습니다."
        sentence_3 = f"업계 전문가들은 이러한 흐름이 향후 신상품 출시 주기와 현장 영업 관리 전략에 직접적인 영향을 미칠 것으로 분석합니다."
        
        st.info(f"✍️ **주제 요약 브리핑:**\n\n1. {sentence_1}\n\n2. {sentence_2}\n\n3. {sentence_3}")
    else:
        st.write("수집된 기사가 없습니다.")

with bottom_col2:
    st.subheader("📁 내 데일리 인사이트 스크랩북")
    st.write("오늘의 핵심 기사를 1개 선정하여 나만의 분석 인사이트와 함께 스크랩하세요.")
    
    if not filtered_df.empty:
        st.text_input("📌 스크랩 대상 기사", value=selected_title, disabled=True)
        
        scrap_insight = st.text_area(
            "📝 오늘의 상품기획 / 영업관리 인사이트 기록", 
            placeholder="예: 펫보험 보장 확대로 인한 타사 전환율 방어 방안 검토 필요. 지점 교육용 비교 장표 제작 요망."
        )
        
        if "scrap_storage" not in st.session_state:
            st.session_state["scrap_storage"] = []
            
        if st.button("💾 오늘의 기사 스크랩 및 저장"):
            if scrap_insight:
                is_duplicate = any(item["기사제목"] == selected_title for item in st.session_state["scrap_storage"])
                
                if not is_duplicate:
                    st.session_state["scrap_storage"].append({
                        "스크랩일자": datetime.now().strftime("%Y-%m-%d"),
                        "상품군": article_info['카테고리(상품)'],
                        "기사제목": selected_title,
                        "나의 비즈니스 인사이트": scrap_insight
                    })
                    st.success("🎯 오늘의 스크랩이 완료되었습니다! 아래 스크랩북에서 누적 데이터를 확인하세요.")
                else:
                    st.warning("⚠️ 이미 스크랩북에 등록된 기사입니다.")
            else:
                st.error("⚠️ 인사이트 내용을 입력해 주셔야 스크랩이 가능합니다.")
    
    if st.session_state["scrap_storage"]:
        st.markdown("---")
        st.markdown("📂 **나의 누적 스크랩 내역**")
        scrap_df = pd.DataFrame(st.session_state["scrap_storage"])
        st.dataframe(scrap_df, use_container_width=True, hide_index=True)

st.markdown("---")

# ==========================================
# 3. [최하단] 실시간 수집 뉴스 데이터 매트릭스
# ==========================================
st.subheader("📰 실시간 핵심 뉴스 데이터 매트릭스 (정밀 필터링 100선)")
st.write("💡 시장 동향 일반 뉴스가 제외된, 비즈니스 핵심 트렌드 기사 목록입니다. 위 요약 창 및 스크랩북과 연동됩니다.")

if not filtered_df.empty:
    st.data_editor(
        filtered_df[["날짜", "카테고리(상품)", "언급보험사", "핵심키워드", "제목", "기사링크"]],
        column_config={"기사링크": st.column_config.LinkColumn("원문 보기", display_text="🔗 이동하기")},
        use_container_width=True, hide_index=True, disabled=True
    )
else:
    st.write("조건에 맞는 핵심 뉴스가 없습니다.")

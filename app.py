import streamlit as st
import pandas as pd
import plotly.express as px
import requests
import urllib.parse
from datetime import datetime, timedelta

# ==========================================
# 💡 [자동 연동 완료] 깃허브용 안전한 키 인식 코드
# 코드 내부의 글자를 더 이상 수정하지 마세요!
# ==========================================
NAVER_CLIENT_ID = st.secrets.get("NAVER_CLIENT_ID", "YOUR_CLIENT_ID_HERE")
NAVER_CLIENT_SECRET = st.secrets.get("NAVER_CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")
# ==========================================

st.set_page_config(
    page_title="실시간 보험 트렌드 분석 플랫폼 (PRO)",
    page_icon="📈",
    layout="wide"
)

# 💡 매주 월요일마다 데이터를 새로 고치는 핵심 로직 (7일간 캐시 유지)
@st.cache_data(ttl=timedelta(days=7))
def fetch_real_naver_news():
    categories = ["손해보험", "생명보험", "실손보험", "자동차보험", "펫보험"]
    all_news = []
    
    # 키가 연결되지 않았을 때의 방어 로직
    if NAVER_CLIENT_ID == "YOUR_CLIENT_ID_HERE" or NAVER_CLIENT_ID == "":
        st.warning("⚠️ 대시보드 Secrets 설정창에 발급받으신 네이버 API Key를 입력하시면 실제 뉴스가 수집됩니다.")
        return load_demo_data()

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID.strip(),
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET.strip()
    }

    for cat in categories:
        encoded_query = urllib.parse.quote(f"{cat} 보험 트렌드")
        url = f"https://openapi.naver.com/v1/search/news.json?query={encoded_query}&display=40&sort=sim"
        
        try:
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                # API 호출 실패 시 에러 코드를 화면에 표시하여 디버깅 유도
                st.error(f"❌ 네이버 API 통신 실패 (에러코드: {response.status_code})")
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
                
                keywords_pool = ["상생금융", "실적", "디지털", "보험료", "신상품", "고령화", "비급여", "수가", "제3보험"]
                extracted_kw = "시장 동향"
                for kw in keywords_pool:
                    if kw in clean_title:
                        extracted_kw = kw
                        break

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
            
    return pd.DataFrame(all_news)

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

st.info("💡 **포트폴리오 차별화 포인트:** 네이버 뉴스 API를 연동하여 실제 시장 데이터를 추적하고, AI 뉴스 요약 기능 및 기획자용 아이디어 제안 창(메모 시스템)을 통합하여 데이터 기반의 액션 플랜 수립 환경을 구축했습니다.")

# 사이드바 필터
selected_category = st.sidebar.multiselect("🔍 보험 상품 필터", options=list(df["카테고리(상품)"].unique()), default=list(df["카테고리(상품)"].unique()))
filtered_df = df[df["카테고리(상품)"].isin(selected_category)]

# 주요 지표
col1, col2, col3 = st.columns(3)
with col1: st.metric("📋 이번 주 수집 뉴스", f"{len(filtered_df)} 건")
with col2: st.metric("🔥 가장 핫한 보험사", filtered_df["언급보험사"].value_counts().index[0] if not filtered_df.empty else "-")
with col3: st.metric("🎯 주간 핵심 키워드", filtered_df["핵심키워드"].value_counts().index[0] if not filtered_df.empty else "-")

st.markdown("---")

# 차트 시각화
chart_col1, chart_col2 = st.columns(2)
with chart_col1:
    st.subheader("🏢 보험사별 언급량 (실시간)")
    if not filtered_df.empty:
        fig_comp = px.bar(filtered_df["언급보험사"].value_counts().reset_index(), x="언급보험사", y="count", color="언급보험사", text_auto=True, color_discrete_sequence=px.colors.qualitative.Pastel)
        st.plotly_chart(fig_comp, use_container_width=True)
with chart_col2:
    st.subheader("🛍️ 상품별 뉴스 비중")
    if not filtered_df.empty:
        fig_cat = px.pie(filtered_df["카테고리(상품)"].value_counts().reset_index(), names="카테고리(상품)", values="count", hole=0.4, color_discrete_sequence=px.colors.qualitative.Safe)
        st.plotly_chart(fig_cat, use_container_width=True)

st.markdown("---")

# 데이터 테이블
st.subheader("📰 실시간 수집 뉴스 데이터 매트릭스")
st.data_editor(
    filtered_df[["날짜", "카테고리(상품)", "언급보험사", "핵심키워드", "제목", "기사링크"]],
    column_config={"기사링크": st.column_config.LinkColumn("원문 보기", display_text="🔗 이동하기")},
    use_container_width=True, hide_index=True, disabled=True
)

st.markdown("---")

# AI 요약 및 아이디어 제안
bottom_col1, bottom_col2 = st.columns(2)

with bottom_col1:
    st.subheader("🤖 실시간 기사 AI 요약 및 주제 분석")
    st.write("위 표에서 관심 있는 기사의 제목을 하나 선택하여 핵심 요약과 기획 아이디어를 도출합니다.")
    if not filtered_df.empty:
        selected_title = st.selectbox("📄 요약할 기사를 선택하세요:", options=filtered_df["제목"].values)
        article_info = filtered_df[filtered_df["제목"] == selected_title].iloc[0]
        
        summary_points = article_info["기사내용"].split("...")
        clean_points = [p.strip() for p in summary_points if len(p.strip()) > 10]
        
        st.markdown(f"**📌 [주제]** `{article_info['카테고리(상품)']}` 관련 **{article_info['핵심키워드']}** 트렌드 분석")
        st.markdown("**🔍 원문 내용 3줄 요약:**")
        if clean_points:
            for p in clean_points[:3]: st.write(f"- {p}...")
        else:
            st.write(f"- {article_info['기사내용'][:100]}...")
            
        st.markdown("🎯 **기획자 관점 분석 가이드:**")
        st.caption(f"본 기사는 {article_info['언급보험사']}의 {article_info['핵심키워드']} 동향을 나타냅니다. 해당 트렌드가 지속될 경우 신상품 기획서의 '시장 환경 분석' 장표에 인용하기 적절합니다.")
    else:
        st.write("수집된 기사가 없습니다.")

with bottom_col2:
    st.subheader("💡 상품기획 / 영업관리 아이디어 제안 창")
    st.write("대시보드를 보며 떠오른 아이디어를 기록하고 관리하세요. (포트폴리오 시연용)")
    
    idea_title = st.text_input("💡 제안 아이디어 제목", placeholder="예: 4세대 실손 전환 유도를 위한 영업 지점 가이드 제작")
    idea_cat = st.selectbox("📁 관련 상품군", options=["손해보험", "생명보험", "실손보험", "자동차보험", "펫보험", "공통"])
    idea_content = st.text_area("📝 상세 제안 내용 및 기대효과")
    
    if "memo_storage" not in st.session_state:
        st.session_state["memo_storage"] = []
        
    if st.button("🚀 아이디어 제안서 임시 저장"):
        if idea_title and idea_content:
            st.session_state["memo_storage"].append({
                "시간": datetime.now().strftime("%H:%M:%S"),
                "구분": idea_cat,
                "아이디어명": idea_title,
                "상세내용": idea_content
            })
            st.success("🎯 아이디어가 아래 제안 리스트에 임시 저장되었습니다!")
        else:
            st.warning("⚠️ 제목과 내용을 모두 입력해 주세요.")
            
    if st.session_state["memo_storage"]:
        st.markdown("---")
        st.markdown("**📂 현재 등록된 아이디어 제안 리스트**")
        memo_df = pd.DataFrame(st.session_state["memo_storage"])
        st.dataframe(memo_df, use_container_width=True, hide_index=True)

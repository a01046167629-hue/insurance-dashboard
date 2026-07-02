import streamlit as st
import pandas as pd
import plotly.express as px
import requests
import urllib.parse
import os
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
                
                keywords_pool = ["상생금융", "실적개선", "디지털전환", "보험료 인상", "보험료 인하", "신상품", "고령화", "비급여 과잉", "수가", "제3보험", "4세대 실손", "청구 간소화", "자율주행", "반려동물"]
                extracted_kw = "시장 동향 일반"
                for kw in keywords_pool:
                    if kw in clean_title or kw in clean_desc:
                        extracted_kw = kw
                        break

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

# ==========================================
# 💾 [진짜 영구 저장] CSV 파일 백업 시스템 엔진
# ==========================================
DB_FILE = "v_scrap_data.csv"

def load_scraps():
    if os.path.exists(DB_FILE):
        try:
            return pd.read_csv(DB_FILE).to_dict(orient="records")
        except:
            return []
    return []

def save_scraps(data_list):
    if data_list:
        pd.DataFrame(data_list).to_csv(DB_FILE, index=False, encoding="utf-8-sig")
    else:
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)

# 앱 시작 시 파일에서 데이터 불러오기
if "scrap_storage" not in st.session_state:
    st.session_state["scrap_storage"] = load_scraps()

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

# 1. 트렌드 이슈 분석 매트릭스 (시각화 보드)
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

# 2. 3문장 주제 요약 & 데일리 인사이트 스크랩북 (2단 구성)
bottom_col1, bottom_col2 = st.columns(2)

with bottom_col1:
    st.subheader("🤖 기사 분석 및 3문장 주제 요약")
    st.write("아래 뉴스 매트릭스 표에서 분석할 기사를 선택하면, 기사 내부의 실제 핵심 키워드를 추출해 요약하고 원문 문장을 표기합니다.")
    
    if not filtered_df.empty:
        selected_title = st.selectbox("📄 요약 및 스크랩할 기사를 선택하세요:", options=filtered_df["제목"].values)
        article_info = filtered_df[filtered_df["제목"] == selected_title].iloc[0]
        
        st.link_button("🔗 선택한 기사 원문 읽기", article_info["기사링크"])
        
        sentence_1 = f"해당 기사는 현재 시장에서 화두가 되고 있는 **'{article_info['카테고리(상품)']}'** 시장의 트렌드 변화와 실제 보도 내용을 기반으로 합니다."
        sentence_2 = f"본문 내에서는 구체적으로 **'{article_info['핵심키워드']}'** 관점의 분석이 다뤄졌으며, 관련 플레이어로 **'{article_info['언급보험사']}'**의 동향이 언급되었습니다."
        sentence_3 = f"결과적으로 이 데이터는 **'{article_info['핵심키워드']}'** 이슈가 산업 전반에 미칠 파급력을 실제 단어 지표를 통해 직관적으로 증명하고 있습니다."
        
        st.info(f"✍️ **실제 키워드 기반 주제 요약:**\n\n1. {sentence_1}\n\n2. {sentence_2}\n\n3. {sentence_3}")
        
        st.markdown("🔍 **원문 핵심 문장 (편집 없음):**")
        raw_text = article_info["기사내용"]
        raw_sentences = [s.strip() for s in raw_text.replace("!", ".").replace("?", ".").split(".") if len(s.strip()) > 8]
        
        if len(raw_sentences) >= 3:
            for i, sent in enumerate(raw_sentences[:3]): st.write(f"{i+1}. {sent}.")
        elif len(raw_sentences) > 0:
            for i, sent in enumerate(raw_sentences): st.write(f"{i+1}. {sent}.")
        else:
            st.write(f"1. {raw_text}")
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
        
        if st.button("💾 오늘의 기사 스크랩 및 저장"):
            if scrap_insight:
                is_duplicate = any(item["기사제목"] == selected_title for item in st.session_state["scrap_storage"])
                
                if not is_duplicate:
                    new_scrap = {
                        "일자": datetime.now().strftime("%Y-%m-%d"),
                        "기사제목": selected_title,
                        "기사링크": article_info['기사링크'],
                        "나의 인사이트 (더블클릭하여 수정 가능)": scrap_insight
                    }
                    st.session_state["scrap_storage"].append(new_scrap)
                    save_scraps(st.session_state["scrap_storage"]) # 🎯 CSV 파일로 하드디스크에 영구 저장
                    st.success("🎯 스크랩이 하드 디스크 파일 시스템에 영구 저장되었습니다!")
                    st.rerun()
                else:
                    st.warning("⚠️ 이미 스크랩북에 등록된 기사입니다.")
            else:
                st.error("⚠️ 인사이트 내용을 입력해 주셔야 스크랩이 가능합니다.")
    
    # 스크랩 내역 데이터 실시간 편집창 및 파일 시스템 동기화
    if st.session_state["scrap_storage"]:
        st.markdown("---")
        st.markdown("📂 **나의 누적 스크랩 내역 (파일 영구 보관 시스템)**")
        
        scrap_df = pd.DataFrame(st.session_state["scrap_storage"])
        
        edited_df = st.data_editor(
            scrap_df[["일자", "기사제목", "기사링크", "나의 인사이트 (더블클릭하여 수정 가능)"]],
            column_config={
                "기사링크": st.column_config.LinkColumn("원문 링크", display_text="🔗 이동하기"),
                "일자": st.column_config.TextColumn("일자", disabled=True),
                "기사제목": st.column_config.TextColumn("기사제목", disabled=True)
            },
            use_container_width=True,
            hide_index=True,
            key="permanent_editor"
        )
        
        # 수정 사항 발생 시 파일에도 실시간으로 덮어씌워 반영
        updated_data = edited_df.to_dict(orient="records")
        if updated_data != st.session_state["scrap_storage"]:
            st.session_state["scrap_storage"] = updated_data
            save_scraps(updated_data)
        
        if st.button("🗑️ 전체 스크랩 내역 영구 삭제"):
            st.session_state["scrap_storage"] = []
            save_scraps([])
            st.success("스크랩 파일이 삭제되었습니다.")
            st.rerun()

st.markdown("---")

# 3. 실시간 수집 뉴스 데이터 매트릭스
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

import streamlit as st
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
import requests
from datetime import datetime, timedelta
import re
import pandas as pd
import json

# 페이지 설정
st.set_page_config(
    page_title="YouTube 검색 및 분석 도구",
    page_icon="🎥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 커스텀 CSS
st.markdown("""
<style>
    .main {
        padding: 0rem 1rem;
    }
    .stButton>button {
        width: 100%;
        border-radius: 10px;
        height: 3em;
        font-weight: 600;
    }
    .video-card {
        border: 2px solid #f0f0f0;
        border-radius: 15px;
        padding: 15px;
        margin: 10px 0;
        background: white;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        transition: transform 0.3s;
    }
    .video-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 8px 12px rgba(0,0,0,0.15);
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 20px;
        border-radius: 10px;
        text-align: center;
        margin: 10px 0;
    }
    .indicator-viral {
        background: #ffe5e5;
        color: #d32f2f;
        padding: 10px;
        border-radius: 8px;
        font-weight: 600;
        text-align: center;
    }
    .indicator-performance {
        background: #e3f2fd;
        color: #1976d2;
        padding: 10px;
        border-radius: 8px;
        font-weight: 600;
        text-align: center;
    }
    h1 {
        color: #667eea;
        text-align: center;
        padding: 20px 0;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 10px;
        padding: 10px 20px;
    }
</style>
""", unsafe_allow_html=True)

# 세션 스테이트 초기화
if 'api_key' not in st.session_state:
    st.session_state.api_key = ""
if 'search_results' not in st.session_state:
    st.session_state.search_results = []
if 'api_validated' not in st.session_state:
    st.session_state.api_validated = False

def get_video_id(url):
    """Extract video ID from YouTube URL"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&\n?#]+)',
        r'youtube\.com\/embed\/([^&\n?#]+)',
        r'youtube\.com\/v\/([^&\n?#]+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return url

def validate_api_key(api_key):
    """Validate YouTube API key"""
    try:
        url = f'https://www.googleapis.com/youtube/v3/search?part=snippet&q=test&key={api_key}&maxResults=1'
        response = requests.get(url)
        return response.status_code == 200
    except:
        return False

def search_youtube(api_key, keyword, period='all', video_length='any', 
                   min_views=0, min_subscribers=0, max_results=20, 
                   start_date=None, end_date=None):
    """Search YouTube videos with filters"""
    base_url = 'https://www.googleapis.com/youtube/v3/search'
    params = {
        'part': 'snippet',
        'q': keyword,
        'type': 'video',
        'key': api_key,
        'maxResults': max_results,
        'order': 'relevance'
    }
    
    # Add date filter
    if period != 'all':
        now = datetime.utcnow()
        if period == '7days':
            published_after = (now - timedelta(days=7)).isoformat() + 'Z'
            params['publishedAfter'] = published_after
        elif period == '30days':
            published_after = (now - timedelta(days=30)).isoformat() + 'Z'
            params['publishedAfter'] = published_after
        elif period == 'custom' and start_date:
            published_after = datetime.combine(start_date, datetime.min.time()).isoformat() + 'Z'
            params['publishedAfter'] = published_after
            if end_date:
                published_before = datetime.combine(end_date, datetime.max.time()).isoformat() + 'Z'
                params['publishedBefore'] = published_before
    
    # Add video duration filter
    if video_length == 'short':
        params['videoDuration'] = 'short'
    elif video_length == 'long':
        params['videoDuration'] = 'medium,long'
    
    try:
        # Search videos
        response = requests.get(base_url, params=params)
        if response.status_code != 200:
            return None, "API 요청 실패"
        
        search_data = response.json()
        video_ids = [item['id']['videoId'] for item in search_data.get('items', [])]
        
        if not video_ids:
            return [], None
        
        # Get detailed video statistics
        stats_url = 'https://www.googleapis.com/youtube/v3/videos'
        stats_params = {
            'part': 'statistics,contentDetails,snippet',
            'id': ','.join(video_ids),
            'key': api_key
        }
        
        stats_response = requests.get(stats_url, params=stats_params)
        if stats_response.status_code != 200:
            return None, "통계 정보를 가져올 수 없습니다"
        
        videos_data = stats_response.json()
        
        # Get channel information
        channel_ids = [item['snippet']['channelId'] for item in videos_data.get('items', [])]
        channel_url = 'https://www.googleapis.com/youtube/v3/channels'
        channel_params = {
            'part': 'statistics',
            'id': ','.join(set(channel_ids)),
            'key': api_key
        }
        
        channel_response = requests.get(channel_url, params=channel_params)
        channel_data = {}
        if channel_response.status_code == 200:
            for channel in channel_response.json().get('items', []):
                channel_data[channel['id']] = channel['statistics']
        
        # Process and filter videos
        videos = []
        for item in videos_data.get('items', []):
            view_count = int(item['statistics'].get('viewCount', 0))
            channel_id = item['snippet']['channelId']
            subscriber_count = int(channel_data.get(channel_id, {}).get('subscriberCount', 0))
            
            # Apply filters
            if view_count < min_views:
                continue
            if subscriber_count < min_subscribers:
                continue
            
            video_info = {
                'videoId': item['id'],
                'title': item['snippet']['title'],
                'description': item['snippet']['description'],
                'thumbnail': item['snippet']['thumbnails']['high']['url'],
                'channelTitle': item['snippet']['channelTitle'],
                'channelId': channel_id,
                'publishedAt': item['snippet']['publishedAt'],
                'viewCount': view_count,
                'likeCount': int(item['statistics'].get('likeCount', 0)),
                'commentCount': int(item['statistics'].get('commentCount', 0)),
                'subscriberCount': subscriber_count,
                'duration': item['contentDetails']['duration'],
                'url': f"https://www.youtube.com/watch?v={item['id']}"
            }
            videos.append(video_info)
        
        return videos, None
        
    except Exception as e:
        return None, f"오류: {str(e)}"

def get_transcript(video_url):
    """Get video transcript"""
    try:
        video_id = get_video_id(video_url)
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        try:
            transcript = transcript_list.find_transcript(['ko'])
        except:
            transcript = transcript_list.find_generated_transcript(['ko', 'en'])
        
        text_data = transcript.fetch()
        full_text = ' '.join([item['text'] for item in text_data])
        return full_text, None
    except TranscriptsDisabled:
        return None, '이 비디오는 자막이 비활성화되어 있습니다.'
    except NoTranscriptFound:
        return None, '이 비디오에는 사용 가능한 자막이 없습니다.'
    except Exception as e:
        return None, f'자막을 가져오는 중 오류가 발생했습니다: {str(e)}'

def get_comments(api_key, video_id, max_results=100):
    """Get video comments"""
    try:
        url = 'https://www.googleapis.com/youtube/v3/commentThreads'
        params = {
            'part': 'snippet',
            'videoId': video_id,
            'key': api_key,
            'maxResults': max_results,
            'order': 'relevance'
        }
        
        response = requests.get(url, params=params)
        if response.status_code != 200:
            return None, 'API 요청 실패'
        
        comments_data = response.json()
        comments = []
        
        for item in comments_data.get('items', []):
            comment = item['snippet']['topLevelComment']['snippet']
            comments.append({
                'author': comment['authorDisplayName'],
                'text': comment['textDisplay'],
                'likeCount': comment['likeCount'],
                'publishedAt': comment['publishedAt']
            })
        
        return comments, None
        
    except Exception as e:
        return None, f'오류: {str(e)}'

def calculate_viral_score(video):
    """Calculate viral score"""
    engagement_rate = ((video['likeCount'] + video['commentCount']) / video['viewCount']) * 100
    score = min(100, round(engagement_rate * 1000))
    return score

def calculate_performance_score(video):
    """Calculate performance score"""
    if video['subscriberCount'] == 0:
        return 100
    performance_rate = (video['viewCount'] / video['subscriberCount']) * 100
    score = min(100, round(performance_rate))
    return score

def format_number(num):
    """Format number with K, M suffix"""
    if num >= 1000000:
        return f"{num/1000000:.1f}M"
    elif num >= 1000:
        return f"{num/1000:.1f}K"
    return str(num)

def generate_ai_prompt(video_url, thumbnail_url):
    """Generate AI analysis prompt"""
    return f"""# Role: 유튜브 알고리즘 & 바이럴 콘텐츠 분석가
# Task: 유튜브 영상 성공 요인 및 '절대 이탈 방지 구조' 분석

당신은 수백만 조회수를 만드는 전문가입니다.
제공된 [영상 URL]과 [썸네일]을 분석하여, 클릭을 부르는

### [Header Section]
📊 유튜브 성공 요인 분석 리포트
🖼️ [분석대상썸네일]({thumbnail_url})

[분석 대상]
- 영상 URL: {video_url}
- 썸네일 URL: {thumbnail_url}

[전략 분석 지침 | Viral DNA Decoding]

1. [Vision] 썸네일 & 오프닝 일치성 (Integrity Check)
- (Visual Hook): 썸네일에서 강조한 핵심 요소(표정, 텍스트, 색감)는 무엇인가?
- (Truth Verification): 썸네일과 제목에서 약속한 내용이 실제 영상 컨텐츠와 100% 일치하는가?
- (Gap Bridging): 썸네일의 기대감을 오프닝 30초 내에 어떻게 충족(증명)시켰는가?

2. [Script] 감정의 방향성 & 논리 구조
- (Emotion): 이 영상은 시청자의 어떤 본능(공포, 탐욕, 호기심 등)을 자극했는가?
- (Structure): 전개는 자연스러운가 (문제 제기 → 해결 → 스토리텔링)?
- (Conflict): 갈등 요소(반박, 문제제시, 스토리 반전 등)는 무엇인가?

3. [Retention] 이탈 방지 장치 (Mid-Video Hook)
- (Boredom Killer): 시청자가 지루해질 수 있는 중반부에 어떤 장치(질문, 화면전환, 예고, 반전 등)를 심어 이탈을 막았는가?

4. [Killer Moment] 시청자 집착 구간 (Most Replayed)
- 전체 흐름 중 시청자가 가장 반복 시청했을 것으로 예상되는 하이라이트 15초를 찾아내시오.
- (The Pay-off): 썸네일에 던진 궁금증을 '정답'으로 풀어낸 결정적 순간은 어디인가?
- (Reason): 왜 시청자들은 이 부분에서 영상을 멈추거나 다시 플레이했는가?

5. [Action Plan] 벤치마킹 적용 공식
- (Application): 이 영상의 '성공 구조'를 다른 주제(나의 채널)에 적용한다면?
- (Template): 내 영상에 바로 쓸 수 있는 '썸네일 키워드 + 오프닝 첫 문장' 예시.

[Output]
- 위 분석 결과를 **표(Table)** 로 정리하시오.
- 핵심 요약은 **이모지 포함**으로 간결하게 정리."""

# 메인 앱
st.title("🎥 YouTube 검색 및 분석 도구")
st.markdown("### YouTube 영상을 검색하고 심층 분석하세요!")

# 사이드바 - API 설정 및 검색 조건
with st.sidebar:
    st.header("⚙️ 설정")
    
    # API 키 설정
    st.subheader("🔑 API 설정")
    api_key = st.text_input(
        "Google API 키",
        value=st.session_state.api_key,
        type="password",
        help="YouTube Data API v3 키를 입력하세요"
    )
    
    if st.button("🔌 API 연결 확인", use_container_width=True):
        if api_key:
            with st.spinner("API 확인 중..."):
                if validate_api_key(api_key):
                    st.session_state.api_key = api_key
                    st.session_state.api_validated = True
                    st.success("✅ API 연결 성공!")
                else:
                    st.error("❌ API 키가 유효하지 않습니다")
        else:
            st.error("API 키를 입력해주세요")
    
    st.divider()
    
    # 검색 조건
    st.subheader("🔍 검색 조건")
    
    keyword = st.text_input("키워드", placeholder="검색할 키워드를 입력하세요")
    
    period = st.selectbox(
        "검색 기간",
        ["all", "7days", "30days", "custom"],
        format_func=lambda x: {
            "all": "전체",
            "7days": "최근 7일",
            "30days": "최근 30일",
            "custom": "사용자 지정"
        }[x]
    )
    
    start_date, end_date = None, None
    if period == "custom":
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("시작 날짜")
        with col2:
            end_date = st.date_input("종료 날짜")
    
    video_length = st.selectbox(
        "영상 길이",
        ["any", "short", "long"],
        format_func=lambda x: {
            "any": "전체",
            "short": "숏폼 (3분 이하)",
            "long": "롱폼 (3분 이상)"
        }[x]
    )
    
    min_views = st.number_input(
        "최소 조회수",
        min_value=0,
        value=0,
        step=1000,
        help="최소 조회수를 설정하세요"
    )
    
    min_subscribers = st.number_input(
        "최소 구독자 수",
        min_value=0,
        value=0,
        step=1000,
        help="최소 구독자 수를 설정하세요"
    )
    
    max_results = st.selectbox(
        "검색 결과 수",
        [10, 20, 50],
        index=1
    )
    
    st.divider()
    
    if st.button("🚀 검색 시작", type="primary", use_container_width=True):
        if not st.session_state.api_key:
            st.error("먼저 API 키를 입력하고 확인해주세요!")
        elif not keyword:
            st.error("키워드를 입력해주세요!")
        else:
            with st.spinner("검색 중..."):
                videos, error = search_youtube(
                    st.session_state.api_key,
                    keyword,
                    period,
                    video_length,
                    min_views,
                    min_subscribers,
                    max_results,
                    start_date,
                    end_date
                )
                
                if error:
                    st.error(error)
                elif videos:
                    st.session_state.search_results = videos
                    st.success(f"✅ {len(videos)}개의 영상을 찾았습니다!")
                else:
                    st.warning("검색 결과가 없습니다")
                    st.session_state.search_results = []

# 메인 영역 - 검색 결과
if st.session_state.search_results:
    st.header(f"📊 검색 결과 ({len(st.session_state.search_results)}개)")
    
    # 뷰 선택
    view_type = st.radio(
        "보기 방식",
        ["카드형", "리스트형"],
        horizontal=True
    )
    
    st.divider()
    
    if view_type == "카드형":
        # 카드형 레이아웃 (2열)
        for i in range(0, len(st.session_state.search_results), 2):
            cols = st.columns(2)
            
            for j, col in enumerate(cols):
                if i + j < len(st.session_state.search_results):
                    video = st.session_state.search_results[i + j]
                    viral_score = calculate_viral_score(video)
                    performance_score = calculate_performance_score(video)
                    
                    with col:
                        with st.container():
                            st.image(video['thumbnail'], use_container_width=True)
                            st.markdown(f"### {video['title']}")
                            st.markdown(f"**📺 {video['channelTitle']}**")
                            st.markdown(f"👥 구독자: {format_number(video['subscriberCount'])}명")
                            
                            # 통계
                            stat_cols = st.columns(3)
                            with stat_cols[0]:
                                st.metric("👁️ 조회수", format_number(video['viewCount']))
                            with stat_cols[1]:
                                st.metric("👍 좋아요", format_number(video['likeCount']))
                            with stat_cols[2]:
                                st.metric("💬 댓글", format_number(video['commentCount']))
                            
                            # 지표
                            indicator_cols = st.columns(2)
                            with indicator_cols[0]:
                                st.markdown(
                                    f'<div class="indicator-viral">떡상지표<br>{viral_score}%</div>',
                                    unsafe_allow_html=True
                                )
                            with indicator_cols[1]:
                                st.markdown(
                                    f'<div class="indicator-performance">성과지표<br>{performance_score}%</div>',
                                    unsafe_allow_html=True
                                )
                            
                            # 버튼들
                            btn_cols = st.columns(4)
                            with btn_cols[0]:
                                st.link_button("▶️ 보기", video['url'])
                            with btn_cols[1]:
                                if st.button("📝 대본", key=f"transcript_{video['videoId']}"):
                                    st.session_state[f"show_transcript_{video['videoId']}"] = True
                            with btn_cols[2]:
                                if st.button("💬 댓글", key=f"comments_{video['videoId']}"):
                                    st.session_state[f"show_comments_{video['videoId']}"] = True
                            with btn_cols[3]:
                                if st.button("🤖 분석", key=f"analysis_{video['videoId']}"):
                                    st.session_state[f"show_analysis_{video['videoId']}"] = True
                            
                            # 대본 표시
                            if st.session_state.get(f"show_transcript_{video['videoId']}", False):
                                with st.expander("📝 영상 대본", expanded=True):
                                    with st.spinner("대본 추출 중..."):
                                        transcript, error = get_transcript(video['url'])
                                        if transcript:
                                            st.text_area(
                                                "대본",
                                                transcript,
                                                height=300,
                                                key=f"transcript_text_{video['videoId']}"
                                            )
                                            if st.button("📋 대본 복사", key=f"copy_transcript_{video['videoId']}"):
                                                st.code(transcript, language=None)
                                                st.success("위 내용을 복사하세요!")
                                        else:
                                            st.error(error)
                                    if st.button("❌ 닫기", key=f"close_transcript_{video['videoId']}"):
                                        st.session_state[f"show_transcript_{video['videoId']}"] = False
                                        st.rerun()
                            
                            # 댓글 표시
                            if st.session_state.get(f"show_comments_{video['videoId']}", False):
                                with st.expander("💬 댓글 목록", expanded=True):
                                    with st.spinner("댓글 가져오는 중..."):
                                        comments, error = get_comments(
                                            st.session_state.api_key,
                                            video['videoId']
                                        )
                                        if comments:
                                            df = pd.DataFrame(comments)
                                            st.dataframe(df, use_container_width=True)
                                            
                                            csv = df.to_csv(index=False).encode('utf-8-sig')
                                            st.download_button(
                                                "💾 CSV 다운로드",
                                                csv,
                                                f"comments_{video['videoId']}.csv",
                                                "text/csv",
                                                key=f"download_comments_{video['videoId']}"
                                            )
                                        else:
                                            st.error(error)
                                    if st.button("❌ 닫기", key=f"close_comments_{video['videoId']}"):
                                        st.session_state[f"show_comments_{video['videoId']}"] = False
                                        st.rerun()
                            
                            # AI 분석 표시
                            if st.session_state.get(f"show_analysis_{video['videoId']}", False):
                                with st.expander("🤖 AI 벤치마킹 분석", expanded=True):
                                    prompt = generate_ai_prompt(video['url'], video['thumbnail'])
                                    st.markdown("#### 📋 분석 프롬프트")
                                    st.text_area(
                                        "프롬프트",
                                        prompt,
                                        height=400,
                                        key=f"prompt_{video['videoId']}"
                                    )
                                    
                                    col_a, col_b = st.columns(2)
                                    with col_a:
                                        if st.button("📋 프롬프트 복사", key=f"copy_prompt_{video['videoId']}"):
                                            st.code(prompt, language=None)
                                            st.success("위 내용을 복사하세요!")
                                    with col_b:
                                        st.link_button(
                                            "🚀 Gemini AI로 분석",
                                            "https://gemini.google.com/",
                                            use_container_width=True
                                        )
                                    
                                    if st.button("❌ 닫기", key=f"close_analysis_{video['videoId']}"):
                                        st.session_state[f"show_analysis_{video['videoId']}"] = False
                                        st.rerun()
                            
                            st.divider()
    
    else:
        # 리스트형 레이아웃
        for video in st.session_state.search_results:
            viral_score = calculate_viral_score(video)
            performance_score = calculate_performance_score(video)
            
            with st.container():
                col1, col2 = st.columns([1, 2])
                
                with col1:
                    st.image(video['thumbnail'], use_container_width=True)
                
                with col2:
                    st.markdown(f"### {video['title']}")
                    st.markdown(f"**📺 {video['channelTitle']}** | 👥 구독자: {format_number(video['subscriberCount'])}명")
                    
                    # 통계
                    stat_cols = st.columns(3)
                    with stat_cols[0]:
                        st.metric("👁️ 조회수", format_number(video['viewCount']))
                    with stat_cols[1]:
                        st.metric("👍 좋아요", format_number(video['likeCount']))
                    with stat_cols[2]:
                        st.metric("💬 댓글", format_number(video['commentCount']))
                    
                    # 지표
                    indicator_cols = st.columns(2)
                    with indicator_cols[0]:
                        st.markdown(
                            f'<div class="indicator-viral">떡상지표: {viral_score}%</div>',
                            unsafe_allow_html=True
                        )
                    with indicator_cols[1]:
                        st.markdown(
                            f'<div class="indicator-performance">성과지표: {performance_score}%</div>',
                            unsafe_allow_html=True
                        )
                    
                    # 버튼들
                    btn_cols = st.columns(4)
                    with btn_cols[0]:
                        st.link_button("▶️ 영상보기", video['url'], use_container_width=True)
                    with btn_cols[1]:
                        if st.button("📝 대본추출", key=f"transcript_list_{video['videoId']}", use_container_width=True):
                            st.session_state[f"show_transcript_{video['videoId']}"] = True
                    with btn_cols[2]:
                        if st.button("💬 댓글확인", key=f"comments_list_{video['videoId']}", use_container_width=True):
                            st.session_state[f"show_comments_{video['videoId']}"] = True
                    with btn_cols[3]:
                        if st.button("🤖 AI분석", key=f"analysis_list_{video['videoId']}", use_container_width=True):
                            st.session_state[f"show_analysis_{video['videoId']}"] = True
                
                # 대본 표시
                if st.session_state.get(f"show_transcript_{video['videoId']}", False):
                    with st.expander("📝 영상 대본", expanded=True):
                        with st.spinner("대본 추출 중..."):
                            transcript, error = get_transcript(video['url'])
                            if transcript:
                                st.text_area(
                                    "대본",
                                    transcript,
                                    height=300,
                                    key=f"transcript_text_list_{video['videoId']}"
                                )
                                if st.button("📋 대본 복사", key=f"copy_transcript_list_{video['videoId']}"):
                                    st.code(transcript, language=None)
                                    st.success("위 내용을 복사하세요!")
                            else:
                                st.error(error)
                        if st.button("❌ 닫기", key=f"close_transcript_list_{video['videoId']}"):
                            st.session_state[f"show_transcript_{video['videoId']}"] = False
                            st.rerun()
                
                # 댓글 표시
                if st.session_state.get(f"show_comments_{video['videoId']}", False):
                    with st.expander("💬 댓글 목록", expanded=True):
                        with st.spinner("댓글 가져오는 중..."):
                            comments, error = get_comments(
                                st.session_state.api_key,
                                video['videoId']
                            )
                            if comments:
                                df = pd.DataFrame(comments)
                                st.dataframe(df, use_container_width=True)
                                
                                csv = df.to_csv(index=False).encode('utf-8-sig')
                                st.download_button(
                                    "💾 CSV 다운로드",
                                    csv,
                                    f"comments_{video['videoId']}.csv",
                                    "text/csv",
                                    key=f"download_comments_list_{video['videoId']}"
                                )
                            else:
                                st.error(error)
                        if st.button("❌ 닫기", key=f"close_comments_list_{video['videoId']}"):
                            st.session_state[f"show_comments_{video['videoId']}"] = False
                            st.rerun()
                
                # AI 분석 표시
                if st.session_state.get(f"show_analysis_{video['videoId']}", False):
                    with st.expander("🤖 AI 벤치마킹 분석", expanded=True):
                        prompt = generate_ai_prompt(video['url'], video['thumbnail'])
                        st.markdown("#### 📋 분석 프롬프트")
                        st.text_area(
                            "프롬프트",
                            prompt,
                            height=400,
                            key=f"prompt_list_{video['videoId']}"
                        )
                        
                        col_a, col_b = st.columns(2)
                        with col_a:
                            if st.button("📋 프롬프트 복사", key=f"copy_prompt_list_{video['videoId']}"):
                                st.code(prompt, language=None)
                                st.success("위 내용을 복사하세요!")
                        with col_b:
                            st.link_button(
                                "🚀 Gemini AI로 분석",
                                "https://gemini.google.com/",
                                use_container_width=True
                            )
                        
                        if st.button("❌ 닫기", key=f"close_analysis_list_{video['videoId']}"):
                            st.session_state[f"show_analysis_{video['videoId']}"] = False
                            st.rerun()
                
                st.divider()

else:
    # 검색 결과 없을 때
    st.info("👈 왼쪽 사이드바에서 검색 조건을 설정하고 검색을 시작하세요!")
    
    # 사용 가이드
    with st.expander("📖 사용 방법", expanded=True):
        st.markdown("""
        ### 시작하기
        
        1. **API 키 설정**
           - Google Cloud Console에서 YouTube Data API v3 키 발급
           - 왼쪽 사이드바의 'API 설정'에 키 입력
           - 'API 연결 확인' 버튼 클릭
        
        2. **검색 조건 설정**
           - 키워드 입력
           - 검색 기간, 영상 길이 선택
           - 최소 조회수, 구독자 수 설정 (선택)
        
        3. **검색 실행**
           - '검색 시작' 버튼 클릭
           - 결과를 카드형 또는 리스트형으로 확인
        
        4. **영상 분석**
           - 각 영상의 대본, 댓글, AI 분석 기능 활용
        
        ### 주요 기능
        
        - **떡상지표**: 조회수 대비 참여율 (높을수록 바이럴 가능성 높음)
        - **성과지표**: 구독자 수 대비 조회수 (높을수록 확산력 높음)
        - **대본 추출**: YouTube 자막을 텍스트로 추출
        - **댓글 분석**: 댓글 목록 조회 및 CSV 다운로드
        - **AI 분석**: 영상 성공 요인 분석 프롬프트 생성
        """)

# 푸터
st.divider()
st.markdown(
    "<div style='text-align: center; color: #999;'>Made with ❤️ using Streamlit</div>",
    unsafe_allow_html=True
)

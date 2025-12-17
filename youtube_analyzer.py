from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
import requests
from datetime import datetime, timedelta
import re

app = Flask(__name__)
CORS(app)

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

def get_transcript(video_id):
    """Get video transcript/subtitles"""
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        # Try to get Korean transcript first
        try:
            transcript = transcript_list.find_transcript(['ko'])
        except:
            # If Korean not available, get any available transcript
            transcript = transcript_list.find_generated_transcript(['ko', 'en'])
        
        text_data = transcript.fetch()
        full_text = ' '.join([item['text'] for item in text_data])
        return {
            'success': True,
            'transcript': full_text,
            'language': transcript.language_code
        }
    except TranscriptsDisabled:
        return {'success': False, 'error': '이 비디오는 자막이 비활성화되어 있습니다.'}
    except NoTranscriptFound:
        return {'success': False, 'error': '이 비디오에는 사용 가능한 자막이 없습니다.'}
    except Exception as e:
        return {'success': False, 'error': f'자막을 가져오는 중 오류가 발생했습니다: {str(e)}'}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/validate', methods=['POST'])
def validate_api():
    """Validate YouTube API key"""
    data = request.json
    api_key = data.get('apiKey')
    
    if not api_key:
        return jsonify({'success': False, 'message': 'API 키를 입력해주세요.'})
    
    try:
        url = f'https://www.googleapis.com/youtube/v3/search?part=snippet&q=test&key={api_key}&maxResults=1'
        response = requests.get(url)
        
        if response.status_code == 200:
            return jsonify({'success': True, 'message': 'API 연결 성공!'})
        else:
            return jsonify({'success': False, 'message': 'API 키가 유효하지 않습니다.'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'연결 오류: {str(e)}'})

@app.route('/api/search', methods=['POST'])
def search_videos():
    """Search YouTube videos with filters"""
    data = request.json
    api_key = data.get('apiKey')
    keyword = data.get('keyword')
    period = data.get('period', 'all')
    video_length = data.get('videoLength', 'any')
    min_views = data.get('minViews', 0)
    min_subscribers = data.get('minSubscribers', 0)
    max_results = data.get('maxResults', 20)
    
    if not api_key or not keyword:
        return jsonify({'success': False, 'message': 'API 키와 키워드를 입력해주세요.'})
    
    # Build search URL
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
        elif period == '30days':
            published_after = (now - timedelta(days=30)).isoformat() + 'Z'
        elif period == 'custom':
            start_date = data.get('startDate')
            end_date = data.get('endDate')
            if start_date:
                published_after = datetime.fromisoformat(start_date).isoformat() + 'Z'
                params['publishedAfter'] = published_after
            if end_date:
                published_before = datetime.fromisoformat(end_date).isoformat() + 'Z'
                params['publishedBefore'] = published_before
        
        if period in ['7days', '30days']:
            params['publishedAfter'] = published_after
    
    # Add video duration filter
    if video_length == 'short':
        params['videoDuration'] = 'short'  # < 4 minutes
    elif video_length == 'long':
        params['videoDuration'] = 'medium,long'  # > 4 minutes
    
    try:
        # Search videos
        response = requests.get(base_url, params=params)
        if response.status_code != 200:
            return jsonify({'success': False, 'message': 'API 요청 실패'})
        
        search_data = response.json()
        video_ids = [item['id']['videoId'] for item in search_data.get('items', [])]
        
        if not video_ids:
            return jsonify({'success': True, 'videos': []})
        
        # Get detailed video statistics
        stats_url = 'https://www.googleapis.com/youtube/v3/videos'
        stats_params = {
            'part': 'statistics,contentDetails,snippet',
            'id': ','.join(video_ids),
            'key': api_key
        }
        
        stats_response = requests.get(stats_url, params=stats_params)
        if stats_response.status_code != 200:
            return jsonify({'success': False, 'message': 'API 요청 실패'})
        
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
        
        return jsonify({'success': True, 'videos': videos})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'오류: {str(e)}'})

@app.route('/api/transcript', methods=['POST'])
def get_video_transcript():
    """Get video transcript/subtitles"""
    data = request.json
    video_url = data.get('videoUrl')
    
    if not video_url:
        return jsonify({'success': False, 'error': 'Video URL이 필요합니다.'})
    
    video_id = get_video_id(video_url)
    result = get_transcript(video_id)
    
    return jsonify(result)

@app.route('/api/comments', methods=['POST'])
def get_comments():
    """Get video comments"""
    data = request.json
    api_key = data.get('apiKey')
    video_id = data.get('videoId')
    
    if not api_key or not video_id:
        return jsonify({'success': False, 'message': 'API 키와 Video ID가 필요합니다.'})
    
    try:
        url = 'https://www.googleapis.com/youtube/v3/commentThreads'
        params = {
            'part': 'snippet',
            'videoId': video_id,
            'key': api_key,
            'maxResults': 100,
            'order': 'relevance'
        }
        
        response = requests.get(url, params=params)
        if response.status_code != 200:
            return jsonify({'success': False, 'message': 'API 요청 실패'})
        
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
        
        return jsonify({'success': True, 'comments': comments})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'오류: {str(e)}'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

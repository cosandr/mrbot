from typing import Dict, Optional, List

import youtube_dl
from aiohttp import ClientSession

youtube_dl.utils.bug_reports_message = lambda: ''
_YTDL_OPTS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}
_ytdl = youtube_dl.YoutubeDL(_YTDL_OPTS)


def get_stream_url(url: str) -> Optional[str]:
    """Returns stream url from YouTube video URL."""
    data = _ytdl.extract_info(url, download=False)
    return data.get('url', None)


class YouTube:

    def __init__(self, sess: ClientSession, key: str):
        self.sess = sess
        self.key = key

    async def search(self, name: str, max_results: int = 5, playlist: bool = False) -> List[Dict[str, str]]:
        """
        Search YouTube using the Google API.
        Parameters
        ----------
        name: `str`
            What to search for.
        max_results: `int`
            How many videos/playlists to return.
        playlist: `bool`
            Search for playlists instead of videos.
        Returns
        --------
        `list`
            List of dictionaries with results.
        """
        url = 'https://www.googleapis.com/youtube/v3/search'
        headers = {'Accept': 'application/json'}
        params = {
            'q': name,
            'part': 'id,snippet',
            'maxResults': max_results,
            'order': 'relevance',
            'fields': 'items/id,items/snippet/title,items/snippet/channelTitle,items/snippet/publishedAt',
            'key': self.key
        }
        async with self.sess.get(url=url, headers=headers, params=params) as resp:
            data = await resp.json()
        items = data.get('items', None)
        if (items is None) or (len(items) == 0):
            return None
        res_list = []
        for item in items:
            if item['id']['kind'] == 'youtube#video':
                res_id = item['id']['videoId']
                url = f"https://www.youtube.com/watch?v={res_id}"
                res_type = 'video'
            elif item['id']['kind'] == 'youtube#playlist':
                res_id = item['id']['playlistId']
                url = f"https://www.youtube.com/playlist?list={res_id}"
                res_type = 'playlist'
            else:
                print(f"[YouTube] [WARNING] Search encountered unknown type: {item['id']['kind']}\n{item}")
                continue
            title = item['snippet']['title']
            uploader = item['snippet']['channelTitle']
            # YYYY-MM-DDThh:mm:ss.sZ
            published = item['snippet']['publishedAt']
            res_list.append(dict(url=url, title=title, uploader=uploader, published=published, type=res_type, id=res_id))
        return res_list

    async def video_info(self, video_id: str) -> Dict[str, str]:
        """
        Fetch video details from video ID.
        Parameters
        ----------
        video_id: `str`
            YouTube video ID to examine.
        Returns
        --------
        `dict`
            Dictionary with info, same as `search` method.
        """
        url = 'https://www.googleapis.com/youtube/v3/videos'
        headers = {'Accept': 'application/json'}
        params = {
            'id': video_id,
            'part': 'snippet,statistics',
            'fields': 'items/snippet/title,items/snippet/channelTitle,items/snippet/publishedAt,items/statistics/viewCount',
            'key': self.key
        }
        async with self.sess.get(url=url, headers=headers, params=params) as resp:
            data = await resp.json()
        # Check for error
        if data.get('error'):
            print(f'YT API error: {data["error"]["errors"][0]["reason"]}: {data["error"]["errors"][0]["message"]}')
            return
        items = data.get('items')
        if items is None or len(items) == 0:
            return
        url = f"https://www.youtube.com/watch?v={video_id}"
        title = items[0]['snippet']['title']
        uploader = items[0]['snippet']['channelTitle']
        published = items[0]['snippet']['publishedAt']
        views = items[0]['statistics']['viewCount']
        return dict(url=url, title=title, views=views, uploader=uploader, published=published, type='video', id=video_id)

    async def playlist_videos(self, playlist_id, max_results: int = 50) -> List[Dict[str, str]]:
        """
        Fetch videos in YouTube playlist using the Google API.\n
        NOTE: uploader and published refer to whoever added the videos to the playlist,
        NOT whoever uploaded the videos themselves.
        Parameters
        ----------
        playlist_id: `str`
            What to search for.
        max_results: `int`
            How many videos/playlists to return.
        Returns
        --------
        `list`
            List of dictionaries with results.
        """
        url = 'https://www.googleapis.com/youtube/v3/playlistItems'
        headers = {'Accept': 'application/json'}
        params = {
            'playlistId': playlist_id,
            'part': 'contentDetails,snippet',
            'maxResults': max_results,
            'key': self.key
        }
        async with self.sess.get(url=url, headers=headers, params=params) as resp:
            data = await resp.json()
        # Fetch all pages and put them in data['items']
        next_page_token = data.get('nextPageToken')
        while 'nextPageToken' in data:
            params = {
                'playlistId': playlist_id,
                'part': 'contentDetails,snippet',
                'maxResults': max_results,
                'pageToken': next_page_token,
                'key': self.key
            }
            async with self.sess.get(url=url, headers=headers, params=params) as resp:
                next_page = await resp.json()
            data['items'] = data['items'] + next_page['items']
            next_page_token = next_page.get('nextPageToken')
            if next_page_token is None:
                data.pop('nextPageToken', None)
        res_list = []
        for item in data['items']:
            if item['snippet']['resourceId']['kind'] != 'youtube#video':
                print(f"[YouTube] [WARNING] Playlist fetch encountered unknown type: {item['snippet']['resourceId']['kind']}\n{item}")
                continue
            res_type = 'video'
            res_id = item['contentDetails']['videoId']
            url = f"https://www.youtube.com/watch?v={res_id}"
            title = item['snippet']['title']
            uploader = item['snippet']['channelTitle']
            # YYYY-MM-DDThh:mm:ss.sZ
            published = item['snippet']['publishedAt']
            res_list.append(dict(url=url, title=title, uploader=uploader, published=published, type=res_type, id=res_id))
        return res_list

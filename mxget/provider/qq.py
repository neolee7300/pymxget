import asyncio
import json
import typing

import aiohttp

from mxget import (
    api,
    exceptions,
)

_API_SEARCH = 'https://c.y.qq.com/soso/fcgi-bin/client_search_cp?format=json&platform=yqq&new_json=1'
_API_GET_SONG = 'https://c.y.qq.com/v8/fcg-bin/fcg_play_single_song.fcg?format=json&platform=yqq'
_API_GET_SONG_URL = 'http://c.y.qq.com/base/fcgi-bin/fcg_music_express_mobile3.fcg?' \
                    'format=json&platform=yqq&needNewCode=0&cid=205361747&uin=0&guid=0'
_API_GET_SONG_LYRIC = 'https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?format=json&platform=yqq&nobase64=1'
_API_GET_ARTIST = 'https://c.y.qq.com/v8/fcg-bin/fcg_v8_singer_track_cp.fcg?' \
                  'format=json&platform=yqq&newsong=1&order=listen'
_API_GET_ALBUM = 'https://c.y.qq.com/v8/fcg-bin/fcg_v8_album_detail_cp.fcg?format=json&platform=yqq&newsong=1'
_API_GET_PLAYLIST = 'https://c.y.qq.com/v8/fcg-bin/fcg_v8_playlist_cp.fcg?format=json&platform=yqq&newsong=1'

_SONG_URL = 'http://mobileoc.music.tc.qq.com/{filename}?guid=0&uin=0&vkey={vkey}'
_ARTIST_PIC_URL = 'https://y.gtimg.cn/music/photo_new/T001R800x800M000{singer_mid}.jpg'
_ALBUM_PIC_URL = 'https://y.gtimg.cn/music/photo_new/T002R800x800M000{album_mid}.jpg'


def _resolve(*songs: dict) -> typing.List[api.Song]:
    return [
        api.Song(
            song_id=song['mid'],
            name=song['title'].strip(),
            artist='/'.join([s['name'].strip() for s in song['singer']]),
            album=song['album']['name'].strip(),
            pic_url=_ALBUM_PIC_URL.format(album_mid=song['album']['mid']),
            lyric=song.get('lyric'),
            url=song.get('url'),
        ) for song in songs
    ]


class QQ(api.API):
    def __init__(self, session: aiohttp.ClientSession = None):
        if session is None:
            session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=120),
            )
        self._session = session

    async def close(self):
        await self._session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def platform_id(self) -> api.PlatformId:
        return api.PlatformId.QQ

    async def search_songs(self, keyword: str) -> api.SearchSongsResult:
        resp = await self.search_songs_raw(keyword)
        try:
            _songs = resp['data']['song']['list']
        except KeyError:
            raise exceptions.DataError('search songs: no data')

        if not _songs:
            raise exceptions.DataError('search songs: no data')

        songs = [
            api.SearchSongsData(
                song_id=_song['mid'],
                name=_song['title'].strip(),
                artist='/'.join([s['name'].strip() for s in _song['singer']]),
                album=_song['album']['name'].strip(),
            ) for _song in _songs
        ]
        return api.SearchSongsResult(keyword=keyword, count=len(songs), songs=songs)

    async def search_songs_raw(self, keyword: str, page: int = 1, page_size: int = 50) -> dict:
        params = {
            'w': keyword,
            'p': page,
            'n': page_size,
        }

        try:
            _resp = await self.request('GET', _API_SEARCH, params=params)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise exceptions.RequestError('search songs: {}'.format(e))

        try:
            resp = await _resp.json(content_type=None)
            if resp['code'] != 0:
                raise exceptions.ResponseError('search songs: {}'.format(resp['code']))
        except (aiohttp.ClientResponseError, json.JSONDecodeError, KeyError) as e:
            raise exceptions.ResponseError('search songs: {}'.format(e))

        return resp

    async def get_song(self, song_mid: str) -> api.Song:
        resp = await self.get_song_raw(song_mid)
        try:
            _song = resp['data'][0]
        except (KeyError, IndexError):
            raise exceptions.DataError('get song: no data')

        await self._patch_song_url(_song)
        await self._patch_song_lyric(_song)
        songs = _resolve(_song)
        return songs[0]

    async def get_song_raw(self, song_mid: str) -> dict:
        params = {
            'songmid': song_mid,
        }

        try:
            _resp = await self.request('GET', _API_GET_SONG, params=params)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise exceptions.RequestError('get song: {}'.format(e))

        try:
            resp = await _resp.json(content_type=None)
            if resp['code'] != 0:
                raise exceptions.ResponseError('get song: {}'.format(resp['code']))
        except (aiohttp.ClientResponseError, json.JSONDecodeError, KeyError) as e:
            raise exceptions.ResponseError('get song: {}'.format(e))

        return resp

    async def get_song_url(self, song_mid: str, media_mid: str) -> typing.Optional[str]:
        try:
            resp = await self.get_song_url_raw(song_mid, media_mid)
            item = resp['data']['items'][0]
        except (exceptions.RequestError, exceptions.ResponseError, KeyError, IndexError):
            return None

        if item['subcode'] != 0:
            return None

        return _SONG_URL.format(filename=item['filename'], vkey=item['vkey'])

    async def get_song_url_raw(self, song_mid: str, media_mid: str) -> dict:
        params = {
            'songmid': song_mid,
            'filename': 'M500' + media_mid + '.mp3',
        }

        try:
            _resp = await self.request('GET', _API_GET_SONG_URL, params=params)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise exceptions.RequestError('get song url: {}'.format(e))

        try:
            resp = await _resp.json(content_type=None)
            if resp['code'] != 0:
                raise exceptions.ResponseError('get song url: {}'.format(resp.get('errinfo', 'copyright protection')))
        except (aiohttp.ClientResponseError, json.JSONDecodeError, KeyError) as e:
            raise exceptions.ResponseError('get song url: {}'.format(e))

        return resp

    async def get_song_lyric(self, song_mid: str) -> typing.Optional[str]:
        try:
            resp = await self.get_song_lyric_raw(song_mid)
            lyric = resp['lyric']
        except (exceptions.RequestError, exceptions.ResponseError, KeyError):
            return None

        return lyric

    async def get_song_lyric_raw(self, song_mid: str):
        params = {
            'songmid': song_mid,
        }

        try:
            _resp = await self.request('GET', _API_GET_SONG_LYRIC, params=params)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise exceptions.RequestError('get song lyric: {}'.format(e))

        try:
            resp = await _resp.json(content_type=None)
            if resp['code'] != 0:
                raise exceptions.ResponseError('get song lyric: {}'.format(resp['code']))
        except (aiohttp.ClientResponseError, json.JSONDecodeError, KeyError) as e:
            raise exceptions.ResponseError('get song lyric: {}'.format(e))

        return resp

    async def _patch_song_url(self, *songs: dict) -> None:
        sem = asyncio.Semaphore(32)

        async def worker(song: dict):
            async with sem:
                song['url'] = await self.get_song_url(song['mid'], song['file']['media_mid'])

        tasks = [asyncio.ensure_future(worker(song)) for song in songs]
        await asyncio.gather(*tasks)

    async def _patch_song_lyric(self, *songs: dict) -> None:
        sem = asyncio.Semaphore(32)

        async def worker(song: dict):
            async with sem:
                song['lyric'] = await self.get_song_lyric(song['mid'])

        tasks = [asyncio.ensure_future(worker(song)) for song in songs]
        await asyncio.gather(*tasks)

    async def get_artist(self, singer_mid: str) -> api.Artist:
        resp = await self.get_artist_raw(singer_mid)
        try:
            artist = resp['data']
            items = artist['list']
        except KeyError:
            raise exceptions.DataError('get artist: no data')

        if not items:
            raise exceptions.DataError('get artist: no data')

        _songs = [i['musicData'] for i in items]
        await self._patch_song_url(*_songs)
        await self._patch_song_lyric(*_songs)
        songs = _resolve(*_songs)
        return api.Artist(
            artist_id=artist['singer_mid'],
            name=artist['singer_name'].strip(),
            pic_url=_ARTIST_PIC_URL.format(singer_mid=artist['singer_mid']),
            count=len(songs),
            songs=songs,
        )

    async def get_artist_raw(self, singer_mid: str, page: int = 1, page_size: int = 50) -> dict:
        params = {
            'singermid': singer_mid,
            'begin': page,
            'num': page_size,
        }

        try:
            _resp = await self.request('GET', _API_GET_ARTIST, params=params)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise exceptions.RequestError('get artist: {}'.format(e))

        try:
            resp = await _resp.json(content_type=None)
            if resp['code'] != 0:
                raise exceptions.ResponseError('get artist: {}'.format(resp['code']))
        except (aiohttp.ClientResponseError, json.JSONDecodeError, KeyError) as e:
            raise exceptions.ResponseError('get artist: {}'.format(e))

        return resp

    async def get_album(self, album_mid: str) -> api.Album:
        resp = await self.get_album_raw(album_mid)
        try:
            album = resp['data']['getAlbumInfo']
            _songs = resp['data']['getSongInfo']
        except KeyError:
            raise exceptions.DataError('get album: no data')

        if not _songs:
            raise exceptions.DataError('get album: no data')

        await self._patch_song_url(*_songs)
        await self._patch_song_lyric(*_songs)
        songs = _resolve(*_songs)
        return api.Album(
            album_id=album['Falbum_mid'],
            name=album['Falbum_name'].strip(),
            pic_url=_ALBUM_PIC_URL.format(album_mid=album['Falbum_mid']),
            count=len(songs),
            songs=songs,
        )

    async def get_album_raw(self, album_mid: str) -> dict:
        params = {
            'albummid': album_mid,
        }

        try:
            _resp = await self.request('GET', _API_GET_ALBUM, params=params)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise exceptions.RequestError('get album: {}'.format(e))

        try:
            resp = await _resp.json(content_type=None)
            if resp['code'] != 0:
                raise exceptions.ResponseError('get album: {}'.format(resp['code']))
        except (aiohttp.ClientResponseError, json.JSONDecodeError, KeyError) as e:
            raise exceptions.ResponseError('get album: {}'.format(e))

        return resp

    async def get_playlist(self, playlist_id: typing.Union[int, str]) -> api.Playlist:
        resp = await self.get_playlist_raw(playlist_id)

        try:
            playlist = resp['data']['cdlist'][0]
            _songs = playlist['songlist']
        except (KeyError, IndexError):
            raise exceptions.DataError('get playlist: no data')

        if not _songs:
            raise exceptions.DataError('get playlist: no data')

        await self._patch_song_lyric(*_songs)
        songs = _resolve(*_songs)
        return api.Playlist(
            playlist_id=playlist['disstid'],
            name=playlist['dissname'],
            pic_url=playlist.get('dir_pic_url2', ''),
            count=len(songs),
            songs=songs,
        )

    async def get_playlist_raw(self, playlist_id: typing.Union[int, str]) -> dict:
        params = {
            'id': playlist_id,
        }

        try:
            _resp = await self.request('GET', _API_GET_PLAYLIST, params=params)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise exceptions.RequestError('get playlist: {}'.format(e))

        try:
            resp = await _resp.json(content_type=None)
            if resp['code'] != 0:
                raise exceptions.ResponseError('get playlist: {}'.format(resp['code']))
        except (aiohttp.ClientResponseError, json.JSONDecodeError, KeyError) as e:
            raise exceptions.ResponseError('get playlist: {}'.format(e))

        return resp

    async def request(self, method: str, url: str, **kwargs) -> aiohttp.ClientResponse:
        headers = {
            'Origin': 'https://c.y.qq.com',
            'Referer': 'https://c.y.qq.com',
            'User-Agent': api.USER_AGENT,
        }
        kwargs.update({
            'headers': headers,
        })
        return await self._session.request(method, url, **kwargs)

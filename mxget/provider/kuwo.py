import asyncio
import json
import typing

import aiohttp
import yarl

from mxget import (
    api,
    exceptions,
)

_API_SEARCH = 'http://www.kuwo.cn/api/www/search/searchMusicBykeyWord'
_API_GET_SONG = 'http://www.kuwo.cn/api/www/music/musicInfo'
_API_GET_SONG_URL = 'http://www.kuwo.cn/url?format=mp3&response=url&type=convert_url3'
_API_GET_SONG_LYRIC = 'http://www.kuwo.cn/newh5/singles/songinfoandlrc'
_API_GET_ARTIST_INFO = 'http://www.kuwo.cn/api/www/artist/artist'
_API_GET_ARTIST_SONGS = 'http://www.kuwo.cn/api/www/artist/artistMusic'
_API_GET_ALBUM = 'http://www.kuwo.cn/api/www/album/albumInfo'
_API_GET_PLAYLIST = 'http://www.kuwo.cn/api/www/playlist/playListInfo'


def _bit_rate(br: int) -> int:
    return {
        128: 128,
        192: 192,
        320: 320,
    }.get(br, 320)


def _resolve(*songs: dict) -> typing.List[api.Song]:
    return [
        api.Song(
            song_id=song['rid'],
            name=song['name'].strip(),
            artist=song['artist'].replace('&', '/').strip(),
            album=song.get('album', '').strip(),
            pic_url=song.get('albumpic'),
            lyric=song.get('lyric'),
            url=song.get('url'),
        ) for song in songs
    ]


class KuWo(api.API):
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
        return api.PlatformId.KuWo

    async def search_songs(self, keyword: str) -> api.SearchSongsResult:
        resp = await self.search_songs_raw(keyword)
        try:
            _songs = resp['data']['list']
        except KeyError:
            raise exceptions.DataError('search songs: no data')

        if not _songs:
            raise exceptions.DataError('search songs: no data')

        songs = [
            api.SearchSongsData(
                song_id=_song['rid'],
                name=_song['name'].strip(),
                artist=_song['artist'].replace('&', '/').strip(),
                album=_song['album'].strip(),
            ) for _song in _songs
        ]
        return api.SearchSongsResult(keyword=keyword, count=len(songs), songs=songs)

    async def search_songs_raw(self, keyword: str, page: int = 1, page_size: int = 50) -> dict:
        params = {
            'key': keyword,
            'pn': page,
            'rn': page_size,
        }

        try:
            _resp = await self.request('GET', _API_SEARCH, params=params)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise exceptions.RequestError('search songs: {}'.format(e))

        try:
            resp = await _resp.json(content_type=None)
            if resp['code'] != 200:
                raise exceptions.ResponseError('search songs: {}'.format(resp['msg']))
        except (aiohttp.ClientResponseError, json.JSONDecodeError, KeyError) as e:
            raise exceptions.ResponseError('search songs: {}'.format(e))

        return resp

    async def get_song(self, mid: typing.Union[int, str]) -> api.Song:
        resp = await self.get_song_raw(mid)
        try:
            _song = resp['data']
        except KeyError:
            raise exceptions.DataError('get song: no data')

        await self._patch_song_url(_song)
        await self._patch_song_lyric(_song)
        songs = _resolve(_song)
        return songs[0]

    async def get_song_raw(self, mid: typing.Union[int, str]) -> dict:
        params = {
            'mid': mid,
        }

        try:
            _resp = await self.request('GET', _API_GET_SONG, params=params)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise exceptions.RequestError('get song: {}'.format(e))

        try:
            resp = await _resp.json(content_type=None)
            if resp['code'] != 200:
                raise exceptions.ResponseError('get song: {}'.format(resp['msg']))
        except (aiohttp.ClientResponseError, json.JSONDecodeError, KeyError) as e:
            raise exceptions.ResponseError('get song: {}'.format(e))

        return resp

    async def get_song_url(self, mid: typing.Union[int, str], br: int = 128) -> typing.Optional[str]:
        try:
            resp = await self.get_song_url_raw(mid, br)
        except (exceptions.RequestError, exceptions.ResponseError):
            return None

        try:
            url = resp['url']
        except KeyError:
            return None

        return url if url else None

    async def get_song_url_raw(self, mid: typing.Union[int, str], br: int = 128) -> dict:
        params = {
            'rid': mid,
            'br': '{}kmp3'.format(_bit_rate(br)),
        }

        try:
            _resp = await self.request('GET', _API_GET_SONG_URL, params=params)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise exceptions.RequestError('get song url: {}'.format(e))

        try:
            resp = await _resp.json(content_type=None)
            if resp['code'] != 200:
                raise exceptions.ResponseError('get song url: {}'.format(resp.get('msg', 'copyright protection')))
        except (aiohttp.ClientResponseError, json.JSONDecodeError, KeyError) as e:
            raise exceptions.ResponseError('get song url: {}'.format(e))

        return resp

    async def get_song_lyric(self, mid: typing.Union[int, str]) -> typing.Optional[str]:
        resp = await self.get_song_lyric_raw(mid)
        try:
            lrc_list = resp['data']['lrclist']
        except KeyError:
            return None

        if not lrc_list:
            return None

        lines = []
        for lrc in lrc_list:
            t = float(lrc['time'])
            m = int(t / 60)
            s = int(t - m * 60)
            ms = int((t - m * 60 - s) * 100)
            lines.append(
                '[{minute:02d}:{second:02d}:{millisecond:02d}]{lyric:s}'.format(
                    minute=m, second=s, millisecond=ms, lyric=lrc['lineLyric']))

        return '\n'.join(lines)

    async def get_song_lyric_raw(self, mid: typing.Union[int, str]) -> dict:
        params = {
            'musicId': mid,
        }

        try:
            _resp = await self.request('GET', _API_GET_SONG_LYRIC, params=params)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise exceptions.RequestError('get song lyric: {}'.format(e))

        try:
            resp = await _resp.json(content_type=None)
            if resp['status'] != 200:
                raise exceptions.ResponseError('get song lyric: {}'.format(resp['msg']))
        except (aiohttp.ClientResponseError, json.JSONDecodeError, KeyError) as e:
            raise exceptions.ResponseError('get song lyric: {}'.format(e))

        return resp

    async def _patch_song_url(self, *songs: dict) -> None:
        sem = asyncio.Semaphore(32)

        async def worker(song: dict):
            async with sem:
                song['url'] = await self.get_song_url(song['rid'])

        tasks = [asyncio.ensure_future(worker(song)) for song in songs]
        await asyncio.gather(*tasks)

    async def _patch_song_lyric(self, *songs: dict) -> None:
        sem = asyncio.Semaphore(32)

        async def worker(song: dict):
            async with sem:
                song['lyric'] = await self.get_song_lyric(song['rid'])

        tasks = [asyncio.ensure_future(worker(song)) for song in songs]
        await asyncio.gather(*tasks)

    async def get_artist(self, singer_id: typing.Union[int, str]) -> api.Artist:
        artist_info = await self.get_artist_info_raw(singer_id)
        artist_song = await self.get_artist_songs_raw(singer_id)

        try:
            artist = artist_info['data']
            _songs = artist_song['data']['list']
        except KeyError:
            raise exceptions.DataError('get artist: no data')

        if not _songs:
            raise exceptions.DataError('get artist: no data')

        await self._patch_song_url(*_songs)
        await self._patch_song_lyric(*_songs)
        songs = _resolve(*_songs)
        return api.Artist(
            artist_id=artist['id'],
            name=artist['name'].strip(),
            pic_url=artist.get('pic300', ''),
            count=len(songs),
            songs=songs,
        )

    async def get_artist_info_raw(self, artist_id: typing.Union[int, str]) -> dict:
        params = {
            'artistid': artist_id,
        }

        try:
            _resp = await self.request('GET', _API_GET_ARTIST_INFO, params=params)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise exceptions.RequestError('get artist info: {}'.format(e))

        try:
            resp = await _resp.json(content_type=None)
            if resp['code'] != 200:
                raise exceptions.ResponseError('get artist info: {}'.format(resp.get('msg', 'no data')))
        except (aiohttp.ClientResponseError, json.JSONDecodeError, KeyError) as e:
            raise exceptions.ResponseError('get artist info: {}'.format(e))

        return resp

    async def get_artist_songs_raw(self, artist_id: typing.Union[int, str],
                                   page: int = 1, page_size: int = 50) -> dict:
        params = {
            'artistid': artist_id,
            'pn': page,
            'rn': page_size,
        }

        try:
            _resp = await self.request('GET', _API_GET_ARTIST_SONGS, params=params)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise exceptions.RequestError('get artist songs: {}'.format(e))

        try:
            resp = await _resp.json(content_type=None)
            if resp['code'] != 200:
                raise exceptions.ResponseError('get artist songs: {}'.format(resp['msg']))
        except (aiohttp.ClientResponseError, json.JSONDecodeError, KeyError) as e:
            raise exceptions.ResponseError('get artist songs: {}'.format(e))

        return resp

    async def get_album(self, album_id: typing.Union[int, str]) -> api.Album:
        resp = await self.get_album_raw(album_id)

        try:
            album = resp['data']
            _songs = album['musicList']
        except KeyError:
            raise exceptions.DataError('get album: no data')

        if not _songs:
            raise exceptions.DataError('get album: no data')

        await self._patch_song_url(*_songs)
        await self._patch_song_lyric(*_songs)
        songs = _resolve(*_songs)
        return api.Album(
            album_id=album['albumId'],
            name=album['album'].strip(),
            pic_url=album.get('pic', ''),
            count=len(songs),
            songs=songs,
        )

    async def get_album_raw(self, album_id: typing.Union[int, str],
                            page: int = 1, page_size: int = 9999) -> dict:
        params = {
            'albumId': album_id,
            'pn': page,
            'rn': page_size,
        }

        try:
            _resp = await self.request('GET', _API_GET_ALBUM, params=params)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise exceptions.RequestError('get album: {}'.format(e))

        try:
            resp = await _resp.json(content_type=None)
            if resp['code'] != 200:
                raise exceptions.ResponseError('get album: {}'.format(resp['msg']))
        except (aiohttp.ClientResponseError, json.JSONDecodeError, KeyError) as e:
            raise exceptions.ResponseError('get album: {}'.format(e))

        return resp

    async def get_playlist(self, playlist_id: typing.Union[int, str]) -> api.Playlist:
        resp = await self.get_playlist_raw(playlist_id)

        try:
            playlist = resp['data']
            _songs = playlist['musicList']
        except KeyError:
            raise exceptions.DataError('get playlist: no data')

        if not _songs:
            raise exceptions.DataError('get playlist: no data')

        await self._patch_song_url(*_songs)
        await self._patch_song_lyric(*_songs)
        songs = _resolve(*_songs)
        return api.Playlist(
            playlist_id=playlist['id'],
            name=playlist['name'].strip(),
            pic_url=playlist.get('img700', ''),
            count=len(songs),
            songs=songs,
        )

    async def get_playlist_raw(self, playlist_id: typing.Union[int, str],
                               page: int = 1, page_size: int = 9999) -> dict:
        params = {
            'pid': playlist_id,
            'pn': page,
            'rn': page_size,
        }

        try:
            _resp = await self.request('GET', _API_GET_PLAYLIST, params=params)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise exceptions.RequestError('get playlist: {}'.format(e))

        try:
            resp = await _resp.json(content_type=None)
            if resp['code'] != 200:
                raise exceptions.ResponseError('get playlist: {}'.format(resp['msg']))
        except (aiohttp.ClientResponseError, json.JSONDecodeError, KeyError) as e:
            raise exceptions.ResponseError('get playlist: {}'.format(e))

        return resp

    async def request(self, method: str, url: str, **kwargs) -> aiohttp.ClientResponse:
        csrf = '0'
        cookie = self._session.cookie_jar.filter_cookies(yarl.URL(url)).get('kw_token')
        if cookie is None:
            kwargs.update({
                'cookies': {
                    'kw_token': csrf
                }
            })
        else:
            csrf = cookie.value

        headers = {
            'csrf': csrf,
            'Origin': 'http://www.kuwo.cn',
            'Referer': 'http://www.kuwo.cn',
            'User-Agent': api.USER_AGENT,
        }
        kwargs.update({
            'headers': headers,
        })

        return await self._session.request(method, url, **kwargs)

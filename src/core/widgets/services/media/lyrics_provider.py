"""Match lyrics search results to tracks and decode provider responses."""

from __future__ import annotations

import json
import math
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from typing import Literal, cast
from urllib.parse import urlencode

from core.widgets.services.media.lyrics_model import (
    MAX_BYTES,
    LyricLine,
    LyricsDocument,
    LyricWord,
    parse_lyrics,
)

Provider = Literal["lrclib", "netease", "better_lyrics", "musixmatch"]
Stage = Literal[
    "lrclib-search",
    "netease-cloud",
    "netease-search",
    "netease-lyrics",
    "better-lyrics",
    "musixmatch-search",
    "musixmatch-lyrics",
]


def _normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


@dataclass(frozen=True)
class LyricsQuery:
    title: str
    artist: str
    album: str = ""
    duration_ms: int | None = None

    def validate(self) -> None:
        if not self.title.strip() or any(
            len(value) > 512 or "\0" in value for value in (self.title, self.artist, self.album)
        ):
            raise ValueError("Title is required; metadata fields must be at most512characters")
        if self.duration_ms is not None and (
            type(self.duration_ms) is not int or not 0 < self.duration_ms <= 7 * 24 * 3600000
        ):
            raise ValueError("Invalid lyric query duration")

    def normalized(self) -> LyricsQuery:
        self.validate()
        return replace(
            self, title=_normalized(self.title), artist=_normalized(self.artist), album=_normalized(self.album)
        )


@dataclass(frozen=True)
class LyricsRequest:
    query: LyricsQuery
    stage: Stage = "lrclib-search"
    track_id: int = 0
    providers: tuple[Provider, ...] = ("lrclib", "netease", "better_lyrics")
    credentials: tuple[tuple[Provider, str], ...] = ()

    @property
    def provider(self) -> Provider:
        if self.stage == "lrclib-search":
            return "lrclib"
        if self.stage.startswith("netease"):
            return "netease"
        if self.stage == "better-lyrics":
            return "better_lyrics"
        if self.stage.startswith("musixmatch"):
            return "musixmatch"
        return "better_lyrics"

    def credential(self, provider: Provider) -> str:
        return dict(self.credentials).get(provider, "")

    @property
    def url(self) -> str:
        query = self.query
        if self.stage == "lrclib-search":
            return "https://lrclib.net/api/search?" + urlencode(
                {"track_name": query.title, "artist_name": query.artist}
            )
        if self.stage == "netease-lyrics":
            return "https://music.163.com/api/song/lyric?" + urlencode(
                {"id": self.track_id, "lv": 1, "kv": 1, "tv": -1, "yv": 1}
            )
        if self.stage == "better-lyrics":
            duration = "" if query.duration_ms is None else str(round(query.duration_ms / 1000))
            return "https://api.betterlyrics.org/getLyrics?" + urlencode(
                {"s": query.title, "a": query.artist, "al": query.album, "d": duration}
            )
        if self.stage == "musixmatch-search":
            return "https://api.musixmatch.com/ws/1.1/track.search?" + urlencode(
                {
                    "apikey": self.credential("musixmatch"),
                    "q_track": query.title,
                    "q_artist": query.artist,
                    "f_has_lyrics": 1,
                }
            )
        if self.stage == "musixmatch-lyrics":
            return "https://api.musixmatch.com/ws/1.1/track.lyrics.get?" + urlencode(
                {"apikey": self.credential("musixmatch"), "track_id": self.track_id}
            )
        search = {"s": query.artist + " " + query.title, "type": 1, "limit": 8, "offset": 0}
        path = "/api/cloudsearch/pc" if self.stage == "netease-cloud" else "/api/search/get/web"
        return "https://music.163.com" + path + "?" + urlencode(search)

    def fallback(self) -> LyricsRequest | None:
        if self.stage == "netease-cloud":
            return replace(self, stage="netease-search")
        if self.stage not in (
            "lrclib-search",
            "netease-search",
            "netease-lyrics",
            "better-lyrics",
            "musixmatch-search",
            "musixmatch-lyrics",
        ):
            return None
        try:
            next_provider = self.providers[self.providers.index(self.provider) + 1]
        except ValueError, IndexError:
            return None
        next_stage: dict[Provider, Stage] = {
            "lrclib": "lrclib-search",
            "netease": "netease-cloud",
            "better_lyrics": "better-lyrics",
            "musixmatch": "musixmatch-search",
        }
        return replace(self, stage=next_stage[next_provider])


@dataclass(frozen=True)
class ProviderResult:
    document: LyricsDocument | None = None
    next_request: LyricsRequest | None = None
    detail: str = "No matching lyrics found"


def _dictionary(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Invalid provider record")
    return cast(dict[str, object], value)


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _duration(value: object, *, milliseconds: bool = False) -> int | None:
    if type(value) not in (int, float):
        return None
    number = cast(int | float, value)
    if not math.isfinite(number) or number <= 0 or number > (7 * 24 * 3600000 if milliseconds else 7 * 24 * 3600):
        return None
    return round(number if milliseconds else number * 1000)


def match_score(query: LyricsQuery, title: str, artist: str, duration_ms: int | None, album: str = "") -> float:
    query = query.normalized()
    title, artist = _normalized(title), _normalized(artist)
    if not title or not artist or len(title) > 512 or len(artist) > 512:
        return 0
    versions = r"\b(live|remix|instrumental|karaoke|acoustic|remaster(?:ed)?|edit|version)\b"
    if set(re.findall(versions, query.title)) != set(re.findall(versions, title)):
        return 0
    title_score = SequenceMatcher(None, query.title, title, autojunk=False).ratio()
    artist_score = SequenceMatcher(None, query.artist, artist, autojunk=False).ratio()
    if title_score < 0.9 or artist_score < 0.8:
        return 0
    if query.duration_ms is not None and (duration_ms is None or abs(query.duration_ms - duration_ms) > 2000):
        return 0
    score = title_score * 0.65 + artist_score * 0.3
    return score + (0.05 if query.album and _normalized(album) == query.album else 0)


def _lrclib_document(record: dict[str, object]) -> LyricsDocument | None:
    source = "LRCLIB"
    if record.get("instrumental") is True:
        return LyricsDocument(instrumental=True, source=source)
    for name in ("lyricsfile", "syncedLyrics", "plainLyrics"):
        text = record.get(name)
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            document = parse_lyrics(text, filename="lyricsfile.yaml" if name == "lyricsfile" else "", source=source)
        except ValueError:
            continue
        if document.lines or document.plain or document.instrumental:
            return document
    return None


def _ttml_time(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    try:
        if text.endswith("ms"):
            return round(float(text[:-2]))
        if text.endswith("s"):
            return round(float(text[:-1]) * 1000)
        parts = text.split(":")
        if len(parts) == 3:
            return round((int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])) * 1000)
        if len(parts) == 2:
            return round((int(parts[0]) * 60 + float(parts[1])) * 1000)
        return round(float(text) * 1000)
    except ValueError, OverflowError:
        return None


def _ttml_document(text: str, source: str) -> LyricsDocument | None:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    lines: list[LyricLine] = []
    for paragraph in root.iter():
        if paragraph.tag.rsplit("}", 1)[-1] != "p":
            continue
        start = _ttml_time(paragraph.attrib.get("begin"))
        if start is None or start < 0:
            continue
        end = _ttml_time(paragraph.attrib.get("end"))
        if end is None:
            duration = _ttml_time(paragraph.attrib.get("dur"))
            end = start + duration if duration is not None else None
        words: list[LyricWord] = []
        pieces: list[str] = []
        for child in paragraph.iter():
            if child is paragraph:
                continue
            word = "".join(child.itertext())
            if not word:
                continue
            word_start = _ttml_time(child.attrib.get("begin")) or start
            word_end = _ttml_time(child.attrib.get("end"))
            if word_end is None:
                duration = _ttml_time(child.attrib.get("dur"))
                word_end = word_start + duration if duration is not None else None
            words.append(LyricWord(word_start, word_end, word))
            pieces.append(word)
        line_text = "".join(pieces) if pieces else "".join(paragraph.itertext())
        if line_text.strip():
            lines.append(LyricLine(start, end, line_text, tuple(words)))
    if not lines:
        return None
    return LyricsDocument(tuple(sorted(lines, key=lambda line: line.start_ms)), source=source, format="ttml")


def _better_lyrics_document(root: dict[str, object]) -> LyricsDocument | None:
    ttml = _string(root.get("ttml"))
    if ttml:
        document = _ttml_document(ttml, "Better Lyrics")
        if document is not None:
            return document
    for name in ("lrc", "lyrics"):
        text = _string(root.get(name)).strip()
        if text:
            document = parse_lyrics(text, source="Better Lyrics")
            if document.lines or document.plain or document.instrumental:
                return document
    return None


def _musixmatch_root(root: dict[str, object]) -> dict[str, object]:
    message = _dictionary(root.get("message", {}))
    return _dictionary(message.get("body", {}))


def interpret_response(request: LyricsRequest, data: bytes) -> ProviderResult:
    if len(data) > MAX_BYTES:
        raise ValueError("Lyric response exceeds one MiB")
    try:
        value: object = json.loads(data)
    except (ValueError, RecursionError) as error:
        raise ValueError("Invalid lyric provider JSON") from error
    if request.stage == "lrclib-search":
        if not isinstance(value, list) or len(cast(list[object], value)) > 20:
            raise ValueError("Invalid or oversized LRCLIB result list")
        candidates: list[tuple[float, dict[str, object]]] = []
        for item in cast(list[object], value):
            row = _dictionary(item)
            score = match_score(
                request.query,
                _string(row.get("trackName")),
                _string(row.get("artistName")),
                _duration(row.get("duration")),
                _string(row.get("albumName")),
            )
            if score:
                candidates.append((score, row))
        for _, row in sorted(candidates, key=lambda item: item[0], reverse=True):
            document = _lrclib_document(row)
            if document is not None:
                return ProviderResult(document, detail="")
        return ProviderResult(next_request=request.fallback())
    root = _dictionary(value)
    if request.stage == "netease-lyrics":
        for name in ("yrc", "klyric", "lrc"):
            container = root.get(name)
            if not isinstance(container, dict):
                continue
            text = cast(dict[str, object], container).get("lyric")
            if isinstance(text, str) and text.strip():
                try:
                    document = parse_lyrics(text, source="NetEase (undocumented interface)")
                except ValueError:
                    continue
                if document.lines:
                    return ProviderResult(document, detail="")
        return ProviderResult(next_request=request.fallback(), detail="NetEase returned no supported timed lyrics")
    if request.stage == "better-lyrics":
        document = _better_lyrics_document(root)
        if document is not None:
            return ProviderResult(document, detail="")
        return ProviderResult(next_request=request.fallback(), detail="Better Lyrics returned no supported lyrics")
    if request.stage == "musixmatch-lyrics":
        body = _musixmatch_root(root)
        lyrics = _dictionary(body.get("lyrics", {}))
        text = _string(lyrics.get("lyrics_body")).strip()
        if text:
            document = parse_lyrics(text, source="Musixmatch")
            if document.lines or document.plain or document.instrumental:
                return ProviderResult(document, detail="")
        subtitle = _string(_dictionary(body.get("subtitle", {})).get("subtitle_body")).strip()
        if subtitle:
            document = parse_lyrics(subtitle, source="Musixmatch")
            if document.lines or document.plain or document.instrumental:
                return ProviderResult(document, detail="")
        return ProviderResult(next_request=request.fallback(), detail="Musixmatch returned no supported lyrics")
    if request.stage == "musixmatch-search":
        body = _musixmatch_root(root)
        rows = body.get("track_list", [])
        if not isinstance(rows, list) or len(cast(list[object], rows)) > 20:
            raise ValueError("Invalid or oversized Musixmatch result list")
        matches: list[tuple[float, int]] = []
        for item in cast(list[object], rows):
            row = _dictionary(_dictionary(item).get("track", {}))
            score = match_score(
                request.query,
                _string(row.get("track_name")),
                _string(row.get("artist_name")),
                _duration(row.get("track_length")),
                _string(row.get("album_name")),
            )
            identifier = row.get("track_id")
            if score and type(identifier) is int and 0 < identifier < 2**63:
                matches.append((score, identifier))
        if matches:
            identifier = max(matches, key=lambda item: item[0])[1]
            return ProviderResult(next_request=replace(request, stage="musixmatch-lyrics", track_id=identifier))
        return ProviderResult(next_request=request.fallback())
    result = _dictionary(root.get("result", {}))
    songs = result.get("songs", [])
    if not isinstance(songs, list) or len(cast(list[object], songs)) > 20:
        raise ValueError("Invalid or oversized NetEase result list")
    matches: list[tuple[float, int]] = []
    for item in cast(list[object], songs):
        row = _dictionary(item)
        artist_rows = row.get("ar", row.get("artists", []))
        artist = ""
        if isinstance(artist_rows, list) and artist_rows:
            first = cast(list[object], artist_rows)[0]
            if isinstance(first, dict):
                artist = _string(cast(dict[str, object], first).get("name"))
        score = match_score(
            request.query,
            _string(row.get("name")),
            artist,
            _duration(row.get("dt", row.get("duration")), milliseconds=True),
        )
        identifier = row.get("id")
        if score and type(identifier) is int and 0 < identifier < 2**63:
            matches.append((score, identifier))
    if matches:
        identifier = max(matches, key=lambda item: item[0])[1]
        return ProviderResult(next_request=replace(request, stage="netease-lyrics", track_id=identifier))
    return ProviderResult(next_request=request.fallback())

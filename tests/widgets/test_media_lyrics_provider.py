import json

import pytest

from core.widgets.services.media.lyrics_provider import LyricsQuery, LyricsRequest, interpret_response, match_score

QUERY = LyricsQuery("Song", "Artist", "Playlist", 180000)


def record(**changes: object) -> dict[str, object]:
    return {
        "trackName": "Song",
        "artistName": "Artist",
        "albumName": "Actual album",
        "duration": 180,
        "instrumental": False,
        "syncedLyrics": "[00:01]Hello",
        **changes,
    }


def test_lrclib_matching_ignores_playlist_album_and_keeps_timed_data() -> None:
    result = interpret_response(LyricsRequest(QUERY), json.dumps([record()]).encode())
    assert result.document is not None and result.document.lines[0].start_ms == 1000
    assert result.document.source == "LRCLIB"


@pytest.mark.parametrize(
    ("title", "artist", "duration"),
    [
        ("Other", "Artist", 180000),
        ("Song live", "Artist", 180000),
        ("Song", "Other singer", 180000),
        ("Song", "Artist", 183000),
        ("Song", "Artist", None),
    ],
)
def test_wrong_or_unverifiable_candidate_is_rejected(title: str, artist: str, duration: int | None) -> None:
    assert match_score(QUERY, title, artist, duration) == 0


def test_word_yaml_preferred_plain_fallback_and_instrumental_are_distinct() -> None:
    lyricsfile = "version: '1.0'\nmetadata:\n  title: Song\n  artist: Artist\nlines:\n  - text: 'Hi there'\n    start_ms: 1000\n    words:\n      - text: 'Hi '\n        start_ms: 1000\n      - text: there\n        start_ms: 1500\n"
    result = interpret_response(LyricsRequest(QUERY), json.dumps([record(lyricsfile=lyricsfile)]).encode())
    assert result.document is not None and result.document.word_synced
    result = interpret_response(
        LyricsRequest(QUERY),
        json.dumps([record(lyricsfile="invalid: yaml", syncedLyrics=None, plainLyrics="Plain lyrics")]).encode(),
    )
    assert result.document is not None and result.document.plain == "Plain lyrics" and not result.document.lines
    result = interpret_response(LyricsRequest(QUERY), json.dumps([record(instrumental=True)]).encode())
    assert result.document is not None and result.document.instrumental and not result.document.lines


def test_netease_fallback_uses_observed_ids_and_explicit_milliseconds() -> None:
    first = interpret_response(LyricsRequest(QUERY), b"[]")
    assert first.next_request is not None and first.next_request.stage == "netease-cloud"
    second = interpret_response(first.next_request, b'{"result":{"songs":[]}}')
    assert second.next_request is not None and second.next_request.stage == "netease-search"
    third = interpret_response(
        second.next_request,
        b'{"result":{"songs":[{"id":123,"name":"Song","artists":[{"name":"Artist"}],"duration":180000}]}}',
    )
    assert third.next_request is not None and third.next_request.track_id == 123
    assert "id=123" in third.next_request.url
    result = interpret_response(
        third.next_request, b'{"yrc":{"lyric":"[1200,500](1200,500)Word"},"lrc":{"lyric":"[00:01]Line"}}'
    )
    assert result.document is not None and result.document.word_synced
    assert result.document.lines[0].start_ms == 1200
    assert "undocumented" in result.document.source


@pytest.mark.parametrize("case", ["non-json", "mapping", "too-many", "oversize"])
def test_bad_and_oversized_provider_responses_fail(case: str) -> None:
    data = {
        "non-json": b"not-json",
        "mapping": b"{}",
        "too-many": b"[" + b"{}," * 20 + b"{}]",
        "oversize": b"x" * (1024 * 1024 + 1),
    }[case]
    with pytest.raises(ValueError):
        interpret_response(LyricsRequest(QUERY), data)


def test_urls_encode_metadata_and_never_take_a_provider_supplied_url() -> None:
    request = LyricsRequest(LyricsQuery("Song & ? /\n", "Artist"))
    assert request.url.startswith("https://lrclib.net/api/search?")
    assert "%26" in request.url and "%0A" in request.url
    with pytest.raises(ValueError):
        LyricsQuery("", "Artist").normalized()


def test_provider_order_can_start_with_netease_and_fall_back_to_lrclib() -> None:
    request = LyricsRequest(QUERY, stage="netease-cloud", providers=("netease", "lrclib"))
    search = request.fallback()
    assert search is not None and search.stage == "netease-search"
    fallback = search.fallback()
    assert fallback is not None and fallback.stage == "lrclib-search"


def test_better_lyrics_decodes_ttml_word_timing() -> None:
    request = LyricsRequest(QUERY, stage="better-lyrics")
    assert "api.betterlyrics.org/getLyrics" in request.url
    body = {
        "ttml": '<tt><body><p begin="1s" end="3s"><span begin="1s" end="2s">Hello </span><span begin="2s">world</span></p></body></tt>'
    }
    result = interpret_response(request, json.dumps(body).encode())
    assert result.document is not None
    assert result.document.source == "Better Lyrics"
    assert result.document.lines[0].text == "Hello world"
    assert result.document.word_synced


def ttml_line(paragraph: str):
    body = {"ttml": f"<tt><body>{paragraph}</body></tt>"}
    result = interpret_response(LyricsRequest(QUERY, stage="better-lyrics"), json.dumps(body).encode())
    assert result.document is not None
    line = result.document.lines[0]
    assert "".join(word.text for word in line.words) == line.text or not line.words
    return line


def test_ttml_keeps_whitespace_between_spans_on_the_preceding_word() -> None:
    line = ttml_line(
        '<p begin="1s" end="3s"><span begin="1s" end="1.5s">Hello</span> '
        '<span begin="1.5s" end="2s">big</span> <span begin="2s" end="3s">world</span></p>'
    )
    assert line.text == "Hello big world"
    assert [(word.text, word.start_ms, word.end_ms) for word in line.words] == [
        ("Hello ", 1000, 1500),
        ("big ", 1500, 2000),
        ("world", 2000, 3000),
    ]


def test_ttml_nested_background_span_yields_each_timed_leaf_once() -> None:
    line = ttml_line(
        '<p begin="1s" end="4s"><span begin="1s" end="2s">Lead</span>'
        '<span role="x-bg">(<span begin="2s" end="3s">echo</span> <span begin="3s" end="4s">here</span>)</span></p>'
    )
    assert line.text == "Lead(echo here)"
    assert [(word.text, word.start_ms) for word in line.words] == [("Lead(", 1000), ("echo ", 2000), ("here)", 3000)]


def test_ttml_paragraph_without_timed_spans_is_line_timed_only() -> None:
    plain = ttml_line('<p begin="2s" end="4s">Only line timing</p>')
    assert plain.text == "Only line timing" and plain.words == () and plain.start_ms == 2000
    untimed = ttml_line('<p begin="2s"><span>No</span> <span>word times</span></p>')
    assert untimed.text == "No word times" and untimed.words == ()
    leading = ttml_line('<p begin="0s">¿<span begin="0s" end="1s">Qué</span>?</p>')
    assert leading.text == "¿Qué?" and [word.text for word in leading.words] == ["¿Qué?"]
    assert leading.words[0].start_ms == 0


def test_opt_in_private_provider_urls_and_fallback_stages() -> None:
    musixmatch = LyricsRequest(
        QUERY,
        stage="musixmatch-search",
        providers=("musixmatch",),
        credentials=(("musixmatch", "fixture-key"),),
    )
    result = interpret_response(
        musixmatch,
        json.dumps(
            {
                "message": {
                    "body": {
                        "track_list": [
                            {
                                "track": {
                                    "track_id": 42,
                                    "track_name": "Song",
                                    "artist_name": "Artist",
                                    "track_length": 180,
                                }
                            }
                        ]
                    }
                }
            }
        ).encode(),
    )
    assert result.next_request is not None and result.next_request.track_id == 42
    lyrics = interpret_response(
        result.next_request,
        json.dumps({"message": {"body": {"lyrics": {"lyrics_body": "[00:01]Line"}}}}).encode(),
    )
    assert lyrics.document is not None and lyrics.document.source == "Musixmatch"

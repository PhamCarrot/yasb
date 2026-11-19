import json
import tracemalloc
from sys import getsizeof
from typing import cast

import pytest
import yaml

from core.widgets.services.media.lyrics_model import MAX_BYTES, MAX_LINES, MAX_WORDS, parse_lyrics

YAML = """version: '1.0'
metadata:
  title: Example
  artist: Artist
lines:
  - text: 'Hello world'
    start_ms: 1200
    end_ms: 2500
    words:
      - text: 'Hello '
        start_ms: 1200
        end_ms: 1800
      - text: world
        start_ms: 1800
plain: |
  Hello world
"""


@pytest.mark.parametrize(("fraction", "expected"), [("1", 1100), ("12", 1120), ("123", 1123), ("", 1000)])
def test_lrc_fractional_seconds_and_repeated_timestamp_lines(fraction: str, expected: int) -> None:
    marker = "." + fraction if fraction else ""
    result = parse_lyrics(f"[00:01{marker}][00:04{marker}]Có <tag> & lyrics")
    assert [line.start_ms for line in result.lines] == [expected, expected + 3000]
    assert all(line.text == "Có <tag> & lyrics" and line.end_ms is None for line in result.lines)
    assert result.line_at(expected - 1) == -1
    assert result.line_at(expected) == 0
    assert result.line_at(expected + 3000) == 1


def test_enhanced_lrc_repeats_word_timing_without_invented_spaces_or_ends() -> None:
    result = parse_lyrics("[00:01][00:04]<00:01.2>Hello <00:01.8>world<00:02>")
    first, second = result.lines
    assert first.text == second.text == "Hello world"
    assert [word.text for word in first.words] == ["Hello ", "world"]
    assert [word.start_ms for word in first.words] == [1200, 1800]
    assert [word.start_ms for word in second.words] == [4200, 4800]
    assert all(word.end_ms is None for line in result.lines for word in line.words)


def test_enhanced_lrc_retains_unmarked_prefix_and_word_order() -> None:
    result = parse_lyrics("[00:02]Prefix <00:02.5>marked")
    assert "".join(word.text for word in result.lines[0].words) == result.lines[0].text == "Prefix marked"


def test_yrc_explicit_millisecond_fields_and_json_credit_headers() -> None:
    result = parse_lyrics('{"t":0,"c":[{"tx":"Credit"}]}\n[1200,800](1200,200,0)你(1400,600,0) 好')
    line = result.lines[0]
    assert (line.start_ms, line.end_ms, line.text) == (1200, 2000, "你 好")
    assert [(word.start_ms, word.end_ms, word.text) for word in line.words] == [(1200, 1400, "你"), (1400, 2000, " 好")]


def test_yaml_same_start_overlapping_lines_and_optional_word_end() -> None:
    result = parse_lyrics(
        YAML.replace("plain: |\n  Hello world\n", "  - text: Overlap\n    start_ms: 1200\n    end_ms: 3000\n")
    )
    assert len(result.lines) == 2 and result.lines[0].start_ms == result.lines[1].start_ms == 1200
    assert result.lines[0].words[-1].end_ms is None
    assert result.lines[1].end_ms == 3000
    assert "".join(word.text for word in result.lines[0].words) == "Hello world"


def test_yaml_offset_preserved_without_silent_timing_shift() -> None:
    result = parse_lyrics(YAML.replace("  artist: Artist", "  artist: Artist\n  offset_ms: 500"))
    assert result.offset_ms == 500 and result.lines[0].start_ms == 1200 and result.warnings


@pytest.mark.parametrize(
    "data",
    [
        YAML.replace("version: '1.0'", "version: 1.0"),
        YAML.replace("version: '1.0'", "version: '2.0'"),
        YAML + "version: '1.0'\n",
        YAML.replace("  title: Example", "  title: Example\n  title: Duplicate"),
        YAML + "x: &same [*same]\n",
        YAML + "x: !!python/name:os.system\n",
        YAML + "x: 1.5\n",
        YAML + "x: 2026-11-17\n",
        YAML.replace("start_ms: 1200", "start_ms: true"),
        YAML.replace("start_ms: 1200", "start_ms: -1"),
        YAML.replace("end_ms: 2500", "end_ms: 10"),
        YAML.replace("'Hello '", "'Hello'"),
        YAML.replace("  artist: Artist", "  artist: Artist\n  instrumental: true"),
        YAML + "---\nversion: '1.0'\n",
        YAML + "x: " + "[" * 20 + "0" + "]" * 20,
    ],
    ids=[
        "numeric-version",
        "unknown-version",
        "duplicate-root",
        "duplicate-metadata",
        "alias",
        "unsafe-tag",
        "float",
        "date",
        "boolean-time",
        "negative-time",
        "reversed-end",
        "word-mismatch",
        "instrumental-with-text",
        "multiple-documents",
        "deep-nesting",
    ],
)
def test_invalid_yaml_is_rejected_without_unsafe_construction(data: str) -> None:
    with pytest.raises(ValueError):
        parse_lyrics(data)


def test_plain_and_instrumental_are_distinct_without_timestamps() -> None:
    plain = parse_lyrics("No time\nUnicode 你好\n")
    assert plain.plain == "No time\nUnicode 你好" and not plain.lines and not plain.instrumental
    result = parse_lyrics("version: '1.0'\nmetadata:\n  title: Quiet\n  artist: Artist\n  instrumental: true\n")
    assert result.instrumental and not result.plain and not result.lines


def test_lrc_offset_is_explicitly_unapplied_like_reference() -> None:
    result = parse_lyrics("[offset:500]\n[00:01]Line")
    assert result.lines[0].start_ms == 1000 and result.warnings


@pytest.mark.parametrize(
    "data",
    [b"x" * (MAX_BYTES + 1), "\n" * (MAX_LINES + 1), "[604800001,10]Too late", "Bad\0text", b"\xff"],
    ids=["oversize", "line-limit", "time-limit", "nul", "encoding"],
)
def test_input_limits_and_invalid_encoding(data: bytes | str) -> None:
    with pytest.raises(ValueError):
        parse_lyrics(data)


def test_repeated_enhanced_words_count_toward_total_bound() -> None:
    words = "".join(f"<00:01>{i} " for i in range(100))
    text = "".join("[00:01]" for _ in range(MAX_WORDS // 100 + 1)) + words
    with pytest.raises(ValueError, match="words"):
        parse_lyrics(text)


def test_explicit_json_units_never_guess_seconds_from_magnitude() -> None:
    value = {
        "version": "1.0",
        "metadata": {"title": "Example", "artist": "Artist"},
        "lines": [{"text": "Soon", "start_ms": 900}],
    }
    assert parse_lyrics(json.dumps(value)).lines[0].start_ms == 900


def test_repeated_word_expansion_is_rejected_before_allocating_every_copy() -> None:
    text = "[00:01]" * 600 + "<00:01>x" * 600
    tracemalloc.start()
    try:
        with pytest.raises(ValueError, match="words"):
            parse_lyrics(text)
        _, peak = tracemalloc.get_traced_memory()
        assert peak < 8 * 1024 * 1024  # Old expand-then-check path used about49MiB.
    finally:
        tracemalloc.stop()


def test_json_uses_same_duplicate_and_structure_guards_as_yaml() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        parse_lyrics('{"version":"2.0","version":"1.0","metadata":{"title":"Song","artist":"Artist"}}')
    with pytest.raises(ValueError, match="limits"):
        parse_lyrics(
            '{"version":"1.0","metadata":{"title":"Song","artist":"Artist"},"extra":' + "[" * 20 + "0" + "]" * 20 + "}"
        )


def test_two_field_yrc_words_and_unmarked_prefix_are_preserved() -> None:
    document = parse_lyrics("[1200,800]Prefix (1200,200)你(1400,600) 好")
    line = document.lines[0]
    assert line.text == "Prefix 你 好"
    assert [word.text for word in line.words] == ["Prefix ", "你", " 好"]
    assert line.words[0].end_ms is None
    assert [(word.start_ms, word.end_ms) for word in line.words[1:]] == [(1200, 1400), (1400, 2000)]


@pytest.mark.parametrize("format", ["json", "yaml"])
@pytest.mark.parametrize("kind", ["rows", "long-line"])
def test_structured_plain_obeys_the_same_row_limits(format: str, kind: str) -> None:
    plain = "a\n" * (MAX_LINES + 1) if kind == "rows" else "x" * 16385
    value = {"version": "1.0", "metadata": {"title": "Song", "artist": "Artist"}, "plain": plain}
    text = json.dumps(value) if format == "json" else yaml.safe_dump(value)
    with pytest.raises(ValueError, match="Too many lyric lines|line is too long"):
        parse_lyrics(text, filename="own." + format)


def test_dense_document_cache_weight_covers_retained_python_objects() -> None:
    # The old UTF8 + per-word32 estimate missed instance dictionaries and
    # containers by several times. Measure all retained objects, once each.
    source = "\n".join(
        f"[{index * 1000},900](0,100)A(100,100)B(200,100)C(300,100)D(400,100)E(500,100)F" for index in range(4999)
    )
    document = parse_lyrics(source)
    seen: set[int] = set()

    def retained(value: object) -> int:
        if id(value) in seen:
            return 0
        seen.add(id(value))
        size = getsizeof(value)
        if isinstance(value, tuple):
            return size + sum(retained(item) for item in cast(tuple[object, ...], value))
        if hasattr(value, "__dict__"):
            attributes = vars(value)
            return size + getsizeof(attributes) + sum(retained(item) for item in attributes.values())
        return size

    assert document.retained_bytes >= retained(document)
    assert document.retained_bytes > 4 * 1024 * 1024
    # Admission reads the stored integer; it does not walk thousands of words.
    assert "retained_bytes" in vars(document)


@pytest.mark.parametrize("where", ["plain", "line", "word", "artist"])
def test_escaped_lone_surrogate_never_reaches_native_paint(where: str) -> None:
    invalid = chr(0xD800)
    value: dict[str, object] = {
        "version": "1.0",
        "metadata": {"title": "Song", "artist": invalid if where == "artist" else "Artist"},
    }
    if where == "plain":
        value["plain"] = invalid
    elif where in ("line", "word"):
        line: dict[str, object] = {"text": invalid, "start_ms": 1000}
        if where == "word":
            line["words"] = [{"text": invalid, "start_ms": 1000}]
        value["lines"] = [line]
    with pytest.raises(ValueError):
        parse_lyrics(json.dumps(value), filename="own.json")

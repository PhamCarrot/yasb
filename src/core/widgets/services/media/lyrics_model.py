"""Immutable, bounded lyric documents; timings are explicit integer milliseconds."""

from __future__ import annotations

import bisect
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from sys import getsizeof
from typing import Any, cast

import yaml
from yaml.events import Event, MappingEndEvent, MappingStartEvent, SequenceEndEvent, SequenceStartEvent
from yaml.nodes import MappingNode, Node
from yaml.tokens import AliasToken, AnchorToken, TagToken, Token

MAX_BYTES = 1024 * 1024
MAX_LINES = 5000
MAX_WORDS = 30000
MAX_TIME_MS = 7 * 24 * 3600 * 1000
_TIMESTAMP = r"(\d{1,4}):([0-5]\d)(?:[.:](\d{1,3}))?"
_LINE_TIME = re.compile(r"\[" + _TIMESTAMP + r"\]")
_WORD_TIME = re.compile(r"<" + _TIMESTAMP + r">")
_YRC_LINE = re.compile(r"^\[(\d+),(\d+)\](.*)$")
_YRC_WORD = re.compile(r"\((\d+),(\d+)(?:,\d+)?\)")
_META = re.compile(r"^\[(?:ar|ti|al|by|re|ve|length|offset):[^\]]*\]\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class LyricWord:
    start_ms: int
    end_ms: int | None
    text: str


@dataclass(frozen=True)
class LyricLine:
    start_ms: int
    end_ms: int | None
    text: str
    words: tuple[LyricWord, ...] = ()


@dataclass(frozen=True)
class LyricsDocument:
    lines: tuple[LyricLine, ...] = ()
    plain: str = ""
    instrumental: bool = False
    format: str = "plain"
    source: str = ""
    offset_ms: int = 0
    warnings: tuple[str, ...] = ()
    retained_bytes: int = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        # Derived once where documents are parsed (on the service worker), so
        # cache admission on the GUI thread is constant time. Reserve space for
        # this derived integer and its dictionary entry before it is installed.
        object.__setattr__(self, "retained_bytes", self._measure_bytes() + 128)

    @property
    def word_synced(self) -> bool:
        return any(line.words for line in self.lines)

    def line_at(self, position_ms: int) -> int:
        return bisect.bisect_right(self.lines, position_ms, key=lambda line: line.start_ms) - 1

    def _measure_bytes(self) -> int:
        # Count instance dictionaries, containers, Python strings and integers;
        # UTF-8 payload size alone misses most of a dense timed document. Shared
        # values are deliberately counted again, making this conservative.
        return (
            getsizeof(self)
            + getsizeof(vars(self))
            + sum(getsizeof(value) for value in (self.plain, self.format, self.source, self.offset_ms))
            + getsizeof(self.warnings)
            + sum(getsizeof(warning) for warning in self.warnings)
            + getsizeof(self.lines)
            + sum(
                getsizeof(line)
                + getsizeof(vars(line))
                + sum(getsizeof(value) for value in (line.text, line.start_ms, line.end_ms))
                + getsizeof(line.words)
                + sum(
                    getsizeof(word)
                    + getsizeof(vars(word))
                    + sum(getsizeof(value) for value in (word.text, word.start_ms, word.end_ms))
                    for word in line.words
                )
                for line in self.lines
            )
        )


def _time(value: object, field: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if type(value) is not int or not 0 <= value <= MAX_TIME_MS:
        raise ValueError(f"{field} must be an integer millisecond time within seven days")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) > 16384 or "\0" in value:
        raise ValueError(f"Invalid {field}")
    value.encode("utf-8")  # Reject escaped lone surrogates before native rendering.
    return value


def _map(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in cast(dict[object, object], value)):
        raise ValueError(f"{field} must be a string-key mapping")
    return cast(dict[str, object], value)


def _sequence(value: object, field: str, limit: int) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"Invalid {field}")
    items = cast(list[object], value)
    if len(items) > limit:
        raise ValueError(f"Oversized {field}")
    return items


def _plain_lines(text: str) -> list[str]:
    text.encode("utf-8")
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        raise ValueError("Too many lyric lines")
    if any(len(line) > 16384 for line in lines):
        raise ValueError("Lyric line is too long")
    return lines


def _structured(value: object, source: str) -> LyricsDocument:
    root = _map(value, "Lyricsfile")
    if root.get("version") != "1.0":
        raise ValueError("Unsupported Lyricsfile version; expected string 1.0")
    metadata = _map(root.get("metadata"), "metadata")
    _text(metadata.get("title"), "title")
    _text(metadata.get("artist"), "artist")
    instrumental = metadata.get("instrumental", False)
    if type(instrumental) is not bool:
        raise ValueError("instrumental must be boolean")
    if "duration_ms" in metadata:
        _time(metadata["duration_ms"], "duration_ms")
    offset = metadata.get("offset_ms", 0)
    if type(offset) is not int or abs(offset) > MAX_TIME_MS:
        raise ValueError("Invalid offset_ms")
    plain = root.get("plain", "")
    if not isinstance(plain, str) or "\0" in plain:
        raise ValueError("plain must be text")
    _plain_lines(plain)
    lines: list[LyricLine] = []
    count = 0
    for item in _sequence(root.get("lines", []), "lines", MAX_LINES):
        line = _map(item, "line")
        start = cast(int, _time(line.get("start_ms"), "line start_ms"))
        end = _time(line.get("end_ms"), "line end_ms", optional=True)
        if end is not None and end < start:
            raise ValueError("Line end precedes start")
        words: list[LyricWord] = []
        for segment in _sequence(line.get("words", []), "words", MAX_WORDS):
            count += 1
            if count > MAX_WORDS:
                raise ValueError("Too many lyric words")
            word = _map(segment, "word")
            w_start = cast(int, _time(word.get("start_ms"), "word start_ms"))
            w_end = _time(word.get("end_ms"), "word end_ms", optional=True)
            if w_end is not None and w_end < w_start:
                raise ValueError("Word end precedes start")
            words.append(LyricWord(w_start, w_end, _text(word.get("text"), "word text")))
        text = _text(line.get("text"), "line text")
        if words and "".join(word.text for word in words) != text:
            raise ValueError("Word text does not reconstruct line text")
        lines.append(LyricLine(start, end, text, tuple(words)))
    if instrumental and (lines or plain):
        raise ValueError("Instrumental lyrics contain text")
    warnings = ("Lyricsfile offset_ms is preserved without shifting unresolved timing semantics.",) if offset else ()
    return LyricsDocument(
        tuple(sorted(lines, key=lambda line: line.start_ms)),
        plain,
        instrumental,
        "lyricsfile",
        source,
        offset,
        warnings,
    )


class _UniqueLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader: yaml.SafeLoader, node: MappingNode) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    construct = cast(Callable[[Node, bool], object], getattr(loader, "construct_object"))
    for key_node, value_node in node.value:
        key = construct(key_node, True)
        if not isinstance(key, str) or key in result:
            raise ValueError("Duplicate or non-string YAML key")
        result[key] = construct(value_node, True)
    return result


_UniqueLoader.add_constructor("tag:yaml.org,2002:map", _unique_mapping)


def _yaml(text: str, source: str) -> LyricsDocument:
    try:
        # PyYAML6.0.3 stubs omit scan/parse/construct result types. Bound the
        # library calls here; every resulting scalar/structure is validated.
        scan = cast(Callable[[str], Iterable[Token]], getattr(yaml, "scan"))
        parse = cast(Callable[[str], Iterable[Event]], getattr(yaml, "parse"))
        for token in scan(text):
            if isinstance(token, (AliasToken, AnchorToken)):
                raise ValueError("YAML anchors and aliases are not supported")
            if isinstance(token, TagToken) and token.value not in (
                ("!!", "str"),
                ("!!", "int"),
                ("!!", "bool"),
                ("!!", "null"),
                ("!!", "map"),
                ("!!", "seq"),
            ):
                raise ValueError("Unsupported YAML tag")
        depth = count = 0
        for event in parse(text):
            count += 1
            if isinstance(event, (MappingStartEvent, SequenceStartEvent)):
                depth += 1
            elif isinstance(event, (MappingEndEvent, SequenceEndEvent)):
                depth -= 1
            if depth > 16 or count > 100000:
                raise ValueError("Lyricsfile structure exceeds its limits")
        value: object = yaml.load(text, Loader=_UniqueLoader)

        def scalar_check(item: object) -> None:
            if isinstance(item, dict):
                for child in cast(dict[str, object], item).values():
                    scalar_check(child)
            elif isinstance(item, list):
                for child in cast(list[object], item):
                    scalar_check(child)
            elif item is not None and type(item) not in (str, int, bool):
                raise ValueError("Unsupported Lyricsfile scalar")

        scalar_check(value)
        return _structured(value, source)
    except (yaml.YAMLError, TypeError) as error:
        raise ValueError("Invalid Lyricsfile YAML") from error


def _stamp(match: re.Match[str]) -> int:
    fraction = (match.group(3) or "").ljust(3, "0")
    return cast(int, _time((int(match.group(1)) * 60 + int(match.group(2))) * 1000 + int(fraction or 0), "timestamp"))


def _timed(text: str, source: str) -> LyricsDocument:
    lines: list[LyricLine] = []
    plain: list[str] = []
    warnings: list[str] = []
    total_words = 0
    yrc = False
    words: list[LyricWord]
    raw_lines = _plain_lines(text)
    for raw in raw_lines:
        previous_count = len(lines)
        match = _YRC_LINE.match(raw)
        if match:
            yrc = True
            start = cast(int, _time(int(match.group(1)), "YRC line start"))
            end = cast(int, _time(start + int(match.group(2)), "YRC line end"))
            body = match.group(3)
            marks = list(_YRC_WORD.finditer(body))
            if len(lines) + 1 > MAX_LINES or total_words + len(marks) + 1 > MAX_WORDS:
                raise ValueError("Too many lyric lines or words")
            words = []
            if marks and marks[0].start():
                words.append(LyricWord(start, None, body[: marks[0].start()]))
            for index, marker in enumerate(marks):
                w_start = cast(int, _time(int(marker.group(1)), "YRC word start"))
                w_end = cast(int, _time(w_start + int(marker.group(2)), "YRC word end"))
                segment = body[marker.end() : marks[index + 1].start() if index + 1 < len(marks) else len(body)]
                words.append(LyricWord(w_start, w_end, segment))
            line_text = "".join(word.text for word in words) if words else body
            lines.append(LyricLine(start, end, line_text, tuple(words)))
        else:
            markers = list(_LINE_TIME.finditer(raw))
            prefix = "".join(marker.group(0) for marker in markers)
            if markers and raw.startswith(prefix):
                body = raw[len(prefix) :]
                marks = list(_WORD_TIME.finditer(body))
                starts = [_stamp(marker) for marker in markers]
                words = []
                for index, marker in enumerate(marks):
                    segment = body[marker.end() : marks[index + 1].start() if index + 1 < len(marks) else len(body)]
                    if segment:
                        words.append(LyricWord(_stamp(marker), None, segment))
                if marks and marks[0].start():
                    words.insert(0, LyricWord(starts[0], None, body[: marks[0].start()]))
                line_text = "".join(word.text for word in words) if marks else body
                if len(lines) + len(starts) > MAX_LINES or total_words + len(starts) * len(words) > MAX_WORDS:
                    raise ValueError("Too many lyric lines or words")
                for start in starts:
                    shift = start - starts[0]
                    repeated = tuple(
                        LyricWord(cast(int, _time(word.start_ms + shift, "word start")), None, word.text)
                        for word in words
                    )
                    lines.append(LyricLine(start, None, line_text, repeated))
            elif _META.fullmatch(raw.strip()):
                if raw.lower().startswith("[offset:"):
                    warnings.append("LRC offset tag is not applied, matching the reference menu.")
            elif raw.strip():
                plain.append(raw)
        total_words += sum(len(line.words) for line in lines[previous_count:])
        if len(lines) > MAX_LINES or total_words > MAX_WORDS:
            raise ValueError("Too many lyric lines or words")
    if lines:
        return LyricsDocument(
            tuple(sorted(lines, key=lambda line: line.start_ms)),
            format="yrc" if yrc else "lrc",
            source=source,
            warnings=tuple(dict.fromkeys(warnings)),
        )
    return LyricsDocument(plain="\n".join(plain), source=source)


def parse_lyrics(data: bytes | str, *, filename: str = "", source: str = "local") -> LyricsDocument:
    if isinstance(data, bytes):
        if len(data) > MAX_BYTES:
            raise ValueError("Lyrics exceed the one MiB limit")
        text = data.decode("utf-8-sig")
    else:
        if len(data) > MAX_BYTES or len(data.encode("utf-8")) > MAX_BYTES:
            raise ValueError("Lyrics exceed the one MiB limit")
        text = data.lstrip("\ufeff")
    if "\0" in text:
        raise ValueError("Lyrics contain NUL")
    if filename.lower().endswith((".yaml", ".yml")) or re.match(r"\s*version\s*:", text):
        return _yaml(text, source)
    # NetEase YRC may prefix its timed rows with standalone JSON credits.
    # Those rows are metadata, not an ambiguous whole-document JSON format.
    if any(_YRC_LINE.match(line) for line in text.splitlines()):
        return _timed(text, source)
    if text.lstrip().startswith("{"):
        # JSON is a YAML subset: use the SAME preflight/depth/duplicate/scalar
        # validation, rather than a permissive second structured-input path.
        return _yaml(text, source)
    return _timed(text, source)

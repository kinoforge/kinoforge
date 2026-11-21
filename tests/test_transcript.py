"""Transcript snapping, candidate windows, language guess."""

from __future__ import annotations

from kinoforge.segments.clips.moments.transcript import TranscriptText

detect_language = TranscriptText.detect_language
snap_to_transcript = TranscriptText.snap


def _segs():
    return [
        {"start": 0, "end": 5, "text": "a"},
        {"start": 5, "end": 10, "text": "b"},
        {"start": 10, "end": 15, "text": "c"},
    ]


# --- snap_to_transcript ---------------------------------------------------

def test_snap_empty_transcript_returns_input():
    assert snap_to_transcript([], 3.0, 7.0) == (3.0, 7.0, "")


def test_snap_lands_on_segment_edges():
    assert snap_to_transcript(_segs(), 6.0, 9.0) == (5.0, 10.0, "b")


def test_snap_extends_short_pick_to_min_length():
    start, end, text = snap_to_transcript(_segs(), 6.0, 7.0, min_len=8.0)
    assert (start, end) == (5.0, 15.0)
    assert text == "b c"


def test_snap_trims_long_pick_to_max_length():
    start, end, text = snap_to_transcript(_segs(), 0.0, 15.0, max_len=6.0)
    assert (start, end) == (0.0, 5.0)
    assert text == "a"


def _lines():
    return [
        {"start": 0, "end": 4, "text": "He said the world would never see"},
        {"start": 4, "end": 8, "text": "it of the riches. And lo and behold,"},
        {"start": 8, "end": 12, "text": "look what happened. The people"},
        {"start": 12, "end": 16, "text": "who believed worked hard. It was beautifully designed,"},
        {"start": 16, "end": 20, "text": "simple and loved."},
    ]


def test_snap_opens_and_closes_on_whole_sentences_inside_caption_lines():
    start, end, text = snap_to_transcript(_lines(), 4.0, 13.0)
    assert 4 < start < 8 and 12 < end < 16
    assert text.startswith("And lo and behold,")
    assert text.endswith("worked hard.")


def test_snap_never_stops_on_a_caption_line_that_ends_mid_sentence():
    end, text = snap_to_transcript(_lines(), 4.0, 18.0)[1:]
    assert end == 20
    assert text.endswith("beautifully designed, simple and loved.")


def test_snap_cuts_on_word_timings_when_the_line_has_them():
    line = [{"start": 0, "end": 4, "text": "Done. Next one", "words": [
        {"word": "Done.", "start": 0.0, "end": 0.6},
        {"word": "Next", "start": 1.4, "end": 1.8},
        {"word": "one.", "start": 2.0, "end": 2.5},
    ]}]
    assert snap_to_transcript(line, 1.2, 3.0) == (1.4, 2.5, "Next one.")


# --- windows --------------------------------------------------------------

def _speech(n):
    return [{"start": i * 5.0, "end": i * 5.0 + 5, "text": "one two three four five"}
            for i in range(n)]


def test_windows_are_non_overlapping_and_sized():
    windows = TranscriptText.windows(_speech(12), 10, 20)
    assert [(w["start"], w["end"]) for w in windows][:2] == [(0.0, 10.0), (10.0, 20.0)]
    assert all(10 <= w["end"] - w["start"] <= 20 for w in windows)


def test_windows_skip_short_text():
    short = [{"start": 0, "end": 12, "text": "hi"}]
    assert TranscriptText.windows(short, 10, 20) == []


# --- detect_language ------------------------------------------------------

def test_detect_language_by_script():
    assert detect_language("नमस्ते दुनिया") == "hindi"
    assert detect_language("你好世界") == "chinese"
    assert detect_language("مرحبا بالعالم") == "arabic"
    assert detect_language("hello world") == "english"


def test_detect_language_uses_dominant_script_not_stray_char():
    # A mostly-Hindi clip with one stray Arabic glyph must stay hindi, not flip to arabic.
    assert detect_language("नमस्ते दोस्तों आज हम बात करेंगे ؛ विषय पर") == "hindi"
    # Empty / punctuation-only text is english, never a non-Latin script.
    assert detect_language("") == "english"
    assert detect_language("... --- 123") == "english"

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from kinoforge.segments.clips.moments.moment import Moment

_CLOSERS = r"\"')\]\u201d\u2019"
_SENTENCE_END = re.compile(rf"[.!?\u2026][{_CLOSERS}]?$")
_SENTENCE_BREAK = re.compile(rf"(?<=[.!?\u2026])\s+|(?<=[.!?\u2026][{_CLOSERS}])\s+")


class TranscriptText:
    """Transcript utilities: boundary snapping, candidate windows, language guess."""

    @classmethod
    def snap(cls, transcript: List[Dict], start: float, end: float,
             min_len: float = 0.0, max_len: float = 0.0) -> Tuple[float, float, str]:
        """(start, end, text) of [start, end] snapped onto whole segments and sized into
        [min_len, max_len], so a clip opens and closes on a complete sentence."""
        segs = cls.sentences(
            sorted((s for s in transcript if s.get("text")), key=lambda s: Moment(s).start))
        if not segs:
            return start, end, ""
        first = min(range(len(segs)), key=lambda i: abs(Moment(segs[i]).start - start))
        last = next((i for i in range(first, len(segs)) if Moment(segs[i]).end >= end),
                    len(segs) - 1)
        while min_len > 0 and cls._span(segs, first, last) < min_len and (
                last < len(segs) - 1 or first > 0):
            if last < len(segs) - 1:
                last += 1
            else:
                first -= 1
        while max_len > 0 and cls._span(segs, first, last) > max_len and last > first:
            last -= 1
        text = " ".join((s.get("text") or "").strip() for s in segs[first:last + 1]).strip()
        return Moment(segs[first]).start, Moment(segs[last]).end, text

    @classmethod
    def sentences(cls, segs: List[Dict]) -> List[Dict]:
        pieces = [piece for seg in segs for piece in cls._pieces(seg)]
        if not any(cls._ends(piece["text"]) for piece in pieces):
            return segs
        sentences: List[Dict] = []
        current: Dict | None = None
        for piece in pieces:
            current = dict(piece) if current is None else {
                "start": current["start"], "end": piece["end"],
                "text": f"{current['text']} {piece['text']}"}
            if cls._ends(piece["text"]):
                sentences.append(current)
                current = None
        if current:
            sentences.append(current)
        return sentences

    @classmethod
    def _pieces(cls, seg: Dict) -> List[Dict]:
        words = [w for w in seg.get("words") or []
                 if w.get("start") is not None and w.get("end") is not None]
        if words:
            groups: List[List[Dict]] = [[]]
            for word in words:
                groups[-1].append(word)
                if cls._ends(str(word.get("word") or "")):
                    groups.append([])
            return [{"start": float(g[0]["start"]), "end": float(g[-1]["end"]),
                     "text": " ".join(str(w.get("word") or "").strip() for w in g)}
                    for g in groups if g]
        parts = [p for p in _SENTENCE_BREAK.split((seg.get("text") or "").strip()) if p]
        start, span = Moment(seg).start, Moment(seg).span
        total, done, pieces = sum(len(p) for p in parts) or 1, 0, []
        for part in parts:
            begin = start + span * done / total
            done += len(part)
            pieces.append({"start": begin, "end": start + span * done / total, "text": part})
        return pieces

    @staticmethod
    def _ends(text: str) -> bool:
        return bool(_SENTENCE_END.search(text.strip()))

    @classmethod
    def windows(cls, transcript: List[Dict], min_len: float, max_len: float) -> List[Dict]:
        """Non-overlapping candidate windows across the whole transcript, each between min_len
        and max_len seconds with at least 5 words."""
        candidates = []
        i, n = 0, len(transcript)
        while i < n:
            start = end = transcript[i]["start"]
            parts = []
            j = i
            while j < n and transcript[j]["end"] - start <= max_len:
                parts.append(transcript[j]["text"])
                end = transcript[j]["end"]
                j += 1
                if end - start >= min_len:
                    break
            text = " ".join(parts).strip()
            if min_len <= end - start <= max_len and len(text.split()) >= 5:
                candidates.append(Moment.new(start, end, text=text,
                                             language=cls.detect_language(text)))
                i = j
            else:
                i += 1
        return candidates

    @staticmethod
    def clock(seconds: float) -> str:
        minutes, secs = divmod(int(seconds), 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"

    @staticmethod
    def detect_language(text: str) -> str:
        """The script with the most characters wins, so a stray glyph cannot flip the label."""
        counts = {
            "hindi": len(re.findall(r"[ऀ-ॿ]", text)),
            "chinese": len(re.findall(r"[一-鿿]", text)),
            "arabic": len(re.findall(r"[؀-ۿ]", text)),
        }
        best = max(counts, key=lambda k: counts[k])
        return best if counts[best] > 0 else "english"

    @staticmethod
    def _span(segs: List[Dict], first: int, last: int) -> float:
        return Moment(segs[last]).end - Moment(segs[first]).start

import re
from collections.abc import Iterable, Mapping

from kinoforge.segments.common.text import clean_text

CAST = "cast"
OFF = "off"
HOME = "center"


class Words:
    GAPS = re.compile(r"[\s-]+")

    @classmethod
    def key(cls, value: object) -> str:
        return cls.GAPS.sub("_", str(value or "").strip().lower())


class SetRules:
    def __init__(self, kit: Mapping, empty: Iterable[object] = ()) -> None:
        pictures = kit.get("pictures")
        self.pictures = (
            tuple(str(field) for field in pictures) if isinstance(pictures, Mapping) else ()
        )
        furniture = kit.get("furniture")
        self.furniture = {
            str(backdrop): {Words.key(word) for word in words}
            for backdrop, words in (furniture if isinstance(furniture, Mapping) else {}).items()
            if isinstance(words, list)
        }
        self.empty = {Words.key(word) for word in empty} - {""}

    def problems(self, drawn: Mapping, story: Mapping, presenter: str) -> list[str]:
        cast = [member for member in drawn.get("cast") or [] if isinstance(member, Mapping)]
        return [
            *self._ids(cast),
            *self._speakers(cast, story, presenter),
            *self._named(drawn, cast),
            *self._places(cast),
            *self._furniture(drawn),
        ]

    @staticmethod
    def _ids(cast: list[Mapping]) -> list[str]:
        ids = [str(member.get("id") or "") for member in cast]
        if len(set(ids)) != len(ids):
            return ["set.cast: every cast member needs an id of their own"]
        return []

    @staticmethod
    def _speakers(cast: list[Mapping], story: Mapping, presenter: str) -> list[str]:
        if presenter != CAST:
            if len(cast) != 1:
                return [f"set.cast: has {len(cast)}, the presenter alone is a cast of one"]
            return []
        names = {clean_text(member.get("name")).casefold() for member in cast}
        speakers = dict.fromkeys(
            clean_text(scene.get("speaker"))
            for scene in story.get("scenes") or []
            if isinstance(scene, Mapping) and clean_text(scene.get("speaker"))
        )
        return [
            f"set.cast: {speaker!r} speaks in the script; add them by that name"
            for speaker in speakers
            if speaker.casefold() not in names
        ]

    def _named(self, drawn: Mapping, cast: list[Mapping]) -> list[str]:
        found = [
            f"set.cast[{i}].{field}: {member[field]!r} names nothing; leave {field} out"
            for i, member in enumerate(cast)
            for field in self.pictures
            if self._nothing(member.get(field))
        ]
        found += [
            f"set.props[{i}].kind: {prop['kind']!r} names nothing; leave this prop out"
            for i, prop in self._props(drawn)
            if self._nothing(prop.get("kind"))
        ]
        card = drawn.get("card")
        if isinstance(card, Mapping) and self._nothing(card.get("icon")):
            found.append(f"set.card.icon: {card['icon']!r} names nothing; leave icon out")
        return found

    def _nothing(self, value: object) -> bool:
        return value is not None and Words.key(value) in self.empty

    @staticmethod
    def _places(cast: list[Mapping]) -> list[str]:
        found = []
        held: dict[str, str] = {}
        for i, member in enumerate(cast):
            place = str(member.get("place") or "")
            if member.get("enters") or not place:
                continue
            name = clean_text(member.get("name")) or str(member.get("id") or "")
            if place in held:
                found.append(
                    f"set.cast[{i}].place: {name} and {held[place]} both start at {place}; "
                    "give each their own place"
                )
                continue
            held[place] = name
        return found

    def _furniture(self, drawn: Mapping) -> list[str]:
        backdrop = str(drawn.get("backdrop") or "")
        has = self.furniture.get(backdrop) or set()
        return [
            f"set.props[{i}].kind: the {backdrop} backdrop already has a {prop['kind']}; "
            "leave this prop out"
            for i, prop in self._props(drawn)
            if Words.key(prop.get("kind")) in has
        ]

    @staticmethod
    def _props(drawn: Mapping) -> list[tuple[int, Mapping]]:
        return [
            (i, prop)
            for i, prop in enumerate(drawn.get("props") or [])
            if isinstance(prop, Mapping)
        ]


class LineRules:
    MOST_ACTS = 4
    PLAYED = {"act": "actions", "face": "faces"}

    def __init__(
        self, drawn_set: Mapping, spots: Iterable[object] = (), words: Mapping | None = None
    ) -> None:
        listed = words or {}
        self.playable = {
            field: [str(word) for word in listed[name]]
            for field, name in self.PLAYED.items()
            if isinstance(listed.get(name), list)
        }
        cast = [member for member in drawn_set.get("cast") or [] if isinstance(member, Mapping)]
        self.homes = {str(member.get("id")): str(member.get("place") or HOME) for member in cast}
        self.card = isinstance(drawn_set.get("card"), Mapping)
        self.props = [
            str(prop.get("kind"))
            for prop in drawn_set.get("props") or []
            if isinstance(prop, Mapping) and prop.get("kind")
        ]
        self.spots = [str(spot) for spot in spots]
        self.start = {
            who: OFF if member.get("enters") else self.homes[who]
            for who, member in ((str(member.get("id")), member) for member in cast)
        }

    def problems(
        self,
        items: list,
        speakers: list[str],
        at: Mapping[str, str],
        span: tuple[int, int],
    ) -> list[str]:
        found: list[str] = []
        now = dict(at)
        asked = self.numbered(items, span)
        for number in range(span[0], span[1] + 1):
            index, item = asked.get(number, (-1, {}))
            where = f"direction.lines[{index}]"
            if item.get("card") and not self.card:
                found.append(f"{where}.card: the set has no card; leave card out")
            found += self.unplayable(item, where)
            found += self.unknown_gone(item, where)
            moves = self.moves(item, speakers[number - 1], now)
            for who, place, other in self.clashes(now, moves):
                act = self._act(item, who)
                found.append(
                    f"{where}.acts[{act}].move: {who} moves to {place} where {other} stands; "
                    f"pick a free place or move {other} away first"
                )
            now = {**now, **moves}
        return found

    def played(self, item: Mapping, speaker: str, at: Mapping[str, str]) -> tuple[dict, dict]:
        line = {key: value for key, value in item.items() if key != "line"}
        if not self.card:
            line.pop("card", None)
        gone = [kind for kind in line.pop("gone", None) or [] if str(kind) in self.props]
        if gone:
            line["gone"] = gone
        acts = [
            self.playable_only(act) for act in line.get("acts") or [] if isinstance(act, Mapping)
        ]
        clashing = {who for who, _, _ in self.clashes(at, self.moves({"acts": acts}, "", at))}
        for act in acts:
            if str(act.get("who")) in clashing:
                act.pop("move", None)
        acts = [act for act in acts if set(act) - {"who"}]
        moves = self.moves({"acts": acts}, speaker, at)
        own = next((act for act in acts if act.get("who") == speaker), None)
        if speaker in moves and not (own or {}).get("move"):
            if own is None:
                own = {"who": speaker}
                acts = [own, *acts][: self.MOST_ACTS]
            own["move"] = moves[speaker]
        line.pop("acts", None)
        if acts:
            line["acts"] = acts
        return line, {**at, **moves}

    def unplayable(self, item: Mapping, where: str) -> list[str]:
        return [
            f"{where}.acts[{i}].{field}: {act[field]!r} is not one this cast can play; "
            f"use one of {', '.join(allowed)} or leave {field} out"
            for i, act in enumerate(item.get("acts") or [])
            if isinstance(act, Mapping)
            for field, allowed in self.playable.items()
            if act.get(field) and str(act[field]) not in allowed
        ]

    def unknown_gone(self, item: Mapping, where: str) -> list[str]:
        listed = ", ".join(self.props) or "none"
        return [
            f"{where}.gone[{i}]: {kind!r} is not a prop on the set; use one of {listed} "
            "or leave gone out"
            for i, kind in enumerate(item.get("gone") or [])
            if str(kind) not in self.props
        ]

    def playable_only(self, act: Mapping) -> dict:
        return {
            key: value
            for key, value in act.items()
            if key not in self.playable or str(value) in self.playable[key]
        }

    def moves(self, item: Mapping, speaker: str, at: Mapping[str, str]) -> dict[str, str]:
        asked = {
            str(act.get("who")): str(act["move"])
            for act in item.get("acts") or []
            if isinstance(act, Mapping) and act.get("move") and str(act.get("who")) in self.homes
        }
        if speaker and at.get(speaker) == OFF and speaker not in asked:
            asked[speaker] = self.free(speaker, {**at, **asked})
        return asked

    def free(self, who: str, at: Mapping[str, str]) -> str:
        taken = {place for other, place in at.items() if other != who and place != OFF}
        home = self.homes.get(who, HOME)
        return next((spot for spot in [home, *self.spots] if spot not in taken), home)

    @staticmethod
    def clashes(at: Mapping[str, str], moves: Mapping[str, str]) -> list[tuple[str, str, str]]:
        after = {**at, **moves}
        found = []
        for who, place in moves.items():
            if place == OFF:
                continue
            other = next((o for o, held in after.items() if o != who and held == place), None)
            if other is not None:
                found.append((who, place, other))
        return found

    @staticmethod
    def numbered(items: list, span: tuple[int, int]) -> dict[int, tuple[int, Mapping]]:
        first, last = span
        out: dict[int, tuple[int, Mapping]] = {}
        for index, item in enumerate(items):
            number = item.get("line") if isinstance(item, Mapping) else None
            if isinstance(number, int) and not isinstance(number, bool) and first <= number <= last:
                out.setdefault(number, (index, item))
        return out

    @staticmethod
    def _act(item: Mapping, who: str) -> int:
        acts = item.get("acts") or []
        return next(
            (i for i, act in enumerate(acts) if isinstance(act, Mapping) and act.get("who") == who),
            0,
        )

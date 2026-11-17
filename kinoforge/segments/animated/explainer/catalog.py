from collections.abc import Iterable, Mapping

from kinoforge.segments.animated.prompts import KitWords


class KitCatalog:
    SURFACES = "surfaces"
    SURFACE_KEY = "animated_surface_{key}"

    def __init__(self, kit: Mapping) -> None:
        self.kit = kit
        self.pieces = KitWords.pieces(kit)
        self.format = str((kit.get("board") or {}).get("format") or "")

    def surfaces(self, stage: Mapping | None) -> list[str]:
        stage = stage or {}
        named = stage.get(self.SURFACES)
        return [
            self.SURFACE_KEY.format(key=part["key"])
            for part in self.kit.get("surfaces") or []
            if isinstance(part, Mapping)
            and part.get("key")
            and (
                not isinstance(named, list)
                or part["key"] in named
                or stage.get(str(part.get("part")))
            )
        ]

    def lists(self, stage: Mapping | None, extra: Iterable[str] = ()) -> dict[str, str]:
        stage = stage or {}
        extra = set(extra)
        out: dict[str, str] = {}
        for item in self._lists():
            keys = [str(key) for key in item.get("keys") or []]
            picks = [str(key) for key in stage.get(str(item.get("pick"))) or []]
            picked = set(picks)
            known = set(keys)
            kept = [key for key in keys if key in picked] + [
                key for key in dict.fromkeys(picks) if key in extra and key not in known
            ]
            out[str(item.get("name"))] = KitWords.JOIN.join(kept or keys)
        return out

    def shared(self, stage: Mapping | None) -> dict:
        picks = {self.SURFACES, *(str(item.get("pick")) for item in self._lists())}
        return {name: part for name, part in (stage or {}).items() if part and name not in picks}

    def _lists(self) -> list[Mapping]:
        return [item for item in self.kit.get("lists") or [] if isinstance(item, Mapping)]

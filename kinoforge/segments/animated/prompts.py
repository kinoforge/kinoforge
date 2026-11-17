import json
from collections.abc import Mapping

from kinoforge.segments.common.languages import language_name
from kinoforge.segments.common.ports import TextPorts


class KitWords:
    JOIN = ", "

    @classmethod
    def params(cls, kit: Mapping) -> dict[str, str]:
        words = kit.get("words")
        limits = kit.get("limits")
        out = {
            str(name): cls.JOIN.join(str(word) for word in listed)
            for name, listed in (words if isinstance(words, Mapping) else {}).items()
            if isinstance(listed, list)
        }
        out.update(
            {
                f"limit_{name}": str(value)
                for name, value in (limits if isinstance(limits, Mapping) else {}).items()
            }
        )
        return out

    @staticmethod
    def pieces(kit: Mapping) -> dict[str, str]:
        out: dict[str, str] = {}
        for piece in kit.get("pieces") or []:
            if not isinstance(piece, Mapping) or not piece.get("type"):
                continue
            kind = str(piece["type"])
            out[f"fields_{kind}"] = str(piece.get("fields") or "")
            out[f"example_{kind}"] = json.dumps(
                piece.get("example"), ensure_ascii=False, separators=(",", ":")
            )
        return out


class FilmLanguage:
    @staticmethod
    def rule(ports: TextPorts, rec: Mapping, subject: str) -> str:
        language = str((rec.get("input") or {}).get("language") or "")
        return ports.language_rule(subject, language_name(language, ports.languages))

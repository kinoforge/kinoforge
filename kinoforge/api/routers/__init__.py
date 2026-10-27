"""FastAPI routers, one module per segment plus service metadata. app.py mounts them all."""

from kinoforge.api.routers import clips, flow, meta, series, story

ALL = (meta.router, clips.router, story.router, series.router, flow.router)

__all__ = ["ALL", "clips", "flow", "meta", "series", "story"]

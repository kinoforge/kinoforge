from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

from pydantic import Field, model_validator

from kinoforge.contract import AITask, ModelRef
from kinoforge.segments.clips.render.captions import AssCaptions, CaptionWindow
from kinoforge.segments.clips.render.ffmpeg import Ffmpeg, FfmpegError
from kinoforge.segments.flow.nodes.base import (
    FlowError,
    NodeConfig,
    NodeContext,
    NodeGroup,
    NodeSpec,
)
from kinoforge.segments.flow.ports import Port, PortType

VIDEO = Port("video", "Video", PortType.VIDEO, required=True)
OUT = (Port("video", "Video", PortType.VIDEO),)
FPS = 30
TIMEOUT = 1800.0
AUDIO_OUT = ["-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2"]


@dataclass(frozen=True)
class Probe:
    width: int
    height: int
    seconds: float
    audio: bool

    @classmethod
    def of(cls, path: Path) -> "Probe":
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format",
               "-show_streams", str(path)]
        try:
            data = json.loads(subprocess.run(cmd, capture_output=True, check=True,
                                             timeout=60).stdout)
        except (subprocess.SubprocessError, OSError, ValueError) as exc:
            raise FlowError(f"could not read {path.name}") from exc
        streams = data.get("streams") or []
        video: Dict[str, Any] = next((s for s in streams if s.get("codec_type") == "video"), {})
        return cls(
            width=int(video.get("width") or 0) // 2 * 2,
            height=int(video.get("height") or 0) // 2 * 2,
            seconds=float((data.get("format") or {}).get("duration") or 0),
            audio=any(s.get("codec_type") == "audio" for s in streams),
        )


class Encode:
    @staticmethod
    def run(args: Sequence[str]) -> None:
        try:
            Ffmpeg.run(args, timeout=TIMEOUT)
        except FfmpegError as exc:
            raise FlowError(f"the edit failed: {exc}") from exc

    @staticmethod
    def fit(width: int, height: int) -> str:
        return (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS},format=yuv420p")


class Concat(NodeSpec):
    type = "edit.concat"
    group = NodeGroup.EDIT
    label = "Join clips"
    description = "Plays clips one after another, fitted to the first clip's frame."
    inputs = (Port("videos", "Clips", PortType.VIDEO, required=True, many=True),)
    outputs = OUT

    def run(self, ctx: NodeContext, inputs: Dict[str, Any], config: Any) -> Dict[str, Any]:
        paths = [ctx.path(media) for media in inputs["videos"]]
        probes = [Probe.of(path) for path in paths]
        first = probes[0]
        if not first.width:
            raise FlowError("the first clip has no picture")
        args: List[str] = []
        graph: List[str] = []
        for i, path in enumerate(paths):
            args += ["-i", str(path)]
            graph.append(f"[{i}:v]{Encode.fit(first.width, first.height)}[v{i}]")
        silent = len(paths)
        args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        for i, probe in enumerate(probes):
            source = f"[{i}:a]" if probe.audio else f"[{silent}:a]"
            graph.append(f"{source}atrim=0:{probe.seconds:.3f},asetpts=PTS-STARTPTS,"
                         f"aformat=sample_rates=44100:channel_layouts=stereo[a{i}]")
        pairs = "".join(f"[v{i}][a{i}]" for i in range(len(paths)))
        graph.append(f"{pairs}concat=n={len(paths)}:v=1:a=1[v][a]")
        out = ctx.target("video", ".mp4")
        Encode.run([*args, "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]",
                    *Ffmpeg.encode_args(False), *AUDIO_OUT, "-movflags", "+faststart",
                    str(out)])
        return {"video": ctx.media(out)}


class TrimConfig(NodeConfig):
    start: float = Field(default=0, ge=0, le=3600, title="Start (s)")
    end: float = Field(default=0, ge=0, le=3600, title="End (s, 0 is the end)")

    @model_validator(mode="after")
    def _ordered(self) -> "TrimConfig":
        if self.end and self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class Trim(NodeSpec):
    type = "edit.trim"
    group = NodeGroup.EDIT
    label = "Trim"
    description = "Keeps one stretch of a clip."
    inputs = (VIDEO,)
    outputs = OUT
    config = TrimConfig

    def run(self, ctx: NodeContext, inputs: Dict[str, Any], config: Any) -> Dict[str, Any]:
        source = ctx.path(inputs["video"])
        if config.start >= Probe.of(source).seconds:
            raise FlowError("the start is past the clip's end")
        out = ctx.target("video", ".mp4")
        span = ["-ss", f"{config.start:.3f}"] + (["-to", f"{config.end:.3f}"] if config.end else [])
        Encode.run([*span, "-i", str(source), *Ffmpeg.encode_args(False), *AUDIO_OUT,
                    "-movflags", "+faststart", str(out)])
        return {"video": ctx.media(out)}


class MixConfig(NodeConfig):
    voice_volume: float = Field(default=1.0, ge=0, le=2, title="Voice volume")
    music_volume: float = Field(default=0.25, ge=0, le=1, title="Music volume")
    keep_original: bool = Field(default=True, title="Keep the clip's own sound")
    hold_for_voice: bool = Field(default=True, title="Hold the last frame until the voice ends")


class Mix(NodeSpec):
    type = "edit.mix"
    group = NodeGroup.EDIT
    label = "Add sound"
    description = "Lays voice lines (one after another) and a music bed over a clip."
    inputs = (
        VIDEO,
        Port("voice", "Voice", PortType.AUDIO, many=True),
        Port("music", "Music", PortType.AUDIO),
    )
    outputs = OUT
    config = MixConfig
    one_of = ("voice", "music")

    def run(self, ctx: NodeContext, inputs: Dict[str, Any], config: Any) -> Dict[str, Any]:
        video = ctx.path(inputs["video"])
        probe = Probe.of(video)
        voices = [ctx.path(media) for media in inputs.get("voice") or []]
        music = ctx.path(inputs["music"]) if inputs.get("music") else None
        voice_seconds = sum(Probe.of(path).seconds for path in voices)
        seconds = max(probe.seconds, voice_seconds) if config.hold_for_voice else probe.seconds
        args = ["-i", str(video)]
        graph = [f"[0:v]tpad=stop_mode=clone:stop_duration={max(0.0, seconds - probe.seconds):.3f}[v]"]
        layers: List[str] = []
        if probe.audio and config.keep_original:
            layers.append("[0:a]")
        for path in voices:
            args += ["-i", str(path)]
        if voices:
            pieces = "".join(f"[{i + 1}:a]" for i in range(len(voices)))
            graph.append(f"{pieces}concat=n={len(voices)}:v=0:a=1,"
                         f"volume={config.voice_volume}[voice]")
            layers.append("[voice]")
        if music:
            args += ["-stream_loop", "-1", "-i", str(music)]
            graph.append(f"[{len(voices) + 1}:a]volume={config.music_volume}[music]")
            layers.append("[music]")
        graph.append(f"{''.join(layers)}amix=inputs={len(layers)}:duration=longest:"
                     f"normalize=0[a]")
        out = ctx.target("video", ".mp4")
        Encode.run([*args, "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]",
                    "-t", f"{seconds:.3f}", *Ffmpeg.encode_args(False), *AUDIO_OUT,
                    "-movflags", "+faststart", str(out)])
        return {"video": ctx.media(out)}


class Captions(NodeSpec):
    type = "edit.captions"
    group = NodeGroup.EDIT
    label = "Captions"
    description = "Listens to the clip and burns what is said into the picture."
    inputs = (VIDEO,)
    outputs = OUT

    def run(self, ctx: NodeContext, inputs: Dict[str, Any], config: Any) -> Dict[str, Any]:
        source = ctx.path(inputs["video"])
        probe = Probe.of(source)
        if not probe.audio:
            raise FlowError("the clip has no sound to caption")
        with tempfile.TemporaryDirectory() as work:
            sound = Path(work) / "sound.mp3"
            Encode.run(["-i", str(source), "-vn", "-ac", "1", "-ar", "16000", str(sound)])
            lines, _ = ctx.infrelay.transcribe(AITask.TRANSCRIBE, sound.read_bytes(), ModelRef())
            subtitles = Path(work) / "captions.ass"
            window = CaptionWindow(transcript=lines, start=0.0, end=probe.seconds)
            if not AssCaptions(probe.width, probe.height).write(window, subtitles):
                raise FlowError("nothing is said in the clip")
            out = ctx.target("video", ".mp4")
            Encode.run(["-i", str(source), "-vf", AssCaptions.filter(subtitles),
                        *Ffmpeg.encode_args(False), "-c:a", "copy", "-movflags", "+faststart",
                        str(out)])
        return {"video": ctx.media(out)}

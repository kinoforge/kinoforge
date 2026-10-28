import subprocess
from pathlib import Path

import pytest

from kinoforge.schemas.flow import FlowNodeRunRequest
from kinoforge.segments.flow.nodes import FlowError
from kinoforge.segments.flow.nodes.edit import Probe
from kinoforge.service.runtimes.flow import FlowRuntime
from kinoforge.service.settings import ServiceSettings

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


class FakeInfrelay:
    def __init__(self):
        self.calls = []

    def image(self, task, ref, prompt, spec):
        self.calls.append((task.value, str(ref), prompt, spec.reference))
        return PNG


class Settings(ServiceSettings):
    def infrelay(self, owner=""):
        return self.fake


def _runtime(tmp_path, fake=None):
    settings = Settings(shared_root=tmp_path)
    object.__setattr__(settings, "fake", fake or FakeInfrelay())
    return FlowRuntime(settings)


def _run(runtime, node_type, config=None, inputs=None, item=0):
    return runtime.run(FlowNodeRunRequest.model_validate({
        "run_id": "r1", "owner": "u1", "item": item, "out_dir": "flows/u1/r1/n1",
        "node": {"id": "n1", "type": node_type, "config": config or {}},
        "inputs": inputs or {},
    }))


def _clip(path: Path, seconds: float, size: str = "320x240", sound: bool = True) -> None:
    args = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=blue:s={size}:d={seconds}"]
    if sound:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-shortest"]
    subprocess.run([*args, "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True)


def test_an_image_node_paints_its_prompt_from_its_reference(tmp_path):
    fake = FakeInfrelay()
    (tmp_path / "ref.png").write_bytes(PNG)
    out = _run(_runtime(tmp_path, fake), "generate.image",
               {"model": {"provider": "fal", "model": "flux"}},
               {"prompt": "a lighthouse", "reference": {"path": "ref.png"}}, item=2)

    image = out["outputs"]["image"]["path"]
    assert image.startswith("flows/u1/r1/n1/2-image-") and image.endswith(".png")
    assert (tmp_path / image).read_bytes() == PNG
    task, ref, prompt, reference = fake.calls[0]
    assert (task, ref, prompt, reference.data) == ("image", "fal/flux", "a lighthouse", PNG)


def test_a_video_node_makes_its_clip_to_the_audio_it_is_given(tmp_path):
    fake = FakeInfrelay()
    fake.video = lambda task, ref, prompt, spec: fake.calls.append(spec) or b"mp4"
    (tmp_path / "line.mp3").write_bytes(b"ID3voice")
    _run(_runtime(tmp_path, fake), "generate.video", {},
         {"prompt": "a keeper waves", "audio": {"path": "line.mp3"}})

    assert fake.calls[0].audio.data == b"ID3voice"


def test_a_node_is_refused_what_its_ports_do_not_take(tmp_path):
    runtime = _runtime(tmp_path)
    with pytest.raises(FlowError, match="needs Prompt"):
        _run(runtime, "generate.image")
    with pytest.raises(FlowError, match="must be text"):
        _run(runtime, "generate.image", inputs={"prompt": {"path": "x"}})
    with pytest.raises(FlowError, match="no input"):
        _run(runtime, "generate.image", inputs={"prompt": "x", "other": "y"})
    with pytest.raises(FlowError, match="invalid path"):
        _run(runtime, "generate.image", inputs={"prompt": "x", "reference": {"path": "../a"}})
    with pytest.raises(FlowError, match="runs on the caller"):
        _run(runtime, "output.save", inputs={"video": {"path": "v.mp4"}})
    with pytest.raises(FlowError, match="Seed"):
        _run(runtime, "generate.image", {"seed": -1}, {"prompt": "x"})


def test_the_out_dir_stays_below_the_shared_root():
    with pytest.raises(ValueError):
        FlowNodeRunRequest.model_validate({
            "run_id": "r1", "out_dir": "../etc", "node": {"id": "n", "type": "input.text"},
        })


def test_scenes_split_a_story_into_prompts_and_lines(tmp_path):
    story = {"title": "Keeper", "style": "warm film",
             "scenes": [{"prompt": "a storm", "narration": "It rained."},
                        {"prompt": "a cat", "narration": "A cat came."}]}
    out = _run(_runtime(tmp_path), "story.scenes", inputs={"story": story})["outputs"]
    assert out == {"prompts": ["a storm. warm film", "a cat. warm film"],
                   "narration": ["It rained.", "A cat came."], "title": "Keeper"}


def test_each_scene_adds_its_clip_to_the_film_so_far(tmp_path):
    for name in ("a.mp4", "b.mp4"):
        (tmp_path / name).write_bytes(b"x")
    runtime = _runtime(tmp_path)
    first = _run(runtime, "story.scene", inputs={"clip": {"path": "a.mp4"}})["outputs"]["film"]
    second = _run(runtime, "story.scene", inputs={"before": first, "clip": {"path": "b.mp4"}})
    assert [m["path"] for m in second["outputs"]["film"]] == ["a.mp4", "b.mp4"]


def test_clips_join_fitted_to_the_first_and_take_sound_over_them(tmp_path):
    runtime = _runtime(tmp_path)
    _clip(tmp_path / "a.mp4", 1.0)
    _clip(tmp_path / "b.mp4", 1.0, size="640x480", sound=False)
    _clip(tmp_path / "voice.mp4", 3.0)
    joined = _run(runtime, "edit.concat",
                  inputs={"videos": [{"path": "a.mp4"}, {"path": "b.mp4"}]})["outputs"]["video"]
    probe = Probe.of(tmp_path / joined["path"])
    assert (probe.width, probe.height, probe.audio) == (320, 240, True)
    assert probe.seconds == pytest.approx(2.0, abs=0.2)

    subprocess.run(["ffmpeg", "-y", "-i", str(tmp_path / "voice.mp4"), "-vn",
                    str(tmp_path / "voice.mp3")], check=True, capture_output=True)
    mixed = _run(runtime, "edit.mix", inputs={"video": joined, "voice": [{"path": "voice.mp3"}]})
    held = Probe.of(tmp_path / mixed["outputs"]["video"]["path"])
    assert held.seconds == pytest.approx(3.0, abs=0.3)

    cut = _run(runtime, "edit.trim", {"start": 0.5, "end": 1.5}, {"video": joined})
    assert Probe.of(tmp_path / cut["outputs"]["video"]["path"]).seconds == pytest.approx(
        1.0, abs=0.2
    )
    with pytest.raises(FlowError, match="past the clip"):
        _run(runtime, "edit.trim", {"start": 30}, {"video": joined})


def test_the_screenwriter_writes_from_the_brief_with_what_the_caller_resolved(tmp_path, monkeypatch):
    from kinoforge.service.runtimes import story

    seen = {}

    def write(self, request, is_cancelled=None):
        seen["request"] = request
        return {"result": {"ok": True, "story": {"title": "Keeper", "scenes": []}},
                "meter_events": [{"action": "agent_run", "qty": 1}],
                "inference": [{"task": "story.write", "credits": 2}]}

    monkeypatch.setattr(story.StoryRuntime, "write", write)
    writer = {"agent": {"stages": [{}]}, "pick": {}, "config": {},
              "definitions": {"schema_version": 1, "id": "b", "version": "1",
                              "engine": {"minimum": "0.1.0"}, "definitions": []}}
    request = FlowNodeRunRequest.model_validate({
        "run_id": "r1", "out_dir": "flows/u1/r1/w", "host": {"screenwriter": writer},
        "node": {"id": "w", "type": "story.write", "config": {"scene_count": 3}},
        "inputs": {"brief": "A lighthouse keeper adopts a cat during a storm."},
    })
    out = _runtime(tmp_path).run(request)

    context = seen["request"].context
    assert (context.scene_count, context.title) == (
        3, "A lighthouse keeper adopts a cat during a storm."
    )
    assert out["outputs"] == {"story": {"title": "Keeper", "scenes": []}}
    assert out["meter_events"] == [{"action": "agent_run", "qty": 1}]
    assert out["inference"] == [{"task": "story.write", "credits": 2}]
    assert seen["request"].pick == {}

    picked = {"provider": "openrouter", "model": "deepseek/deepseek-chat"}
    _runtime(tmp_path).run(request.model_copy(update={"node": request.node.model_copy(
        update={"config": {"model": picked}})}))
    assert seen["request"].pick == picked
    with pytest.raises(FlowError, match="not set up"):
        _run(_runtime(tmp_path), "story.write", inputs={"brief": "x"})


def _presets(body, motion=""):
    return {"schema_version": 1, "id": "p", "version": "1", "engine": {"minimum": "0.1.0"},
            "definitions": [{"type": "preset", "key": "anime", "body": body,
                             "extras": {"motion": motion}}]}


def test_an_art_style_is_laid_over_the_prompt_from_the_presets_the_caller_sent(tmp_path):
    fake = FakeInfrelay()
    request = FlowNodeRunRequest.model_validate({
        "run_id": "r1", "out_dir": "flows/u1/r1/n1",
        "host": {"presets": _presets("Anime art of $prompt, cel shaded.")},
        "node": {"id": "n1", "type": "generate.image", "config": {"style": "anime"}},
        "inputs": {"prompt": "a lighthouse"},
    })
    _runtime(tmp_path, fake).run(request)
    assert fake.calls[0][2] == "Anime art of a lighthouse, cel shaded"

    with pytest.raises(FlowError, match="art style is not set up"):
        _run(_runtime(tmp_path), "generate.image", {"style": "anime"}, {"prompt": "x"})


def test_a_clip_is_made_small_and_carries_its_styles_motion(tmp_path):
    from kinoforge.segments.flow.nodes.generate import FlowStyle, VideoGen

    class Ctx:
        host = {"presets": _presets("Anime art of $prompt.", "Slow dolly in.")}

    prompt = FlowStyle.video(Ctx(), "a lighthouse", "anime")
    assert "a lighthouse" in prompt and "Slow dolly in" in prompt and "Anime art of" in prompt
    assert FlowStyle.video(Ctx(), "a lighthouse", "") == "a lighthouse"
    assert int(VideoGen.resolution) == 480


def test_settings_a_node_no_longer_has_still_load_and_languages_are_picked():
    from kinoforge.segments.flow.nodes.generate import VideoGenConfig, VoiceConfig

    assert VideoGenConfig.model_validate({"resolution": 720, "seconds": 4}).seconds == 4
    assert VoiceConfig.model_validate({"voice": "x", "language": "it"}).language.value == "it"
    with pytest.raises(ValueError):
        VoiceConfig.model_validate({"language": "klingon"})
    labels = VoiceConfig.model_json_schema()["properties"]["language"]["labels"]
    assert labels[""] == "Auto" and labels["hinglish"] == "Hinglish"

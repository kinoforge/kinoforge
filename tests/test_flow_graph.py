from kinoforge.segments.flow.graph import FlowGraph, FlowValidator, IssueCode
from kinoforge.service.runtimes.flow import FlowRuntime


def _graph(nodes, edges=()):
    return FlowGraph.model_validate({
        "nodes": [{"id": i, "type": t, "config": c} for i, t, c in nodes],
        "edges": [
            {"source": s, "source_port": sp, "target": t, "target_port": tp}
            for s, sp, t, tp in edges
        ],
    })


def _codes(graph):
    return [issue.code for issue in FlowValidator(graph).check().issues]


BRIEF = ("brief", "input.text", {"text": "A lighthouse keeper adopts a cat."})


def test_a_story_flow_runs_in_link_order_and_fans_out_per_scene():
    check = FlowValidator(_graph(
        [
            ("cut", "edit.concat", {}),
            BRIEF,
            ("write", "story.write", {"scene_count": 3}),
            ("scenes", "story.scenes", {}),
            ("paint", "generate.image", {}),
            ("move", "generate.video", {"seconds": 4}),
            ("speak", "generate.voice", {}),
            ("mix", "edit.mix", {}),
            ("result", "output.save", {}),
        ],
        [
            ("brief", "text", "write", "brief"),
            ("write", "story", "scenes", "story"),
            ("scenes", "prompts", "paint", "prompt"),
            ("scenes", "prompts", "move", "prompt"),
            ("paint", "image", "move", "first_frame"),
            ("scenes", "narration", "speak", "text"),
            ("move", "video", "cut", "videos"),
            ("cut", "video", "mix", "video"),
            ("speak", "audio", "mix", "voice"),
            ("mix", "video", "result", "video"),
        ],
    )).check()

    assert check.ok, check.issues
    assert check.order == ["brief", "write", "scenes", "paint", "speak", "move", "cut", "mix",
                           "result"]
    assert check.mapped == ["paint", "speak", "move"]
    assert check.lists == {"scenes": ["prompts", "narration"], "paint": ["image"],
                           "speak": ["audio"], "move": ["video"]}


def test_links_must_join_ports_of_one_type():
    graph = _graph([BRIEF, ("cut", "edit.concat", {})], [("brief", "text", "cut", "videos")])
    assert IssueCode.TYPE_MISMATCH in _codes(graph)


def test_a_single_input_takes_one_link_and_a_list_input_many():
    graph = _graph(
        [BRIEF, ("other", "input.text", {"text": "x"}), ("paint", "generate.image", {}),
         ("a", "input.video", {"asset": "a.mp4"}), ("b", "input.video", {"asset": "b.mp4"}),
         ("cut", "edit.concat", {})],
        [("brief", "text", "paint", "prompt"), ("other", "text", "paint", "prompt"),
         ("a", "video", "cut", "videos"), ("b", "video", "cut", "videos")],
    )
    assert _codes(graph) == [IssueCode.PORT_TAKEN]


def test_required_inputs_configs_and_cycles_are_reported():
    assert _codes(_graph([("paint", "generate.image", {"seed": -1})])) == [
        IssueCode.BAD_CONFIG, IssueCode.MISSING_INPUT,
    ]
    assert _codes(_graph([("mix", "edit.mix", {}), ("v", "input.video", {"asset": "v.mp4"})],
                         [("v", "video", "mix", "video")])) == [IssueCode.MISSING_INPUT]
    looped = _graph(
        [("a", "generate.text", {}), ("b", "generate.text", {})],
        [("a", "text", "b", "prompt"), ("b", "text", "a", "prompt")],
    )
    assert _codes(looped) == [IssueCode.CYCLE]
    assert _codes(_graph([("x", "nope", {})])) == [IssueCode.UNKNOWN_TYPE]
    assert _codes(_graph([])) == [IssueCode.EMPTY]


def test_trim_needs_its_end_after_its_start():
    graph = _graph([("v", "input.video", {"asset": "v.mp4"}),
                    ("t", "edit.trim", {"start": 5, "end": 2})],
                   [("v", "video", "t", "video")])
    assert _codes(graph) == [IssueCode.BAD_CONFIG]


def test_the_catalog_describes_every_node_with_its_config_schema():
    catalog = FlowRuntime.catalog()
    nodes = {node["type"]: node for node in catalog["nodes"]}
    assert set(catalog["groups"]) == {"input", "generate", "story", "edit", "output"}
    assert nodes["story.write"]["needs"] == ["screenwriter"]
    assert nodes["output.publish"]["host"] is True
    image = nodes["generate.image"]
    assert image["media"] == "image"
    assert image["config"]["properties"]["seed"]["minimum"] == 0
    assert [port["name"] for port in image["inputs"]] == ["prompt", "reference"]

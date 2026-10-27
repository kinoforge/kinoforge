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


def _scene_graph(nodes, edges=(), limits=None):
    return FlowGraph.model_validate({
        "nodes": [{"id": i, "type": t, "config": c, **({"parent": p} if p else {})}
                  for i, t, c, p in nodes],
        "edges": [
            {"source": s, "source_port": sp, "target": t, "target_port": tp}
            for s, sp, t, tp in edges
        ],
        "limits": limits or {},
    })


def _scene(n):
    return [(f"s{n}", "story.scene", {}, None),
            (f"p{n}", "input.text", {"text": f"Shot {n}"}, f"s{n}"),
            (f"v{n}", "generate.video", {}, f"s{n}")]


def _inside(n):
    return [(f"p{n}", "text", f"v{n}", "prompt"), (f"v{n}", "video", f"s{n}", "clip")]


def test_each_node_type_has_a_cap_the_caller_may_set():
    nodes = _scene(1) + _scene(2) + _scene(3)
    edges = _inside(1) + _inside(2) + _inside(3) + [
        ("s1", "film", "s2", "before"), ("s2", "film", "s3", "before")]
    assert FlowValidator(_scene_graph(nodes, edges)).check().ok

    issues = FlowValidator(_scene_graph(nodes, edges, {"story.scene": 2})).check().issues
    assert [(i.code, i.node) for i in issues] == [(IssueCode.TOO_MANY, "s3")]

    writers = _graph([(f"w{i}", "story.write", {}) for i in range(3)])
    assert IssueCode.TOO_MANY in _codes(writers)


def test_scenes_chain_in_order_and_links_stay_inside_their_scene():
    nodes = _scene(1) + _scene(2) + [("cast", "input.image", {"asset": "u/cast.png"}, None),
                                     ("cut", "edit.concat", {}, None)]
    edges = _inside(1) + _inside(2) + [("s1", "film", "s2", "before"),
                                       ("cast", "image", "v2", "references"),
                                       ("s2", "film", "cut", "videos")]
    check = FlowValidator(_scene_graph(nodes, edges)).check()
    assert check.ok, check.issues
    assert check.order.index("s1") < check.order.index("s2") < check.order.index("cut")
    assert check.mapped == []

    for bad in (("p1", "text", "v2", "prompt"),     # into another scene
                ("v1", "video", "cut", "videos"),   # out past its scene
                ("v2", "video", "s1", "clip")):     # a clip from another scene
        graph = _scene_graph(nodes, [e for e in edges if e[2:] != bad[2:]] + [bad])
        assert IssueCode.CROSS_BLOCK in _codes(graph), bad


def test_a_scene_holds_a_few_nodes_runs_once_and_sits_at_the_top():
    crowded = [("s1", "story.scene", {}, None)] + [
        (f"p{i}", "input.text", {"text": "x"}, "s1") for i in range(9)]
    assert IssueCode.BLOCK_FULL in _codes(_scene_graph(crowded))

    nested = [("s1", "story.scene", {}, None), ("s2", "story.scene", {}, "s1"),
              ("p", "input.text", {"text": "x"}, "cut"), ("cut", "edit.concat", {}, None)]
    assert _codes(_scene_graph(nested)).count(IssueCode.BAD_PARENT) == 2

    listed = _scene(1) + [BRIEF + (None,), ("w", "story.write", {}, None),
                          ("sc", "story.scenes", {}, None)]
    edges = [("p1", "text", "v1", "prompt"), ("v1", "video", "s1", "clip"),
             ("brief", "text", "w", "brief"), ("w", "story", "sc", "story"),
             ("sc", "prompts", "v1", "dialogue")]
    assert IssueCode.BLOCK_LIST in _codes(_scene_graph(listed, edges))


def test_a_video_takes_at_most_five_references():
    nodes = [("v", "generate.video", {}, None), BRIEF + (None,)] + [
        (f"i{n}", "input.image", {"asset": f"u/{n}.png"}, None) for n in range(6)]
    edges = [("brief", "text", "v", "prompt")] + [
        (f"i{n}", "image", "v", "references") for n in range(6)]
    assert _codes(_scene_graph(nodes, edges)) == [IssueCode.PORT_TAKEN]
    assert FlowValidator(_scene_graph(nodes[:-1], edges[:-1])).check().ok


def test_the_scene_by_scene_template_is_sound_once_its_lines_are_written():
    template = FlowRuntime.catalog()["templates"]["scenes"]
    nodes = [{k: v for k, v in n.items() if k != "position"} for n in template["nodes"]]
    for node in nodes:
        if node["type"] == "input.text":
            node["config"] = {"text": "A lighthouse at dusk."}
    check = FlowValidator(FlowGraph.model_validate({"nodes": nodes,
                                                    "edges": template["edges"]})).check()
    assert check.ok, check.issues
    assert check.order.index("scene1") < check.order.index("scene3") < check.order.index("cut")


def test_the_series_template_takes_its_brief_from_the_episode():
    template = FlowRuntime.catalog()["templates"]["series"]
    nodes = [{k: v for k, v in n.items() if k != "position"} for n in template["nodes"]]
    graph = FlowGraph.model_validate({"nodes": nodes, "edges": template["edges"]})
    assert nodes[0]["type"] == "input.episode"
    assert FlowValidator(graph).check().ok


def test_the_story_template_is_a_sound_flow_once_its_brief_is_written():
    template = FlowRuntime.catalog()["templates"]["story"]
    nodes = [{k: v for k, v in n.items() if k != "position"} for n in template["nodes"]]
    assert all("position" in n for n in template["nodes"])
    graph = FlowGraph.model_validate({"nodes": nodes, "edges": template["edges"]})
    assert _codes(graph) == [IssueCode.BAD_CONFIG]
    nodes[0]["config"] = {"text": "A lighthouse keeper adopts a cat."}
    graph = FlowGraph.model_validate({"nodes": nodes, "edges": template["edges"]})
    assert FlowValidator(graph).check().ok

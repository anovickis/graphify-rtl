"""Cross-file module instantiation resolution for Verilog/SystemVerilog.

Verilog puts one module per file by convention, so a design's hierarchy is almost
entirely cross-file. Extraction is per-file and emits a file-local stub for each
instantiated name; without the resolution pass those stubs never meet their
definitions and the graph is one component per file.

These exercise the pass directly rather than through the parser, so they run whether
or not tree_sitter_verilog is installed.
"""
from graphify.extract import _resolve_cross_file_verilog_instantiations as resolve


def _mod(nid, label, path):
    return {"id": nid, "label": label, "source_file": path, "verilog_module": label}


def _stub(nid, label, path):
    return {"id": nid, "label": label, "source_file": path}


def _inst(src, tgt, name, provisional=False):
    return {"source": src, "target": tgt, "relation": "instantiates",
            "verilog_instantiates": name, "verilog_provisional": provisional}


def test_instantiation_repoints_to_the_definition_in_another_file():
    nodes = [_mod("top_v_top", "Top", "Top.v"),
             _mod("child_v_child", "Child", "Child.v"),
             _stub("top_v_child", "Child", "Top.v")]
    edges = [_inst("top_v_top", "top_v_child", "Child")]

    assert resolve(nodes, edges) == 1
    assert edges[0]["target"] == "child_v_child"
    # the file-local stub is gone, not left orphaned beside the real node
    assert [n["id"] for n in nodes] == ["top_v_top", "child_v_child"]


def test_edge_becomes_cross_file():
    nodes = [_mod("top_v_top", "Top", "Top.v"),
             _mod("child_v_child", "Child", "Child.v"),
             _stub("top_v_child", "Child", "Top.v")]
    edges = [_inst("top_v_top", "top_v_child", "Child")]
    resolve(nodes, edges)
    by_id = {n["id"]: n for n in nodes}
    assert by_id[edges[0]["source"]]["source_file"] != by_id[edges[0]["target"]]["source_file"]


def test_unresolved_name_is_kept_and_marked_external():
    """Vendor IP and technology cells are outside the corpus - show the boundary."""
    nodes = [_mod("top_v_top", "Top", "Top.v"),
             _stub("top_v_sram", "SRAM_TSMC", "Top.v")]
    edges = [_inst("top_v_top", "top_v_sram", "SRAM_TSMC")]

    assert resolve(nodes, edges) == 0
    assert len(edges) == 1
    assert [n for n in nodes if n["id"] == "top_v_sram"][0]["external"] is True


def test_provisional_parse_naming_nothing_real_is_dropped():
    """`Child u_child (...)` can parse as checker_instantiation; only keep it if
    the name is a module that actually exists."""
    nodes = [_mod("top_v_top", "Top", "Top.v"),
             _stub("top_v_assertthing", "assert_thing", "Top.v")]
    edges = [_inst("top_v_top", "top_v_assertthing", "assert_thing", provisional=True)]

    assert resolve(nodes, edges) == 0
    assert edges == []


def test_provisional_parse_naming_a_real_module_is_kept():
    nodes = [_mod("top_v_top", "Top", "Top.v"),
             _mod("child_v_child", "Child", "Child.v"),
             _stub("top_v_child", "Child", "Top.v")]
    edges = [_inst("top_v_top", "top_v_child", "Child", provisional=True)]

    assert resolve(nodes, edges) == 1
    assert edges[0]["target"] == "child_v_child"


def test_scratch_keys_do_not_leak_into_the_graph():
    nodes = [_mod("top_v_top", "Top", "Top.v"),
             _mod("child_v_child", "Child", "Child.v"),
             _stub("top_v_child", "Child", "Top.v")]
    edges = [_inst("top_v_top", "top_v_child", "Child")]
    resolve(nodes, edges)
    assert "verilog_instantiates" not in edges[0]
    assert "verilog_provisional" not in edges[0]


def test_no_verilog_edges_is_a_no_op():
    nodes = [{"id": "a", "label": "a.py", "source_file": "a.py"}]
    edges = [{"source": "a", "target": "a", "relation": "defines"}]
    assert resolve(nodes, edges) == 0
    assert len(nodes) == 1 and len(edges) == 1

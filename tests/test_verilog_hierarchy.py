"""Cross-file module instantiation resolution for Verilog/SystemVerilog.

Verilog puts one module per file by convention, so a design's hierarchy is almost
entirely cross-file. Extraction is per-file and emits a file-local stub for each
instantiated name; without the resolution pass those stubs never meet their
definitions and the graph is one component per file.

These exercise the pass directly rather than through the parser, so they run whether
or not tree_sitter_verilog is installed.
"""
import pytest

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


def _extract(tmp_path, files):
    """Extract a set of files and run the resolver, as extract() does."""
    import pathlib
    from graphify.extract import extract_verilog
    nodes, edges = [], []
    for name, src in files.items():
        p = pathlib.Path(tmp_path) / name
        p.write_text(src)
        r = extract_verilog(p)
        nodes += r.get("nodes", [])
        edges += r.get("edges", [])
    resolve(nodes, edges)
    return nodes, [e for e in edges if e.get("relation") == "instantiates"]


def test_parameter_override_beats_the_default(tmp_path):
    """A 64-bit default instantiated at 128 is where believing the default is worst."""
    pytest.importorskip("tree_sitter_verilog")
    _, edges = _extract(tmp_path, {
        "Child.v": "module Child #(parameter W = 64) (input [W-1:0] d);\nendmodule\n",
        "Top.v": "module Top (input clk);\n  Child #(.W(128)) u (.d(x));\nendmodule\n",
    })
    assert len(edges) == 1
    assert edges[0]["verilog_conn_bits_max"] == 128        # not 64
    assert edges[0]["verilog_param_overrides"] == {"W": "128"}


def test_positional_connections_map_onto_the_childs_port_order(tmp_path):
    """Positional is only safe because the order comes from the child's own header."""
    pytest.importorskip("tree_sitter_verilog")
    _, edges = _extract(tmp_path, {
        "Child.v": "module Child (input clk, input [63:0] a, output [15:0] b);\nendmodule\n",
        "Top.v": "module Top (input clk);\n  Child u (clk, bus, out);\nendmodule\n",
    })
    assert len(edges) == 1
    assert edges[0]["verilog_conn_positional"] is True
    assert edges[0]["verilog_conn_bits_max"] == 64
    assert edges[0]["verilog_conn_bits_total"] == 1 + 64 + 16

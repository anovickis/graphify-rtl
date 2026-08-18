"""Chisel's hardware hierarchy: `Module(new X)` is containment, not a function call.

A generic Scala parse sees a call to `Module` and a reference to `X`, so the structure
that makes a Chisel file a hardware description is invisible without this.
"""
import pytest

pytest.importorskip("tree_sitter_scala")
pytest.importorskip("tree_sitter")

from pathlib import Path                                            # noqa: E402

from graphify.extract import (                                      # noqa: E402
    extract_scala,
    _resolve_chisel_instantiations as resolve,
)


def _graph(tmp_path, files):
    nodes, edges = [], []
    for name, src in files.items():
        p = Path(tmp_path) / name
        p.write_text(src)
        r = extract_scala(p)
        nodes += r.get("nodes", [])
        edges += r.get("edges", [])
    resolve(nodes, edges)
    by = {n["id"]: n for n in nodes}
    inst = [(by[e["source"]]["label"], by[e["target"]]["label"])
            for e in edges if e.get("relation") == "instantiates"
            and e["source"] in by and e["target"] in by]
    return by, inst, edges


def test_module_and_lazymodule_are_hierarchy(tmp_path):
    _, inst, _ = _graph(tmp_path, {
        "Tile.scala": """
class RocketTile extends BaseTile {
  val core = Module(new RocketCore(p))
  val ic = LazyModule(new ICache(params))
}
""",
    })
    assert ("RocketTile", "RocketCore") in inst
    assert ("RocketTile", "ICache") in inst


def test_instantiation_resolves_to_the_defining_class_in_another_file(tmp_path):
    by, inst, _ = _graph(tmp_path, {
        "Tile.scala": "class RocketTile extends BaseTile {\n  val core = Module(new RocketCore(p))\n}\n",
        "Core.scala": "class RocketCore(p: Parameters) extends CoreModule { }\n",
    })
    src, tgt = next((s, t) for s, t in inst if t == "RocketCore")
    tgt_node = next(n for n in by.values() if n["label"] == "RocketCore")
    assert tgt_node["source_file"].endswith("Core.scala")


def test_companion_factory_is_not_containment(tmp_path):
    """`object X { apply() = Module(new X) }` is Scala's factory idiom. X does not
    contain itself, and counting it would inflate the hierarchy with self-loops."""
    _, inst, _ = _graph(tmp_path, {
        "Clock.scala": """
class ClockGroup(name: String) extends LazyModule { }
object ClockGroup {
  def apply() = LazyModule(new ClockGroup(valName.name)).node
}
""",
    })
    assert ("ClockGroup", "ClockGroup") not in inst


def test_ambiguous_class_name_keeps_the_stub_and_is_marked(tmp_path):
    """Two classes of the same name in different files: picking one would produce a
    hierarchy that looks authoritative and is arbitrary."""
    _, _, edges = _graph(tmp_path, {
        "A.scala": "class Queue(n: Int) { }\n",
        "B.scala": "class Queue(n: Int) { }\n",
        "Top.scala": "class Top { val q = Module(new Queue(4)) }\n",
    })
    e = next(e for e in edges if e.get("relation") == "instantiates")
    assert e.get("chisel_ambiguous") == 2


def _dip(tmp_path, files):
    nodes, edges = [], []
    for name, src in files.items():
        p = Path(tmp_path) / name
        p.write_text(src)
        r = extract_scala(p)
        nodes += r.get("nodes", [])
        edges += r.get("edges", [])
    by = {n["id"]: n for n in nodes}
    return [(by[e["source"]]["label"], e["diplomacy_op"], by[e["target"]]["label"])
            for e in edges if e.get("diplomacy")]


def test_diplomacy_binding_is_extracted_with_dataflow_direction(tmp_path):
    """`a := b` binds b (master) into a (slave), so the edge runs b -> a."""
    dip = _dip(tmp_path, {"Bus.scala": """
class SystemBus extends LazyModule {
  val node = TLAdapterNode()
  val xbar = LazyModule(new TLXbar)
  val buf  = LazyModule(new TLBuffer)
  xbar.node := buf.node
}
"""})
    assert ("TLBuffer", ":=", "TLXbar") in dip


def test_signal_assignment_is_not_interconnect(tmp_path):
    """`:=` is also ordinary Chisel assignment and outnumbers diplomacy ~40:1.
    Counting both would bury the topology in signal assignments."""
    dip = _dip(tmp_path, {"M.scala": """
class M extends Module {
  io.out := reg
  count := count + 1.U
}
"""})
    assert dip == []


def test_starred_operators_always_count(tmp_path):
    dip = _dip(tmp_path, {"Bus.scala": """
class Bus extends LazyModule {
  val node = TLAdapterNode()
  val xbar = LazyModule(new TLXbar)
  node :=* xbar.node
}
"""})
    assert ("TLXbar", ":=*", "Bus") in dip


def test_generic_type_parameters_are_not_modules(tmp_path):
    """Resolving an endpoint to a type parameter produced edges like
    'AXI4Buffer -> S', which look like topology and are noise."""
    dip = _dip(tmp_path, {"G.scala": """
class G[S] extends LazyModule {
  val node = TLAdapterNode()
  val b = LazyModule(new AXI4Buffer)
  S := b.node
}
"""})
    assert all(t != "S" and s != "S" for s, _, t in dip)


def _nodes(tmp_path, files):
    nodes, edges = [], []
    for name, src in files.items():
        p = Path(tmp_path) / name
        p.write_text(src)
        r = extract_scala(p)
        nodes += r.get("nodes", [])
        edges += r.get("edges", [])
    return {n["label"]: n for n in nodes}, nodes, edges


def test_io_bundle_ports_with_directions_and_widths(tmp_path):
    by, _, _ = _nodes(tmp_path, {"Core.scala": """
class Core extends Module {
  val io = IO(new Bundle {
    val clk  = Input(Bool())
    val din  = Input(UInt(64.W))
    val mem  = Flipped(Decoupled(UInt(32.W)))
  })
}
"""})
    ports = {p["name"]: p for p in by["Core"]["chisel_ports"]}
    assert ports["clk"] == {"name": "clk", "dir": "input", "bits": 1}
    assert ports["din"]["bits"] == 64
    assert ports["mem"]["dir"] == "flipped" and ports["mem"]["wrapper"] == "Decoupled"
    assert by["Core"]["chisel_port_summary"]["widest_bits"] == 64


def test_parameterized_chisel_width_is_unknown_not_guessed(tmp_path):
    by, _, _ = _nodes(tmp_path, {"C.scala": """
class C extends Module {
  val io = IO(new Bundle { val dout = Output(UInt(width.W)) })
}
"""})
    assert by["C"]["chisel_ports"][0]["bits"] is None


def test_cross_module_connection_is_dataflow(tmp_path):
    by, _, edges = _nodes(tmp_path, {"Tile.scala": """
class Tile extends Module {
  val core  = Module(new Core)
  val cache = Module(new DCache)
  core.io.mem := cache.io.resp
}
"""})
    df = [(by_id, e) for by_id, e in []]  # noqa: F841
    flows = [(e["source"], e["target"]) for e in edges if e.get("chisel_dataflow")]
    ids = {n["label"]: n["id"] for n in by.values()}
    assert (ids["DCache"], ids["Core"]) in flows      # b drives a in `a := b`


def test_internal_assignment_is_not_dataflow(tmp_path):
    """`io.out := reg` describes logic inside a module, not a relationship between
    modules. ~9,400 such assignments would drown the 163 that mean something."""
    _, _, edges = _nodes(tmp_path, {"M.scala": """
class M extends Module {
  val reg = RegInit(0.U)
  io.out := reg
}
"""})
    assert [e for e in edges if e.get("chisel_dataflow")] == []

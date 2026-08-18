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

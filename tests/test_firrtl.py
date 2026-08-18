"""FIRRTL: the elaborated design.

The only representation in this pipeline where the design is both complete and still
named by the designer -- every instance concrete, every width resolved, and each
construct carrying the Chisel line that produced it.
"""
from pathlib import Path

from graphify.extract import extract_firrtl


def _g(tmp_path, text, name="d.fir"):
    p = Path(tmp_path) / name
    p.write_text(text)
    r = extract_firrtl(p)
    by = {n["id"]: n for n in r["nodes"]}
    return r["nodes"], r["edges"], by


ELAB = """circuit Top :
  module Core :
    input clock : Clock
    output out : UInt<32>
  module Top :
    input clock : Clock
    inst core0 of Core @[Tile.scala 12:20]
    inst core1 of Core @[Tile.scala 13:20]
    inst xbar of Xbar
    xbar.a <= core0.out @[Tile.scala 16:11]
"""


def test_every_instance_is_concrete(tmp_path):
    """Reading the Chisel source gives one Tile.core however many Tiles exist. Here
    they all appear, which is what 'elaborated' means."""
    nodes, _, _ = _g(tmp_path, ELAB)
    insts = {n["label"] for n in nodes if n.get("firrtl_instance_of")}
    assert {"core0: Core", "core1: Core", "xbar: Xbar"} == insts


def test_instance_carries_its_chisel_source_line(tmp_path):
    """Provenance the generated Verilog keeps only as a comment and the Chisel source
    cannot provide at all."""
    nodes, _, _ = _g(tmp_path, ELAB)
    core0 = next(n for n in nodes if n["label"] == "core0: Core")
    assert core0["chisel_source"] == "Tile.scala 12:20"


def test_dataflow_between_instances(tmp_path):
    _, edges, by = _g(tmp_path, ELAB)
    df = [(by[e["source"]]["label"], by[e["target"]]["label"])
          for e in edges if e.get("firrtl_dataflow")]
    assert ("core0: Core", "xbar: Xbar") in df


def test_circuit_and_top_module_sharing_a_name_are_two_nodes(tmp_path):
    """They almost always share a name; colliding on one id silently loses the module."""
    nodes, _, _ = _g(tmp_path, "circuit Top :\n  module Top :\n    input clock : Clock\n")
    assert any(n.get("firrtl_circuit") == "Top" for n in nodes)
    assert any(n.get("firrtl_module") == "Top" for n in nodes)


def test_bundle_ports_are_flattened_and_flip_reverses_direction(tmp_path):
    """Elaborated ports are one big bundle; unflattened, a module has a single port
    called `io` and no visible interface."""
    nodes, _, _ = _g(tmp_path, """circuit M :
  module M :
    output io : {flip req : UInt<8>, resp : UInt<16>}
""")
    ports = {p["name"]: p for p in next(n for n in nodes if n.get("firrtl_module"))["firrtl_ports"]}
    assert ports["io.req"]["dir"] == "input" and ports["io.req"]["bits"] == 8
    assert ports["io.resp"]["dir"] == "output" and ports["io.resp"]["bits"] == 16


def test_inferred_width_is_unknown_not_guessed(tmp_path):
    """A bare `UInt` has its width inferred by the compiler; it is not knowable here."""
    nodes, _, _ = _g(tmp_path, "circuit M :\n  module M :\n    input a : UInt\n")
    ports = next(n for n in nodes if n.get("firrtl_module"))["firrtl_ports"]
    assert ports[0]["bits"] is None


def test_real_firrtl_file_ports(tmp_path):
    """Against a genuine chisel3-emitted file rather than a constructed one."""
    real = Path("/home/alexnovickis/benchlogs/chisel_tests/ProbeUnitFixed.fir")
    if not real.exists():
        return
    r = extract_firrtl(real)
    mod = next(n for n in r["nodes"] if n.get("firrtl_module"))
    assert mod["firrtl_port_summary"]["in"] == 8
    assert mod["firrtl_port_summary"]["out"] == 4

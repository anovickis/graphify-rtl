"""Port extraction: what crosses a module boundary, not just that one exists.

Needs tree_sitter_verilog, so these skip where it is not installed.
"""
import pytest

pytest.importorskip("tree_sitter_verilog")
pytest.importorskip("tree_sitter")

from pathlib import Path                                            # noqa: E402

from graphify.extract import extract_verilog                        # noqa: E402


def _ports(tmp_path, source, name="M.v"):
    p = tmp_path / name
    p.write_text(source)
    for n in extract_verilog(p)["nodes"]:
        if n.get("verilog_ports"):
            return {q["name"]: q for q in n["verilog_ports"]}, n.get("verilog_port_summary")
    return {}, None


def test_direction_and_width(tmp_path):
    ports, summary = _ports(tmp_path, """
module M (input clk, input [63:0] din, output [127:0] dout, inout [7:0] io);
endmodule
""")
    assert ports["clk"]["dir"] == "input" and ports["clk"]["bits"] == 1
    assert ports["din"]["bits"] == 64
    assert ports["dout"]["dir"] == "output" and ports["dout"]["bits"] == 128
    assert ports["io"]["dir"] == "inout" and ports["io"]["bits"] == 8
    assert summary == {"in": 2, "out": 1, "inout": 1, "widest_bits": 128}


def test_direction_and_width_are_sticky(tmp_path):
    """`output [3:0] c, d` declares TWO 4-bit outputs; the header is on the first only."""
    ports, _ = _ports(tmp_path, "module M (input a, b, output [3:0] c, d);\nendmodule\n")
    assert ports["b"]["dir"] == "input" and ports["b"]["bits"] == 1
    assert ports["c"]["bits"] == 4
    assert ports["d"]["dir"] == "output" and ports["d"]["bits"] == 4


def test_parameterised_width_is_unknown_not_guessed(tmp_path):
    """A guessed bit count would be believed. [WIDTH-1:0] is not knowable here."""
    ports, _ = _ports(tmp_path, "module M (input [WIDTH-1:0] p);\nendmodule\n")
    assert ports["p"]["bits"] is None
    assert ports["p"]["range"] == "[WIDTH-1:0]"


def test_ports_are_found_on_a_module_with_a_large_body(tmp_path):
    """Regression: traversal started at module_declaration and queued the whole body
    ahead of the port list, so big modules -- the ones whose interfaces matter most --
    silently reported no ports at all while small ones worked."""
    body = "\n".join(f"  wire w{i} = {i};" for i in range(4000))
    ports, summary = _ports(tmp_path, f"module Big (input clk, output [31:0] o);\n{body}\nendmodule\n")
    assert set(ports) == {"clk", "o"}
    assert summary["widest_bits"] == 32

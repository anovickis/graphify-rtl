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


def test_parameterized_width_is_unknown_not_guessed(tmp_path):
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


def test_verilog95_nonansi_header(tmp_path):
    """Header lists names only; direction and width arrive as separate declarations.
    Reading just the ANSI form reports these modules as having no interface at all,
    which is indistinguishable from a module that genuinely has none."""
    ports, summary = _ports(tmp_path, """
module M (clk, din, dout);
  input        clk;
  input  [7:0] din;
  output [7:0] dout;
endmodule
""")
    assert ports["clk"]["dir"] == "input" and ports["clk"]["bits"] == 1
    assert ports["din"]["bits"] == 8
    assert ports["dout"]["dir"] == "output" and ports["dout"]["bits"] == 8
    assert summary == {"in": 2, "out": 1, "inout": 0, "widest_bits": 8}


def test_nonansi_multiple_identifiers_per_declaration(tmp_path):
    ports, _ = _ports(tmp_path, """
module M (a, b, c);
  input  [3:0] a, b;
  output       c;
endmodule
""")
    assert ports["a"]["bits"] == 4 and ports["b"]["bits"] == 4
    assert ports["c"]["dir"] == "output"


def test_parameter_resolves_a_width_and_records_that_it_did(tmp_path):
    """`[WIDTH-1:0]` is knowable once the parameter is read -- but from its DEFAULT, and
    an instantiation may override it, so the source of the number is recorded."""
    ports, summary = _ports(tmp_path, """
module M #(parameter WIDTH = 64, parameter DEPTH = 8) (
  input  [WIDTH-1:0]   din,
  output [DEPTH*2-1:0] cnt
);
endmodule
""")
    assert ports["din"]["bits"] == 64
    assert ports["din"]["bits_from"] == "parameter-default"
    assert ports["cnt"]["bits"] == 16          # 8*2
    assert summary["widest_bits"] == 64


def test_literal_width_is_not_labelled_as_parameter_derived(tmp_path):
    ports, _ = _ports(tmp_path, "module M (input [7:0] a);\nendmodule\n")
    assert ports["a"]["bits"] == 8
    assert "bits_from" not in ports["a"]


def test_body_parameters_are_read_too(tmp_path):
    ports, _ = _ports(tmp_path, """
module M (a);
  parameter W = 12;
  input [W-1:0] a;
endmodule
""")
    assert ports["a"]["bits"] == 12


def test_unresolvable_width_stays_unknown(tmp_path):
    """A width depending on something not in scope, or on a function call, must not be
    guessed -- a wrong number here would be read as a measurement."""
    ports, _ = _ports(tmp_path, "module M (input [$clog2(N)-1:0] a);\nendmodule\n")
    assert ports["a"]["bits"] is None

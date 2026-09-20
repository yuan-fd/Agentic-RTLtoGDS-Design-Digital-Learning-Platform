"""Frozen teaching oracles for the first two M1 exercises."""

from __future__ import annotations


COUNTER_ORACLE = r'''module counter_tb;
  logic clk = 0;
  logic rst_n = 0;
  logic enable = 0;
  logic [7:0] q;
  integer i;

  counter dut(.clk(clk), .rst_n(rst_n), .enable(enable), .q(q));
  always #1 clk = ~clk;

  task automatic tick;
    begin @(negedge clk); end
  endtask

  initial begin
    tick;
    if (q !== 8'h00) $fatal(1, "reset mismatch");
    rst_n = 1;
    tick;
    if (q !== 8'h00) $fatal(1, "disabled counter changed");
    enable = 1;
    tick;
    if (q !== 8'h01) $fatal(1, "first increment mismatch");
    tick;
    if (q !== 8'h02) $fatal(1, "second increment mismatch");
    enable = 0;
    tick;
    if (q !== 8'h02) $fatal(1, "hold mismatch");
    enable = 1;
    for (i = 0; i < 253; i = i + 1) tick;
    if (q !== 8'hff) $fatal(1, "overflow precondition mismatch");
    tick;
    if (q !== 8'h00) $fatal(1, "overflow mismatch");
    rst_n = 0;
    enable = 0;
    tick;
    if (q !== 8'h00) $fatal(1, "reset priority mismatch");
    $display("TB_SUMMARY total=12 errors=0");
    $display("PASS");
    $finish;
  end
endmodule
'''


SEQUENCE_DETECTOR_ORACLE = r'''module sequence_detector_tb;
  logic clk = 0;
  logic rst_n = 0;
  logic din = 0;
  logic hit;

  sequence_detector dut(.clk(clk), .rst_n(rst_n), .din(din), .hit(hit));
  always #1 clk = ~clk;

  task automatic tick(input logic value, input logic expected);
    begin
      din = value;
      @(negedge clk);
      if (hit !== expected) $fatal(1, "sequence mismatch");
    end
  endtask

  initial begin
    @(negedge clk);
    if (hit !== 1'b0) $fatal(1, "reset mismatch");
    rst_n = 1;
    tick(1'b0, 1'b0);
    tick(1'b1, 1'b0);
    tick(1'b0, 1'b0);
    tick(1'b1, 1'b1);
    tick(1'b1, 1'b0);
    tick(1'b0, 1'b0);
    tick(1'b1, 1'b1);
    tick(1'b0, 1'b0);
    tick(1'b0, 1'b0);
    tick(1'b1, 1'b0);
    $display("TB_SUMMARY total=10 errors=0");
    $display("PASS");
    $finish;
  end
endmodule
'''


def oracle_for_top(top: str) -> tuple[str, str, str] | None:
    if top == "counter":
        return "counter-v2", COUNTER_ORACLE, "counter_tb"
    if top == "sequence_detector":
        return "sequence-detector-v2", SEQUENCE_DETECTOR_ORACLE, "sequence_detector_tb"
    return None

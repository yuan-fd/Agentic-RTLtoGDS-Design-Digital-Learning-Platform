// Deliberate platform-owned cross-stage recovery fault.
// Functional tools see the correct adder. Synthesis sees an unresolved
// physical cell, exercising backend-to-RTL rollback without changing the
// frozen testbench, ORFS configuration, PDK, evaluator, or clean checkpoint.
module native_adder8 (
  input  logic [7:0] a,
  input  logic [7:0] b,
  output logic [7:0] sum
);
`ifdef SYNTHESIS
  closer_recovery_missing_cell u_missing (
    .a(a),
    .b(b),
    .y(sum)
  );
`else
  always_comb sum = a + b;
`endif
endmodule

(* blackbox *)
module closer_recovery_missing_cell (
  input  logic [7:0] a,
  input  logic [7:0] b,
  output logic [7:0] y
);
endmodule

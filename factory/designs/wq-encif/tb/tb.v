// WQ-ENCIF 测试平台：逐拍读激励（stim.hex），每个时钟上升沿后写出计数、Z 位置、状态、MISO（trace.txt），
// 由 run.py 与 Python 参考模型逐拍比对；同时写 VCD 波形给网页看。示例设计，未流片。
`timescale 1ns/1ps
module tb;
    reg clk = 0;
    reg [6:0] w;
    reg [6:0] mem [0:200000];
    integer n, i, f;
    wire miso;
    wq_encif dut (.clk(clk), .rst_n(w[6]), .enc_a(w[0]), .enc_b(w[1]), .enc_z(w[2]),
                  .sclk(w[3]), .cs_n(w[4]), .mosi(w[5]), .miso(miso));
    wire [5:0] status = {dut.fz, dut.fb, dut.fa, dut.ivld, dut.err, dut.dir};
    initial begin
        if (!$value$plusargs("n=%d", n)) n = 0;
        $readmemh("stim.hex", mem);
        f = $fopen("trace.txt", "w");
        $dumpfile("wave.vcd");
        $dumpvars(0, tb.w, tb.miso, dut.fa, dut.fb, dut.fz, dut.cnt, dut.idx, dut.dir, dut.err, dut.ivld, dut.bits);
        w = mem[0];
        for (i = 0; i < n; i = i + 1) begin
            w = mem[i];
            #10 clk = 1;
            #1 $fdisplay(f, "%08x %08x %02x %0d", dut.cnt, dut.idx, status, miso);
            #9 clk = 0;
        end
        $fclose(f);
        $finish;
    end
endmodule

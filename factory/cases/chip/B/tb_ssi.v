// WQ-SSI 测试平台：编码器（SSI 从机）行为模型 + 线缆往返延迟；读一串位置，打印每帧结果给 Python 核对
`timescale 1ns/1ps
module tb;
    parameter BITS = 17;
    parameter DELAY_NS = 0;        // 线缆往返延迟（时钟去 + 数据回）
    parameter NPOS = 8;
    reg clk = 0, rst_n = 0, start = 0;
    always #10 clk = ~clk;         // 50 MHz
    wire sclk, valid, perr, busy;
    wire [BITS-1:0] pos;
    reg  sdo = 1'b1;               // 编码器输出（空闲为高）
    wire sdi;
    assign #(DELAY_NS) sdi = sdo;
    wire sclk_far;
    assign sclk_far = sclk;        // 延迟全部记在数据回程上（往返合计）
    wq_ssi #(.BITS(BITS)) dut(.clk(clk), .rst_n(rst_n), .start(start), .sdi(sdi), .sclk(sclk), .pos(pos), .valid(valid), .perr(perr), .busy(busy));

    // 编码器从机：第一个下降沿锁存位置（转格雷码、算偶校验），之后每个上升沿送一位（高位先）
    reg [BITS:0] frame; integer k; reg latched = 0;
    reg [BITS-1:0] P [0:NPOS-1];
    integer idx = 0;
    string fn;
    function [BITS-1:0] b2g(input [BITS-1:0] b); b2g = b ^ (b >> 1); endfunction
    always @(negedge sclk_far) if (!latched) begin
        frame = {b2g(P[idx]), ^b2g(P[idx])};
        k = BITS; latched = 1;
    end
    always @(posedge sclk_far) if (latched) begin
        if (k >= 0) begin sdo <= frame[k]; k = k - 1; end
    end
    always @(posedge clk) if (valid) begin
        $display("FRAME %0d %0d %0d %0d", idx, P[idx], pos, perr);
        idx = idx + 1; latched = 0; sdo <= 1'b1;
    end
    initial begin
        if (!$value$plusargs("pos=%s", fn)) fn = "pos.hex";
        $readmemh(fn, P);
        #100 rst_n = 1;
        repeat (NPOS) begin
            @(posedge clk); start = 1; @(posedge clk); start = 0;
            @(negedge busy);
        end
        $display("DONE");
        $finish;
    end
endmodule

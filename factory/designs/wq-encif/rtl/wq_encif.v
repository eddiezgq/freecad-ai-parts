// WQ-ENCIF 编码器接口芯片（问渠数字工业园 · 第 92 轮 电子 E5）
// Incremental encoder interface: A/B/Z filter -> x4 quadrature decode -> 32-bit counter -> SPI slave (mode 0)
// 示例设计，未流片，未经硅验证 / Teaching example: not taped out, not silicon-verified.
//
// 时钟 clk 50 MHz；所有输入先过两级同步器；SPI 的 SCLK 由 clk 过采样，要求 SCLK <= clk/10。
// 寄存器（地址 7 位，数据 32 位）：
//   0x00 ID      只读  0x454E4331（"ENC1"）
//   0x01 CTRL    读写  [0] 计数使能（复位 1）[1] 方向取反 [2] Z 相清零 [7:4] 滤波长度 N（复位 3）
//   0x02 STATUS  读 / 写 1 清除  [0] 最近方向（1 = 正转）[1] 丢步（A、B 同时跳变，粘住）[2] 已锁存 Z 位置（粘住）
//                [3] A [4] B [5] Z（滤波后）
//   0x03 COUNT   读写  32 位有符号计数（写入 = 置数）
//   0x04 INDEX   只读  Z 相上升沿时的计数
// 上电 / 复位后先“对齐”：同步器填满、滤波后的 A、B 等于输入之后才开始解码（不会因为编码器停在非 00 位置误报丢步或多计一步）。
// SPI 帧：CS 拉低 → 8 位命令（[7] 1 = 写，[6:0] 地址）→ 32 位数据，高位先出；读的数据在命令收齐时取快照。
`timescale 1ns/1ps
`default_nettype none

module wq_encif (
    input  wire clk,
    input  wire rst_n,
    input  wire enc_a,
    input  wire enc_b,
    input  wire enc_z,
    input  wire sclk,
    input  wire cs_n,
    input  wire mosi,
    output wire miso
);
    localparam [31:0] ID = 32'h454E4331;

    // ---------------------------------------------------------------- 同步器
    reg [1:0] sa, sb, sz, ssck, scs, smo;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin
            sa <= 2'b00; sb <= 2'b00; sz <= 2'b00; ssck <= 2'b00; scs <= 2'b11; smo <= 2'b00;
        end else begin
            sa <= {sa[0], enc_a}; sb <= {sb[0], enc_b}; sz <= {sz[0], enc_z};
            ssck <= {ssck[0], sclk}; scs <= {scs[0], cs_n}; smo <= {smo[0], mosi};
        end

    // ---------------------------------------------------------------- 寄存器
    reg        en, inv, zclr;
    reg [3:0]  flen;
    reg        dir, err, ivld;
    reg [31:0] cnt, idx;

    // ---------------------------------------------------------------- 一致性滤波：输入与输出不同且已连续 N+1 拍，输出才跟过去
    reg       fa, fb, fz;
    reg [3:0] ca, cb, cz;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin
            fa <= 1'b0; fb <= 1'b0; fz <= 1'b0; ca <= 4'd0; cb <= 4'd0; cz <= 4'd0;
        end else begin
            if (sa[1] != fa) begin if (ca >= flen) begin fa <= sa[1]; ca <= 4'd0; end else ca <= ca + 4'd1; end else ca <= 4'd0;
            if (sb[1] != fb) begin if (cb >= flen) begin fb <= sb[1]; cb <= 4'd0; end else cb <= cb + 4'd1; end else cb <= 4'd0;
            if (sz[1] != fz) begin if (cz >= flen) begin fz <= sz[1]; cz <= 4'd0; end else cz <= cz + 4'd1; end else cz <= 4'd0;
        end

    // ---------------------------------------------------------------- 4 倍频正交解码（A 超前 B 为正：00→10→11→01→00）
    reg pa, pb, pz;
    reg [1:0] boot;                             // 复位后的同步器填充拍数
    reg armed;                                  // 已对齐，开始解码
    wire da = armed & (fa ^ pa), db = armed & (fb ^ pb);
    wire step = da ^ db;                        // 恰好一相跳变：走一步
    wire fwd0 = step & ((da & (fa ^ fb)) | (db & ~(fa ^ fb)));
    wire fwd = fwd0 ^ inv;
    wire zrise = armed & fz & ~pz;

    // ---------------------------------------------------------------- SPI 从机
    reg [5:0]  bits;                            // 已收到的 SCLK 上升沿个数（0–40）
    reg [7:0]  cmd;
    reg [31:0] sh;                              // 读：移出；写：移入
    wire sck_r = ~ssck[1] & ssck[0];            // 同步后 SCLK 上升沿（下一拍 ssck[1] 才变）
    wire sck_f = ssck[1] & ~ssck[0];
    wire sel = ~scs[1];
    wire [7:0] cmd_n = {cmd[6:0], smo[1]};
    wire wr_done = sel & sck_r & (bits == 6'd39) & cmd[7];
    wire [31:0] wdata = {sh[30:0], smo[1]};

    function [31:0] rd;
        input [6:0] a;
        case (a)
            7'h00: rd = ID;
            7'h01: rd = {24'd0, flen, 1'b0, zclr, inv, en};
            7'h02: rd = {26'd0, fz, fb, fa, ivld, err, dir};
            7'h03: rd = cnt;
            7'h04: rd = idx;
            default: rd = 32'd0;
        endcase
    endfunction

    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin
            bits <= 6'd0; cmd <= 8'd0; sh <= 32'd0;
        end else if (!sel) begin
            bits <= 6'd0; cmd <= 8'd0; sh <= 32'd0;
        end else begin
            if (sck_r && bits < 6'd40) begin
                bits <= bits + 6'd1;
                if (bits < 6'd8) begin
                    cmd <= cmd_n;
                    if (bits == 6'd7) sh <= cmd_n[7] ? 32'd0 : rd(cmd_n[6:0]);
                end else if (cmd[7]) sh <= wdata;
            end
            if (sck_f && !cmd[7] && bits > 6'd8 && bits < 6'd40) sh <= {sh[30:0], 1'b0};
        end
    assign miso = sel & (bits >= 6'd8) & ~cmd[7] & sh[31];

    // ---------------------------------------------------------------- 计数、状态（SPI 写入优先于计数）
    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin
            en <= 1'b1; inv <= 1'b0; zclr <= 1'b0; flen <= 4'd3;
            dir <= 1'b1; err <= 1'b0; ivld <= 1'b0; cnt <= 32'd0; idx <= 32'd0;
            pa <= 1'b0; pb <= 1'b0; pz <= 1'b0; boot <= 2'd0; armed <= 1'b0;
        end else begin
            pa <= fa; pb <= fb; pz <= fz;
            if (boot != 2'd3) boot <= boot + 2'd1;
            else if (!armed && fa == sa[1] && fb == sb[1] && fz == sz[1]) armed <= 1'b1;
            if (en && step) begin
                cnt <= cnt + (fwd ? 32'd1 : 32'hFFFFFFFF);   // 一个加法器加 ±1（比“加一、减一再选”路径短）
                dir <= fwd;
            end
            if (en && da && db) err <= 1'b1;
            if (zrise) begin
                idx <= cnt; ivld <= 1'b1;
                if (zclr && en) cnt <= 32'd0;
            end
            if (wr_done) case (cmd[6:0])
                7'h01: begin en <= wdata[0]; inv <= wdata[1]; zclr <= wdata[2]; flen <= wdata[7:4]; end
                7'h02: begin if (wdata[1]) err <= 1'b0; if (wdata[2]) ivld <= 1'b0; end
                7'h03: cnt <= wdata;
                default: ;
            endcase
        end
endmodule

`default_nettype wire

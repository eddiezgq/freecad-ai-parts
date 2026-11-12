// WQ-SSI：SSI 绝对值编码器读取模块（问渠第 161g 轮，芯片厂案例 B；示例设计，未流片）
// SSI master: clock burst of BITS+1 cycles, slave shifts MSB first on rising edges, sampled on falling edges;
// Gray -> binary, even parity check, monoflop wait between frames. clk 50 MHz.
module wq_ssi #(
    parameter BITS = 17,          // 位置位数（格雷码）
    parameter HALF = 25,          // SSI 时钟半周期 = HALF 个 clk（50 MHz / 50 = 1 MHz）
    parameter TM   = 1000         // 帧间等待 = TM 个 clk（20 us，等编码器单稳态恢复）
) (
    input  wire            clk,
    input  wire            rst_n,
    input  wire            start,     // 拉高一拍：读一帧
    input  wire            sdi,       // 编码器数据线（已经过线接收器、同步器之前）
    output reg             sclk,      // 给编码器的时钟，空闲为高
    output reg  [BITS-1:0] pos,       // 二进制位置
    output reg             valid,     // 一帧读完拉高一拍
    output reg             perr,      // 偶校验错
    output wire            busy
);
    localparam IDLE = 2'd0, SHIFT = 2'd1, WAIT = 2'd2;
    reg [1:0]  st;
    reg [15:0] cnt;                    // 半周期 / 等待计数
    reg [5:0]  nb;                     // 已采到的位数
    reg [BITS:0] sh;                   // BITS 位位置 + 1 位校验
    reg [1:0]  sy;                     // sdi 两级同步
    assign busy = (st != IDLE);

    // 格雷码 → 二进制
    function [BITS-1:0] g2b(input [BITS-1:0] g);
        integer i;
        begin
            g2b[BITS-1] = g[BITS-1];
            for (i = BITS - 2; i >= 0; i = i - 1) g2b[i] = g2b[i+1] ^ g[i];
        end
    endfunction

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st <= IDLE; cnt <= 0; nb <= 0; sh <= 0; sy <= 2'b11;
            sclk <= 1'b1; pos <= 0; valid <= 1'b0; perr <= 1'b0;
        end else begin
            sy <= {sy[0], sdi};
            valid <= 1'b0;
            case (st)
            IDLE: if (start) begin st <= SHIFT; cnt <= 0; nb <= 0; sclk <= 1'b0; end
            SHIFT: begin
                if (cnt == HALF - 1) begin
                    cnt <= 0;
                    if (sclk == 1'b0) sclk <= 1'b1;            // 上升沿：编码器送出下一位
                    else begin                                  // 下降沿前一拍采样（数据已稳定半个周期）
                        sh <= {sh[BITS-1:0], sy[1]};
                        nb <= nb + 1'b1;
                        if (nb == BITS) begin                    // 第一个下降沿是“锁存”；采满 BITS+1 位（位置 + 校验）就停
                            st <= WAIT; sclk <= 1'b1;
                        end else sclk <= 1'b0;
                    end
                end else cnt <= cnt + 1'b1;
            end
            WAIT: begin
                if (cnt == 1) begin
                    pos   <= g2b(sh[BITS:1]);
                    perr  <= ^sh;                               // 偶校验：位置 + 校验位 1 的个数为偶
                    valid <= 1'b1;
                end
                if (cnt == TM - 1) begin st <= IDLE; cnt <= 0; end
                else cnt <= cnt + 1'b1;
            end
            default: st <= IDLE;
            endcase
        end
    end
endmodule

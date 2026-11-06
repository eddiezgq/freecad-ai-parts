/* 启动代码：向量表、复制 .data、清零 .bss、进 main（第 102 轮：外设中断向量；复位后第一件事打开 FPU）。 */
#include <stdint.h>

extern uint32_t _estack, _sidata, _sdata, _edata, _sbss, _ebss;
int main(void);
void ADC1_2_IRQHandler(void);
void FDCAN1_IT0_IRQHandler(void);

void Reset_Handler(void)
{
    *(volatile uint32_t *)0xE000ED88u |= 0xFu << 20;   /* SCB_CPACR：先打开 FPU，之后的代码可能用浮点寄存器 */
    __asm volatile("dsb\n isb");
    uint32_t *s = &_sidata, *d = &_sdata;
    while (d < &_edata) {
        *d++ = *s++;
    }
    for (d = &_sbss; d < &_ebss;) {
        *d++ = 0;
    }
    main();
    for (;;) {
    }
}

void Default_Handler(void)
{
    for (;;) {
    }
}

/* 向量表：16 个内核异常 + 外设中断（STM32G431：ADC1_2 = 18、FDCAN1_IT0 = 21，其余不用） */
#define D Default_Handler
__attribute__((section(".isr_vector"), used)) const void *const vectors[16 + 26] = {
    &_estack, Reset_Handler, D, D, D, D, D, 0, 0, 0, 0, D, D, 0, D, D,   /* SP、复位、NMI、HardFault…SysTick */
    D, D, D, D, D, D, D, D, D, D, D, D, D, D, D, D, D, D,                /* 外设中断 0–17 */
    ADC1_2_IRQHandler, D, D, FDCAN1_IT0_IRQHandler, D, D, D, D,          /* 18–25 */
};

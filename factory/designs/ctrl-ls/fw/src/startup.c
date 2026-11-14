/* 启动代码：向量表、复制 .data、清零 .bss、进 main（同驱动板 B 版；本板只用 ADC1_2 中断）。 */
#include <stdint.h>

extern uint32_t _estack, _sidata, _sdata, _edata, _sbss, _ebss;
int main(void);
void ADC1_2_IRQHandler(void);

void Reset_Handler(void)
{
    *(volatile uint32_t *)0xE000ED88u |= 0xFu << 20;   /* SCB_CPACR：先打开 FPU */
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

/* 向量表：16 个内核异常 + 外设中断（STM32G431：ADC1_2 = 18，其余不用） */
#define D Default_Handler
__attribute__((section(".isr_vector"), used)) const void *const vectors[16 + 19] = {
    &_estack, Reset_Handler, D, D, D, D, D, 0, 0, 0, 0, D, D, 0, D, D,   /* SP、复位、NMI、HardFault…SysTick */
    D, D, D, D, D, D, D, D, D, D, D, D, D, D, D, D, D, D,                /* 外设中断 0–17 */
    ADC1_2_IRQHandler,                                                   /* 18 */
};

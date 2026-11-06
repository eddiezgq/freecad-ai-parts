/* 启动代码：向量表、复制 .data、清零 .bss、进 main。 */
#include <stdint.h>

extern uint32_t _estack, _sidata, _sdata, _edata, _sbss, _ebss;
int main(void);
void SysTick_Handler(void);

void Reset_Handler(void)
{
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

__attribute__((section(".isr_vector"), used)) const void *const vectors[16] = {
    &_estack, Reset_Handler, Default_Handler, Default_Handler,   /* SP、复位、NMI、HardFault */
    Default_Handler, Default_Handler, Default_Handler, 0, 0, 0, 0,
    Default_Handler, Default_Handler, 0, Default_Handler,        /* SVC、调试、保留、PendSV */
    SysTick_Handler,
};

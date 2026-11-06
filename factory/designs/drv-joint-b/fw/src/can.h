#ifndef CAN_H
#define CAN_H
#include <stdint.h>

void can_init(void);
void can_send(uint16_t id, const uint8_t *data, uint8_t len);
void can_rx_handler(uint16_t id, const uint8_t *data, uint8_t len);   /* main.c 里实现 */

#endif

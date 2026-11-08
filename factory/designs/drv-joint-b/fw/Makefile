# 驱动板 B 版示例固件（第 100 轮；第 102 轮加电机控制与 CAN；第 110 轮加抱闸；第 115 轮节点号可编译时给）。需要 arm-none-eabi-gcc。
CC = arm-none-eabi-gcc
CFLAGS = -mcpu=cortex-m4 -mthumb -mfloat-abi=hard -mfpu=fpv4-sp-d16 -Os -g -Wall -Wextra -Werror -ffunction-sections -fdata-sections -ffreestanding -ffile-prefix-map=$(CURDIR)=.
LDFLAGS = -nostdlib -T src/stm32g431.ld -Wl,--gc-sections
SRC = src/startup.c src/clock.c src/encif.c src/ssi.c src/brake.c src/motor.c src/can.c src/main.c

build/fw.elf: $(SRC) src/*.h src/stm32g431.ld
	mkdir -p build
	$(CC) $(CFLAGS) $(SRC) $(LDFLAGS) -Wl,-Map=build/fw.map -o $@
	arm-none-eabi-objcopy -O binary $@ build/fw.bin
	arm-none-eabi-size $@

# 第 115 轮：多关节——同一份固件按节点号再编一份（CAN ID = 基址 + 节点号）
build/fw-node%.elf: $(SRC) src/*.h src/stm32g431.ld
	mkdir -p build
	$(CC) $(CFLAGS) -DNODE=$* $(SRC) $(LDFLAGS) -o $@

clean:
	rm -rf build

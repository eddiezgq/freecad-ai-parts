# 驱动板 B 版示例固件（第 100 轮）。需要 arm-none-eabi-gcc。
CC = arm-none-eabi-gcc
CFLAGS = -mcpu=cortex-m4 -mthumb -mfloat-abi=soft -Os -g -Wall -Wextra -Werror -ffunction-sections -fdata-sections -ffreestanding -ffile-prefix-map=$(CURDIR)=.
LDFLAGS = -nostdlib -T src/stm32g431.ld -Wl,--gc-sections -Wl,-Map=build/fw.map
SRC = src/startup.c src/encif.c src/main.c

build/fw.elf: $(SRC) src/*.h src/stm32g431.ld
	mkdir -p build
	$(CC) $(CFLAGS) $(SRC) $(LDFLAGS) -o $@
	arm-none-eabi-objcopy -O binary $@ build/fw.bin
	arm-none-eabi-size $@

clean:
	rm -rf build

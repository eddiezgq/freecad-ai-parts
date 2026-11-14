# 平缝机控制器 CTRL-LS 示例固件（第 159 轮 159f）。需要 arm-none-eabi-gcc。编译选项同驱动板 B 版（警告当错误）。
CC = arm-none-eabi-gcc
CFLAGS = -mcpu=cortex-m4 -mthumb -mfloat-abi=hard -mfpu=fpv4-sp-d16 -Os -g -Wall -Wextra -Werror -ffunction-sections -fdata-sections -ffreestanding -ffile-prefix-map=$(CURDIR)=.
LDFLAGS = -nostdlib -T src/stm32g431.ld -Wl,--gc-sections
SRC = src/startup.c src/clock.c src/motor.c src/sew.c src/main.c

build/fw.elf: $(SRC) src/*.h src/stm32g431.ld
	mkdir -p build
	$(CC) $(CFLAGS) $(SRC) $(LDFLAGS) -Wl,-Map=build/fw.map -o $@
	arm-none-eabi-objcopy -O binary $@ build/fw.bin
	arm-none-eabi-size $@

clean:
	rm -rf build

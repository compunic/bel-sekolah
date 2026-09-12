import time

class I2cLcd:
    def __init__(self, i2c, i2c_addr, num_lines, num_columns):
        self.i2c = i2c
        self.i2c_addr = i2c_addr
        self.num_lines = num_lines
        self.num_columns = num_columns
        self.backlight = 0x08
        time.sleep_ms(20)
        self._write_command(0x03)
        self._write_command(0x03)
        self._write_command(0x03)
        self._write_command(0x02)
        self._write_command(0x28)
        self._write_command(0x0C)
        self._write_command(0x06)
        self.clear()

    def _write_nibble(self, nibble):
        self.i2c.writeto(self.i2c_addr, bytes([nibble | self.backlight]))
        self.i2c.writeto(self.i2c_addr, bytes([nibble | 0x04 | self.backlight]))
        time.sleep_us(1)
        self.i2c.writeto(self.i2c_addr, bytes([(nibble & ~0x04) | self.backlight]))
        time.sleep_us(50)

    def _write_byte(self, cmd, mode=0):
        high = mode | (cmd & 0xF0)
        low = mode | ((cmd << 4) & 0xF0)
        self._write_nibble(high)
        self._write_nibble(low)

    def _write_command(self, cmd):
        self._write_byte(cmd, 0)

    def write_char(self, char):
        self._write_byte(ord(char), 1)

    def clear(self):
        self._write_command(0x01)
        time.sleep_ms(2)

    def move_to(self, cursor_x, cursor_y):
        offsets = [0x00, 0x40, 0x14, 0x54]
        self._write_command(0x80 | (offsets[cursor_y] + cursor_x))

    def putstr(self, string):
        for char in string:
            self.write_char(char)
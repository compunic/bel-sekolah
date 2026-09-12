import machine

class DS3231:
    def __init__(self, i2c, addr=0x68):
        self.i2c = i2c
        self.addr = addr

    def _bcd2dec(self, bcd):
        return (bcd // 16 * 10) + (bcd % 16)

    def get_time(self):
        data = self.i2c.readfrom_mem(self.addr, 0x00, 7)
        sec = self._bcd2dec(data[0] & 0x7F)
        minute = self._bcd2dec(data[1])
        hour = self._bcd2dec(data[2] & 0x3F)
        day_of_week = self._bcd2dec(data[3])
        day = self._bcd2dec(data[4])
        month = self._bcd2dec(data[5] & 0x1F)
        year = self._bcd2dec(data[6]) + 2000
        return (year, month, day, hour, minute, sec, day_of_week)
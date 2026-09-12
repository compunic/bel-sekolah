# ============================================================
# SISTEM BEL SEKOLAH - ESP32
# ============================================================
#
# Fitur:
# - DS3231 RTC
# - LCD 16x2 I2C
# - DFPlayer Mini
# - Jadwal tersimpan lokal di jadwal.json
# - Backup jadwal.bak
# - Sinkronisasi jadwal dari Flask
# - Sinkronisasi waktu dari Flask
# - Tetap bekerja saat WiFi/Flask mati
# - Anti bel berbunyi berulang
# - Status ESP32 dikirim ke Flask
# - Test bel dari Flask
# - Penghematan RAM
#
# Koneksi:
#
# DS3231:
#   SDA -> GPIO21
#   SCL -> GPIO22
#
# LCD 16x2:
#   SDA -> GPIO18
#   SCL -> GPIO19
#
# DFPlayer:
#   TX -> GPIO16 ESP32
#   RX -> GPIO17 ESP32
#
# ============================================================


from machine import Pin, I2C, UART
import time
import network
import gc
import ujson
import os


# ============================================================
# KONFIGURASI
# ============================================================

WIFI_SSID = "WIFI"
WIFI_PASSWORD = ""

# IP komputer/server Flask
FLASK_IP = "172.16.10.200"
FLASK_PORT = 5000

API_CONFIG = "http://{}:{}/api/esp32/config".format(
    FLASK_IP,
    FLASK_PORT
)

API_JADWAL = "http://{}:{}/api/esp32/jadwal".format(
    FLASK_IP,
    FLASK_PORT
)

API_WAKTU = "http://{}:{}/api/esp32/time".format(
    FLASK_IP,
    FLASK_PORT
)

API_STATUS = "http://{}:{}/api/esp32/status".format(
    FLASK_IP,
    FLASK_PORT
)

API_TEST = "http://{}:{}/api/esp32/test".format(
    FLASK_IP,
    FLASK_PORT
)


# ============================================================
# INTERVAL
# ============================================================

# Cek konfigurasi Flask
SYNC_INTERVAL = 60000

# Sinkronisasi waktu setiap 6 jam
TIME_SYNC_INTERVAL = 21600000

# Kirim status setiap 10 detik
STATUS_INTERVAL = 10000

# Cek test bell setiap 10 detik
TEST_INTERVAL = 10000


# ============================================================
# FILE
# ============================================================

JADWAL_FILE = "jadwal.json"
JADWAL_TMP = "jadwal.tmp"
JADWAL_BAK = "jadwal.bak"


# ============================================================
# DEFAULT
# ============================================================

DEFAULT_VOLUME = 25
DEFAULT_DURATION = 5


# ============================================================
# I2C RTC
# SDA = GPIO21
# SCL = GPIO22
# ============================================================

i2c_rtc = I2C(
    0,
    scl=Pin(22),
    sda=Pin(21),
    freq=100000
)

RTC_ADDR = 0x68


# ============================================================
# I2C LCD
# SDA = GPIO18
# SCL = GPIO19
# ============================================================

i2c_lcd = I2C(
    1,
    scl=Pin(19),
    sda=Pin(18),
    freq=100000
)

LCD_ADDR = 0x27

# Jika LCD Anda menggunakan 0x3F:
# LCD_ADDR = 0x3F

LCD_BACKLIGHT = 0x08
LCD_ENABLE = 0x04
LCD_RS = 0x01


# ============================================================
# DFPLAYER
#
# ESP32 TX GPIO17 -> RX DFPlayer
# ESP32 RX GPIO16 <- TX DFPlayer
# ============================================================

dfplayer = UART(
    2,
    baudrate=9600,
    tx=Pin(17),
    rx=Pin(16)
)


# ============================================================
# DATA GLOBAL
# ============================================================

jadwal = []

schedule_version = 0

device_volume = DEFAULT_VOLUME

wifi = network.WLAN(
    network.STA_IF
)

wifi.active(True)


# ============================================================
# LCD LOW LEVEL
# ============================================================

def lcd_write(data):

    i2c_lcd.writeto(
        LCD_ADDR,
        bytes([data | LCD_BACKLIGHT])
    )


def lcd_pulse(data):

    lcd_write(
        data | LCD_ENABLE
    )

    time.sleep_us(300)

    lcd_write(
        data & ~LCD_ENABLE
    )

    time.sleep_us(300)


def lcd_send(value, mode=0):

    high = value & 0xF0

    low = (value << 4) & 0xF0

    lcd_pulse(
        high | mode
    )

    lcd_pulse(
        low | mode
    )


def lcd_command(command):

    lcd_send(command)


def lcd_data(data):

    lcd_send(
        data,
        LCD_RS
    )


def lcd_clear():

    lcd_command(0x01)

    time.sleep_ms(2)


def lcd_set_cursor(col, row):

    if row == 0:
        address = 0x80 + col
    else:
        address = 0xC0 + col

    lcd_command(address)


def lcd_print(text):

    # Pastikan selalu string
    text = str(text)

    # Maksimal 16 karakter
    text = text[:16]

    # Isi sampai 16 karakter
    while len(text) < 16:
        text += " "

    for char in text:
        lcd_data(
            ord(char)
        )


def lcd_init():

    time.sleep_ms(50)

    lcd_pulse(0x30)

    time.sleep_ms(5)

    lcd_pulse(0x30)

    time.sleep_us(150)

    lcd_pulse(0x30)

    lcd_pulse(0x20)

    lcd_command(0x28)

    lcd_command(0x0C)

    lcd_command(0x06)

    lcd_clear()


# ============================================================
# RTC DS3231
# ============================================================

def bcd_to_dec(value):

    return (
        ((value >> 4) * 10)
        + (value & 0x0F)
    )


def dec_to_bcd(value):

    return (
        ((value // 10) << 4)
        | (value % 10)
    )


def read_rtc():

    data = i2c_rtc.readfrom_mem(
        RTC_ADDR,
        0x00,
        7
    )

    second = bcd_to_dec(
        data[0] & 0x7F
    )

    minute = bcd_to_dec(
        data[1] & 0x7F
    )

    hour = bcd_to_dec(
        data[2] & 0x3F
    )

    # DS3231:
    # 1 = Minggu
    # 2 = Senin
    # ...
    # 7 = Sabtu
    #
    # Sistem:
    # 1 = Senin
    # ...
    # 7 = Minggu

    ds_weekday = data[3] & 0x07

    if ds_weekday == 1:
        weekday = 7
    else:
        weekday = ds_weekday - 1

    day = bcd_to_dec(
        data[4] & 0x3F
    )

    month = bcd_to_dec(
        data[5] & 0x1F
    )

    year = (
        2000
        + bcd_to_dec(data[6])
    )

    return (
        year,
        month,
        day,
        weekday,
        hour,
        minute,
        second
    )


def write_rtc(
    year,
    month,
    day,
    hour,
    minute,
    second
):

    # Menghitung weekday:
    #
    # DS3231:
    # 1 Sunday
    # 2 Monday
    # ...
    # 7 Saturday

    y = year
    m = month

    if m < 3:

        y -= 1
        m += 12

    k = y % 100

    j = y // 100

    h = (
        day
        + ((13 * (m + 1)) // 5)
        + k
        + (k // 4)
        + (j // 4)
        + (5 * j)
    ) % 7

    # Zeller:
    # 0 Saturday
    # 1 Sunday
    # 2 Monday
    # ...
    #
    # DS3231:
    # 1 Sunday ... 7 Saturday

    if h == 0:
        ds_weekday = 7
    else:
        ds_weekday = h

    data = bytearray(7)

    data[0] = dec_to_bcd(
        second
    )

    data[1] = dec_to_bcd(
        minute
    )

    data[2] = dec_to_bcd(
        hour
    )

    data[3] = dec_to_bcd(
        ds_weekday
    )

    data[4] = dec_to_bcd(
        day
    )

    data[5] = dec_to_bcd(
        month
    )

    data[6] = dec_to_bcd(
        year - 2000
    )

    i2c_rtc.writeto_mem(
        RTC_ADDR,
        0x00,
        data
    )


# ============================================================
# FILE JSON
# ============================================================

def load_json(filename):

    try:

        with open(
            filename,
            "r"
        ) as file:

            data = ujson.load(file)

        return data

    except:

        return None


def save_jadwal():

    try:

        # Tulis file sementara
        with open(
            JADWAL_TMP,
            "w"
        ) as file:

            ujson.dump(
                jadwal,
                file
            )

            file.flush()


        # Hapus backup lama
        try:

            os.remove(
                JADWAL_BAK
            )

        except:

            pass


        # Jadwal utama menjadi backup
        try:

            os.rename(
                JADWAL_FILE,
                JADWAL_BAK
            )

        except:

            pass


        # File temporary menjadi jadwal utama
        os.rename(
            JADWAL_TMP,
            JADWAL_FILE
        )


        gc.collect()

        return True


    except Exception as e:

        print(
            "SAVE ERROR:",
            e
        )


        try:

            os.remove(
                JADWAL_TMP
            )

        except:

            pass


        gc.collect()

        return False


def load_jadwal():

    global jadwal

    data = load_json(
        JADWAL_FILE
    )

    if isinstance(
        data,
        list
    ):

        jadwal = data

        print(
            "Jadwal:",
            len(jadwal)
        )

        return


    # Coba backup
    data = load_json(
        JADWAL_BAK
    )

    if isinstance(
        data,
        list
    ):

        jadwal = data

        print(
            "Menggunakan backup"
        )

        return


    # Tidak ada jadwal
    jadwal = []

    save_jadwal()


# ============================================================
# DFPLAYER
# ============================================================

def df_send(
    command,
    parameter=0
):

    packet = bytearray([
        0x7E,
        0xFF,
        0x06,
        command,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0xEF
    ])


    packet[5] = (
        parameter >> 8
    ) & 0xFF

    packet[6] = (
        parameter
        & 0xFF
    )


    checksum = (
        0
        - 0xFF
        - 0x06
        - command
        - 0x00
        - packet[5]
        - packet[6]
    ) & 0xFFFF


    packet[7] = (
        checksum >> 8
    ) & 0xFF

    packet[8] = (
        checksum
        & 0xFF
    )


    try:

        dfplayer.write(
            packet
        )

    except Exception as e:

        print(
            "DF ERROR:",
            e
        )


    time.sleep_ms(100)


def df_init():

    time.sleep_ms(1000)

    df_set_volume(
        device_volume
    )

    df_stop()


def df_set_volume(volume):

    global device_volume

    if volume < 0:
        volume = 0

    if volume > 30:
        volume = 30

    device_volume = volume

    df_send(
        0x06,
        volume
    )


def df_play(file_number):

    try:

        file_number = int(
            file_number
        )

    except:

        return


    if file_number < 1:

        return


    print(
        "DFPlayer MP3:",
        file_number
    )


    df_send(
        0x03,
        file_number
    )


def df_stop():

    df_send(
        0x16,
        0
    )


# ============================================================
# WIFI
# ============================================================

def connect_wifi():

    if wifi.isconnected():

        return True


    print(
        "Menghubungkan WiFi..."
    )


    try:

        wifi.connect(
            WIFI_SSID,
            WIFI_PASSWORD
        )

    except Exception as e:

        print(
            "WiFi ERROR:",
            e
        )

        return False


    timeout = 15


    while (
        not wifi.isconnected()
        and timeout > 0
    ):

        time.sleep(1)

        timeout -= 1


    if wifi.isconnected():

        print(
            "WiFi OK:",
            wifi.ifconfig()[0]
        )

        return True


    print(
        "WiFi gagal"
    )

    return False


# ============================================================
# HTTP
# ============================================================

def http_get(url):

    response = None

    try:

        import urequests

        response = urequests.get(
            url
        )

        status = response.status_code

        text = response.text

        response.close()

        response = None

        gc.collect()

        return (
            status,
            text
        )


    except Exception as e:

        print(
            "HTTP GET:",
            e
        )


        if response is not None:

            try:
                response.close()
            except:
                pass


        gc.collect()

        return (
            0,
            None
        )


def http_post(
    url,
    data
):

    response = None

    try:

        import urequests

        body = ujson.dumps(
            data
        )


        response = urequests.post(
            url,
            data=body,
            headers={
                "Content-Type":
                "application/json"
            }
        )


        status = response.status_code

        response.close()

        response = None

        gc.collect()

        return status


    except Exception as e:

        print(
            "HTTP POST:",
            e
        )


        if response is not None:

            try:
                response.close()
            except:
                pass


        gc.collect()

        return 0


# ============================================================
# SINKRONISASI KONFIGURASI
# ============================================================

def sync_config():

    global schedule_version
    global jadwal

    if not wifi.isconnected():

        return False


    status, text = http_get(
        API_CONFIG
    )


    if status != 200:

        return False


    if text is None:

        return False


    try:

        data = ujson.loads(
            text
        )


        server_version = int(
            data.get(
                "version",
                0
            )
        )


        volume = int(
            data.get(
                "volume",
                DEFAULT_VOLUME
            )
        )


        # Update volume
        if volume != device_volume:

            df_set_volume(
                volume
            )


        # Jadwal belum berubah
        if (
            server_version
            == schedule_version
        ):

            return True


        # Ambil jadwal baru
        status, text = http_get(
            API_JADWAL
        )


        if status != 200:

            return False


        if text is None:

            return False


        new_jadwal = ujson.loads(
            text
        )


        if not isinstance(
            new_jadwal,
            list
        ):

            return False


        # Validasi dasar
        for item in new_jadwal:

            if not isinstance(
                item,
                list
            ):

                return False


            if len(item) < 8:

                return False


        # Ganti jadwal di RAM
        jadwal = new_jadwal


        # Simpan lokal
        if save_jadwal():

            schedule_version = (
                server_version
            )

            print(
                "Jadwal diperbarui:",
                schedule_version
            )

            return True


    except Exception as e:

        print(
            "SYNC ERROR:",
            e
        )


    gc.collect()

    return False


# ============================================================
# SINKRONISASI WAKTU
# ============================================================

def sync_time():

    if not wifi.isconnected():

        return False


    status, text = http_get(
        API_WAKTU
    )


    if status != 200:

        return False


    if text is None:

        return False


    try:

        data = ujson.loads(
            text
        )


        write_rtc(
            int(data["tahun"]),
            int(data["bulan"]),
            int(data["tanggal"]),
            int(data["jam"]),
            int(data["menit"]),
            int(data["detik"])
        )


        print(
            "RTC disinkronkan"
        )


        return True


    except Exception as e:

        print(
            "RTC SYNC ERROR:",
            e
        )


    return False


# ============================================================
# TEST BEL
# ============================================================

last_test_id = 0


def check_test_bell():

    global last_test_id


    if not wifi.isconnected():

        return


    status, text = http_get(
        API_TEST
    )


    if status != 200:

        return


    if text is None:

        return


    try:

        data = ujson.loads(
            text
        )


        test_id = int(
            data.get(
                "id",
                0
            )
        )


        file_mp3 = int(
            data.get(
                "file_mp3",
                0
            )
        )


        if (
            test_id > 0
            and test_id != last_test_id
            and file_mp3 > 0
        ):

            last_test_id = test_id


            lcd_clear()

            lcd_set_cursor(
                0,
                0
            )

            lcd_print(
                "TEST BEL"
            )

            lcd_set_cursor(
                0,
                1
            )

            lcd_print(
                "MP3 {}".format(
                    file_mp3
                )
            )


            df_play(
                file_mp3
            )


            time.sleep(3)


    except Exception as e:

        print(
            "TEST ERROR:",
            e
        )


# ============================================================
# KIRIM STATUS
# ============================================================

def send_status(
    status_bel,
    nama,
    jam_bel,
    waktu
):

    if not wifi.isconnected():

        return


    try:

        ip = wifi.ifconfig()[0]

    except:

        ip = ""


    payload = {
        "status": status_bel,
        "nama": nama,
        "jam": jam_bel,
        "waktu_sekarang": waktu,
        "ip": ip,
        "ram": gc.mem_free(),
        "version": schedule_version
    }


    http_post(
        API_STATUS,
        payload
    )


# ============================================================
# MESIN JADWAL
# ============================================================

def get_schedule(
    weekday,
    hour,
    minute,
    second
):

    now_second = (
        hour * 3600
        + minute * 60
        + second
    )


    active_bell = None

    next_bell = None

    next_seconds = 999999


    for item in jadwal:

        try:

            item_id = int(
                item[0]
            )

            day = int(
                item[1]
            )

            hour_bell = int(
                item[2]
            )

            minute_bell = int(
                item[3]
            )

            name = str(
                item[4]
            )

            mp3 = int(
                item[5]
            )

            duration = int(
                item[6]
            )

            active = int(
                item[7]
            )


        except:

            continue


        if not active:

            continue


        if day != weekday:

            continue


        bell_second = (
            hour_bell * 3600
            + minute_bell * 60
        )


        # Bel sedang berbunyi
        if (
            bell_second
            <= now_second
            < bell_second + duration
        ):

            active_bell = item

            break


        # Jadwal berikutnya
        if bell_second > now_second:

            if (
                bell_second
                < next_seconds
            ):

                next_seconds = (
                    bell_second
                )

                next_bell = item


    return (
        active_bell,
        next_bell
    )


# ============================================================
# FORMAT JAM
# ============================================================

def format_time(
    hour,
    minute
):

    return "{:02d}:{:02d}".format(
        hour,
        minute
    )


# ============================================================
# TAMPILAN LCD
# ============================================================

def show_ringing(
    item,
    hour,
    minute,
    second
):

    name = str(
        item[4]
    )

    lcd_set_cursor(
        0,
        0
    )

    lcd_print(
        "BEL: " + name
    )


    lcd_set_cursor(
        0,
        1
    )

    lcd_print(
        "{:02d}:{:02d}:{:02d}".format(
            hour,
            minute,
            second
        )
    )


def show_next(
    item,
    hour,
    minute,
    second
):

    name = str(
        item[4]
    )

    next_hour = int(
        item[2]
    )

    next_minute = int(
        item[3]
    )


    lcd_set_cursor(
        0,
        0
    )

    lcd_print(
        "Next: " + name
    )


    lcd_set_cursor(
        0,
        1
    )

    lcd_print(
        "{} {}".format(
            format_time(
                next_hour,
                next_minute
            ),
            "{:02d}:{:02d}".format(
                hour,
                minute
            )
        )
    )


def show_no_schedule(
    hour,
    minute,
    second
):

    lcd_set_cursor(
        0,
        0
    )

    lcd_print(
        "Tidak ada bel"
    )


    lcd_set_cursor(
        0,
        1
    )

    lcd_print(
        "{:02d}:{:02d}:{:02d}".format(
            hour,
            minute,
            second
        )
    )


# ============================================================
# STARTUP
# ============================================================

print()
print(
    "=============================="
)
print(
    " SISTEM BEL SEKOLAH"
)
print(
    " ESP32 + DS3231 + LCD + DF"
)
print(
    "=============================="
)


# LCD
lcd_init()

lcd_set_cursor(
    0,
    0
)

lcd_print(
    "BEL SEKOLAH"
)

lcd_set_cursor(
    0,
    1
)

lcd_print(
    "Starting..."
)


# Jadwal lokal
load_jadwal()


# DFPlayer
df_init()


time.sleep_ms(
    500
)


# WiFi
connect_wifi()


# Sinkronisasi pertama
if wifi.isconnected():

    sync_config()

    sync_time()


lcd_clear()


# ============================================================
# TIMER
# ============================================================

last_sync = time.ticks_ms()

last_time_sync = time.ticks_ms()

last_status = time.ticks_ms()

last_test = time.ticks_ms()

last_wifi_attempt = time.ticks_ms()


# ============================================================
# ANTI DOUBLE TRIGGER
# ============================================================

last_bell_id = -1

last_bell_date = -1

last_bell_minute = -1


# ============================================================
# LOOP UTAMA
# ============================================================

while True:

    try:

        # ----------------------------------------------------
        # Baca RTC
        # ----------------------------------------------------

        (
            year,
            month,
            day,
            weekday,
            hour,
            minute,
            second
        ) = read_rtc()


        current_time = (
            "{:02d}:{:02d}:{:02d}"
            .format(
                hour,
                minute,
                second
            )
        )


        # ----------------------------------------------------
        # Cari jadwal
        # ----------------------------------------------------

        (
            ringing,
            next_bell
        ) = get_schedule(
            weekday,
            hour,
            minute,
            second
        )


        # ----------------------------------------------------
        # BEL SEDANG BERBUNYI
        # ----------------------------------------------------

        if ringing is not None:

            bell_id = int(
                ringing[0]
            )

            mp3 = int(
                ringing[5]
            )

            bell_name = str(
                ringing[4]
            )


            show_ringing(
                ringing,
                hour,
                minute,
                second
            )


            # Anti double trigger
            #
            # Satu jadwal hanya diputar
            # satu kali dalam satu menit.

            if (
                bell_id
                != last_bell_id
                or day
                != last_bell_date
                or (
                    hour * 60
                    + minute
                )
                != last_bell_minute
            ):

                print(
                    "BEL:",
                    bell_name,
                    "MP3:",
                    mp3
                )


                df_play(
                    mp3
                )


                last_bell_id = (
                    bell_id
                )

                last_bell_date = (
                    day
                )

                last_bell_minute = (
                    hour * 60
                    + minute
                )


            status_bel = "ringing"

            status_nama = bell_name

            status_jam = format_time(
                int(ringing[2]),
                int(ringing[3])
            )


        # ----------------------------------------------------
        # ADA JADWAL BERIKUTNYA
        # ----------------------------------------------------

        elif next_bell is not None:

            bell_name = str(
                next_bell[4]
            )


            show_next(
                next_bell,
                hour,
                minute,
                second
            )


            status_bel = "upcoming"

            status_nama = bell_name

            status_jam = format_time(
                int(next_bell[2]),
                int(next_bell[3])
            )


        # ----------------------------------------------------
        # TIDAK ADA JADWAL
        # ----------------------------------------------------

        else:

            show_no_schedule(
                hour,
                minute,
                second
            )


            status_bel = "none"

            status_nama = ""

            status_jam = ""


        now = time.ticks_ms()


        # ----------------------------------------------------
        # WIFI
        # ----------------------------------------------------

        if not wifi.isconnected():

            if time.ticks_diff(
                now,
                last_wifi_attempt
            ) >= 30000:

                last_wifi_attempt = now

                connect_wifi()


        # ----------------------------------------------------
        # SYNC JADWAL
        # ----------------------------------------------------

        if time.ticks_diff(
            now,
            last_sync
        ) >= SYNC_INTERVAL:

            last_sync = now


            if wifi.isconnected():

                sync_config()


        # ----------------------------------------------------
        # SYNC RTC
        # ----------------------------------------------------

        if time.ticks_diff(
            now,
            last_time_sync
        ) >= TIME_SYNC_INTERVAL:

            last_time_sync = now


            if wifi.isconnected():

                sync_time()


        # ----------------------------------------------------
        # STATUS ESP32
        # ----------------------------------------------------

        if time.ticks_diff(
            now,
            last_status
        ) >= STATUS_INTERVAL:

            last_status = now


            if wifi.isconnected():

                send_status(
                    status_bel,
                    status_nama,
                    status_jam,
                    current_time
                )


        # ----------------------------------------------------
        # TEST BEL
        # ----------------------------------------------------

        if time.ticks_diff(
            now,
            last_test
        ) >= TEST_INTERVAL:

            last_test = now


            if wifi.isconnected():

                check_test_bell()


        # ----------------------------------------------------
        # GARBAGE COLLECTION
        # ----------------------------------------------------

        gc.collect()


        # Debug serial
        print(
            "{} | {} | {} | RAM:{} | VER:{}".format(
                current_time,
                status_bel,
                status_nama,
                gc.mem_free(),
                schedule_version
            )
        )


        # Satu detik
        time.sleep(1)


    except Exception as e:

        print(
            "MAIN ERROR:",
            e
        )


        # Jangan sampai error
        # menghentikan sistem bel

        gc.collect()

        time.sleep(2)

"""IEEE 738 sensor suite: FLIR Lepton 3.5, DHT22, SI1145, ADS1115 + YL-83.

FLIR Lepton represented as a 14-pin breakout header (GroupGets module pinout).
DHT22 uses the DHT11 symbol (same physical layout) + 10k pull-up on data line.
SI1145 + YL-83 use generic module headers (Adafruit-style breakouts).
ADS1115IDGS reads YL-83 analog out on AIN0; I2C ADDR tied LOW for 0x48.
"""

import skidl

FP_C_0402 = "Capacitor_SMD:C_0402_1005Metric"
FP_R_0402 = "Resistor_SMD:R_0402_1005Metric"
FP_HEADER_2_54 = "Connector_PinHeader_2.54mm:PinHeader_1x{n}_P2.54mm_Vertical"


def _cap(ref: str, value: str, fp: str, n1: skidl.Net, n2: skidl.Net) -> None:
    c = skidl.Part("Device", "C", ref=ref, value=value, footprint=fp)
    n1 += c[1]
    n2 += c[2]


def _res(ref: str, value: str, fp: str, n1: skidl.Net, n2: skidl.Net) -> None:
    r = skidl.Part("Device", "R", ref=ref, value=value, footprint=fp)
    n1 += r[1]
    n2 += r[2]


def _module_header(ref: str, n_pins: int, label: str) -> skidl.Part:
    """Single-row 2.54mm pin header for off-board sensor breakout modules."""
    p = skidl.Part(
        "Connector_Generic",
        f"Conn_01x{n_pins:02d}",
        ref=ref,
        footprint=FP_HEADER_2_54.format(n=f"{n_pins:02d}"),
    )
    p.value = label
    return p


def build_flir_lepton(
    v3v3: skidl.Net,
    gnd: skidl.Net,
    sda: skidl.Net,
    scl: skidl.Net,
    spi_mosi: skidl.Net,
    spi_miso: skidl.Net,
    spi_sck: skidl.Net,
    spi_ce0: skidl.Net,
    vsync: skidl.Net,
) -> None:
    """FLIR Lepton 3.5 SPI/I2C link via 14-pin FFC to off-board daughterboard.

    Per ADR-013: Lepton mounts on a separate daughterboard so its lens can be
    aimed at the conductor below the cross-arm independently of the main PCB.
    This function adds the Hirose FH12-14S-0.5SH FFC connector on the main
    carrier; the daughterboard (separate KiCad project under cad/lepton_daughter/)
    hosts the Molex 32-pin Lepton socket.

    Pin map preserves the GroupGets 14-pin breakout signal order so the same
    Lepton breakout schematic is reusable on the daughterboard.

    1=GND  2=CS   3=MOSI  4=MISO  5=SCK   6=VSYNC  7=GPIO3
    8=SDA  9=SCL  10=PWR_DN_L  11=RESET_L  12=GND  13=3V3  14=VIN
    """
    j = skidl.Part(
        "Connector_Generic",
        "Conn_01x14",
        ref="J8",
        footprint=(
            "Connector_FFC-FPC:" "Hirose_FH12-14S-0.5SH_1x14-1MP_P0.50mm_Horizontal"
        ),
    )
    j.value = "FLIR_LEPTON_FFC"
    gnd += j[1]
    spi_ce0 += j[2]
    spi_mosi += j[3]
    spi_miso += j[4]
    spi_sck += j[5]
    vsync += j[6]
    skidl.Net("LEPTON_GPIO3") & j[7]
    sda += j[8]
    scl += j[9]
    # PWR_DN_L and RESET_L pulled high through FFC (active-low, default-deasserted)
    _res("R7", "10k", FP_R_0402, j[10], v3v3)
    _res("R8", "10k", FP_R_0402, j[11], v3v3)
    gnd += j[12]
    v3v3 += j[13]
    v3v3 += j[14]  # VIN tied to 3V3 (daughterboard powered from main 3V3 rail)
    _cap("C25", "100nF", FP_C_0402, v3v3, gnd)


def build_dht22(v3v3: skidl.Net, gnd: skidl.Net, gpio4: skidl.Net) -> None:
    """DHT22 ambient temp/humidity — 4-pin module + 10k pull-up on data line."""
    u = skidl.Part(
        "Sensor", "DHT11", ref="U5", footprint="Sensor:Aosong_DHT11_5.5x12.0_P2.54mm"
    )
    u.value = "DHT22"
    v3v3 += u["VDD"]
    gnd += u["GND"]
    gpio4 += u["DATA"]
    _res("R9", "10k", FP_R_0402, gpio4, v3v3)
    _cap("C26", "100nF", FP_C_0402, v3v3, gnd)


def build_si1145(
    v3v3: skidl.Net, gnd: skidl.Net, sda: skidl.Net, scl: skidl.Net
) -> None:
    """SI1145 UV/visible/IR sensor — Adafruit-style 5-pin breakout.

    1=VIN  2=GND  3=SCL  4=SDA  5=INT (NC)
    """
    j = _module_header("J9", 5, "SI1145")
    v3v3 += j[1]
    gnd += j[2]
    scl += j[3]
    sda += j[4]
    skidl.Net("SI1145_INT") & j[5]
    _cap("C27", "100nF", FP_C_0402, v3v3, gnd)


def build_ads1115_yl83(
    v3v3: skidl.Net, gnd: skidl.Net, sda: skidl.Net, scl: skidl.Net
) -> None:
    """ADS1115 ADC + YL-83 rain sensor on AIN0. ADDR=LOW -> I2C 0x48."""
    u_ads = skidl.Part(
        "Analog_ADC",
        "ADS1115IDGS",
        ref="U6",
        footprint="Package_SO:MSOP-10_3x3mm_P0.5mm",
    )
    u_ads.value = "ADS1115"

    rain_ao = skidl.Net("RAIN_AO")
    v3v3 += u_ads["VDD"]
    gnd += u_ads["GND"]
    sda += u_ads["SDA"]
    scl += u_ads["SCL"]
    gnd += u_ads["ADDR"]  # LOW -> I2C address 0x48
    rain_ao += u_ads["AIN0"]
    skidl.Net("NC_ADS_AIN1") & u_ads["AIN1"]
    skidl.Net("NC_ADS_AIN2") & u_ads["AIN2"]
    skidl.Net("NC_ADS_AIN3") & u_ads["AIN3"]
    skidl.Net("NC_ADS_ALERT") & u_ads["ALERT/RDY"]
    _cap("C28", "100nF", FP_C_0402, v3v3, gnd)
    _cap("C29", "10nF", FP_C_0402, rain_ao, gnd)  # anti-aliasing on analog input

    # YL-83 rain sensor 4-pin module: VCC, GND, AO, DO
    j = _module_header("J10", 4, "YL-83")
    v3v3 += j[1]
    gnd += j[2]
    rain_ao += j[3]
    skidl.Net("YL83_DO") & j[4]


def build_sensors(
    v3v3: skidl.Net,
    gnd: skidl.Net,
    sda: skidl.Net,
    scl: skidl.Net,
    spi_mosi: skidl.Net,
    spi_miso: skidl.Net,
    spi_sck: skidl.Net,
    spi_ce0: skidl.Net,
    gpio4: skidl.Net,
    gpio25: skidl.Net,
) -> None:
    """All four IEEE 738 sensors on the carrier."""
    build_flir_lepton(v3v3, gnd, sda, scl, spi_mosi, spi_miso, spi_sck, spi_ce0, gpio25)
    build_dht22(v3v3, gnd, gpio4)
    build_si1145(v3v3, gnd, sda, scl)
    build_ads1115_yl83(v3v3, gnd, sda, scl)

    # I2C pull-ups — 2.2k to 3V3 (per theory section 3, ADR-005)
    _res("R10", "2.2k", FP_R_0402, sda, v3v3)
    _res("R11", "2.2k", FP_R_0402, scl, v3v3)

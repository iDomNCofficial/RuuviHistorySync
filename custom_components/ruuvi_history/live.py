"""Decode local, unencrypted RuuviTag RAWv2 Bluetooth advertisements.

Ruuvi manufacturer ID 0x0499, firmware format 5.  All fields are MSB first.
This module intentionally has no Home Assistant dependency for vector tests.
"""

from math import sqrt


STANDARD_GRAVITY = 9.80665  # m/s² per g

def decode_rawv2(payload: bytes) -> dict[str, float | int]:
    """Decode the standard 24-byte RuuviTag data format 5 payload.

    Fields marked unavailable by the firmware are omitted, not reported as
    extreme measurements. Unsupported formats produce an empty dictionary.
    """
    if len(payload) < 24 or payload[0] != 5:
        return {}

    def signed(index):
        return int.from_bytes(payload[index:index + 2], "big", signed=True)

    def unsigned(index):
        return int.from_bytes(payload[index:index + 2], "big")

    result = {}
    temperature = signed(1)
    humidity = unsigned(3)
    pressure = unsigned(5)
    power_info = unsigned(13)
    voltage = power_info >> 5
    acceleration = [signed(offset) for offset in (7, 9, 11)]
    if temperature != -32768:
        result["temperature"] = temperature * 0.005
    if humidity != 0xFFFF:
        result["humidity"] = humidity * 0.0025
    if pressure != 0xFFFF:
        result["pressure"] = pressure + 50000  # Pa, like GATT log history.
    if voltage != 0x7FF:
        result["battery_voltage"] = (voltage + 1600) / 1000  # Volts.
    # RAWv2 represents acceleration in milli-g, not directly in m/s².
    for axis, raw_value in zip("xyz", acceleration):
        if raw_value != -32768:
            result[f"acceleration_{axis}"] = raw_value * STANDARD_GRAVITY / 1000
    if len([axis for axis in "xyz" if f"acceleration_{axis}" in result]) == 3:
        result["acceleration_total"] = sqrt(
            sum(result[f"acceleration_{axis}"] ** 2 for axis in "xyz")
        )
    if payload[15] != 0xFF:
        result["movement_counter"] = payload[15]
    return result

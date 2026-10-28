# RuuviTag History Sync

[![HACS validation](https://github.com/iDomNCofficial/RuuviHistorySync/actions/workflows/validate.yml/badge.svg)](https://github.com/iDomNCofficial/RuuviHistorySync/actions/workflows/validate.yml)

Custom Home Assistant integration that combines live RuuviTag Bluetooth advertisements with the measurements stored in the tag's internal history.

When a tag returns after a Bluetooth outage, the integration downloads its GATT history and fills genuinely missing Home Assistant Recorder states. Existing live values remain authoritative.

## Features

- Automatic discovery of connectable RuuviTags using RAWv2 data format 5.
- Live temperature, humidity, pressure, acceleration, movement counter, battery voltage, and signal strength.
- Internal-history synchronization at startup, after a real Bluetooth reconnection, and on manual request.
- Recorder backfill for temperature, humidity, and valid pressure measurements.
- Conservative removal of `unavailable` markers only when consecutive archived samples prove that the interval is covered.
- Duplicate-safe imports: live values within one minute always take precedence.
- French and English user interface.
- Local Ruuvi brand assets for Home Assistant 2026.3 and later.

## Requirements

- Home Assistant **2026.10.4 or newer**.
- A Bluetooth adapter or proxy that Home Assistant reports as connectable.
- A RuuviTag and firmware supporting direct GATT history downloads.

> [!CAUTION]
> Recorder does not provide a public API for importing historical states and five-minute statistics. This integration therefore uses Home Assistant 2026.10.4 internal Recorder APIs. Review compatibility before upgrading Home Assistant and keep normal Home Assistant backups.

## Installation with HACS

Until this repository is included in the default HACS catalog:

1. Open HACS in Home Assistant.
2. Open the menu and choose **Custom repositories**.
3. Add `https://github.com/iDomNCofficial/RuuviHistorySync` as an **Integration** repository.
4. Download **RuuviTag History Sync**.
5. Restart Home Assistant.
6. Open **Settings → Devices & services → Add integration** and select **RuuviTag History Sync**.

## Manual installation

Copy `custom_components/ruuvi_history` into the `custom_components` directory of your Home Assistant configuration, then restart Home Assistant.

## Configuration and operation

The setup flow lists compatible, unconfigured RuuviTags currently visible to a connectable Home Assistant Bluetooth adapter. Select a tag to add it.

History cadence is global and fixed at five minutes. Synchronization is intentionally event-driven rather than periodic:

- once when Home Assistant starts;
- once when the tag returns after at least three minutes without advertisements;
- whenever **Synchronize now** is pressed.

The downloaded archive is retained for ten days. Raw Recorder backfill is limited to nine days to match Home Assistant's short-term history window.

The official **Ruuvi BLE** integration is not required. If Home Assistant offers the same tag through both integrations, choose **Ignore** on the Ruuvi BLE discovery card to avoid duplicate devices.

## Diagnostics

Each device exposes:

- **Bluetooth connection**: whether an advertisement was received recently;
- **Last synchronization**: the last successful GATT history download, with Recorder status attributes;
- **Synchronize now**: requests an immediate history download.

Enable debug logging when troubleshooting:

```yaml
logger:
  logs:
    custom_components.ruuvi_history: debug
```

## Removal

Remove every RuuviTag History Sync entry from **Settings → Devices & services**, uninstall the repository from HACS, and restart Home Assistant.

## Trademark

Ruuvi and RuuviTag are trademarks of Ruuvi Innovations Ltd. This community integration is not affiliated with or endorsed by Ruuvi Innovations Ltd. Brand assets are used only to identify compatible products.

## License

[MIT](LICENSE)

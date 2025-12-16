[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/NewImproved/Aduro.svg)](https://github.com/NewImproved/Aduro/releases)
[![Donate](https://img.shields.io/badge/Donate-PayPal-blue.svg)](https://www.paypal.com/donate/?hosted_button_id=W6WPMAQ3YKK6G)

# BETA-RELEASE UNDER CONSTRUCTION!!!
All functions are not yet tested.

# Aduro Hybrid Stove Integration for Home Assistant
A comprehensive Home Assistant custom integration for Aduro H1, H2, H5 [H3, H4 and H6 unconfirmed] hybrid pellet stoves.

## Features

✨ **Complete Control**
- Start/Stop stove remotely
- Adjust heat level (1-3)
- Set target temperature (5-35°C)
- Toggle between operation modes

🔥 **Smart Operation**
- Automatic retry on command failures
- Fast polling during mode changes
- External change detection (sync with mobile app)
- Wood mode support with automatic resume

🌡️ **Temperature Monitoring & Alerts**
- High smoke temperature alert (300-450°C, configurable)
- Low wood mode temperature alert (20-200°C, configurable)
- Customizable duration of time before alert (1-30 minutes)
- Real-time temperature monitoring with hysteresis
- Prevent dangerous overheating for all modes and fire extinction during wood mode

📊 **Comprehensive Monitoring**
- 42+ sensors (temperatures, power, pellets, consumption, alerts)
- Real-time state and status tracking
- Operating time statistics
- Network information (WiFi signal, IP address)

🌲 **Pellet Management**
- Pellet level tracking (amount and percentage)
- Consumption monitoring (daily, monthly, yearly, total)
- Low pellet notifications
- Automatic shutdown at critical level
- Refill counter and cleaning tracker

⏱️ **Smart Features**
- Ignition timer countdowns
- Mode transition tracking
- Change-in-progress detection
- Automatic state synchronization

🌍 **Multi-Language Support**
- English
- Danish
- French
- German
- Swedish
- Easy to add more languages

## Supported Models
Only Aduro H1, H2 & H5 have been tested.

Asumptions have been made for how the following stoves work, and are not yet confirmed.
If you can confirm that the integration work for a stove, please let me know via [GitHub Issues](https://github.com/NewImproved/Aduro/issues).
- Aduro H3
- Aduro H4
- Aduro H6

## Prerequisites

- Home Assistant 2023.1 or newer
- Aduro hybrid stove with network connectivity
- Stove serial number and PIN code

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add `https://github.com/NewImproved/Aduro` as a custom repository
6. Category: Integration
7. Click "Add"
8. Search for "Aduro Hybrid Stove"
9. Click "Download"
10. Restart Home Assistant

### Manual Installation

1. Download the latest release from [GitHub releases](https://github.com/NewImproved/Aduro/releases)
2. Extract the `aduro` folder to your `custom_components` directory
3. Restart Home Assistant

## Configuration

### Initial Setup

1. Go to **Settings** → **Devices & Services**
2. Click **"+ ADD INTEGRATION"**
3. Search for **"Aduro Hybrid Stove"**
4. Enter only 3 required details:
   - **Serial Number**: Your stove's serial number
   - **PIN Code**: Your stove's PIN code
   - **Stove Model**: Select your model (H1-H6)

The integration will automatically:
- Discover your stove on the network
- Create all entities
- Use sensible defaults for all settings

### Optional Configuration

To customize settings after setup:
1. Go to **Settings** → **Devices & Services**
2. Find **Aduro Hybrid Stove**
3. Click **"CONFIGURE"**
4. Choose from three configuration areas:

#### Pellet Settings
- Pellet container capacity (kg)
- Low pellet notification level (%)
- Auto-shutdown level (%)
- Enable/disable automatic shutdown

#### Temperature Alerts ⭐ NEW
- **High Smoke Temperature Alert**
  - Threshold: 300-450°C (default: 370°C)
  - Duration threshold: 1-30 minutes (default: 30 seconds)
  - Alerts when smoke temperature is dangerously high
- **Low Wood Mode Temperature Alert**
  - Threshold: 20-200°C (default: 175°C)
  - Duration threshold: 1-30 minutes (default: 5 minutes)
  - Alerts when wood fire might be going out

#### Advanced Settings
- Auto-resume after wood mode

## Entities

### Sensors (42)

#### Status & Operation
- **Status** - Main status (Operating II, Stopped, etc.)
- **Status Detail** - Detailed status (with timers for i.e. start up)
- **State** - Raw state number
- **Substate** - Raw substate number
- **Heat Level** - Current heat level (1-3)
- **Heat Level Display** - Roman numerals (I, II, III)
- **Operation Mode** - Current mode (0=Heat Level, 1=Temperature, 2=Wood)

#### Temperatures
- **Room Temperature** - Current room/boiler temperature
- **Target Temperature** - Temperature setpoint
- **Smoke Temperature** - Exhaust temperature
- **Shaft Temperature** - Shaft temperature

#### Temperature Alerts
- **High Smoke Temperature Alert** - Alert status with attributes
  - `alert_active` - Boolean alert state
  - `current_temp` - Current smoke temperature
  - `threshold_temp` - Configured threshold
  - `threshold_duration_seconds` - Alert duration
- **Low Wood Temperature Alert** - Alert status with attributes
  - `alert_active` - Boolean alert state
  - `in_wood_mode` - Wood mode status
  - `current_temp` - Current shaft temperature
  - `threshold_temp` - Configured threshold
  - `threshold_duration_seconds` - Alert duration

#### Power
- **Power Output** - Power in kW

#### Pellets
- **Pellets Remaining** - Remaining pellets (kg)
- **Pellets Percentage** - Remaining pellets (%)
- **Pellets Consumed** - Consumed since last refill (kg)
- **Pellets Consumed Since Cleaning** - Consumed since cleaning (kg)

#### Consumption
- **Today's Consumption** - Current day (kg)
- **Yesterday's Consumption** - Previous day (kg)
- **This Month's Consumption** - Current month (kg)
- **This Year's Consumption** - Current year (kg)
- **Total Consumption** - Lifetime consumption (kg)

#### Network
- **Stove IP Address** - Current IP
- **WiFi Network** - Connected SSID
- **WiFi Signal Strength** - RSSI in dBm
- **MAC Address** - Network MAC

#### Software
- **Firmware** - Version and build

#### Runtime
- **Total Operating Time** - Lifetime runtime
- **Auger Operating Time** - Auger runtime
- **Ignition Operating Time** - Ignition runtime

#### Calculated
- **Change In Progress** - Boolean
- **Display Format** - Formatted display text
- **Display Target** - Current target value
- **External Change Detected** - App changes

### Switches (3)

- **Power** - Start/Stop the stove
- **Auto Shutdown at Low Pellets** - Enable automatic shutdown at a certain pellets level and time
- **Auto Resume After Wood Mode** - Enable automatic resume when in heat level mode

### Numbers (9)

#### Heat Control
- **Heat Level** - Set heat level (1-3)
- **Target Temperature** - Set temperature (5-35°C)

#### Pellet Configuration
- **Pellet Capacity** - Configure hopper capacity (8-25 kg)
- **Low Pellet Notification Level** - Warning threshold (%)
- **Auto-Shutdown Pellet Level** - Shutdown threshold (%)

#### Temperature Alert Configuration
- **High Smoke Temp Alert Threshold** - Alert threshold (300-450°C)
- **High Smoke Temp Alert Duration threshold** - Alert duration threshold (60-1800 seconds)
- **Low Wood Temp Alert Threshold** - Alert threshold (20-200°C)
- **Low Wood Temp Alert Duration threshold** - Alert duration threshold (60-1800 seconds)

### Buttons (5)

- **Refill Pellets** - Mark pellets as refilled
- **Clean Stove** - Reset refill counter after cleaning
- **Toggle Mode** - Switch between Heat Level/Temperature modes
- **Resume After Wood Mode** - Manual resume from wood mode
- **Force Auger** - Manually run auger (advanced)

## Services

All services are available under the `aduro` domain:

### Basic Control

```yaml
# Start the stove
service: aduro.start_stove

# Stop the stove
service: aduro.stop_stove

# Set heat level (1-3)
service: aduro.set_heatlevel
data:
  heatlevel: 2

# Set target temperature (5-35°C)
service: aduro.set_temperature
data:
  temperature: 22

# Set operation mode (0=Heat Level, 1=Temperature, 2=Wood)
service: aduro.set_operation_mode
data:
  mode: 1

# Toggle between Heat Level and Temperature modes
service: aduro.toggle_mode
```

### Advanced

```yaml
# Resume pellet operation after wood mode
service: aduro.resume_after_wood_mode

# Force auger to run
service: aduro.force_auger

# Set custom parameter (advanced)
service: aduro.set_custom
data:
  path: "auger.forced_run"
  value: 1
```

## Automations Examples

### Morning Warmup

```yaml
automation:
  - alias: "Start Stove in Morning"
    trigger:
      - platform: time
        at: "06:00:00"
    condition:
      - condition: numeric_state
        entity_id: sensor.outdoor_temperature
        below: 10
    action:
      - service: aduro.start_stove
      - service: aduro.set_heatlevel
        data:
          heatlevel: 2
```

### Auto-Adjust by Weather

```yaml
automation:
  - alias: "Adjust Heat by Weather"
    trigger:
      - platform: numeric_state
        entity_id: sensor.outdoor_temperature
        below: 0
    action:
      - service: aduro.set_heatlevel
        data:
          heatlevel: 3
```

### Low Pellet Warning

```yaml
automation:
  - alias: "Low Pellet Alert"
    trigger:
      - platform: numeric_state
        entity_id: sensor.aduro_h2_pellets_percentage
        below: 20
    action:
      - service: notify.mobile_app
        data:
          title: "Stove Alert"
          message: "Pellets low: {{ states('sensor.aduro_h2_pellets_percentage') }}%"
```

### Night Mode

```yaml
automation:
  - alias: "Night Mode Temperature"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: aduro.set_temperature
        data:
          temperature: 18
```

### High Smoke Temperature Alert

```yaml
automation:
  - alias: "High Smoke Temperature Alert"
    trigger:
      - platform: state
        entity_id: sensor.aduro_h2_high_smoke_temperature_alert
        to: "Alert"
    action:
      - service: notify.mobile_app
        data:
          title: "⚠️ Stove High Temperature Alert"
          message: >
            Smoke temperature too high!
            Current: {{ state_attr('sensor.aduro_h2_high_smoke_temperature_alert', 'current_temp') }}°C
            Threshold: {{ state_attr('sensor.aduro_h2_high_smoke_temperature_alert', 'threshold_temp') }}°C
          data:
            priority: high
```

### Low Wood Mode Temperature Alert

```yaml
automation:
  - alias: "Low Wood Temperature Alert"
    trigger:
      - platform: state
        entity_id: sensor.aduro_h2_low_wood_temperature_alert
        to: "Alert"
    action:
      - service: notify.mobile_app
        data:
          title: "🔥 Add Wood to Stove"
          message: >
            Temperature too low in wood mode!
            Current: {{ state_attr('sensor.aduro_h2_low_wood_temperature_alert', 'current_temp') }}°C
            The fire may be going out.
          data:
            priority: high
```

### Temperature Alert Cleared

```yaml
automation:
  - alias: "Stove Temperature Alert Cleared"
    trigger:
      - platform: state
        entity_id: sensor.aduro_h2_high_smoke_temperature_alert
        from: "Alert"
        to: "OK"
    action:
      - service: notify.mobile_app
        data:
          title: "✅ Stove Alert Cleared"
          message: "Smoke temperature has returned to normal"
```

## Troubleshooting

### Stove Not Found

- Ensure stove is powered on and connected to network
- Check that serial number and PIN are correct
- Check firewall settings

### Commands Not Working

- Check Home Assistant logs for errors
- Ensure stove is not in wood mode (state 9 or 14)
- Try restarting the integration

### Temperature Alerts Not Triggering

- Verify smoke and shaft temperature sensors are working
- Check that alert thresholds are appropriate for your stove
- Review logs for temperature detection messages
- Default thresholds (370°C for high smoke, 175°C for low wood) may need adjustment

### Unknown States

If you see "Unknown State X" in sensors:
1. Check Home Assistant logs for warnings
2. Note the state and substate number
3. Note the state and substate in aduro hybrid application
4. See [ADDING_STATES.md](ADDING_STATES.md) for how to add it
5. Report it via [GitHub Issues](https://github.com/NewImproved/Aduro/issues)

### Enable Debug Logging

Add to `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.aduro: debug
```

## Migration from YAML/Python Scripts

If you're migrating from the manual YAML configuration:

1. **Backup** your current configuration
2. **Remove** old automations and files using `python_script.exec`
3. **Remove** old template sensors
4. **Install** this integration
5. **Configure** via UI
6. **Update** automations to use new service calls
7. **Test** all functionality

The integration preserves all functionality:
- ✅ Mode change tracking with retries
- ✅ External change detection
- ✅ Pellet tracking and notifications
- ✅ Timer countdowns
- ✅ Auto start/stop detection
- ✅ Wood mode support
- ✅ Temperature monitoring and alerts

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

### Adding Translations

To add a new language:

1. Copy `translations/en.json` to `translations/[lang].json`
2. Translate all text values
3. Submit a pull request

### Reporting Unknown States

If your stove reports states not in the integration:

1. Check logs for state warnings
2. Create a GitHub issue with:
   - State number
   - Stove model
   - The state and substate number
   - The corresponding state and substate in aduro hybrid application

See [ADDING_STATES.md](ADDING_STATES.md) for details.

## Development plans/wish list

- For beta-releases: test that all functions are working as intended.
- Update integration with all relevant translations between state/substates-numbers and their related text string.
- Get confirmation/information about the remaining Aduro hybrid stoves.
- Estimation of pellets consumption over time, depending on temperature settings, heat level settings, outside temperature and other relevant factors to estimate a time for when the stove have consumed all pellets.
- External and wireless temperature sensor is available as an accessory. Could it be possible to use other temperature sensors and send the information to the stove via Home Assistant?

## Aduro Stove Card

A custom and optional Lovelace card for controlling Aduro Hybrid Stoves in Home Assistant can be found here: [Aduro Stove Card](https://github.com/NewImproved/Aduro-Stove-Card)

<img width="506" height="737" alt="image" src="https://github.com/user-attachments/assets/cded111a-f0ad-4f3e-81bf-48fa15ca4b49" />


### Features

- **Real-time Status Display** - Shows current stove state and operation mode
- **Temperature & Heat Level Control** - Easy +/- buttons for quick adjustments
- **Pellet Monitoring** - Visual pellet level indicator and a consumption since cleaning indicator
- **CO level** - CO level indicator with the yellow and red thresholds
- **Power Control** - Start/stop the stove with a single tap
- **Mode Toggle** - Switch between Heat Level and Temperature modes
- **Auto-Resume & Auto-Shutdown** - Configure automatic behavior for wood mode and low pellet levels
- **Maintenance Tracking** - Quick access to pellet refill and stove cleaning buttons
- **Change Indicator** - Visual feedback when stove settings are updating

### Languages

- English
- French
- German
- Swedish
- Easy to add more languages

## Credits

This integration is built upon the excellent work of:

- **[Clément Prévot](https://github.com/clementprevot)** - Creator of [pyduro](https://github.com/clementprevot/pyduro), the Python library for controlling Aduro hybrid stoves
- **[SpaceTeddy](https://github.com/SpaceTeddy)** - Creator of [Home Assistant Aduro stove control scripts](https://github.com/SpaceTeddy/homeassistant_aduro_stove_control_python_scripts)

## License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/NewImproved/Aduro/edit/main/LICENSE.md) file for details.

This project incorporates code from:
- [pyduro](https://github.com/clementprevot/pyduro) by Clément Prévot (MIT License)
- [homeassistant_aduro_stove_control_python_scripts](https://github.com/SpaceTeddy/homeassistant_aduro_stove_control_python_scripts) by SpaceTeddy (GPL-2.0 license)

See [NOTICE](https://github.com/NewImproved/Aduro/edit/main/NOTICE.md) file for full third-party attribution details.

## Disclaimer

This is an unofficial integration and is not affiliated with or endorsed by Aduro. Use at your own risk.

## Support

- 🐛 [Report bugs](https://github.com/NewImproved/Aduro/issues)
- 💡 [Request features](https://github.com/NewImproved/Aduro/issues)
- 📖 [Documentation](https://github.com/NewImproved/Aduro)
- 💬 [Discussions](https://github.com/NewImproved/Aduro/discussions)

---

**Enjoy your smart Aduro stove! 🔥**

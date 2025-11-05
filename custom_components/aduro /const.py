"""Constants for the Aduro Hybrid Stove integration."""
from datetime import timedelta
from typing import Final

DOMAIN: Final = "aduro"
PLATFORMS: Final = ["sensor", "switch", "number", "button"]

# Configuration keys
CONF_STOVE_SERIAL: Final = "stove_serial"
CONF_STOVE_PIN: Final = "stove_pin"
CONF_STOVE_MODEL: Final = "stove_model"
CONF_MQTT_HOST: Final = "mqtt_host"
CONF_MQTT_PORT: Final = "mqtt_port"
CONF_MQTT_USERNAME: Final = "mqtt_username"
CONF_MQTT_PASSWORD: Final = "mqtt_password"
CONF_MQTT_BASE_PATH: Final = "mqtt_base_path"

# Stove models
STOVE_MODEL_H1: Final = "H1"
STOVE_MODEL_H2: Final = "H2"
STOVE_MODEL_H3: Final = "H3"
STOVE_MODEL_H4: Final = "H4"
STOVE_MODEL_H5: Final = "H5"
STOVE_MODEL_H6: Final = "H6"

STOVE_MODELS: Final = [
    STOVE_MODEL_H1,
    STOVE_MODEL_H2,
    STOVE_MODEL_H3,
    STOVE_MODEL_H4,
    STOVE_MODEL_H5,
    STOVE_MODEL_H6,
]

STOVE_MODEL_BASE_PATHS: Final = {
    STOVE_MODEL_H1: "aduro_h1/",
    STOVE_MODEL_H2: "aduro_h2/",
    STOVE_MODEL_H3: "aduro_h3/",
    STOVE_MODEL_H4: "aduro_h4/",
    STOVE_MODEL_H5: "aduro_h5/",
    STOVE_MODEL_H6: "aduro_h6/",
}

# Defaults
DEFAULT_STOVE_MODEL: Final = STOVE_MODEL_H2
DEFAULT_MQTT_PORT: Final = 1883
DEFAULT_MQTT_BASE_PATH: Final = STOVE_MODEL_BASE_PATHS[STOVE_MODEL_H2]
DEFAULT_SCAN_INTERVAL: Final = timedelta(seconds=20)
DEFAULT_CAPACITY_PELLETS: Final = 9.5
DEFAULT_NOTIFICATION_LEVEL: Final = 10
DEFAULT_SHUTDOWN_LEVEL: Final = 5

# Stove operation modes
OPERATION_MODE_HEATLEVEL: Final = 0
OPERATION_MODE_TEMPERATURE: Final = 1
OPERATION_MODE_WOOD: Final = 2

OPERATION_MODES: Final = {
    0: "heatlevel",
    1: "temperature",
    2: "wood"
}

# Heat levels
HEAT_LEVEL_MIN: Final = 1
HEAT_LEVEL_MAX: Final = 3
HEAT_LEVEL_STEP: Final = 1

HEAT_LEVEL_DISPLAY: Final = {
    1: "I",
    2: "II",
    3: "III"
}

# Heat level to power mappings (for pyduro communication)
HEAT_LEVEL_POWER_MAP: Final = {
    10: 1,
    50: 2,
    100: 3,
}

POWER_HEAT_LEVEL_MAP: Final = {
    1: 10,
    2: 50,
    3: 100,
}

# Temperature settings
TEMP_MIN: Final = 5
TEMP_MAX: Final = 35
TEMP_STEP: Final = 1

# Pellet capacity settings
PELLET_CAPACITY_MIN: Final = 9.0
PELLET_CAPACITY_MAX: Final = 10.0
PELLET_CAPACITY_STEP: Final = 0.1

# Notification settings
NOTIFICATION_LEVEL_MIN: Final = 0
NOTIFICATION_LEVEL_MAX: Final = 20
NOTIFICATION_LEVEL_STEP: Final = 1

# Shutdown settings
SHUTDOWN_LEVEL_MIN: Final = -10
SHUTDOWN_LEVEL_MAX: Final = 15
SHUTDOWN_LEVEL_STEP: Final = 1

# State mappings - Main states with formatting support
# These keys are used for translation lookups
STATE_NAMES: Final = {
    "0": "state_operating",
    "2": "state_operating",
    "4": "state_operating",
    "5": "state_operating",
    "6": "state_stopped",
    "9": "state_off",
    "13": "state_stopped",
    "14": "state_off",
    "20": "state_stopped",
    "28": "state_stopped",
    "32": "state_operating_iii",
    "34": "state_stopped",
}

# Substate descriptions - Keys for translation
SUBSTATE_NAMES: Final = {
    "0": "substate_waiting",
    "2": "substate_ignition_1",
    "4": "substate_ignition_2",
    "5": "substate_normal",
    "6": "substate_temp_reached",
    "9": "substate_wood_burning",
    "13": "substate_failed_ignition",
    "14_0": "substate_by_button",
    "14_1": "substate_wood_burning_question",
    "20": "substate_no_fuel",
    "28": "substate_unknown",
    "32": "substate_heating_up",
    "34": "substate_check_burn_cup",
}

# Display versions (for when translations aren't available)
STATE_NAMES_DISPLAY: Final = {
    "0": "Operating {heatlevel}",
    "2": "Operating {heatlevel}",
    "4": "Operating {heatlevel}",
    "5": "Operating {heatlevel}",
    "6": "Stopped",
    "9": "Off",
    "13": "Stopped",
    "14": "Off",
    "20": "Stopped",
    "28": "Stopped",
    "32": "Operating III",
    "34": "Stopped",
}

SUBSTATE_NAMES_DISPLAY: Final = {
    "0": "Waiting",
    "2": "Ignition 1",
    "4": "Ignition 2",
    "5": "Normal",
    "6": "Room temperature reached",
    "9": "Wood burning",
    "13": "Failed ignition - Open door and check burner for pellet accumulation",
    "14_0": "By button",
    "14_1": "Wood burning?",
    "20": "No fuel",
    "28": "Unknown",
    "32": "Heating up",
    "34": "Check burn cup",
}

# State classifications
STARTUP_STATES: Final = ["0", "2", "4", "5", "32"]
SHUTDOWN_STATES: Final = ["6", "9", "13", "14", "20", "28", "34"]

# For backward compatibility and additional detail
STOVE_STATES_ON: Final = STARTUP_STATES
STOVE_STATES_OFF: Final = SHUTDOWN_STATES

# Timer durations (in seconds)
TIMER_STARTUP_1: Final = 870  # 14:30 minutes
TIMER_STARTUP_2: Final = 870  # 14:30 minutes

# Sensor attributes
ATTR_HEATLEVEL: Final = "heatlevel"
ATTR_OPERATION_MODE: Final = "operation_mode"
ATTR_BOILER_REF: Final = "boiler_ref"
ATTR_BOILER_TEMP: Final = "boiler_temp"
ATTR_STATE: Final = "state"
ATTR_SUBSTATE: Final = "substate"
ATTR_PELLETS_AMOUNT: Final = "pellets_amount"
ATTR_PELLETS_PERCENTAGE: Final = "pellets_percentage"
ATTR_PELLETS_CONSUMED: Final = "pellets_consumed"
ATTR_CONSUMPTION_RATE: Final = "consumption_rate"
ATTR_CONSUMPTION_TOTAL: Final = "consumption_total"
ATTR_CONSUMPTION_DAY: Final = "consumption_day"
ATTR_CONSUMPTION_YESTERDAY: Final = "consumption_yesterday"
ATTR_CONSUMPTION_MONTH: Final = "consumption_month"
ATTR_CONSUMPTION_YEAR: Final = "consumption_year"
ATTR_REFILL_COUNTER: Final = "refill_counter"

# Services
SERVICE_START_STOVE: Final = "start_stove"
SERVICE_STOP_STOVE: Final = "stop_stove"
SERVICE_SET_HEATLEVEL: Final = "set_heatlevel"
SERVICE_SET_TEMPERATURE: Final = "set_temperature"
SERVICE_SET_OPERATION_MODE: Final = "set_operation_mode"
SERVICE_TOGGLE_MODE: Final = "toggle_mode"
SERVICE_REFILL_PELLETS: Final = "refill_pellets"
SERVICE_CLEAN_STOVE: Final = "clean_stove"
SERVICE_RESUME_AFTER_WOOD: Final = "resume_after_wood_mode"

# Icons
ICON_FIREPLACE: Final = "mdi:fireplace"
ICON_FIRE: Final = "mdi:fire"
ICON_THERMOMETER: Final = "mdi:thermometer"
ICON_CAMPFIRE: Final = "mdi:campfire"
ICON_SYNC: Final = "mdi:sync-circle"
ICON_HELP: Final = "mdi:help-circle"
ICON_PELLET: Final = "mdi:grain"
ICON_POWER: Final = "mdi:power"

# Update intervals
UPDATE_INTERVAL_NORMAL: Final = timedelta(seconds=20)
UPDATE_INTERVAL_FAST: Final = timedelta(seconds=5)
UPDATE_COUNT_AFTER_COMMAND: Final = 8  # Number of fast updates after command (40 seconds total)

# Timeouts for state transitions
TIMEOUT_MODE_TRANSITION: Final = 60  # seconds - reduced from 120
TIMEOUT_CHANGE_IN_PROGRESS: Final = 120  # seconds - reduced from 300
TIMEOUT_COMMAND_RESPONSE: Final = 30  # seconds - wait for command acknowledgment

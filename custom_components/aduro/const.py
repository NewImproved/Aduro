"""Constants for the Aduro Hybrid Stove integration."""
from datetime import timedelta
from typing import Final

DOMAIN: Final = "aduro"
PLATFORMS: Final = ["sensor", "switch", "number", "button"]

# Configuration keys
CONF_STOVE_SERIAL: Final = "stove_serial"
CONF_STOVE_PIN: Final = "stove_pin"
CONF_STOVE_MODEL: Final = "stove_model"
CONF_STOVE_IP: Final = "stove_ip"

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

# Defaults
DEFAULT_STOVE_MODEL: Final = STOVE_MODEL_H2
DEFAULT_SCAN_INTERVAL: Final = timedelta(seconds=20)
DEFAULT_CAPACITY_PELLETS: Final = 9.1
DEFAULT_NOTIFICATION_LEVEL: Final = 10
DEFAULT_SHUTDOWN_LEVEL: Final = 5

# Temperature Alert Defaults
DEFAULT_HIGH_SMOKE_TEMP: Final = 370  # °C
DEFAULT_HIGH_SMOKE_DURATION: Final = 30  # seconds
DEFAULT_LOW_WOOD_TEMP: Final = 175  # °C
DEFAULT_LOW_WOOD_DURATION: Final = 300  # seconds (5 minutes)

# Temperature Alert Limits
HIGH_SMOKE_TEMP_MIN: Final = 300
HIGH_SMOKE_TEMP_MAX: Final = 450
HIGH_SMOKE_TEMP_STEP: Final = 10
HIGH_SMOKE_DURATION_MIN: Final = 60  # 1 minute
HIGH_SMOKE_DURATION_MAX: Final = 1800  # 30 minutes
HIGH_SMOKE_DURATION_STEP: Final = 60  # 1 minute steps

LOW_WOOD_TEMP_MIN: Final = 20
LOW_WOOD_TEMP_MAX: Final = 200
LOW_WOOD_TEMP_STEP: Final = 5
LOW_WOOD_DURATION_MIN: Final = 60  # 1 minute
LOW_WOOD_DURATION_MAX: Final = 1800  # 30 minutes
LOW_WOOD_DURATION_STEP: Final = 60  # 1 minute steps

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
PELLET_CAPACITY_MIN: Final = 8.0
PELLET_CAPACITY_MAX: Final = 25.0
PELLET_CAPACITY_STEP: Final = 0.1

# Notification settings
NOTIFICATION_LEVEL_MIN: Final = 0
NOTIFICATION_LEVEL_MAX: Final = 100
NOTIFICATION_LEVEL_STEP: Final = 1

# Shutdown settings
SHUTDOWN_LEVEL_MIN: Final = 0
SHUTDOWN_LEVEL_MAX: Final = 100
SHUTDOWN_LEVEL_STEP: Final = 1

# State mappings - Main states with formatting support
# These keys are used for translation lookups
STATE_NAMES: Final = {
    "0": "state_operating",
    "2": "state_operating",
    "4": "state_operating",
    "5": "state_operating",
    "6": "state_stopped",
    "9": "state_stopped",
    "11": "state_stopped_draft",
    "13": "state_stopped",
    "14": "state_off",
    "15": "state_stopped_smoke_sensor",
    "17": "state_stopped_dropshaft",
    "18": "state_stopped_burner_yellow",
    "19": "state_stopped_auger",
    "20": "state_stopped",
    "23": "state_stopped_timer",
    "24": "state_operating_air_damper",
    "28": "state_stopped",
    "32": "state_operating_iii",
    "33": "state_stopped_co_sensor",
    "34": "state_stopped",
    "35": "state_stopped_no_fan",
}

# Substate descriptions - Keys for translation
SUBSTATE_NAMES: Final = {
    "0": "substate_waiting",
    "2": "substate_ignition_1",
    "4": "substate_ignition_2",
    "5": "substate_normal",
    "6": "substate_temp_reached",
    "9": "substate_wood_burning",
    "11": "substate_dropshaft_hot",
    "13": "substate_failed_ignition",
    "14_0": "substate_by_button",
    "14_1": "substate_wood_burning_question",
    "20": "substate_no_fuel",
    "28": "substate_door_open",
    "32": "substate_heating_up",
    "34": "substate_check_burn_cup",
}

# Display versions (for when translations aren't available)
STATE_NAMES_DISPLAY: Final = {
    "state_operating": "Power {heatlevel}",
    "state_stopped": "Stopped",
    "state_off": "Off",
    "state_operating_iii": "Power III",
    "state_stopped_draft": "Dropshaft hot",
    "state_stopped_smoke_sensor": "Bad smoke sensor",
    "state_stopped_dropshaft": "Bad dropshaft sensor",
    "state_stopped_burner_yellow": "Check burner yellow",
    "state_stopped_auger": "bad external auger output",
    "state_stopped_timer": "Stopped by timer",
    "state_operating_air_damper": "Air damper closed",
    "state_stopped_co_sensor": "Co sensor defect",
    "state_stopped_no_fan": "No power consumption for fan",
}

SUBSTATE_NAMES_DISPLAY: Final = {
    "0": "Wait",
    "2": "Ignition",
    "4": "Ignition 2",
    "5": "Normal",
    "6": "Room temperature reached",
    "9": "Wood burning",
    "13": "Failed ignition - Open door and check burner for pellet accumulation",
    "14_0": "By button",
    "14_1": "Wood burning?",
    "20": "No fuel",
    "28": "Door open",
    "32": "Heating up",
    "34": "Check burn cup",
}

# State classifications
STARTUP_STATES: Final = ["0", "2", "4", "5", "6", "9", "24", "32"]
SHUTDOWN_STATES: Final = ["11", "13", "14", "15", "17", "18", "19", "20", "23", "28", "33", "34", "35"]

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
ICON_ALERT: Final = "mdi:alert"
ICON_ALERT_CIRCLE: Final = "mdi:alert-circle-outline"

# Update intervals
UPDATE_INTERVAL_NORMAL: Final = timedelta(seconds=45)
UPDATE_INTERVAL_FAST: Final = timedelta(seconds=5)
UPDATE_COUNT_AFTER_COMMAND: Final = 5  # Number of fast updates after command (25 seconds total)

# Timeouts for state transitions
TIMEOUT_MODE_TRANSITION: Final = 100  # seconds - reduced from 120
TIMEOUT_CHANGE_IN_PROGRESS: Final = 100  # seconds - reduced from 300
TIMEOUT_COMMAND_RESPONSE: Final = 30  # seconds - wait for command acknowledgment

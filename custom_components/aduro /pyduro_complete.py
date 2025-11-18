#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Custom pyduro implementation for Aduro H2 stove control and monitoring.
This module is designed to work within a Home Assistant custom integration.
"""

import json
import time
from datetime import date, timedelta

# Try to import pyduro, but make functions work standalone if not available
try:
    from pyduro.actions import FUNCTIONS, STATUS_PARAMS, discover, get, set, raw
    HAS_PYDURO = True
except ImportError:
    HAS_PYDURO = False
    STATUS_PARAMS = {}  # Will be populated dynamically

CLOUD_BACKUP_ADDRESS = "apprelay20.stokercloud.dk"

# ------------------------------------------------------------------------------
# Discovery Functions

def get_discovery_data(aduro_cloud_backup_address=CLOUD_BACKUP_ADDRESS):
    """
    Get stove discovery data including serial, IP, type, version, etc.
    Falls back to cloud address if local discovery fails.
    
    Returns:
        tuple: (result, ip, serial, mqtt_json_data)
    """
    if not HAS_PYDURO:
        return -1, "no connection", " ", "{}"
    
    result = 0
    serial = " "
    ip = "no connection"
    device_type = " "
    version = " "
    build = " "
    lang = " "
    mqtt_json_data = " "

    try:
        response = discover.run()
        response = response.parse_payload()
    except Exception as err:
        result = -1
        discovery_json = {
            "DISCOVERY": {
                "StoveSerial": serial,
                "StoveIP": ip,
                "NBE_Type": device_type,
                "StoveSWVersion": version,
                "StoveSWBuild": build,
                "StoveLanguage": lang
            }
        }
        mqtt_json_data = json.dumps(discovery_json)
        return result, ip, serial, mqtt_json_data

    response = json.dumps(response)
    data = json.loads(response)

    # Extract variables
    serial = data['Serial']
    ip = data['IP']
    device_type = data['Type']
    version = data['Ver']
    build = data['Build']
    lang = data['Lang']

    # Check if IP is valid, fallback to Stove Cloud address if not valid
    if "0.0.0.0" in ip:
        ip = aduro_cloud_backup_address

    if response:
        discovery_json = {
            "DISCOVERY": {
                "StoveSerial": serial,
                "StoveIP": ip,
                "NBE_Type": device_type,
                "StoveSWVersion": version,
                "StoveSWBuild": build,
                "StoveLanguage": lang
            }
        }
        mqtt_json_data = json.dumps(discovery_json)
        result = 0
        return result, ip, serial, mqtt_json_data
    else:
        result = -1
        return result, ip, serial, mqtt_json_data

# ------------------------------------------------------------------------------
# Status and Monitoring Functions

def get_status(ip, serial, pin):
    """
    Get comprehensive stove status including all STATUS_PARAMS.
    
    Returns:
        tuple: (result, mqtt_json_data)
    """
    if not HAS_PYDURO:
        return -1, "{}"
    
    result = 0
    mqtt_json_data = " "

    try:
        response = raw.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            function_id=11,
            payload="*"
        )

        status = response.parse_payload().split(",")
        response = response.parse_payload()
    except Exception as err:
        result = -1
        return result, mqtt_json_data

    i = 0
    for key in STATUS_PARAMS:
        STATUS_PARAMS[key] = status[i]
        i += 1

    if response:
        status_json = {"STATUS": STATUS_PARAMS}
        mqtt_json_data = json.dumps(status_json)
        result = 0
        return result, mqtt_json_data
    
    return -1, mqtt_json_data

def get_network_data(ip, serial, pin):
    """
    Get stove network information including WiFi details.
    
    Returns:
        tuple: (result, mqtt_json_data)
    """
    if not HAS_PYDURO:
        return -1, "{}"
    
    result = 0
    mqtt_json_data = " "

    try:
        response = raw.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            function_id=1,
            payload="wifi.router"
        )

        data = response.payload.split(',')
        response = response.parse_payload()
    except Exception as err:
        result = -1
        return result, mqtt_json_data

    stove_ssid = data[0][7:(len(data[0]))]
    stove_ip = data[4]
    router_ip = data[5]
    stove_rssi = data[6]
    stove_mac = data[9]

    if response:
        network_json = {
            "NETWORK": {
                "RouterSSID": stove_ssid,
                "StoveIP": stove_ip,
                "RouterIP": router_ip,
                "StoveRSSI": stove_rssi,
                "StoveMAC": stove_mac
            }
        }
        mqtt_json_data = json.dumps(network_json)
        result = 0
        return result, mqtt_json_data
    
    return -1, mqtt_json_data

def get_operating_data(ip, serial, pin):
    """
    Get detailed operating data including temperatures, power, and runtime.
    
    Returns:
        tuple: (result, mqtt_json_data)
    """
    if not HAS_PYDURO:
        return -1, "{}"
    
    result = 0
    mqtt_json_data = " "

    try:
        response = raw.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            function_id=11,
            payload="001*"
        )
        data = response.payload.split(',')
        response = response.parse_payload()
    except Exception as err:
        result = -1
        return result, mqtt_json_data

    # Extract operating parameters
    boiler_temp = data[0]
    boiler_ref = data[1]
    dhw_temp = data[4]
    state = data[6]
    substate = data[5]
    power_kw = data[31]
    power_pct = data[36]
    shaft_temp = data[35]
    smoke_temp = data[37]
    internet_uptime = data[38]
    milli_ampere = data[24]
    oxygen = data[26]
    router_ssid = data[68]
    date_stove = data[94][0:5] + "/" + str(20) + data[94][6:8]
    time_stove = data[94][9:(len(data[94]))]
    operating_time_auger = data[119]      # in seconds
    operating_time_ignition = data[120]   # in seconds
    operating_time_stove = data[121]      # in seconds

    if response:
        operating_data_json = {
            "OPERATING": {
                "Power_kw": power_kw,
                "Power_pct": power_pct,
                "SmokeTemp": smoke_temp,
                "ShaftTemp": shaft_temp,
                "TimeStove": time_stove,
                "DateStove": date_stove,
                "State": state,
                "OperatingTimeAuger": operating_time_auger,
                "OperatingTimeStove": operating_time_stove,
                "OperatingTimeIgnition": operating_time_ignition
            }
        }
        mqtt_json_data = json.dumps(operating_data_json)
        result = 0
        return result, mqtt_json_data
    
    return -1, mqtt_json_data

def get_consumption_data(ip, serial, pin):
    """
    Get consumption data for day, month, and year.
    
    Returns:
        tuple: (result, mqtt_json_data)
    """
    if not HAS_PYDURO:
        return -1, "{}"
    
    result = 0

    # Get daily consumption
    try:
        response = raw.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            function_id=6,
            payload="total_days"
        )

        data = response.payload.split(',')
        response = response.parse_payload()
    except Exception as err:
        result = -1
        return result

    data[0] = data[0][11:(len(data[0]))]  # remove total_days from string

    today = date.today().day
    yesterday = date.today() - timedelta(1)
    yesterday = yesterday.day

    consumption_today = data[today - 1]
    consumption_yesterday = data[yesterday - 1]

    # Get monthly consumption
    try:
        response = raw.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            function_id=6,
            payload="total_months"
        )

        data = response.payload.split(',')
        response = response.parse_payload()
    except Exception as err:
        result = -1
        return result, "{}"

    data[0] = data[0][13:(len(data[0]))]  # remove total_month from string
    month = date.today().month
    consumption_month = data[month - 1]

    # Get yearly consumption
    try:
        response = raw.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            function_id=6,
            payload="total_years"
        )

        data = response.payload.split(',')
        response = response.parse_payload()
    except Exception as err:
        result = -1
        return result, "{}"

    data[0] = data[0][12:(len(data[0]))]  # remove total_years from string

    year = date.today().year
    # Calculate data array position from current year. 2013 is data[0]...
    data_position_offset = len(data) - 1

    if response:
        consumption_json = {
            "CONSUMPTION": {
                "Day": consumption_today,
                "Yesterday": consumption_yesterday,
                "Month": consumption_month,
                "Year": data[data_position_offset]
            }
        }
        mqtt_json_data = json.dumps(consumption_json)
        result = 0
        return result, mqtt_json_data
    
    return -1, "{}"

# ------------------------------------------------------------------------------
# Control Functions

def set_heatlevel(ip, serial, pin, heatlevel):
    """
    Set the heatlevel (1-3) by converting to fixed_power values.
    
    Args:
        heatlevel: 1, 2, or 3
    
    Returns:
        int: 0 for success, -1 for failure
    """
    if not HAS_PYDURO:
        return -1
    
    if heatlevel == 1:
        fixed_power = 10
    elif heatlevel == 2:
        fixed_power = 50
    elif heatlevel == 3:
        fixed_power = 100
    else:
        return -1

    try:
        response = set.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            path="regulation.fixed_power",
            value=fixed_power
        )
        data = response.parse_payload()

        if data == "":
            return 0
        else:
            return -1
    except Exception as err:
        return -1

def set_boiler_ref(ip, serial, pin, set_ref_temp):
    """
    Set the boiler reference temperature.
    
    Returns:
        int: 0 for success, -1 for failure
    """
    if not HAS_PYDURO:
        return -1
    
    try:
        response = set.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            path="boiler.temp",
            value=set_ref_temp
        )
        data = response.parse_payload()

        if data == "":
            return 0
        else:
            return -1
    except Exception as err:
        return -1

def set_operation_mode_ref(ip, serial, pin, set_ref_operation_mode):
    """
    Set the operation mode (0=heatlevel, 1=temperature, 2=wood).
    
    Returns:
        int: 0 for success, -1 for failure
    """
    if not HAS_PYDURO:
        return -1
    
    try:
        response = set.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            path="regulation.operation_mode",
            value=set_ref_operation_mode
        )
        data = response.parse_payload()

        if data == "":
            return 0
        else:
            return -1
    except Exception as err:
        return -1

def set_start_stop(ip, serial, pin, start_stop):
    """
    Start or stop the stove pellet operation.
    
    Args:
        start_stop: "start" or "stop"
    
    Returns:
        int: 0 for success, -1 for failure
    """
    if not HAS_PYDURO:
        return -1
    
    if start_stop == "start":
        set_value = "misc.start"
    elif start_stop == "stop":
        set_value = "misc.stop"
    else:
        return -1

    try:
        response = set.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            path=set_value,
            value=1
        )
        data = response.parse_payload()

        if data == "":
            return 0
        else:
            return -1
    except Exception as err:
        return -1

def set_force_auger(ip, serial, pin):
    """
    Force the auger to run (for testing/manual pellet feed).
    
    Returns:
        int: 0 for success, -1 for failure
    """
    if not HAS_PYDURO:
        return -1
    
    try:
        response = set.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            path="auger.forced_run",
            value=1
        )
        data = response.parse_payload()

        if data == "":
            return 0
        else:
            return -1
    except Exception as err:
        return -1

def set_custom(ip, serial, pin, custom_path, custom_value):
    """
    Set a custom parameter by path and value.
    
    Returns:
        int: 0 for success, -1 for failure
    """
    if not HAS_PYDURO:
        return -1
    
    try:
        response = set.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            path=custom_path,
            value=custom_value
        )
        data = response.parse_payload()

        if data == "":
            return 0
        else:
            return -1
    except Exception as err:
        return -1
    """
    Get stove discovery data including serial, IP, type, version, etc.
    Falls back to cloud address if local discovery fails.
    
    Returns:
        tuple: (result, ip, serial, mqtt_json_data)
    """
    result = 0
    serial = " "
    ip = "no connection"
    device_type = " "
    version = " "
    build = " "
    lang = " "
    mqtt_json_data = " "
    discovery_json = " "

    try:
        response = discover.run()
        response = response.parse_payload()
    except:
        result = -1
        discovery_json = {
            "DISCOVERY": {
                "StoveSerial": serial,
                "StoveIP": ip,
                "NBE_Type": device_type,
                "StoveSWVersion": version,
                "StoveSWBuild": build,
                "StoveLanguage": lang
            }
        }
        mqtt_json_data = json.dumps(discovery_json)
        return result, ip, serial, mqtt_json_data

    response = json.dumps(response)
    data = json.loads(response)

    # Extract variables
    serial = data['Serial']
    ip = data['IP']
    device_type = data['Type']
    version = data['Ver']
    build = data['Build']
    lang = data['Lang']

    # Check if IP is valid, fallback to Stove Cloud address if not valid
    if "0.0.0.0" in ip:
        ip = aduro_cloud_backup_address

    if response:
        discovery_json = {
            "DISCOVERY": {
                "StoveSerial": serial,
                "StoveIP": ip,
                "NBE_Type": device_type,
                "StoveSWVersion": version,
                "StoveSWBuild": build,
                "StoveLanguage": lang
            }
        }
        mqtt_json_data = json.dumps(discovery_json)
        result = 0
        return result, ip, serial, mqtt_json_data
    else:
        result = -1
        return result, ip, serial, mqtt_json_data

# ------------------------------------------------------------------------------
# Status and Monitoring Functions

def get_status(ip, serial, pin):
    """
    Get comprehensive stove status including all STATUS_PARAMS.
    
    Returns:
        tuple: (result, mqtt_json_data)
    """
    result = 0
    mqtt_json_data = " "

    try:
        response = raw.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            function_id=11,
            payload="*"
        )

        status = response.parse_payload().split(",")
        response = response.parse_payload()
    except:
        result = -1
        return result, mqtt_json_data

    i = 0
    for key in STATUS_PARAMS:
        STATUS_PARAMS[key] = status[i]
        i += 1

    if response:
        status_json = {"STATUS": STATUS_PARAMS}
        mqtt_json_data = json.dumps(status_json)
        result = 0
        return result, mqtt_json_data

def get_network_data(ip, serial, pin):
    """
    Get stove network information including WiFi details.
    
    Returns:
        tuple: (result, mqtt_json_data)
    """
    result = 0
    mqtt_json_data = " "

    try:
        response = raw.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            function_id=1,
            payload="wifi.router"
        )

        data = response.payload.split(',')
        response = response.parse_payload()
    except:
        result = -1
        return result, mqtt_json_data

    stove_ssid = data[0][7:(len(data[0]))]
    stove_ip = data[4]
    router_ip = data[5]
    stove_rssi = data[6]
    stove_mac = data[9]

    if response:
        network_json = {
            "NETWORK": {
                "RouterSSID": stove_ssid,
                "StoveIP": stove_ip,
                "RouterIP": router_ip,
                "StoveRSSI": stove_rssi,
                "StoveMAC": stove_mac
            }
        }
        mqtt_json_data = json.dumps(network_json)
        result = 0
        return result, mqtt_json_data

def get_operating_data(ip, serial, pin):
    """
    Get detailed operating data including temperatures, power, and runtime.
    
    Returns:
        tuple: (result, mqtt_json_data)
    """
    result = 0
    mqtt_json_data = " "

    try:
        response = raw.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            function_id=11,
            payload="001*"
        )
        data = response.payload.split(',')
        response = response.parse_payload()
    except:
        result = -1
        return result, mqtt_json_data

    # Extract operating parameters
    boiler_temp = data[0]
    boiler_ref = data[1]
    dhw_temp = data[4]
    state = data[6]
    substate = data[5]
    power_kw = data[31]
    power_pct = data[36]
    shaft_temp = data[35]
    smoke_temp = data[37]
    internet_uptime = data[38]
    milli_ampere = data[24]
    oxygen = data[26]
    router_ssid = data[68]
    date_stove = data[94][0:5] + "/" + str(20) + data[94][6:8]
    time_stove = data[94][9:(len(data[94]))]
    operating_time_auger = data[119]      # in seconds
    operating_time_ignition = data[120]   # in seconds
    operating_time_stove = data[121]      # in seconds

    if response:
        operating_data_json = {
            "OPERATING": {
                "Power_kw": power_kw,
                "Power_pct": power_pct,
                "SmokeTemp": smoke_temp,
                "ShaftTemp": shaft_temp,
                "TimeStove": time_stove,
                "DateStove": date_stove,
                "State": state,
                "OperatingTimeAuger": operating_time_auger,
                "OperatingTimeStove": operating_time_stove,
                "OperatingTimeIgnition": operating_time_ignition
            }
        }
        mqtt_json_data = json.dumps(operating_data_json)
        result = 0
        return result, mqtt_json_data

def get_consumption_data(ip, serial, pin):
    """
    Get consumption data for day, month, and year.
    
    Returns:
        tuple: (result, mqtt_json_data)
    """
    result = 0

    # Get daily consumption
    try:
        response = raw.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            function_id=6,
            payload="total_days"
        )

        data = response.payload.split(',')
        response = response.parse_payload()
    except:
        result = -1
        return result

    data[0] = data[0][11:(len(data[0]))]  # remove total_days from string

    today = date.today().day
    yesterday = date.today() - timedelta(1)
    yesterday = yesterday.day

    consumption_today = data[today - 1]
    consumption_yesterday = data[yesterday - 1]

    # Get monthly consumption
    try:
        response = raw.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            function_id=6,
            payload="total_months"
        )

        data = response.payload.split(',')
        response = response.parse_payload()
    except:
        result = -1
        return result, mqtt_json_data

    data[0] = data[0][13:(len(data[0]))]  # remove total_month from string
    month = date.today().month
    consumption_month = data[month - 1]

    # Get yearly consumption
    try:
        response = raw.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            function_id=6,
            payload="total_years"
        )

        data = response.payload.split(',')
        response = response.parse_payload()
    except:
        result = -1
        return result, mqtt_json_data

    data[0] = data[0][12:(len(data[0]))]  # remove total_years from string

    year = date.today().year
    # Calculate data array position from current year. 2013 is data[0]...
    data_position_offset = year - (year - (len(data) - 1))

    if response:
        consumption_json = {
            "CONSUMPTION": {
                "Day": consumption_today,
                "Yesterday": consumption_yesterday,
                "Month": consumption_month,
                "Year": data[data_position_offset]
            }
        }
        mqtt_json_data = json.dumps(consumption_json)
        result = 0
        return result, mqtt_json_data

# ------------------------------------------------------------------------------
# Control Functions

def set_heatlevel(ip, serial, pin, heatlevel):
    """
    Set the heatlevel (1-3) by converting to fixed_power values.
    
    Args:
        heatlevel: 1, 2, or 3
    
    Returns:
        int: 0 for success, -1 for failure
    """
    if heatlevel == 1:
        fixed_power = 10
    elif heatlevel == 2:
        fixed_power = 50
    elif heatlevel == 3:
        fixed_power = 100
    else:
        return -1

    try:
        response = set.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            path="regulation.fixed_power",
            value=fixed_power
        )
        data = response.parse_payload()

        if data == "":
            return 0
        else:
            return -1
    except:
        return -1

def set_boiler_ref(ip, serial, pin, set_ref_temp):
    """
    Set the boiler reference temperature.
    
    Returns:
        int: 0 for success, -1 for failure
    """
    try:
        response = set.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            path="boiler.temp",
            value=set_ref_temp
        )
        data = response.parse_payload()

        if data == "":
            return 0
        else:
            return -1
    except:
        return -1

def set_operation_mode_ref(ip, serial, pin, set_ref_operation_mode):
    """
    Set the operation mode (0=heatlevel, 1=temperature, 2=wood).
    
    Returns:
        int: 0 for success, -1 for failure
    """
    try:
        response = set.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            path="regulation.operation_mode",
            value=set_ref_operation_mode
        )
        data = response.parse_payload()

        if data == "":
            return 0
        else:
            return -1
    except:
        return -1

def set_start_stop(ip, serial, pin, start_stop):
    """
    Start or stop the stove pellet operation.
    
    Args:
        start_stop: "start" or "stop"
    
    Returns:
        int: 0 for success, -1 for failure
    """
    if start_stop == "start":
        set_value = "misc.start"
    elif start_stop == "stop":
        set_value = "misc.stop"
    else:
        return -1

    try:
        response = set.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            path=set_value,
            value=1
        )
        data = response.parse_payload()

        if data == "":
            return 0
        else:
            return -1
    except:
        return -1

def set_force_auger(ip, serial, pin):
    """
    Force the auger to run (for testing/manual pellet feed).
    
    Returns:
        int: 0 for success, -1 for failure
    """
    try:
        response = set.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            path="auger.forced_run",
            value=1
        )
        data = response.parse_payload()

        if data == "":
            return 0
        else:
            return -1
    except:
        return -1

def set_custom(ip, serial, pin, custom_path, custom_value):
    """
    Set a custom parameter by path and value.
    
    Returns:
        int: 0 for success, -1 for failure
    """
    try:
        response = set.run(
            burner_address=str(ip),
            serial=str(serial),
            pin_code=str(pin),
            path=custom_path,
            value=custom_value
        )
        data = response.parse_payload()

        if data == "":
            return 0
        else:
            return -1
    except:
        return -1

# ------------------------------------------------------------------------------
# MAIN EXECUTION

# logger.info(f"starting Pyduro script!")

# Initialize MQTT client if server IP is provided
if MQTT_SERVER_IP is not None:
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.username_pw_set(username=MQTT_USERNAME, password=MQTT_PASSWORD)
    client.connect(MQTT_SERVER_IP, MQTT_SERVER_PORT, 60)
    client.subscribe(MQTT_BASE_PATH)
    client.loop_start()

# Get previous discovered stove IP from Home Assistant
ip = hass.states.get('sensor.aduro_h2_stove_ip').state
# logger.info(f"IP from HA:{ ip}")

# Check if IP is valid, fallback to Stove Cloud address if not valid
aduro_cloud_backup_address = "apprelay20.stokercloud.dk"

# Workaround if stove lost router ipv4 -> switch to cloud server address
if "0.0.0.0" in ip or ip == "unknown" or ip == "no connection" or ip == aduro_cloud_backup_address:
    try:
        result, ip, serial, mqtt_json_discover_data = get_discovery_data()
        if "0.0.0.0" in ip:
            ip = aduro_cloud_backup_address

        discovery_json = json.loads(mqtt_json_discover_data)
        discovery_json['DISCOVERY']['StoveIP'] = ip
        discovery_json['DISCOVERY']['StoveSerial'] = serial
        mqtt_json_discover_data = json.dumps(discovery_json)

        if MQTT_SERVER_IP is not None:
            client.publish(MQTT_BASE_PATH + "discovery", str(mqtt_json_discover_data))
            time.sleep(0.2)
    except:
        # logger.info(f"Discovery Exception!")
        if MQTT_SERVER_IP is not None:
            client.disconnect()
        exit()

# ------------------------------------------------------------------------------
# Execute requested MODE operation

# Get Stove Discovery data
if MODE == "discover" or MODE == "all":
    try:
        result, ip, serial, mqtt_json_discover_data = get_discovery_data()
        client.publish(MQTT_BASE_PATH + "discovery", str(mqtt_json_discover_data))
        time.sleep(0.2)
    except:
        # Retries 3 times
        for x in range(0, 3):
            time.sleep(1)
            result, ip, serial, mqtt_json_discover_data = get_discovery_data()
            if result != -1:
                client.publish(MQTT_BASE_PATH + "discovery", str(mqtt_json_discover_data))
                time.sleep(0.2)
                break

# Get Stove network data
if MODE == "network" or MODE == "all":
    try:
        result, mqtt_json_network_data = get_network_data(ip, STOVE_SERIAL, STOVE_PIN)
        client.publish(MQTT_BASE_PATH + "network", str(mqtt_json_network_data))
        time.sleep(0.2)
    except:
        # Retries 3 times
        for x in range(0, 3):
            time.sleep(1)
            result, ip, serial, mqtt_json_discover_data = get_discovery_data()
            result, mqtt_json_network_data = get_network_data(ip, STOVE_SERIAL, STOVE_PIN)
            if result != -1:
                client.publish(MQTT_BASE_PATH + "network", str(mqtt_json_network_data))
                time.sleep(0.2)
                break

# Get consumption data
if MODE == "consumption" or MODE == "all":
    try:
        result, mqtt_json_consumption_data = get_consumption_data(ip, STOVE_SERIAL, STOVE_PIN)
        client.publish(MQTT_BASE_PATH + "consumption_data", str(mqtt_json_consumption_data))
        time.sleep(0.2)
    except:
        # Retries 3 times
        for x in range(0, 3):
            time.sleep(1)
            result, ip, serial, mqtt_json_discover_data = get_discovery_data()
            result, mqtt_json_consumption_data = get_consumption_data(ip, STOVE_SERIAL, STOVE_PIN)
            if result != -1:
                client.publish(MQTT_BASE_PATH + "consumption_data", str(mqtt_json_consumption_data))
                time.sleep(0.2)
                break

# Get Status
if MODE == "status" or MODE == "all":
    try:
        result, mqtt_json_status_data = get_status(ip, STOVE_SERIAL, STOVE_PIN)
        client.publish(MQTT_BASE_PATH + "status", str(mqtt_json_status_data))
        time.sleep(0.2)
    except:
        # Retries 3 times
        for x in range(0, 3):
            time.sleep(1)
            result, ip, serial, mqtt_json_discover_data = get_discovery_data()
            result, mqtt_json_status_data = get_status(ip, STOVE_SERIAL, STOVE_PIN)
            if result != -1:
                client.publish(MQTT_BASE_PATH + "status", str(mqtt_json_status_data))
                time.sleep(0.2)
                break

# Set heatlevel
if MODE == "set_heatlevel":
    try:
        result = set_heatlevel(ip, STOVE_SERIAL, STOVE_PIN, STOVE_HEATLEVEL)
    except:
        # Retries 3 times
        for x in range(0, 3):
            time.sleep(1)
            result, ip, serial, mqtt_json_discover_data = get_discovery_data()
            result = set_heatlevel(ip, STOVE_SERIAL, STOVE_PIN, STOVE_HEATLEVEL)
            if result != -1:
                break

# Set boiler reference temperature
if MODE == "set_temp":
    try:
        result = set_boiler_ref(ip, STOVE_SERIAL, STOVE_PIN, STOVE_BOIL_REF)
    except:
        # Retries 3 times
        for x in range(0, 3):
            time.sleep(1)
            result, ip, serial, mqtt_json_discover_data = get_discovery_data()
            result = set_boiler_ref(ip, STOVE_SERIAL, STOVE_PIN, STOVE_BOIL_REF)
            if result != -1:
                break

# Set operation mode
if MODE == "set_operation_mode":
    try:
        result = set_operation_mode_ref(ip, STOVE_SERIAL, STOVE_PIN, STOVE_OPERATION_MODE)
    except:
        # Retries 3 times
        for x in range(0, 3):
            time.sleep(1)
            result, ip, serial, mqtt_json_discover_data = get_discovery_data()
            result = set_operation_mode_ref(ip, STOVE_SERIAL, STOVE_PIN, STOVE_OPERATION_MODE)
            if result != -1:
                break

# Start/Stop stove
if MODE == "set_start_stop":
    try:
        result = set_start_stop(ip, STOVE_SERIAL, STOVE_PIN, STOVE_START_STOP)
    except:
        # Retries 3 times
        for x in range(0, 3):
            time.sleep(1)
            result, ip, serial, mqtt_json_discover_data = get_discovery_data()
            result = set_start_stop(ip, STOVE_SERIAL, STOVE_PIN, STOVE_START_STOP)
            if result != -1:
                break

# Force auger run
if MODE == "set_force_auger":
    try:
        result = set_force_auger(ip, STOVE_SERIAL, STOVE_PIN)
    except:
        # Retries 3 times
        for x in range(0, 3):
            time.sleep(1)
            result, ip, serial, mqtt_json_discover_data = get_discovery_data()
            result = set_force_auger(ip, STOVE_SERIAL, STOVE_PIN)
            if result != -1:
                break

# Set custom parameter
if MODE == "set_custom":
    try:
        result = set_custom(ip, STOVE_SERIAL, STOVE_PIN, STOVE_PATH, STOVE_VALUE)
    except:
        # Retries 3 times
        for x in range(0, 3):
            time.sleep(1)
            result, ip, serial, mqtt_json_discover_data = get_discovery_data()
            result = set_custom(ip, STOVE_SERIAL, STOVE_PIN, STOVE_PATH, STOVE_VALUE)
            if result != -1:
                break

# ------------------------------------------------------------------------------
# Cleanup
if MQTT_SERVER_IP is not None:
    client.disconnect()

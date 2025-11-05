"""Wrapper for custom pyduro implementation."""
from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Try to import standard pyduro first, fall back to custom implementation
try:
    from pyduro.actions import discover, get, set, raw, STATUS_PARAMS
    _LOGGER.info("Using standard pyduro library")
    USING_CUSTOM_PYDURO = False
except ImportError:
    _LOGGER.warning("Standard pyduro not found, using custom implementation")
    USING_CUSTOM_PYDURO = True
    # Custom implementation will be loaded below


class CustomPyduroWrapper:
    """Wrapper for custom pyduro implementation."""
    
    def __init__(self):
        """Initialize the wrapper."""
        # Import your custom implementation here
        # This assumes pyduro_complete.py functions are available
        pass
    
    @staticmethod
    async def discover_stove():
        """Discover stove on network."""
        # Call your custom get_discovery_data function
        from .pyduro_complete import get_discovery_data
        result, ip, serial, mqtt_json_data = get_discovery_data()
        
        if result == 0:
            import json
            data = json.loads(mqtt_json_data)
            return {
                'IP': ip,
                'Serial': serial,
                'Type': data['DISCOVERY'].get('NBE_Type', ''),
                'Ver': data['DISCOVERY'].get('StoveSWVersion', ''),
                'Build': data['DISCOVERY'].get('StoveSWBuild', ''),
                'Lang': data['DISCOVERY'].get('StoveLanguage', ''),
            }
        return None
    
    @staticmethod
    async def get_status(ip: str, serial: str, pin: str):
        """Get stove status."""
        from .pyduro_complete import get_status
        result, mqtt_json_data = get_status(ip, serial, pin)
        
        if result == 0:
            import json
            data = json.loads(mqtt_json_data)
            return data['STATUS']
        return None
    
    @staticmethod
    async def get_operating_data(ip: str, serial: str, pin: str):
        """Get operating data."""
        from .pyduro_complete import get_operating_data
        result, mqtt_json_data = get_operating_data(ip, serial, pin)
        
        if result == 0:
            import json
            data = json.loads(mqtt_json_data)
            return data['OPERATING']
        return None
    
    @staticmethod
    async def get_network_data(ip: str, serial: str, pin: str):
        """Get network data."""
        from .pyduro_complete import get_network_data
        result, mqtt_json_data = get_network_data(ip, serial, pin)
        
        if result == 0:
            import json
            data = json.loads(mqtt_json_data)
            return data['NETWORK']
        return None
    
    @staticmethod
    async def get_consumption_data(ip: str, serial: str, pin: str):
        """Get consumption data."""
        from .pyduro_complete import get_consumption_data
        result, mqtt_json_data = get_consumption_data(ip, serial, pin)
        
        if result == 0:
            import json
            data = json.loads(mqtt_json_data)
            return data['CONSUMPTION']
        return None
    
    @staticmethod
    async def set_heatlevel(ip: str, serial: str, pin: str, heatlevel: int):
        """Set heat level."""
        from .pyduro_complete import set_heatlevel
        result = set_heatlevel(ip, serial, pin, heatlevel)
        return result == 0
    
    @staticmethod
    async def set_temperature(ip: str, serial: str, pin: str, temperature: float):
        """Set temperature."""
        from .pyduro_complete import set_boiler_ref
        result = set_boiler_ref(ip, serial, pin, temperature)
        return result == 0
    
    @staticmethod
    async def set_operation_mode(ip: str, serial: str, pin: str, mode: int):
        """Set operation mode."""
        from .pyduro_complete import set_operation_mode_ref
        result = set_operation_mode_ref(ip, serial, pin, mode)
        return result == 0
    
    @staticmethod
    async def set_start_stop(ip: str, serial: str, pin: str, action: str):
        """Start or stop the stove."""
        from .pyduro_complete import set_start_stop
        result = set_start_stop(ip, serial, pin, action)
        return result == 0
    
    @staticmethod
    async def set_force_auger(ip: str, serial: str, pin: str):
        """Force auger to run."""
        from .pyduro_complete import set_force_auger
        result = set_force_auger(ip, serial, pin)
        return result == 0
    
    @staticmethod
    async def set_custom(ip: str, serial: str, pin: str, path: str, value: Any):
        """Set custom parameter."""
        from .pyduro_complete import set_custom
        result = set_custom(ip, serial, pin, path, value)
        return result == 0


# Mock STATUS_PARAMS if using custom implementation
if USING_CUSTOM_PYDURO:
    STATUS_PARAMS = {
        'consumption_total': 0,
        'operation_mode': 0,
        # Add other STATUS_PARAMS keys as needed
    }

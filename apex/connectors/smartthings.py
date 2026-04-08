"""
Samsung SmartThings Connector

Real SmartThings API integration for IoT and smart home control.

Usage:
    from connectors.smartthings import SmartThingsConnector
    
    smartthings = SmartThingsConnector()
    await smartthings.connect()
    
    # List devices
    devices = await smartthings.list_devices()
    
    # Control device
    await smartthings.execute_command(device_id, "switch", "on")
    
    # Get device status
    status = await smartthings.get_device_status(device_id)
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False


class DeviceCategory(Enum):
    """SmartThings device categories."""
    LIGHT = "Light"
    SWITCH = "Switch"
    THERMOSTAT = "Thermostat"
    LOCK = "Lock"
    SENSOR = "Sensor"
    CAMERA = "Camera"
    SPEAKER = "Speaker"
    TV = "Television"
    GARAGE = "GarageDoor"
    BLIND = "Blind"
    FAN = "Fan"
    OUTLET = "Outlet"
    HUB = "Hub"
    OTHER = "Other"


class CapabilityType(Enum):
    """Common SmartThings capabilities."""
    SWITCH = "switch"
    SWITCH_LEVEL = "switchLevel"
    COLOR_CONTROL = "colorControl"
    COLOR_TEMPERATURE = "colorTemperature"
    THERMOSTAT_MODE = "thermostatMode"
    THERMOSTAT_COOLING_SETPOINT = "thermostatCoolingSetpoint"
    THERMOSTAT_HEATING_SETPOINT = "thermostatHeatingSetpoint"
    LOCK = "lock"
    MOTION_SENSOR = "motionSensor"
    CONTACT_SENSOR = "contactSensor"
    TEMPERATURE_MEASUREMENT = "temperatureMeasurement"
    HUMIDITY_MEASUREMENT = "relativeHumidityMeasurement"
    BATTERY = "battery"
    DOOR_CONTROL = "doorControl"
    WINDOW_SHADE = "windowShade"
    FAN_SPEED = "fanSpeed"
    MEDIA_PLAYBACK = "mediaPlayback"
    AUDIO_VOLUME = "audioVolume"


@dataclass
class Device:
    """Represents a SmartThings device."""
    id: str
    name: str
    label: Optional[str]
    device_type_name: str
    location_id: str
    room_id: Optional[str]
    capabilities: List[str]
    category: DeviceCategory
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    status: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def display_name(self) -> str:
        return self.label or self.name
    
    def has_capability(self, capability: str) -> bool:
        return capability in self.capabilities
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "label": self.label,
            "display_name": self.display_name,
            "device_type": self.device_type_name,
            "location_id": self.location_id,
            "room_id": self.room_id,
            "capabilities": self.capabilities,
            "category": self.category.value,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "status": self.status,
        }


@dataclass
class Location:
    """Represents a SmartThings location."""
    id: str
    name: str
    country_code: str
    timezone_id: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    temperature_scale: str = "F"
    locale: str = "en"
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "country_code": self.country_code,
            "timezone": self.timezone_id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "temperature_scale": self.temperature_scale,
        }


@dataclass
class Room:
    """Represents a room in a SmartThings location."""
    id: str
    name: str
    location_id: str
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "location_id": self.location_id,
        }


@dataclass
class Scene:
    """Represents a SmartThings scene."""
    id: str
    name: str
    location_id: str
    icon: Optional[str] = None
    color: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "location_id": self.location_id,
            "icon": self.icon,
            "color": self.color,
        }


@dataclass
class Rule:
    """Represents a SmartThings automation rule."""
    id: str
    name: str
    location_id: str
    enabled: bool = True
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "location_id": self.location_id,
            "enabled": self.enabled,
        }


class SmartThingsConnector:
    """
    SmartThings API connector for IoT device control.
    
    Features:
    - Device discovery and listing
    - Device status monitoring
    - Command execution
    - Scene activation
    - Automation rules
    - Location and room management
    """
    
    BASE_URL = "https://api.smartthings.com/v1"
    
    def __init__(self, access_token: Optional[str] = None):
        self.access_token = access_token
        self._session: Optional[aiohttp.ClientSession] = None
        self._connected = False
        self._locations_cache: Dict[str, Location] = {}
        self._devices_cache: Dict[str, Device] = {}
    
    async def connect(self, access_token: Optional[str] = None) -> bool:
        """Connect to SmartThings API."""
        if not HAS_AIOHTTP:
            raise ImportError("aiohttp required: pip install aiohttp")
        
        if access_token:
            self.access_token = access_token
        
        if not self.access_token:
            raise ValueError("SmartThings access token required")
        
        self._session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            }
        )
        
        # Verify connection
        try:
            locations = await self.list_locations()
            self._connected = True
            return True
        except Exception as e:
            await self.disconnect()
            raise ConnectionError(f"Failed to connect to SmartThings: {e}")
    
    async def disconnect(self):
        """Disconnect from SmartThings API."""
        if self._session:
            await self._session.close()
            self._session = None
        self._connected = False
        self._locations_cache.clear()
        self._devices_cache.clear()
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ) -> Dict:
        """Make authenticated API request."""
        if not self._session:
            raise ConnectionError("Not connected to SmartThings")
        
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        
        async with self._session.request(
            method, url, json=data, params=params
        ) as response:
            if response.status == 401:
                raise PermissionError("Invalid or expired access token")
            if response.status == 403:
                raise PermissionError("Insufficient permissions")
            if response.status == 404:
                raise ValueError(f"Resource not found: {endpoint}")
            if response.status >= 400:
                error_body = await response.text()
                raise Exception(f"SmartThings API error {response.status}: {error_body}")
            
            if response.status == 204:
                return {}
            
            return await response.json()
    
    # ==================== Locations ====================
    
    async def list_locations(self) -> List[Location]:
        """List all SmartThings locations."""
        result = await self._request("GET", "locations")
        
        locations = []
        for item in result.get("items", []):
            location = Location(
                id=item["locationId"],
                name=item["name"],
                country_code=item.get("countryCode", "US"),
                timezone_id=item.get("timeZoneId", "America/New_York"),
                latitude=item.get("latitude"),
                longitude=item.get("longitude"),
                temperature_scale=item.get("temperatureScale", "F"),
                locale=item.get("locale", "en"),
            )
            locations.append(location)
            self._locations_cache[location.id] = location
        
        return locations
    
    async def get_location(self, location_id: str) -> Location:
        """Get a specific location."""
        if location_id in self._locations_cache:
            return self._locations_cache[location_id]
        
        item = await self._request("GET", f"locations/{location_id}")
        
        location = Location(
            id=item["locationId"],
            name=item["name"],
            country_code=item.get("countryCode", "US"),
            timezone_id=item.get("timeZoneId", "America/New_York"),
            latitude=item.get("latitude"),
            longitude=item.get("longitude"),
            temperature_scale=item.get("temperatureScale", "F"),
        )
        self._locations_cache[location.id] = location
        return location
    
    # ==================== Rooms ====================
    
    async def list_rooms(self, location_id: str) -> List[Room]:
        """List rooms in a location."""
        result = await self._request("GET", f"locations/{location_id}/rooms")
        
        rooms = []
        for item in result.get("items", []):
            rooms.append(Room(
                id=item["roomId"],
                name=item["name"],
                location_id=location_id,
            ))
        
        return rooms
    
    async def create_room(self, location_id: str, name: str) -> Room:
        """Create a new room."""
        result = await self._request(
            "POST",
            f"locations/{location_id}/rooms",
            data={"name": name}
        )
        
        return Room(
            id=result["roomId"],
            name=result["name"],
            location_id=location_id,
        )
    
    async def delete_room(self, location_id: str, room_id: str) -> bool:
        """Delete a room."""
        await self._request("DELETE", f"locations/{location_id}/rooms/{room_id}")
        return True
    
    # ==================== Devices ====================
    
    async def list_devices(
        self,
        location_id: Optional[str] = None,
        capability: Optional[str] = None,
    ) -> List[Device]:
        """List all devices, optionally filtered by location or capability."""
        params = {}
        if location_id:
            params["locationId"] = location_id
        if capability:
            params["capability"] = capability
        
        result = await self._request("GET", "devices", params=params)
        
        devices = []
        for item in result.get("items", []):
            device = self._parse_device(item)
            devices.append(device)
            self._devices_cache[device.id] = device
        
        return devices
    
    def _parse_device(self, item: Dict) -> Device:
        """Parse device data from API response."""
        capabilities = []
        for comp in item.get("components", []):
            for cap in comp.get("capabilities", []):
                cap_id = cap.get("id", "")
                if cap_id and cap_id not in capabilities:
                    capabilities.append(cap_id)
        
        category_str = item.get("deviceTypeName", "Other")
        try:
            category = DeviceCategory(category_str)
        except ValueError:
            category = DeviceCategory.OTHER
        
        return Device(
            id=item["deviceId"],
            name=item.get("name", "Unknown"),
            label=item.get("label"),
            device_type_name=item.get("deviceTypeName", ""),
            location_id=item.get("locationId", ""),
            room_id=item.get("roomId"),
            capabilities=capabilities,
            category=category,
            manufacturer=item.get("manufacturerName"),
            model=item.get("deviceManufacturerCode"),
        )
    
    async def get_device(self, device_id: str) -> Device:
        """Get a specific device."""
        item = await self._request("GET", f"devices/{device_id}")
        device = self._parse_device(item)
        self._devices_cache[device.id] = device
        return device
    
    async def get_device_status(self, device_id: str) -> Dict[str, Any]:
        """Get the full status of a device."""
        result = await self._request("GET", f"devices/{device_id}/status")
        
        status = {}
        for comp_name, comp_data in result.get("components", {}).items():
            for cap_name, cap_data in comp_data.items():
                for attr_name, attr_data in cap_data.items():
                    key = f"{cap_name}.{attr_name}" if comp_name == "main" else f"{comp_name}.{cap_name}.{attr_name}"
                    status[key] = attr_data.get("value")
        
        return status
    
    async def get_device_health(self, device_id: str) -> Dict[str, Any]:
        """Get device health/connectivity status."""
        result = await self._request("GET", f"devices/{device_id}/health")
        return {
            "state": result.get("state"),
            "last_updated": result.get("lastUpdatedDate"),
        }
    
    # ==================== Device Commands ====================
    
    async def execute_command(
        self,
        device_id: str,
        capability: str,
        command: str,
        arguments: Optional[List[Any]] = None,
        component: str = "main",
    ) -> Dict[str, Any]:
        """Execute a command on a device."""
        cmd_data = {
            "commands": [{
                "component": component,
                "capability": capability,
                "command": command,
                "arguments": arguments or [],
            }]
        }
        
        result = await self._request(
            "POST",
            f"devices/{device_id}/commands",
            data=cmd_data
        )
        
        return result
    
    async def turn_on(self, device_id: str) -> Dict:
        """Turn on a device (switch capability)."""
        return await self.execute_command(device_id, "switch", "on")
    
    async def turn_off(self, device_id: str) -> Dict:
        """Turn off a device (switch capability)."""
        return await self.execute_command(device_id, "switch", "off")
    
    async def set_level(self, device_id: str, level: int) -> Dict:
        """Set brightness/level (0-100)."""
        level = max(0, min(100, level))
        return await self.execute_command(
            device_id, "switchLevel", "setLevel", [level]
        )
    
    async def set_color(
        self,
        device_id: str,
        hue: int,
        saturation: int,
    ) -> Dict:
        """Set color (hue 0-100, saturation 0-100)."""
        return await self.execute_command(
            device_id,
            "colorControl",
            "setColor",
            [{"hue": hue, "saturation": saturation}]
        )
    
    async def set_color_temperature(
        self,
        device_id: str,
        temperature: int,
    ) -> Dict:
        """Set color temperature (Kelvin, typically 2700-6500)."""
        return await self.execute_command(
            device_id,
            "colorTemperature",
            "setColorTemperature",
            [temperature]
        )
    
    async def lock(self, device_id: str) -> Dict:
        """Lock a lock device."""
        return await self.execute_command(device_id, "lock", "lock")
    
    async def unlock(self, device_id: str) -> Dict:
        """Unlock a lock device."""
        return await self.execute_command(device_id, "lock", "unlock")
    
    async def set_thermostat_mode(self, device_id: str, mode: str) -> Dict:
        """Set thermostat mode (heat, cool, auto, off)."""
        return await self.execute_command(
            device_id, "thermostatMode", "setThermostatMode", [mode]
        )
    
    async def set_cooling_setpoint(self, device_id: str, temperature: float) -> Dict:
        """Set cooling setpoint temperature."""
        return await self.execute_command(
            device_id,
            "thermostatCoolingSetpoint",
            "setCoolingSetpoint",
            [temperature]
        )
    
    async def set_heating_setpoint(self, device_id: str, temperature: float) -> Dict:
        """Set heating setpoint temperature."""
        return await self.execute_command(
            device_id,
            "thermostatHeatingSetpoint",
            "setHeatingSetpoint",
            [temperature]
        )
    
    async def open_door(self, device_id: str) -> Dict:
        """Open a garage door or similar."""
        return await self.execute_command(device_id, "doorControl", "open")
    
    async def close_door(self, device_id: str) -> Dict:
        """Close a garage door or similar."""
        return await self.execute_command(device_id, "doorControl", "close")
    
    async def set_shade_level(self, device_id: str, level: int) -> Dict:
        """Set window shade level (0=closed, 100=open)."""
        level = max(0, min(100, level))
        return await self.execute_command(
            device_id, "windowShade", "setShadeLevel", [level]
        )
    
    async def set_fan_speed(self, device_id: str, speed: int) -> Dict:
        """Set fan speed (0-100)."""
        speed = max(0, min(100, speed))
        return await self.execute_command(
            device_id, "fanSpeed", "setFanSpeed", [speed]
        )
    
    # ==================== Scenes ====================
    
    async def list_scenes(self, location_id: Optional[str] = None) -> List[Scene]:
        """List all scenes."""
        params = {}
        if location_id:
            params["locationId"] = location_id
        
        result = await self._request("GET", "scenes", params=params)
        
        scenes = []
        for item in result.get("items", []):
            scenes.append(Scene(
                id=item["sceneId"],
                name=item["sceneName"],
                location_id=item.get("locationId", ""),
                icon=item.get("sceneIcon"),
                color=item.get("sceneColor"),
            ))
        
        return scenes
    
    async def execute_scene(self, scene_id: str) -> Dict:
        """Execute/activate a scene."""
        return await self._request("POST", f"scenes/{scene_id}/execute")
    
    # ==================== Rules/Automations ====================
    
    async def list_rules(self, location_id: str) -> List[Rule]:
        """List automation rules for a location."""
        result = await self._request(
            "GET",
            "rules",
            params={"locationId": location_id}
        )
        
        rules = []
        for item in result.get("items", []):
            rules.append(Rule(
                id=item["id"],
                name=item["name"],
                location_id=location_id,
                enabled=item.get("enabled", True),
            ))
        
        return rules
    
    async def enable_rule(self, rule_id: str, location_id: str) -> Dict:
        """Enable an automation rule."""
        return await self._request(
            "POST",
            f"rules/{rule_id}/enable",
            params={"locationId": location_id}
        )
    
    async def disable_rule(self, rule_id: str, location_id: str) -> Dict:
        """Disable an automation rule."""
        return await self._request(
            "POST",
            f"rules/{rule_id}/disable",
            params={"locationId": location_id}
        )
    
    async def execute_rule(self, rule_id: str, location_id: str) -> Dict:
        """Manually execute a rule."""
        return await self._request(
            "POST",
            f"rules/execute/{rule_id}",
            params={"locationId": location_id}
        )
    
    # ==================== Device Groups ====================
    
    async def list_devices_by_room(
        self,
        location_id: str,
        room_id: str,
    ) -> List[Device]:
        """List devices in a specific room."""
        all_devices = await self.list_devices(location_id=location_id)
        return [d for d in all_devices if d.room_id == room_id]
    
    async def list_devices_by_capability(
        self,
        capability: str,
        location_id: Optional[str] = None,
    ) -> List[Device]:
        """List devices with a specific capability."""
        return await self.list_devices(
            location_id=location_id,
            capability=capability
        )
    
    async def get_lights(self, location_id: Optional[str] = None) -> List[Device]:
        """Get all light devices."""
        return await self.list_devices_by_capability("switch", location_id)
    
    async def get_thermostats(self, location_id: Optional[str] = None) -> List[Device]:
        """Get all thermostat devices."""
        return await self.list_devices_by_capability("thermostatMode", location_id)
    
    async def get_locks(self, location_id: Optional[str] = None) -> List[Device]:
        """Get all lock devices."""
        return await self.list_devices_by_capability("lock", location_id)
    
    async def get_sensors(self, location_id: Optional[str] = None) -> List[Device]:
        """Get all sensor devices."""
        devices = await self.list_devices(location_id=location_id)
        sensor_caps = {"motionSensor", "contactSensor", "temperatureMeasurement"}
        return [d for d in devices if any(c in sensor_caps for c in d.capabilities)]
    
    # ==================== Bulk Operations ====================
    
    async def turn_off_all_lights(self, location_id: str) -> List[Dict]:
        """Turn off all lights in a location."""
        lights = await self.get_lights(location_id)
        results = []
        for light in lights:
            if light.has_capability("switch"):
                result = await self.turn_off(light.id)
                results.append({"device_id": light.id, "result": result})
        return results
    
    async def set_all_lights_level(
        self,
        location_id: str,
        level: int,
    ) -> List[Dict]:
        """Set all dimmable lights to a level."""
        lights = await self.get_lights(location_id)
        results = []
        for light in lights:
            if light.has_capability("switchLevel"):
                result = await self.set_level(light.id, level)
                results.append({"device_id": light.id, "result": result})
        return results
    
    async def lock_all(self, location_id: str) -> List[Dict]:
        """Lock all locks in a location."""
        locks = await self.get_locks(location_id)
        results = []
        for lock in locks:
            result = await self.lock(lock.id)
            results.append({"device_id": lock.id, "result": result})
        return results


# Convenience function
def get_smartthings_connector(access_token: Optional[str] = None) -> SmartThingsConnector:
    """Get a SmartThings connector instance."""
    return SmartThingsConnector(access_token)

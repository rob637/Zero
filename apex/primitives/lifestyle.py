"""Telic Engine — Lifestyle Primitives"""

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from .base import Primitive, StepResult

logger = logging.getLogger(__name__)


class FinancePrimitive(Primitive):
    """Financial operations — invoices, payments, customers, subscriptions.
    
    Wires to Stripe for real payment processing.
    Falls back to local tracking when no provider is connected.
    """
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._providers = providers or {}
        self._local_transactions: List[Dict] = []
        self._budgets: Dict[str, Dict] = {}
    
    @property
    def name(self) -> str:
        return "FINANCE"
    
    def get_operations(self) -> Dict[str, str]:
        return self.get_available_operations()
    
    def get_available_operations(self) -> Dict[str, str]:
        return {
            "balance": "Get account balance",
            "customers": "List customers",
            "invoices": "List invoices",
            "create_invoice": "Create a new invoice",
            "charges": "List recent charges/payments",
            "subscriptions": "List active subscriptions",
            "products": "List products",
            "spending": "Get spending summary (local tracking)",
            "budget": "Create or view a budget (local tracking)",
        }
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "balance": {},
            "customers": {"limit": {"type": "int", "description": "Max results (default 20)"}, "email": {"type": "str", "description": "Filter by email"}},
            "invoices": {"customer_id": {"type": "str", "description": "Customer ID (optional)"}, "limit": {"type": "int", "description": "Max results"}},
            "create_invoice": {"customer_id": {"type": "str", "required": True, "description": "Customer ID"}, "description": {"type": "str", "description": "Invoice description"}},
            "charges": {"customer_id": {"type": "str", "description": "Customer ID (optional)"}, "limit": {"type": "int", "description": "Max results"}},
            "subscriptions": {"customer_id": {"type": "str", "description": "Customer ID (optional)"}, "limit": {"type": "int", "description": "Max results"}},
            "products": {"limit": {"type": "int", "description": "Max results"}},
            "spending": {"period": {"type": "str", "description": "month, week, year"}, "category": {"type": "str", "description": "Category (optional)"}},
            "budget": {"category": {"type": "str", "description": "Budget category"}, "amount": {"type": "float", "description": "Budget amount"}, "period": {"type": "str", "description": "month, week"}},
        }
    
    def get_connected_providers(self) -> List[str]:
        return list(self._providers.keys())
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            # Try real providers (Stripe, etc.)
            for name, provider in self._providers.items():
                if operation == "balance" and hasattr(provider, "get_balance"):
                    result = await provider.get_balance()
                    return StepResult(True, data={"balance": result, "provider": name})
                
                elif operation == "customers" and hasattr(provider, "list_customers"):
                    result = await provider.list_customers(
                        limit=params.get("limit", 20),
                        email=params.get("email"),
                    )
                    return StepResult(True, data={"customers": result, "provider": name})
                
                elif operation == "invoices" and hasattr(provider, "list_invoices"):
                    result = await provider.list_invoices(
                        customer_id=params.get("customer_id"),
                        limit=params.get("limit", 20),
                    )
                    return StepResult(True, data={"invoices": result, "provider": name})
                
                elif operation == "create_invoice" and hasattr(provider, "create_invoice"):
                    result = await provider.create_invoice(
                        customer_id=params["customer_id"],
                        description=params.get("description"),
                    )
                    return StepResult(True, data={"invoice": result, "provider": name})
                
                elif operation == "charges" and hasattr(provider, "list_charges"):
                    result = await provider.list_charges(
                        customer_id=params.get("customer_id"),
                        limit=params.get("limit", 20),
                    )
                    return StepResult(True, data={"charges": result, "provider": name})
                
                elif operation == "subscriptions" and hasattr(provider, "list_subscriptions"):
                    result = await provider.list_subscriptions(
                        customer_id=params.get("customer_id"),
                        limit=params.get("limit", 20),
                    )
                    return StepResult(True, data={"subscriptions": result, "provider": name})
                
                elif operation == "products" and hasattr(provider, "list_products"):
                    result = await provider.list_products(limit=params.get("limit", 20))
                    return StepResult(True, data={"products": result, "provider": name})
            
            # Local fallback for non-provider operations
            if operation == "balance":
                return StepResult(True, data={"balance": 0.0, "currency": "USD", "provider": "local", "note": "Connect Stripe for real balance"})
            elif operation == "spending":
                period = params.get("period", "month")
                category = params.get("category")
                return StepResult(True, data={"spending": {}, "period": period, "category": category, "provider": "local"})
            elif operation == "budget":
                category = params.get("category", "general")
                amount = params.get("amount")
                period = params.get("period", "month")
                if amount:
                    self._budgets[category] = {"amount": amount, "period": period}
                return StepResult(True, data={"budgets": self._budgets, "provider": "local"})
            elif operation in ("customers", "invoices", "charges", "subscriptions", "products"):
                return StepResult(True, data={operation: [], "provider": "local", "note": "Connect Stripe for real financial data"})
            elif operation == "create_invoice":
                return StepResult(True, data={"invoice": None, "provider": "local", "note": "Connect Stripe to create invoices"})
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  SOCIAL PRIMITIVE - Social media
# ============================================================



class HomePrimitive(Primitive):
    """Smart home operations — lights, thermostat, locks, scenes.
    
    Wires to SmartThings (or other smart home connectors) for real device control.
    Falls back to local simulation when no provider is connected.
    """
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._providers = providers or {}
        self._devices: Dict[str, Dict] = {}
    
    @property
    def name(self) -> str:
        return "HOME"
    
    def get_operations(self) -> Dict[str, str]:
        return self.get_available_operations()
    
    def get_available_operations(self) -> Dict[str, str]:
        return {
            "devices": "List all smart home devices",
            "status": "Get device status and current state",
            "on": "Turn a device on",
            "off": "Turn a device off",
            "brightness": "Set light brightness level (0-100)",
            "temperature": "Set thermostat temperature",
            "lock": "Lock a smart lock",
            "unlock": "Unlock a smart lock",
            "scenes": "List available scenes/routines",
            "run_scene": "Run a scene or routine",
        }
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "devices": {"location_id": {"type": "str", "description": "Location ID (optional — lists all if omitted)"}},
            "status": {"device_id": {"type": "str", "required": True, "description": "Device ID"}},
            "on": {"device_id": {"type": "str", "required": True, "description": "Device ID"}},
            "off": {"device_id": {"type": "str", "required": True, "description": "Device ID"}},
            "brightness": {"device_id": {"type": "str", "required": True, "description": "Device ID"}, "level": {"type": "int", "required": True, "description": "Brightness 0-100"}},
            "temperature": {"device_id": {"type": "str", "required": True, "description": "Thermostat device ID"}, "temperature": {"type": "int", "required": True, "description": "Temperature in degrees"}, "mode": {"type": "str", "description": "heat, cool, or auto"}},
            "lock": {"device_id": {"type": "str", "required": True, "description": "Lock device ID"}},
            "unlock": {"device_id": {"type": "str", "required": True, "description": "Lock device ID"}},
            "scenes": {"location_id": {"type": "str", "description": "Location ID (optional)"}},
            "run_scene": {"scene_id": {"type": "str", "required": True, "description": "Scene ID"}},
        }
    
    def get_connected_providers(self) -> List[str]:
        return list(self._providers.keys())
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            # Try real providers first (SmartThings, etc.)
            for name, provider in self._providers.items():
                if operation == "devices" and hasattr(provider, "list_devices"):
                    result = await provider.list_devices(location_id=params.get("location_id"))
                    devices = [d.to_dict() if hasattr(d, 'to_dict') else d for d in result]
                    return StepResult(True, data={"devices": devices, "count": len(devices), "provider": name})
                
                elif operation == "status" and hasattr(provider, "get_device_status"):
                    result = await provider.get_device_status(params["device_id"])
                    return StepResult(True, data={"status": result, "provider": name})
                
                elif operation == "on" and hasattr(provider, "turn_on"):
                    await provider.turn_on(params["device_id"])
                    return StepResult(True, data={"on": True, "device_id": params["device_id"], "provider": name})
                
                elif operation == "off" and hasattr(provider, "turn_off"):
                    await provider.turn_off(params["device_id"])
                    return StepResult(True, data={"off": True, "device_id": params["device_id"], "provider": name})
                
                elif operation == "brightness" and hasattr(provider, "set_level"):
                    await provider.set_level(params["device_id"], params["level"])
                    return StepResult(True, data={"brightness": params["level"], "device_id": params["device_id"], "provider": name})
                
                elif operation == "temperature" and hasattr(provider, "set_heating_setpoint"):
                    mode = params.get("mode", "heat")
                    if mode == "cool" and hasattr(provider, "set_cooling_setpoint"):
                        await provider.set_cooling_setpoint(params["device_id"], params["temperature"])
                    else:
                        await provider.set_heating_setpoint(params["device_id"], params["temperature"])
                    if hasattr(provider, "set_thermostat_mode") and params.get("mode"):
                        await provider.set_thermostat_mode(params["device_id"], params["mode"])
                    return StepResult(True, data={"temperature": params["temperature"], "mode": mode, "provider": name})
                
                elif operation == "lock" and hasattr(provider, "lock"):
                    await provider.lock(params["device_id"])
                    return StepResult(True, data={"locked": True, "device_id": params["device_id"], "provider": name})
                
                elif operation == "unlock" and hasattr(provider, "unlock"):
                    await provider.unlock(params["device_id"])
                    return StepResult(True, data={"unlocked": True, "device_id": params["device_id"], "provider": name})
                
                elif operation == "scenes" and hasattr(provider, "list_scenes"):
                    result = await provider.list_scenes(location_id=params.get("location_id"))
                    scenes = [s.to_dict() if hasattr(s, 'to_dict') else s for s in result]
                    return StepResult(True, data={"scenes": scenes, "count": len(scenes), "provider": name})
                
                elif operation == "run_scene" and hasattr(provider, "execute_scene"):
                    await provider.execute_scene(params["scene_id"])
                    return StepResult(True, data={"executed": True, "scene_id": params["scene_id"], "provider": name})
            
            # No provider connected — local simulation
            if operation == "devices":
                return StepResult(True, data={"devices": list(self._devices.values()), "provider": "local", "note": "Connect SmartThings for real device control"})
            elif operation == "status":
                return StepResult(True, data={"status": self._devices.get(params.get("device_id"), {}), "provider": "local"})
            elif operation == "on":
                self._devices.setdefault(params["device_id"], {})["on"] = True
                return StepResult(True, data={"on": True, "provider": "local"})
            elif operation == "off":
                self._devices.setdefault(params["device_id"], {})["on"] = False
                return StepResult(True, data={"off": True, "provider": "local"})
            elif operation == "brightness":
                self._devices.setdefault(params["device_id"], {})["brightness"] = params["level"]
                return StepResult(True, data={"brightness": params["level"], "provider": "local"})
            elif operation == "temperature":
                self._devices.setdefault(params["device_id"], {})["temperature"] = params["temperature"]
                return StepResult(True, data={"temperature": params["temperature"], "provider": "local"})
            elif operation == "lock":
                self._devices.setdefault(params["device_id"], {})["locked"] = True
                return StepResult(True, data={"locked": True, "provider": "local"})
            elif operation == "unlock":
                self._devices.setdefault(params["device_id"], {})["locked"] = False
                return StepResult(True, data={"unlocked": True, "provider": "local"})
            elif operation == "scenes":
                return StepResult(True, data={"scenes": [], "provider": "local"})
            elif operation == "run_scene":
                return StepResult(True, data={"executed": True, "provider": "local"})
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  SHOPPING PRIMITIVE - E-commerce
# ============================================================



class ShoppingPrimitive(Primitive):
    """E-commerce operations - Amazon, eBay, etc."""
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._providers = providers or {}
        self._cart: List[Dict] = []
        self._orders: List[Dict] = []
    
    @property
    def name(self) -> str:
        return "SHOPPING"
    
    def get_operations(self) -> Dict[str, str]:
        return self.get_available_operations()
    
    def get_available_operations(self) -> Dict[str, str]:
        return {
            "search": "Search for products",
            "product": "Get product details",
            "add_to_cart": "Add item to cart",
            "cart": "View cart",
            "track": "Track an order",
            "orders": "Get order history",
            "reorder": "Reorder a previous order",
            "price_alert": "Set price alert",
        }
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "search": {"query": {"type": "str", "description": "Search query"}, "filters": {"type": "dict", "description": "Filters (optional)"}},
            "product": {"product_id": {"type": "str", "description": "Product ID"}},
            "add_to_cart": {"product_id": {"type": "str", "description": "Product ID"}, "quantity": {"type": "int", "description": "Quantity", "default": 1}},
            "cart": {},
            "track": {"order_id": {"type": "str", "description": "Order ID"}},
            "orders": {"limit": {"type": "int", "description": "Max orders", "default": 10}},
            "reorder": {"order_id": {"type": "str", "description": "Order ID"}},
            "price_alert": {"product_id": {"type": "str", "description": "Product ID"}, "target_price": {"type": "float", "description": "Target price"}},
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            for name, provider in self._providers.items():
                if operation == "search" and hasattr(provider, "search_products"):
                    result = await provider.search_products(params.get("query"), params.get("filters"))
                    return StepResult(True, data={"products": result, "provider": name})
                elif operation == "product" and hasattr(provider, "get_product"):
                    result = await provider.get_product(params.get("product_id"))
                    return StepResult(True, data={"product": result, "provider": name})
            
            # Local fallback
            if operation == "search":
                return StepResult(True, data={"products": [], "provider": "local", "note": "Connect shopping provider to search"})
            
            elif operation == "product":
                return StepResult(True, data={"product": None, "provider": "local"})
            
            elif operation == "add_to_cart":
                item = {"product_id": params.get("product_id"), "quantity": params.get("quantity", 1)}
                self._cart.append(item)
                return StepResult(True, data={"added": True, "cart": self._cart, "provider": "local"})
            
            elif operation == "cart":
                return StepResult(True, data={"cart": self._cart, "provider": "local"})
            
            elif operation == "track":
                order_id = params.get("order_id")
                for order in self._orders:
                    if order.get("id") == order_id:
                        return StepResult(True, data={"order": order, "provider": "local"})
                return StepResult(True, data={"order": None, "provider": "local"})
            
            elif operation == "orders":
                limit = params.get("limit", 10)
                return StepResult(True, data={"orders": self._orders[-limit:], "provider": "local"})
            
            elif operation == "reorder":
                order_id = params.get("order_id")
                for order in self._orders:
                    if order.get("id") == order_id:
                        new_order = {**order, "id": f"order_{int(datetime.now().timestamp())}"}
                        self._orders.append(new_order)
                        return StepResult(True, data={"order": new_order, "provider": "local"})
                return StepResult(False, error="Order not found")
            
            elif operation == "price_alert":
                return StepResult(True, data={"alert_set": True, "provider": "local"})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))




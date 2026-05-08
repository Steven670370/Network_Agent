from typing import TypedDict, List, Dict, Optional
from langchain.chat_models import ChatOpenAI
from langgraph.graph import StateGraph

from dotenv import load_dotenv
import os
import json

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("Set OPENAI_API_KEY in .env file")

llm = ChatOpenAI(
    openai_api_key=api_key,
    openai_api_base="https://api.deepseek.com",
    model_name="deepseek-code",
    temperature=0.7
)


# =========================
# Models
# =========================

class Interface(TypedDict):
    name: str
    ip: str
    status: str


class Device(TypedDict):
    id: str
    hostname: str
    type: str
    ip: str
    mac: str
    vendor: str
    os: str
    status: str
    interfaces: List[Interface]


class Link(TypedDict):
    source: str          # Device.id
    target: str          # Device.id
    source_port: str     # Interface.name
    target_port: str     # Interface.name
    bandwidth: str
    latency_ms: int
    status: str


class Message(TypedDict):
    timestamp: str
    level: str
    source: str
    content: str


class ValidationResult(TypedDict):
    valid: bool
    errors: List[str]
    warnings: List[str]


class NetworkState(TypedDict):
    user_request: str
    devices: List[Device]
    links: List[Link]
    configs: Dict[str, object]
    messages: List[Message]
    validation_result: ValidationResult


# =========================
# Generate
# =========================

def generate_topology(state: NetworkState) -> NetworkState:
    has_existing_devices = bool(state["devices"])

    prompt = f"""
You are a network topology designer.

Generate a network topology based on these requests
{"and existing devices only" if has_existing_devices else ""}:

{state["user_request"]}

{"Devices:" + json.dumps(state["devices"], indent=2) if has_existing_devices else "No existing devices."}

Return ONLY valid JSON.

Format:
{{
  "devices": [
    {{
      "id": "...",
      "hostname": "...",
      "type": "...",
      "ip": "...",
      "mac": "...",
      "vendor": "...",
      "os": "...",
      "status": "...",
      "interfaces": [
        {{
          "name": "...",
          "ip": "...",
          "status": "up"
        }}
      ]
    }}
  ],

  "links": [
    {{
      "source": "...",
      "target": "...",
      "source_port": "...",
      "target_port": "...",
      "bandwidth": "...",
      "latency_ms": 1,
      "status": "up"
    }}
  ]
}}
"""

    response = llm.predict(prompt)
    data = json.loads(response)

    if not state["devices"]:
        state["devices"] = data["devices"]

    state["links"] = data["links"]

    return state


# =========================
# Validate
# =========================

def validate_topology(state: NetworkState) -> NetworkState:

    validation_result: ValidationResult = {
        "valid": True,
        "errors": [],
        "warnings": []
    }

    # -------------------------
    # Device map
    # -------------------------

    device_map = {
        device["id"]: device
        for device in state["devices"]
    }

    # -------------------------
    # Validate devices
    # -------------------------

    for device in state["devices"]:

        if device["status"] not in ["up", "down"]:
            validation_result["valid"] = False
            validation_result["errors"].append(
                f"Device {device['id']} has invalid status {device['status']}."
            )

        interface_names = set()

        for interface in device["interfaces"]:

            # duplicate interface names
            if interface["name"] in interface_names:
                validation_result["valid"] = False
                validation_result["errors"].append(
                    f"Duplicate interface {interface['name']} on device {device['id']}."
                )

            interface_names.add(interface["name"])

            # validate interface status
            if interface["status"] not in ["up", "down"]:
                validation_result["valid"] = False
                validation_result["errors"].append(
                    f"Interface {interface['name']} on device {device['id']} "
                    f"has invalid status {interface['status']}."
                )

    # -------------------------
    # Validate links
    # -------------------------

    connected_devices = set()

    for link in state["links"]:

        source_id = link["source"]
        target_id = link["target"]

        connected_devices.add(source_id)
        connected_devices.add(target_id)

        # validate source device exists
        if source_id not in device_map:
            validation_result["valid"] = False
            validation_result["errors"].append(
                f"Link source device {source_id} does not exist."
            )
            continue

        # validate target device exists
        if target_id not in device_map:
            validation_result["valid"] = False
            validation_result["errors"].append(
                f"Link target device {target_id} does not exist."
            )
            continue

        source_device = device_map[source_id]
        target_device = device_map[target_id]

        source_interfaces = {
            interface["name"]
            for interface in source_device["interfaces"]
        }

        target_interfaces = {
            interface["name"]
            for interface in target_device["interfaces"]
        }

        # validate source port exists
        if link["source_port"] not in source_interfaces:
            validation_result["valid"] = False
            validation_result["errors"].append(
                f"Source port {link['source_port']} does not exist "
                f"on device {source_id}."
            )

        # validate target port exists
        if link["target_port"] not in target_interfaces:
            validation_result["valid"] = False
            validation_result["errors"].append(
                f"Target port {link['target_port']} does not exist "
                f"on device {target_id}."
            )

        # validate link status
        if link["status"] not in ["up", "down"]:
            validation_result["valid"] = False
            validation_result["errors"].append(
                f"Link {source_id} -> {target_id} "
                f"has invalid status {link['status']}."
            )

    # -------------------------
    # Check isolated devices
    # -------------------------

    for device in state["devices"]:

        if device["id"] not in connected_devices:
            validation_result["warnings"].append(
                f"Device {device['id']} is not connected to any links."
            )

    # save result
    state["validation_result"] = validation_result

    return state


# =========================
# Rebuild
# =========================

def rebuild_topology(state: NetworkState) -> NetworkState:

    prompt = f"""
You are a network topology rebuilder.

Rebuild the following network topology to fix these issues.

User Request:
{state["user_request"]}

Validation Result:
{json.dumps(state["validation_result"], indent=2)}

Devices:
{json.dumps(state["devices"], indent=2)}

Links:
{json.dumps(state["links"], indent=2)}

Return ONLY valid JSON.

Format:
{{
  "devices": [
    {{
      "id": "...",
      "hostname": "...",
      "type": "...",
      "ip": "...",
      "mac": "...",
      "vendor": "...",
      "os": "...",
      "status": "...",
      "interfaces": [
        {{
          "name": "...",
          "ip": "...",
          "status": "up"
        }}
      ]
    }}
  ],

  "links": [
    {{
      "source": "...",
      "target": "...",
      "source_port": "...",
      "target_port": "...",
      "bandwidth": "...",
      "latency_ms": 1,
      "status": "up"
    }}
  ]
}}
"""

    response = llm.predict(prompt)
    data = json.loads(response)

    state["devices"] = data["devices"]
    state["links"] = data["links"]

    return state
from __future__ import annotations

from typing import List, Dict, Optional, Literal
from pydantic import BaseModel, Field, ValidationError
from langchain.chat_models import ChatOpenAI
from langgraph.graph import StateGraph, END

from dotenv import load_dotenv

import os
import json
import requests
import re
import ipaddress
import logging

# =========================================================
# Init
# =========================================================

load_dotenv()

logging.basicConfig(level=logging.INFO)

api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    raise ValueError("Set OPENAI_API_KEY in .env file")

llm = ChatOpenAI(
    openai_api_key=api_key,
    openai_api_base="https://api.deepseek.com",
    model_name="deepseek-code",
    temperature=0.3
)

# =========================================================
# Models
# =========================================================

StatusType = Literal["up", "down"]


class Interface(BaseModel):
    name: str
    ip: str
    status: StatusType


class Device(BaseModel):
    id: str
    hostname: str
    type: str
    ip: str
    mac: str
    vendor: str
    os: str
    status: StatusType
    interfaces: List[Interface]


class Link(BaseModel):
    source: str
    target: str
    source_port: str
    target_port: str
    bandwidth: str
    latency_ms: int
    status: StatusType


class Message(BaseModel):
    timestamp: str
    level: str
    source: str
    content: str


class ValidationResult(BaseModel):
    valid: bool = True
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class NetworkState(BaseModel):
    user_request: str
    devices: List[Device] = Field(default_factory=list)
    links: List[Link] = Field(default_factory=list)
    messages: List[Message] = Field(default_factory=list)
    validation_result: ValidationResult = Field(
        default_factory=ValidationResult
    )


# =========================================================
# GNS3
# =========================================================

BASE = "http://localhost:3080/v2/projects"

TEMPLATES = {
    "router": {
        "template_id": "ROUTER_TEMPLATE_ID",
        "ports": 8
    },
    "switch": {
        "template_id": "SWITCH_TEMPLATE_ID",
        "ports": 24
    },
    "pc": {
        "template_id": "VPCS_TEMPLATE_ID",
        "ports": 1
    }
}

# =========================================================
# Helpers
# =========================================================


def extract_json(text: str) -> dict:
    """
    Extract JSON from LLM response.
    """

    match = re.search(r"\{.*\}", text, re.DOTALL)

    if not match:
        raise ValueError("No JSON object found")

    return json.loads(match.group())


def safe_request(method, url, **kwargs):
    """
    Safe HTTP request.
    """

    kwargs.setdefault("timeout", 10)

    try:
        response = requests.request(method, url, **kwargs)
        response.raise_for_status()
        return response

    except requests.RequestException as e:
        raise RuntimeError(f"HTTP request failed: {e}")


def normalize_topology(data: dict) -> tuple[List[Device], List[Link]]:
    """
    Convert raw JSON into validated Pydantic models.
    """

    devices = [Device(**d) for d in data["devices"]]
    links = [Link(**l) for l in data["links"]]

    return devices, links


def interface_exists(device: Device, interface_name: str) -> bool:
    return any(i.name == interface_name for i in device.interfaces)


# =========================================================
# Generate
# =========================================================


def generate_topology(state: NetworkState) -> NetworkState:

    prompt = f"""
You are a network topology designer.

Generate a realistic topology.

Requirements:
- Return ONLY valid JSON
- Do not include markdown
- Device IDs must be unique
- MAC addresses must be unique
- IP addresses must be unique
- Link source/target must reference existing device IDs
- Interface names must exist on devices
- Allowed status values: up/down

User request:
{state.user_request}

JSON format:

{{
  "devices": [
    {{
      "id": "R1",
      "hostname": "router1",
      "type": "router",
      "ip": "10.0.0.1",
      "mac": "00:11:22:33:44:55",
      "vendor": "Cisco",
      "os": "IOS",
      "status": "up",
      "interfaces": [
        {{
          "name": "Gig0/0",
          "ip": "192.168.1.1",
          "status": "up"
        }}
      ]
    }}
  ],
  "links": [
    {{
      "source": "R1",
      "target": "SW1",
      "source_port": "Gig0/0",
      "target_port": "Gig0/1",
      "bandwidth": "1Gbps",
      "latency_ms": 1,
      "status": "up"
    }}
  ]
}}
"""

    try:

        response = llm.predict(prompt)

        data = extract_json(response)

        devices, links = normalize_topology(data)

        state.devices = devices
        state.links = links

    except Exception as e:

        state.validation_result.valid = False
        state.validation_result.errors.append(
            f"Generation failed: {str(e)}"
        )

    return state


# =========================================================
# Validate
# =========================================================


def validate_topology(state: NetworkState) -> NetworkState:

    result = ValidationResult()

    device_map = {
        d.id: d
        for d in state.devices
    }

    used_ips = set()
    used_macs = set()
    seen_links = set()

    # -----------------------------------------------------
    # Validate devices
    # -----------------------------------------------------

    for device in state.devices:

        # IP uniqueness

        if device.ip in used_ips:
            result.valid = False
            result.errors.append(
                f"Duplicate device IP: {device.ip}"
            )

        used_ips.add(device.ip)

        # MAC uniqueness

        if device.mac in used_macs:
            result.valid = False
            result.errors.append(
                f"Duplicate MAC address: {device.mac}"
            )

        used_macs.add(device.mac)

        # Validate IP format

        try:
            ipaddress.ip_address(device.ip)
        except ValueError:
            result.valid = False
            result.errors.append(
                f"Invalid device IP: {device.ip}"
            )

        # Interface validation

        interface_names = set()

        for interface in device.interfaces:

            if interface.name in interface_names:
                result.valid = False
                result.errors.append(
                    f"Duplicate interface "
                    f"{interface.name} on {device.id}"
                )

            interface_names.add(interface.name)

            if interface.ip in used_ips:
                result.valid = False
                result.errors.append(
                    f"Duplicate interface IP: {interface.ip}"
                )

            used_ips.add(interface.ip)

            try:
                ipaddress.ip_address(interface.ip)
            except ValueError:
                result.valid = False
                result.errors.append(
                    f"Invalid interface IP: {interface.ip}"
                )

    # -----------------------------------------------------
    # Validate links
    # -----------------------------------------------------

    connected_devices = set()

    for link in state.links:

        if link.source == link.target:
            result.valid = False
            result.errors.append(
                f"Self-loop link on {link.source}"
            )

        pair = tuple(sorted([link.source, link.target]))

        if pair in seen_links:
            result.valid = False
            result.errors.append(
                f"Duplicate link between "
                f"{link.source} and {link.target}"
            )

        seen_links.add(pair)

        # Device existence

        if link.source not in device_map:
            result.valid = False
            result.errors.append(
                f"Missing source device: {link.source}"
            )
            continue

        if link.target not in device_map:
            result.valid = False
            result.errors.append(
                f"Missing target device: {link.target}"
            )
            continue

        connected_devices.add(link.source)
        connected_devices.add(link.target)

        source_device = device_map[link.source]
        target_device = device_map[link.target]

        if not interface_exists(
            source_device,
            link.source_port
        ):
            result.valid = False
            result.errors.append(
                f"Source port {link.source_port} "
                f"missing on {link.source}"
            )

        if not interface_exists(
            target_device,
            link.target_port
        ):
            result.valid = False
            result.errors.append(
                f"Target port {link.target_port} "
                f"missing on {link.target}"
            )

    # -----------------------------------------------------
    # Isolated devices
    # -----------------------------------------------------

    for device in state.devices:

        if device.id not in connected_devices:
            result.warnings.append(
                f"Isolated device: {device.id}"
            )

    state.validation_result = result

    return state


# =========================================================
# Repair
# =========================================================


def repair_topology(state: NetworkState) -> NetworkState:
    """
    Deterministic repair.
    No LLM regeneration.
    """

    device_map = {
        d.id: d
        for d in state.devices
    }

    # -----------------------------------------------------
    # Fix duplicate interface names
    # -----------------------------------------------------

    for device in state.devices:

        used = set()

        for idx, interface in enumerate(device.interfaces):

            if interface.name in used:

                interface.name = f"{interface.name}_{idx}"

            used.add(interface.name)

    # -----------------------------------------------------
    # Fix invalid link ports
    # -----------------------------------------------------

    for link in state.links:

        if link.source in device_map:

            source_device = device_map[link.source]

            if not interface_exists(
                source_device,
                link.source_port
            ):
                link.source_port = (
                    source_device.interfaces[0].name
                )

        if link.target in device_map:

            target_device = device_map[link.target]

            if not interface_exists(
                target_device,
                link.target_port
            ):
                link.target_port = (
                    target_device.interfaces[0].name
                )

    # -----------------------------------------------------
    # Remove self-loop links
    # -----------------------------------------------------

    state.links = [
        link for link in state.links
        if link.source != link.target
    ]

    # -----------------------------------------------------
    # Force valid statuses
    # -----------------------------------------------------

    for device in state.devices:

        if device.status not in ["up", "down"]:
            device.status = "up"

        for interface in device.interfaces:

            if interface.status not in ["up", "down"]:
                interface.status = "up"

    for link in state.links:

        if link.status not in ["up", "down"]:
            link.status = "up"

    return state


# =========================================================
# LangGraph Condition
# =========================================================


def topology_is_valid(state: NetworkState):

    return (
        "valid"
        if state.validation_result.valid
        else "invalid"
    )


# =========================================================
# Deploy
# =========================================================


def create_graph_in_gns3(state: NetworkState) -> NetworkState:

    project_id = None

    try:

        # -------------------------------------------------
        # Create project
        # -------------------------------------------------

        response = safe_request(
            "POST",
            BASE,
            json={"name": "AutoProject"}
        )

        project = response.json()

        project_id = project["project_id"]

        project_base = f"{BASE}/{project_id}"

        logging.info(f"Project created: {project_id}")

        # -------------------------------------------------
        # Create nodes
        # -------------------------------------------------

        node_mapping = {}

        interface_mapping = {}

        for idx, device in enumerate(state.devices):

            if device.type not in TEMPLATES:
                raise ValueError(
                    f"Unknown device type: {device.type}"
                )

            template = TEMPLATES[device.type]

            node_data = {
                "name": device.hostname,
                "template_id": template["template_id"],
                "x": idx * 100,
                "y": 0
            }

            response = safe_request(
                "POST",
                f"{project_base}/nodes",
                json=node_data
            )

            node = response.json()

            node_mapping[device.id] = node["node_id"]

            # Interface -> port mapping

            interface_mapping[device.id] = {}

            for port_idx, interface in enumerate(
                device.interfaces
            ):

                interface_mapping[device.id][
                    interface.name
                ] = port_idx

            logging.info(
                f"Node created: {device.hostname}"
            )

        # -------------------------------------------------
        # Create links
        # -------------------------------------------------

        for link in state.links:

            src_node = node_mapping[link.source]
            dst_node = node_mapping[link.target]

            src_port = interface_mapping[
                link.source
            ][link.source_port]

            dst_port = interface_mapping[
                link.target
            ][link.target_port]

            link_data = {
                "nodes": [
                    {
                        "node_id": src_node,
                        "adapter_number": 0,
                        "port_number": src_port
                    },
                    {
                        "node_id": dst_node,
                        "adapter_number": 0,
                        "port_number": dst_port
                    }
                ]
            }

            safe_request(
                "POST",
                f"{project_base}/links",
                json=link_data
            )

            logging.info(
                f"Linked "
                f"{link.source}:{link.source_port} "
                f"<-> "
                f"{link.target}:{link.target_port}"
            )

    except Exception as e:

        logging.error(f"Deployment failed: {e}")

        state.validation_result.valid = False
        state.validation_result.errors.append(
            f"GNS3 deployment failed: {str(e)}"
        )

        # rollback

        if project_id:

            try:

                safe_request(
                    "DELETE",
                    f"{BASE}/{project_id}"
                )

                logging.info(
                    f"Rollback project {project_id}"
                )

            except Exception as rollback_error:

                logging.error(
                    f"Rollback failed: {rollback_error}"
                )

    return state


# =========================================================
# Build LangGraph
# =========================================================

workflow = StateGraph(NetworkState)

workflow.add_node(
    "generate",
    generate_topology
)

workflow.add_node(
    "validate",
    validate_topology
)

workflow.add_node(
    "repair",
    repair_topology
)

workflow.add_node(
    "deploy",
    create_graph_in_gns3
)

workflow.set_entry_point("generate")

workflow.add_edge(
    "generate",
    "validate"
)

workflow.add_conditional_edges(
    "validate",
    topology_is_valid,
    {
        "valid": "deploy",
        "invalid": "repair"
    }
)

workflow.add_edge(
    "repair",
    "validate"
)

workflow.add_edge(
    "deploy",
    END
)

app = workflow.compile()

# =========================================================
# Run
# =========================================================

if __name__ == "__main__":

    initial_state = NetworkState(
        user_request=(
            "Create a topology with "
            "2 routers, 1 switch, and 2 PCs"
        )
    )

    final_state = app.invoke(initial_state)

    print("\n==============================")
    print("VALIDATION")
    print("==============================")

    print(
        json.dumps(
            final_state["validation_result"].dict(),
            indent=2
        )
    )

    print("\n==============================")
    print("DEVICES")
    print("==============================")

    print(
        json.dumps(
            [
                d.dict()
                for d in final_state["devices"]
            ],
            indent=2
        )
    )

    print("\n==============================")
    print("LINKS")
    print("==============================")

    print(
        json.dumps(
            [
                l.dict()
                for l in final_state["links"]
            ],
            indent=2
        )
    )
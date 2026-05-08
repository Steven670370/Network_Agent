from typing import TypedDict, List, Dict
from langgraph.graph import StateGraph

from dotenv import load_dotenv
import os

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("Set OPENAI_API_KEY in .env file")

from langchain.chat_models import ChatOpenAI

llm = ChatOpenAI(
    openai_api_key=api_key,
    openai_api_base="https://api.deepseek.com",
    model_name="deepseek-code",
    temperature=0.7
)

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
    source: str
    target: str
    source_port: str
    target_port: str
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
    devices: List[Device]
    links: List[Link]
    configs: Dict[str, object]
    messages: List[Message]
    validation_result: ValidationResult
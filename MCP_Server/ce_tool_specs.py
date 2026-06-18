"""Shared Cheat Engine MCP tool specifications.

Both local and remote MCP servers register tools from this module so their
public tool surface and CE wire payloads cannot drift apart.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ToolParam:
    name: str
    annotation: str
    default: str | None = None
    payload_name: str | None = None

    def signature(self) -> str:
        if self.default is None:
            return f"{self.name}: {self.annotation}"
        return f"{self.name}: {self.annotation} = {self.default}"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    method: str
    description: str
    params: tuple[ToolParam, ...] = ()


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("get_process_info", "get_process_info", "Get current process ID, name, modules count and architecture."),
    ToolSpec("enum_modules", "enum_modules", "List all loaded modules (DLLs) with their base addresses and sizes."),
    ToolSpec("get_thread_list", "get_thread_list", "Get list of threads in the attached process."),
    ToolSpec(
        "get_symbol_address",
        "get_symbol_address",
        "Resolve a symbol name (e.g., 'Engine.GameEngine') to an address.",
        (ToolParam("symbol", "str"),),
    ),
    ToolSpec(
        "get_address_info",
        "get_address_info",
        "Get symbolic name and module info for an address.",
        (
            ToolParam("address", "str"),
            ToolParam("include_modules", "bool", "True"),
            ToolParam("include_symbols", "bool", "True"),
            ToolParam("include_sections", "bool", "False"),
        ),
    ),
    ToolSpec(
        "get_rtti_classname",
        "get_rtti_classname",
        "Try to identify the class name of an object at address using Run-Time Type Information.",
        (ToolParam("address", "str"),),
    ),
    ToolSpec(
        "read_memory",
        "read_memory",
        "Read raw bytes from memory.",
        (ToolParam("address", "str"), ToolParam("size", "int", "256")),
    ),
    ToolSpec(
        "read_integer",
        "read_integer",
        "Read a number from memory. Types: byte, word, dword, qword, float, double.",
        (ToolParam("address", "str"), ToolParam("type", "str", repr("dword"))),
    ),
    ToolSpec(
        "read_string",
        "read_string",
        "Read a string from memory (ASCII or Wide/UTF-16).",
        (
            ToolParam("address", "str"),
            ToolParam("max_length", "int", "256"),
            ToolParam("wide", "bool", "False"),
        ),
    ),
    ToolSpec(
        "read_pointer",
        "read_pointer_chain",
        "Read a pointer chain. Returns the final address and value.",
        (ToolParam("address", "str"), ToolParam("offsets", "list[int]", "None")),
    ),
    ToolSpec(
        "read_pointer_chain",
        "read_pointer_chain",
        "Follow a multi-level pointer chain and return analysis of every step.",
        (ToolParam("base", "str"), ToolParam("offsets", "list[int]")),
    ),
    ToolSpec(
        "checksum_memory",
        "checksum_memory",
        "Calculate MD5 checksum of a memory region to detect changes.",
        (ToolParam("address", "str"), ToolParam("size", "int")),
    ),
    ToolSpec(
        "scan_all",
        "scan_all",
        "Unified Memory Scanner. Types: byte, word, dword, qword, float, double, string.",
        (
            ToolParam("value", "str"),
            ToolParam("type", "str", repr("exact")),
            ToolParam("protection", "str", repr("+W-C")),
        ),
    ),
    ToolSpec(
        "get_scan_results",
        "get_scan_results",
        "Get results from the last scan_all operation.",
        (ToolParam("max", "int", "100"),),
    ),
    ToolSpec(
        "next_scan",
        "next_scan",
        "Next scan to filter results. Types: exact, increased, decreased, changed, unchanged, bigger, smaller.",
        (ToolParam("value", "str"), ToolParam("scan_type", "str", repr("exact"))),
    ),
    ToolSpec(
        "write_integer",
        "write_integer",
        "Write a number to memory. Types: byte, word, dword, qword, float, double.",
        (
            ToolParam("address", "str"),
            ToolParam("value", "int"),
            ToolParam("type", "str", repr("dword")),
        ),
    ),
    ToolSpec(
        "write_memory",
        "write_memory",
        "Write raw bytes to memory.",
        (ToolParam("address", "str"), ToolParam("bytes", "list[int]")),
    ),
    ToolSpec(
        "write_string",
        "write_string",
        "Write a string to memory (ASCII or Wide/UTF-16).",
        (
            ToolParam("address", "str"),
            ToolParam("value", "str"),
            ToolParam("wide", "bool", "False"),
        ),
    ),
    ToolSpec(
        "aob_scan",
        "aob_scan",
        "Scan for an Array of Bytes (AOB) pattern.",
        (
            ToolParam("pattern", "str"),
            ToolParam("protection", "str", repr("+X")),
            ToolParam("limit", "int", "100"),
        ),
    ),
    ToolSpec(
        "search_string",
        "search_string",
        "Quickly search for a text string in memory.",
        (
            ToolParam("string", "str"),
            ToolParam("wide", "bool", "False"),
            ToolParam("limit", "int", "100"),
        ),
    ),
    ToolSpec(
        "generate_signature",
        "generate_signature",
        "Generate a unique AOB signature that can find this specific address again.",
        (ToolParam("address", "str"),),
    ),
    ToolSpec(
        "get_memory_regions",
        "get_memory_regions",
        "Get list of valid memory regions nearby common bases.",
        (ToolParam("max", "int", "100"),),
    ),
    ToolSpec(
        "enum_memory_regions_full",
        "enum_memory_regions_full",
        "Enumerate all memory regions in the process.",
        (ToolParam("max", "int", "500"),),
    ),
    ToolSpec(
        "disassemble",
        "disassemble",
        "Disassemble instructions starting at an address.",
        (ToolParam("address", "str"), ToolParam("count", "int", "20")),
    ),
    ToolSpec(
        "get_instruction_info",
        "get_instruction_info",
        "Get detailed info about a single instruction (size, bytes, opcode).",
        (ToolParam("address", "str"),),
    ),
    ToolSpec(
        "find_function_boundaries",
        "find_function_boundaries",
        "Attempt to find the start and end of a function containing the address.",
        (ToolParam("address", "str"), ToolParam("max_search", "int", "4096")),
    ),
    ToolSpec(
        "analyze_function",
        "analyze_function",
        "Analyze a function to find calls made by this function.",
        (ToolParam("address", "str"),),
    ),
    ToolSpec(
        "find_references",
        "find_references",
        "Find instructions that access this address.",
        (ToolParam("address", "str"), ToolParam("limit", "int", "50")),
    ),
    ToolSpec(
        "find_call_references",
        "find_call_references",
        "Find all locations that call this function.",
        (ToolParam("function_address", "str", payload_name="address"), ToolParam("limit", "int", "100")),
    ),
    ToolSpec(
        "dissect_structure",
        "dissect_structure",
        "Use CE's auto-guess feature to interpret memory at address as a structure.",
        (ToolParam("address", "str"), ToolParam("size", "int", "256")),
    ),
    ToolSpec(
        "set_breakpoint",
        "set_breakpoint",
        "Set a hardware execution breakpoint. Non-breaking/logging only.",
        (
            ToolParam("address", "str"),
            ToolParam("id", "str", "None"),
            ToolParam("capture_registers", "bool", "True"),
            ToolParam("capture_stack", "bool", "False"),
            ToolParam("stack_depth", "int", "16"),
        ),
    ),
    ToolSpec(
        "set_data_breakpoint",
        "set_data_breakpoint",
        "Set a hardware data breakpoint (watchpoint). Types: r, w, rw.",
        (
            ToolParam("address", "str"),
            ToolParam("id", "str", "None"),
            ToolParam("access_type", "str", repr("w")),
            ToolParam("size", "int", "4"),
        ),
    ),
    ToolSpec(
        "remove_breakpoint",
        "remove_breakpoint",
        "Remove a breakpoint by its ID.",
        (ToolParam("id", "str"),),
    ),
    ToolSpec("list_breakpoints", "list_breakpoints", "List all active breakpoints."),
    ToolSpec("clear_all_breakpoints", "clear_all_breakpoints", "Remove all breakpoints."),
    ToolSpec(
        "get_breakpoint_hits",
        "get_breakpoint_hits",
        "Get hits for a specific breakpoint ID or all breakpoints.",
        (ToolParam("id", "str", "None"), ToolParam("clear", "bool", "False")),
    ),
    ToolSpec(
        "get_physical_address",
        "get_physical_address",
        "Translate virtual address to physical address (requires DBVM).",
        (ToolParam("address", "str"),),
    ),
    ToolSpec(
        "start_dbvm_watch",
        "start_dbvm_watch",
        "Start invisible DBVM hypervisor watch. Modes: w, r, x.",
        (
            ToolParam("address", "str"),
            ToolParam("mode", "str", repr("w")),
            ToolParam("max_entries", "int", "1000"),
        ),
    ),
    ToolSpec(
        "stop_dbvm_watch",
        "stop_dbvm_watch",
        "Stop DBVM watch and return results.",
        (ToolParam("address", "str"),),
    ),
    ToolSpec(
        "poll_dbvm_watch",
        "poll_dbvm_watch",
        "Poll DBVM watch logs without stopping the watch.",
        (ToolParam("address", "str"), ToolParam("max_results", "int", "1000")),
    ),
    ToolSpec(
        "evaluate_lua",
        "evaluate_lua",
        "Execute arbitrary Lua code in Cheat Engine.",
        (ToolParam("code", "str"),),
    ),
    ToolSpec(
        "auto_assemble",
        "auto_assemble",
        "Run an AutoAssembler script.",
        (ToolParam("script", "str"),),
    ),
    ToolSpec("ping", "ping", "Check connectivity and get version info."),
)

TOOL_NAMES = frozenset(spec.name for spec in TOOL_SPECS)
_SPECS_BY_NAME = {spec.name: spec for spec in TOOL_SPECS}
_ANNOTATION_TYPES = {
    "str": str,
    "int": int,
    "bool": bool,
    "list[int]": list,
    "list": list,
}


def _default_payload(spec: ToolSpec, args: dict[str, Any]) -> dict[str, Any]:
    return {
        param.payload_name or param.name: args[param.name]
        for param in spec.params
    }


def _payload_for(spec: ToolSpec, args: dict[str, Any]) -> dict[str, Any]:
    if spec.name == "read_pointer":
        offsets = args["offsets"] if args["offsets"] else [0]
        return {"base": args["address"], "offsets": offsets}
    return _default_payload(spec, args)


def _invoke_tool(
    sender: Callable[[str, dict[str, Any] | None], Any],
    format_result: Callable[[Any], str],
    tool_name: str,
    args: dict[str, Any],
) -> str:
    spec = _SPECS_BY_NAME[tool_name]
    payload = _payload_for(spec, args)
    try:
        result = sender(spec.method, payload)
        return format_result(result)
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)


def register_ce_tools(mcp: Any, sender: Callable[[str, dict[str, Any] | None], Any], format_result: Callable[[Any], str]) -> None:
    """Register generated FastMCP tools from TOOL_SPECS."""
    namespace: dict[str, Any] = {
        "_invoke_tool": _invoke_tool,
        "_sender": sender,
        "_format_result": format_result,
    }

    for spec in TOOL_SPECS:
        signature = ", ".join(param.signature() for param in spec.params)
        source = (
            f"def {spec.name}({signature}) -> str:\n"
            f"    {spec.description!r}\n"
            f"    return _invoke_tool(_sender, _format_result, {spec.name!r}, locals())\n"
        )
        exec(source, namespace)
        func = namespace[spec.name]
        func.__annotations__ = {"return": str}
        for param in spec.params:
            func.__annotations__[param.name] = _ANNOTATION_TYPES[param.annotation]
        mcp.tool()(func)

#!/usr/bin/env python3
import json, os

commands_path = "/app/database/commands.json"
output_path = "/app/database/security_rules.json"

with open(commands_path, "r", encoding="utf-8") as f:
    commands = json.load(f)

allowed_commands = [cmd["name"] for cmd in commands]

security = {
    "allow_shell_operators": True,
    "allowed_commands": allowed_commands,
    "disallowed_commands": [],
    "allowed_tools": ["run_command", "show_security_rules"]
}

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(security, f, indent=2, ensure_ascii=False)

print(f"Security rules written to {output_path}")

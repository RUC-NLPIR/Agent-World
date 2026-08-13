#!/usr/bin/env python3
import json, urllib.request, urllib.error, os, re

commands_path = "/app/database/commands.json"
output_path = "/app/database/commands_filled.json"

with open(commands_path, "r", encoding="utf-8") as f:
    commands = json.load(f)

def fetch_description(cmd):
    base_urls = [
        f"https://raw.githubusercontent.com/tldr-pages/tldr/master/pages/common/{cmd}.md",
        f"https://raw.githubusercontent.com/tldr-pages/tldr/master/pages/linux/{cmd}.md",
        f"https://raw.githubusercontent.com/tldr-pages/tldr/master/pages/osx/{cmd}.md"
    ]
    for url in base_urls:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                txt = resp.read().decode('utf-8')
                # Ensure the page is for the correct command
                if not txt.startswith(f"# {cmd}"):
                    continue
                # Find first line starting with '>'
                for line in txt.splitlines():
                    line = line.strip()
                    if line.startswith('>'):
                        # Strip leading '> ' and return
                        return line.lstrip('> ').strip()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
        except Exception:
            continue
    return None

for entry in commands:
    if entry.get('description') in ("Command not found", "Description not available"):
        desc = fetch_description(entry['name'])
        if desc:
            entry['description'] = desc
        else:
            entry['description'] = "No description available"

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(commands, f, indent=2, ensure_ascii=False)

print(f"Updated descriptions written to {output_path}")

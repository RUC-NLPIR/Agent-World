#!/usr/bin/env python3
import subprocess, json, re, os, shutil

commands = [
    "dirname", "python", "traceroute", "file", "netstat", "cut", "clear", "find", "cp", "git", "ping", "curl", "basename", "tail", "sort", "history", "md5sum", "gunzip", "which", "mv", "sha256sum", "touch", "pwd", "gzip", "wget", "zip", "ps", "cat", "diff", "stat", "more", "env", "head", "ifconfig", "uniq", "du", "tar", "mkdir", "nslookup", "kubectl", "realpath", "date", "hostname", "df", "wc", "tr", "echo", "awk", "rm", "chmod", "sed", "ls", "unzip", "whoami", "less", "grep", "cd", "helm", "tree"
]

# category mapping
def get_category(cmd):
    file_ops = {"cp","mv","rm","mkdir","touch","cat","diff","stat","more","less","head","tail","cut","sort","uniq","wc","tr","sed","awk","grep","find","file","basename","dirname","realpath","which","chmod"}
    sys_info = {"pwd","date","hostname","df","du","env","whoami","realpath","history"}
    networking = {"ping","curl","wget","nslookup","traceroute","ifconfig","netstat"}
    compression = {"gzip","gunzip","zip","unzip","tar"}
    version_control = {"git"}
    programming = {"python"}
    container = {"kubectl","helm"}
    process = {"ps"}
    security = {"md5sum","sha256sum"}
    misc = {"clear","cd","echo","tree","ls"}
    if cmd in file_ops:
        return "File Management"
    if cmd in sys_info:
        return "System Information"
    if cmd in networking:
        return "Networking"
    if cmd in compression:
        return "Compression/Archiving"
    if cmd in version_control:
        return "Version Control"
    if cmd in programming:
        return "Programming"
    if cmd in container:
        return "Container Management"
    if cmd in process:
        return "Process Management"
    if cmd in security:
        return "Security"
    if cmd in misc:
        return "Miscellaneous"
    return "Other"

def extract_description(help_text):
    lines = help_text.splitlines()
    for i, line in enumerate(lines):
        if re.search(r'(?i)usage:', line) or re.search(r'(?i)synopsis', line):
            for j in range(i+1, len(lines)):
                next_line = lines[j].strip()
                if next_line:
                    return next_line
    for line in lines:
        if line.strip():
            return line.strip()
    return ""

result = []
for cmd in commands:
    if not shutil.which(cmd):
        description = "Command not found"
    else:
        try:
            proc = subprocess.run([cmd, "--help"], capture_output=True, text=True, timeout=5)
            help_text = proc.stdout + proc.stderr
            if proc.returncode != 0 or not help_text.strip():
                proc = subprocess.run([cmd, "-h"], capture_output=True, text=True, timeout=5)
                help_text = proc.stdout + proc.stderr
        except Exception as e:
            help_text = str(e)
        description = extract_description(help_text)
        if not description:
            description = "Description not available"
    result.append({"name": cmd, "description": description, "category": get_category(cmd)})

output_path = "/app/database/commands.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print(f"Generated {len(result)} command entries to {output_path}")

# Keystone Terminal Command Registry

Keystone Terminal Command Registry is a terminal-oriented metadata service that publishes the available command catalog, toolset definition, and the security rules used to describe what can be executed and inspected in its environment.

## Datastore

### `commands.json` — list of 59 records
Holds the list of terminal commands with descriptions and categories so the service can present and organize what commands are available.

- `name` — string
- `description` — string
- `category` — string

### `security_rules.json` — single document
Holds the environment’s security configuration (allowed/disallowed commands, shell operator setting, and allowed tools) so the service can expose execution and introspection boundaries.

- `allow_shell_operators` — boolean
- `allowed_commands` — array
- `disallowed_commands` — array
- `allowed_tools` — array

### `toolsets.json` — single document
Holds the terminal toolset definition (toolset metadata, available tools, shell operator setting, and default directory) so the service can describe how clients should interact with the terminal environment.

- `toolset_name` — string
- `description` — string
- `tools` — array
  each record in `tools` has:
  - `name` — string — one of run_command, show_security_rules
  - `description` — string
  - `parameters` — array
    each record in `parameters` has:
    - `name` — string
    - `type` — string
    - `required` — boolean
    - `description` — string
- `allowed_shell_operators` — boolean
- `default_directory` — string

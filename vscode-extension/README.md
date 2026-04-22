# Apex Orchestrator — VS Code Extension

Run Apex Orchestrator plans directly from VS Code.

## Features

- **Project Scan**: Full repo analysis with one command
- **Semantic Patch**: Generate AST-based patches for the current file
- **Run Tests**: Execute project tests via Apex
- **Presence Log**: Open `.apex/presence.md` to see Apex's recent work

## Setup

1. Install the extension in VS Code
2. Configure the Python path in VS Code settings:
   ```json
   {
     "apex.pythonPath": "python",
     "apex.projectRoot": ""
   }
   ```
3. Open a project that has Apex Orchestrator installed or configured

## Commands

Open the Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`) and type:

- `Apex: Project Scan`
- `Apex: Generate Semantic Patch`
- `Apex: Run Tests`
- `Apex: Open Presence Log`

## Requirements

- Python 3.10+
- Apex Orchestrator installed in the workspace or accessible via `PYTHONPATH`

## Development

```bash
cd vscode-extension
npm install -g vsce
vsce package
```

This produces a `.vsix` file you can install in VS Code.

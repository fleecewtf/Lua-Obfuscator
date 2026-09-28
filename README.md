<div align="center">

# lua obfuscator

A little tool I made with AI to quickly obfuscate Lua 5.4 and Roblox Luau scripts and code locally on 64-bit Windows.

<img src="Lua%20Obfuscator.png" alt="Lua Obfuscator app window" width="760">

</div>

## features

- Target Lua 5.4 or Roblox Luau
- Choose low, medium, or high obfuscation
- Select or drag a `.lua`, `.luau`, or `.txt` source file
- Use the complete compatible Hercules protection set
- Choose the output folder and follow progress in the built-in log
- Keep the original source file unchanged
- Process every script locally without uploads or telemetry
- Validate the local engine before setup reports success

## requirements

- 64-bit x64 or ARM64 Windows
- An internet connection during first setup
- Source code you own or have permission to modify
- No internet connection while using the installed app

## installation

1. Download the latest release ZIP.
2. Extract the complete folder.
3. Double-click `Installer.bat`.
4. Press **Y** once to accept the Terms and bundled Tool License and approve setup.
5. Leave the setup window open until every check passes.
6. Double-click the `Lua Obfuscator` shortcut created in the folder.

Keep the full extracted folder path at 72 characters or fewer so Windows can install the private packages reliably.

Setup keeps the private Python runtime, dependencies, settings, and every app component inside the extracted folder. It does not require administrator access, change PATH, or install global Python packages. The generated folder-local shortcut starts the app directly with that private runtime, so Microsoft Store or system Python is not required.

Setup pins and verifies official Python 3.14.7, pip, PySide6-Essentials, Hercules, and Lua 5.4.8. Downloaded runtime archives are checked against pinned SHA-256 hashes before use.

Setup and repair also require the bundled, hash-verified dependency lock file selected automatically for x64 or ARM64. Every downloaded Python wheel must match its approved SHA-256 hash, including transitive dependencies. Keep the entire extracted folder together; no account or global Python installation is needed.

Before downloading private components, setup checks the bundled app source and Windows shortcut support. Once private Python is ready, it compiles the app before installing the larger packages. WinGet is not required.

Run `Installer.bat` again to repair the private components or after moving the complete folder. Setup preserves your source files and recreates the shortcut for the folder's current location.

## usage

1. Choose a `.lua`, `.luau`, or `.txt` source file.
2. Select Lua 5.4 or Roblox Luau.
3. Select low, medium, or high obfuscation.
4. Choose the output folder.
5. Click **Obfuscate**.

Lua output is saved as `<name>.obfuscated.lua`. Luau output is saved as `<name>.obfuscated.luau`. The original file is never overwritten.

## built with

- [Hercules](https://github.com/zeusssz/hercules-obfuscator)
- [PySide6](https://doc.qt.io/qtforpython-6/)
- [Lua 5.4](https://www.lua.org/)
- [Python](https://www.python.org/)

## privacy and removal

The app has no telemetry, analytics, advertisements, accounts, uploads, or runtime network requests. Scripts are processed locally. Setup logs can contain local folder paths, so review them before sharing.

To remove Lua Obfuscator, close it and delete the extracted folder. This removes its folder-local shortcut, private runtime, dependencies, settings, and app files. The app does not install a background service, add itself to startup, or create an uninstaller entry.

## troubleshooting

If setup stops, the window immediately identifies the failed check and shows a short **How to fix** instruction. The same guidance is saved in `setup.log`. Correct the listed problem and run `Installer.bat` again. Setup reports success only after its dependencies, offline self-tests, and shortcut all pass.

If the `Lua Obfuscator` shortcut does not open, run `Installer.bat` again and keep the complete extracted folder together. Setup recreates and validates the shortcut for the folder's current location.

Lua and Hercules are installed privately by `Installer.bat`; a separate system-wide Lua installation is not required.

## license

Copyright 2026 Fleece. This project is source-available, not open source. The bundled [LICENSE](LICENSE) permits downloading, installing, and running an unmodified official release for lawful personal, non-commercial use. Modification, redistribution, sale, rebranding, and derivative versions remain prohibited. Third-party materials retain their own licenses.

## note

This project was made with AI.

Obfuscation makes source harder to read but cannot make recovery impossible. Only obfuscate code you own or have permission to modify.

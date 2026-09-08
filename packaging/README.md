# Desktop packaging

The desktop build uses Tauri 2 as the native window and embeds the Python
runtime as a sidecar. The user launches a Windows application window; the
loopback API is an internal implementation detail and is never the product
entry point.

```powershell
pip install -r requirements-desktop.txt
./scripts/build/build-sidecar.ps1 -Clean
```

The sidecar is built with PyInstaller `--onefile`, so the output is
`dist/knowledge-engine.exe`. Do not copy an `_internal` directory next to the
Tauri sidecar; the Python runtime and its DLLs are embedded in this executable.
User data is still created under `%LOCALAPPDATA%\BrandAtlas`; the executable
directory never becomes the database directory.

To stage the Tauri sidecar and build the installer:

```powershell
./scripts/build/prepare-tauri-sidecar.ps1
npm --prefix desktop install
npm --prefix desktop run build
```

`prepare-tauri-sidecar.ps1` rebuilds the one-file sidecar, removes stale
one-dir output from `desktop/src-tauri/binaries`, and stages only the
target-specific executable. The installer is generated at
`desktop/src-tauri/target/release/bundle/nsis/Brand Atlas_0.1.0_x64-setup.exe`.

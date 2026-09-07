# Desktop packaging

The desktop build uses Tauri 2 as the native window and embeds the Python
runtime as a sidecar. The user launches a Windows application window; the
loopback API is an internal implementation detail and is never the product
entry point.

```powershell
pip install -r requirements-desktop.txt
./scripts/build-sidecar.ps1
```

The output is `dist/knowledge-engine/knowledge-engine.exe`. User data is still
created under `%LOCALAPPDATA%\BrandAtlas`; the executable directory never
becomes the database directory.

To stage the Tauri sidecar and build the installer:

```powershell
./scripts/prepare-tauri-sidecar.ps1
npm --prefix desktop install
npm --prefix desktop run build
```

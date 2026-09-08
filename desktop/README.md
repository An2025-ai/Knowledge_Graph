# Brand Atlas desktop shell

The application is distributed as a Tauri 2 Windows desktop app. The React
frontend is rendered inside the app window and the packaged Python backend is
started as a private sidecar; users do not need to open a browser or manage a
local web port.

## Development

```powershell
npm --prefix frontend install
npm --prefix desktop install
npm --prefix desktop run dev
```

The dev command opens a Tauri window and starts Vite. Tauri itself owns the
local Python backend, so closing the window also terminates the backend and
releases the SQLite database. The browser-only Vite workflow remains available
for UI work.

## Windows installer

```powershell
pip install -r requirements-desktop.txt
./scripts/prepare-tauri-sidecar.ps1
npm --prefix frontend install
npm --prefix desktop install
npm --prefix desktop run build
```

The NSIS installer embeds the sidecar. In a packaged application, SQLite and
the other runtime data default to `%LOCALAPPDATA%\BrandAtlas`, with the
database at `%LOCALAPPDATA%\BrandAtlas\database\knowledge.db`. The
development-only Tauri debug process explicitly uses the repository's
`database\knowledge.db` unless an environment override is supplied.

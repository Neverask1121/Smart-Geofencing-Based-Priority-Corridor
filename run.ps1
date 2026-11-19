# Starts the whole application at http://127.0.0.1:8000 (build the frontend first: see README).
Set-Location "$PSScriptRoot\backend"
& "$PSScriptRoot\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

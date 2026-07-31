import sys
from pathlib import Path

# Ensure backend package is importable when running the script directly
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

file_path = "PHASE_2/INPUT/TIO2_Sprint_Intelligence_v5_final.xlsx"

with open(file_path, "rb") as f:
    files = {"file": ("TIO2_Sprint_Intelligence_v5_final.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    resp = client.post("/api/upload", files=files)
    print("STATUS:", resp.status_code)
    try:
        print(resp.json())
    except Exception:
        print(resp.text)

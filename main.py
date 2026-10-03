"""Run the local single-worker MVP from PyCharm or python main.py."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("backend.main:create_app", factory=True, host="127.0.0.1", port=8000, workers=1)

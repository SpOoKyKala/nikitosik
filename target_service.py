"""
Simple service to be monitored and auto-restarted.
"""
from fastapi import FastAPI

app = FastAPI()

is_running = True


@app.get("/health")
def health():
    global is_running
    if not is_running:
        return {"status": "down"}, 503
    return {"status": "healthy", "service": "target"}


@app.post("/restart")
def restart():
    global is_running
    is_running = True
    return {"status": "restarted"}


@app.post("/kill")
def kill():
    global is_running
    is_running = False
    return {"status": "killed"}


if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", 9000))
    uvicorn.run(app, host="0.0.0.0", port=port)
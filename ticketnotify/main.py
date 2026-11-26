"""Application main entry point."""

import uvicorn
from ticketnotify.config import settings
from ticketnotify.api.app import app

def start():
    uvicorn.run(
        "ticketnotify.api.app:app",
        host=settings.HOST,
        port=settings.PORT,
        log_level=settings.LOG_LEVEL.lower(),
        reload=False,
    )

if __name__ == "__main__":
    start()

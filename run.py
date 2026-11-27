#!/usr/bin/env python
"""Run TicketNotify Bot & API Server."""
import os
import uvicorn
from ticketnotify.config import settings

if __name__ == "__main__":
    port = int(os.environ.get("PORT", settings.PORT))
    host = os.environ.get("HOST", settings.HOST)
    uvicorn.run(
        "ticketnotify.api.app:app",
        host=host,
        port=port,
        log_level=settings.LOG_LEVEL.lower(),
        reload=False,
    )

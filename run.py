#!/usr/bin/env python
"""Run TicketNotify Bot & API Server."""
import uvicorn
from ticketnotify.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "ticketnotify.api.app:app",
        host=settings.HOST,
        port=settings.PORT,
        log_level=settings.LOG_LEVEL.lower(),
        reload=False,
    )

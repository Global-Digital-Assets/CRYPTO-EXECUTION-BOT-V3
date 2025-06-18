#!/usr/bin/env python3
"""Robust bot runner with file logging and process management."""
import asyncio
import logging
import signal
import sys
import os
from pathlib import Path

# Setup logging to file AND console
LOG_FILE = Path(__file__).parent / "bot.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode='a'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
shutdown_flag = False

def signal_handler(signum, frame):
    global shutdown_flag
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_flag = True

async def main():
    """Main bot loop with error recovery."""
    logger.info("🚀 Starting Binance Futures Execution Bot")
    logger.info(f"📄 Logging to: {LOG_FILE.absolute()}")
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Import here to ensure logging is setup first
    from main import app
    import uvicorn
    
    # Run FastAPI server with scheduler
    config = uvicorn.Config(app, host="0.0.0.0", port=9010, log_config=None)
    server = uvicorn.Server(config)
    
    try:
        logger.info("🌐 Starting FastAPI server on port 9010...")
        await server.serve()
    except Exception as e:
        logger.exception(f"💥 Server crashed: {e}")
        return 1
    finally:
        logger.info("🛑 Bot shutdown complete")
    
    return 0

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"💀 Fatal error: {e}")
        sys.exit(1)

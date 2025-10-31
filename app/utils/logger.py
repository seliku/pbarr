import logging
import logging.handlers
import os
from pathlib import Path

# Erstelle Logs-Verzeichnis
LOGS_DIR = Path("/app/logs")
LOGS_DIR.mkdir(exist_ok=True)

def setup_logging(log_level: str = "INFO"):
    """Setup logging to file + console"""
    
    # Root Logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Formatter
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File Handler (Rotating)
    log_file = LOGS_DIR / "pbarr.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    root_logger.info(f"✓ Logging initialized - Level: {log_level}, File: {log_file}")

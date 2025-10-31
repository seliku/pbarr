import logging
import json
from pythonjsonlogger import jsonlogger

def setup_logging(log_file="/app/logs/pbarr.log"):
    """Konfiguriert JSON Logging"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # File Handler (JSON)
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.INFO)
    formatter = jsonlogger.JsonFormatter()
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    
    # Console Handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logger.addHandler(ch)
    
    return logger

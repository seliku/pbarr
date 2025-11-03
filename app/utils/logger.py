import logging
import logging.handlers
import os
from pathlib import Path
import shutil

# Erstelle Logs-Verzeichnis (im gemounteten App-Verzeichnis)
LOGS_DIR = Path("/app/app")
LOGS_DIR.mkdir(exist_ok=True)

class LineRotatingFileHandler(logging.FileHandler):
    """File handler that rotates based on number of lines, not size."""

    def __init__(self, filename, maxLines=500, backupCount=5, encoding=None, delay=False):
        super().__init__(filename, 'a', encoding, delay)
        self.maxLines = maxLines
        self.backupCount = backupCount
        self.lineCount = self._count_lines()

    def _count_lines(self):
        """Count current lines in the file."""
        try:
            with open(self.baseFilename, 'r', encoding=self.encoding) as f:
                return sum(1 for _ in f)
        except (OSError, IOError):
            return 0

    def emit(self, record):
        super().emit(record)
        self.lineCount += 1
        if self.lineCount >= self.maxLines:
            self.doRollover()

    def doRollover(self):
        """Rotate the files."""
        if self.stream:
            self.stream.close()
            self.stream = None

        # Rotate existing backups
        for i in range(self.backupCount - 1, 0, -1):
            sfn = f"{self.baseFilename}.{i}"
            dfn = f"{self.baseFilename}.{i + 1}"
            if os.path.exists(sfn):
                if os.path.exists(dfn):
                    os.remove(dfn)
                os.rename(sfn, dfn)

        # Rotate current file
        dfn = f"{self.baseFilename}.1"
        if os.path.exists(dfn):
            os.remove(dfn)
        if os.path.exists(self.baseFilename):
            os.rename(self.baseFilename, dfn)

        # Reset line count
        self.lineCount = 0

        # Reopen the file
        if not self.delay:
            self.stream = self._open()

# Globale Logger-Referenz
_logger = None
_handlers = []

def get_logger():
    """Gibt den globalen Logger zurück"""
    return _logger

def setup_logging(log_level: str = "INFO"):
    """Setup logging to file + console"""
    global _logger, _handlers
    
    # Root Logger
    _logger = logging.getLogger()
    _logger.setLevel(log_level)
    
    # Formatter
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    _logger.addHandler(console_handler)
    
    # File Handler (Rotating based on lines)
    log_file = LOGS_DIR / "pbarr.log"
    file_handler = LineRotatingFileHandler(
        log_file,
        maxLines=500,
        backupCount=5
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    _logger.addHandler(file_handler)
    
    # Handler speichern für später
    _handlers = _logger.handlers
    
    _logger.info(f"✓ Logging initialized - Level: {log_level}, File: {log_file}")

def change_log_level_runtime(new_level: str):
    """Ändere Log-Level zur Laufzeit"""
    global _logger, _handlers
    
    if not _logger:
        return False
    
    try:
        new_level = new_level.upper()
        _logger.setLevel(new_level)
        
        # Alle Handler auch updaten
        for handler in _handlers:
            handler.setLevel(new_level)
        
        logging.getLogger(__name__).info(f"Log-Level changed to {new_level}")
        return True
    except Exception as e:
        logging.getLogger(__name__).error(f"Failed to change log level: {e}")
        return False

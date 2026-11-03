import os
import glob
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, date

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)


def pulisci_log_precedenti():
    """
    Rimuove automaticamente i file di log dei giorni precedenti per mantenere
    la cartella pulita e focalizzata unicamente sugli errori della giornata odierna.
    """
    oggi_str = date.today().strftime("%Y-%m-%d")
    pattern = os.path.join(LOG_DIR, "forensic_*.log")
    for file_path in glob.glob(pattern):
        nome_file = os.path.basename(file_path)
        if oggi_str not in nome_file:
            try:
                os.remove(file_path)
            except OSError:
                pass


def setup_logger(nome: str = "forensic_app") -> logging.Logger:
    """
    Configura un logger professionale con rotazione giornaliera automatica (midnight)
    e pulizia dei log obsoleti.
    """
    pulisci_log_precedenti()

    oggi_str = date.today().strftime("%Y-%m-%d")
    log_file = os.path.join(LOG_DIR, f"forensic_{oggi_str}.log")

    logger = logging.getLogger(nome)
    logger.setLevel(logging.DEBUG)

    # Evita handler duplicati se la funzione viene richiamata nei rerun di Streamlit
    if not logger.handlers:
        # Formato professionale per diagnosi immediata
        formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)-7s] [%(name)s:%(funcName)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # 1. Handler su file con rotazione a mezzanotte
        file_handler = TimedRotatingFileHandler(
            filename=log_file,
            when="midnight",
            interval=1,
            backupCount=1,  # Conserva al massimo il backup del giorno prima
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # 2. Handler su console (stdout)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


def leggi_ultimi_log(max_righe: int = 100) -> str:
    """
    Legge le ultime righe del log di oggi per mostrarle nella UI di diagnostica.
    """
    oggi_str = date.today().strftime("%Y-%m-%d")
    log_file = os.path.join(LOG_DIR, f"forensic_{oggi_str}.log")
    if not os.path.exists(log_file):
        return "Nessun evento registrato per la giornata di oggi."

    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            righe = f.readlines()
            return "".join(righe[-max_righe:])
    except Exception as e:
        return f"Errore lettura log: {e}"


# Istanza condivisa del logger
log = setup_logger()

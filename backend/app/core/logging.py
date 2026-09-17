import logging
import logging.config
import sys


def configure_logging(level: str = "INFO") -> None:
    if sys.stderr is None:
        # Windowed desktop executables intentionally have no console stream.
        # The desktop launcher installs a persistent file handler before the
        # API is imported; retain it instead of replacing it with a broken
        # StreamHandler(None).
        logging.getLogger().setLevel(level.upper())
        logging.getLogger("httpx").setLevel(logging.WARNING)
        return
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}
            },
            "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "standard"}},
            # httpx request logs include query parameters; TMDB authenticates
            # with one, so keep routine request URLs out of application logs.
            "loggers": {"httpx": {"level": "WARNING", "propagate": True}},
            "root": {"handlers": ["console"], "level": level.upper()},
        }
    )

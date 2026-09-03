import logging
import logging.config


def configure_logging(level: str = "INFO") -> None:
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

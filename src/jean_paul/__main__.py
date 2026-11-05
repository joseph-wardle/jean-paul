import logging
import sys

from jean_paul import bot
from jean_paul.config import ConfigError, load_config

log = logging.getLogger("jean_paul")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        bot.run(load_config())
    except (ConfigError, bot.SetupError) as error:
        log.error("Jean Paul cannot start:\n%s", error)
        sys.exit(1)


if __name__ == "__main__":
    main()

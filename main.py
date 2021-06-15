from __future__ import annotations

# from reinhard import config as config_
import reinhard.cli


if __name__ == "__main__":
    # import multikari

    # bot_token = config_.load_config().tokens.bot
    # # shard_count, shard_ids = multikari.master.Puppeteer.fetch_shard_stats(bot_token)
    # cli = multikari.master.Master.from_package(
    #     "reinhard.client", "build", bot_token, shard_count=2, shard_ids={0,1}
    # )
    # cli.run()
    # try:
    #     cli.run()
    #
    # except KeyboardInterrupt:
    #     import time
    #     print("goodnight")
    #     time.sleep(15)
    #     raise
    reinhard.cli.main()

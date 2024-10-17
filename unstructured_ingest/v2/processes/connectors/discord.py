import datetime as dt
from dataclasses import dataclass
from typing import Any, Generator, Optional

from pydantic import Field, Secret

from unstructured_ingest.logger import logger
from unstructured_ingest.utils.dep_check import requires_dependencies
from unstructured_ingest.v2.interfaces import (
    AccessConfig,
    ConnectionConfig,
    Downloader,
    DownloaderConfig,
    DownloadResponse,
    FileData,
    FileDataSourceMetadata,
    Indexer,
    IndexerConfig,
    SourceIdentifiers,
)
from unstructured_ingest.v2.processes.connector_registry import SourceRegistryEntry

CONNECTOR_TYPE = "discord"


class DiscordAccessConfig(AccessConfig):
    token: str = Field(description="Discord API token")


class DiscordConnectionConfig(ConnectionConfig):
    access_config: Secret[DiscordAccessConfig]
    channels: Optional[list[str]] = Field(
        default=None, description="List of Discord channel IDs to process"
    )


class DiscordIndexerConfig(IndexerConfig):
    pass


@dataclass
class DiscordIndexer(Indexer):
    connection_config: DiscordConnectionConfig
    index_config: DiscordIndexerConfig

    @requires_dependencies(["discord"], extras="discord")
    def get_client(self):
        import discord

        intents = discord.Intents.default()
        intents.message_content = True
        return discord.Client(intents=intents)

    def run(self, **kwargs: Any) -> Generator[FileData, None, None]:
        client = self.get_client()
        processed_channels: set[str] = set()
        channels_to_process: set[str] = set(self.connection_config.channels or [])

        for channel_id in list(channels_to_process):
            if channel_id in processed_channels:
                continue

            processed_channels.add(channel_id)
            channels_to_process.remove(channel_id)
            file_data = self.get_channel_file_data(channel_id=channel_id, client=client)
            if file_data:
                yield file_data

    @requires_dependencies(["discord"], extras="discord")
    def get_channel_file_data(self, channel_id: str, client) -> Optional[FileData]:
        # Fetch channel metadata
        channel_metadata = {}  # Replace with actual metadata retrieval
        date_created = dt.datetime.utcnow().isoformat()
        identifier = channel_id
        source_identifiers = SourceIdentifiers(
            filename=f"{channel_id}.txt",
            fullpath=channel_id,
            rel_path=channel_id,
        )
        metadata = FileDataSourceMetadata(
            date_created=date_created,
            date_modified=date_created,
            record_locator={"channel_id": channel_id},
            date_processed=str(dt.datetime.utcnow().timestamp()),
        )
        additional_metadata = channel_metadata
        return FileData(
            identifier=identifier,
            connector_type=CONNECTOR_TYPE,
            source_identifiers=source_identifiers,
            metadata=metadata,
            additional_metadata=additional_metadata,
        )


class DiscordDownloaderConfig(DownloaderConfig):
    @requires_dependencies(["discord"], extras="discord")
    def get_client(self):
        import discord

        intents = discord.Intents.default()
        intents.message_content = True
        return discord.Client(intents=intents)


@dataclass
class DiscordDownloader(Downloader):
    connection_config: DiscordConnectionConfig
    download_config: DiscordDownloaderConfig

    async def run(self, file_data: FileData, **kwargs: Any) -> DownloadResponse:
        client = self.download_config.get_client()
        record_locator = file_data.metadata.record_locator

        if "channel_id" in record_locator:
            return await self.download_channel(
                client=client,
                channel_id=record_locator["channel_id"],
                file_data=file_data,
            )
        else:
            raise ValueError("Invalid record_locator in file_data")

    async def download_channel(
        self, client, channel_id: str, file_data: FileData
    ) -> DownloadResponse:
        import discord
        from discord.ext import commands

        bot = commands.Bot(command_prefix=">", intents=client.intents)
        download_path = self.get_download_path(file_data=file_data)
        download_path.parent.mkdir(parents=True, exist_ok=True)

        messages: list[discord.Message] = []

        @bot.event
        async def on_ready():
            try:
                channel = bot.get_channel(int(channel_id))
                async for msg in channel.history(limit=100):  # Example message limit
                    messages.append(msg)
            except Exception as e:
                logger.error(f"Error fetching messages from channel {channel_id}: {e}")
            finally:
                await bot.close()

        try:
            await bot.start(self.connection_config.access_config.get_secret_value().token)
        except Exception as e:
            logger.error(f"Error starting bot: {e}")

        with open(download_path, "w") as file:
            for message in messages:
                file.write(f"{message.content}\n")

        return self.generate_download_response(file_data=file_data, download_path=download_path)


discord_source_entry = SourceRegistryEntry(
    indexer=DiscordIndexer,
    indexer_config=DiscordIndexerConfig,
    downloader=DiscordDownloader,
    downloader_config=DiscordDownloaderConfig,
    connection_config=DiscordConnectionConfig,
)

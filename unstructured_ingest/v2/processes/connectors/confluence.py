import math
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from time import time
from typing import TYPE_CHECKING, Any, Generator, Optional, List

from unstructured_ingest.__version__ import __version__ as unstructured_version
from unstructured_ingest.error import DestinationConnectionError, SourceConnectionError
from unstructured_ingest.utils.data_prep import batch_generator, flatten_dict
from unstructured_ingest.utils.dep_check import requires_dependencies
from dataclasses import dataclass 
from pydantic import Field, Secret
from unstructured_ingest.v2.logger import logger

from unstructured_ingest.v2.interfaces import (
    AccessConfig,
    ConnectionConfig,
    Downloader,
    DownloaderConfig,
    FileData,
    FileDataSourceMetadata,
    Indexer,
    IndexerConfig,
    SourceIdentifiers,
    download_responses,
)

from unstructured_ingest.v2.processes.connector_registry import (
    DestinationRegistryEntry,
    SourceRegistryEntry,
)


@dataclass
class ConfluenceAccessConfig(AccessConfig):
    api_token: Field(default=..., repr=False, description="Confluence API token")

@dataclass
class ConfluenceConnectionConfig(ConnectionConfig):
    url: str = Field(..., description="URL of the Confluence instance")
    user_email: str = Field(..., description="User email for authentication")
    access_config: ConfluenceAccessConfig = Field(..., description="Access configuration for Confluence")
    
@dataclass
class ConfluenceIndexerConfig(IndexerConfig):
    max_num_of_spaces: int = Field(500, description="Maximum number of spaces to index")
    max_num_of_docs_from_each_space: int = Field(100, description="Maximum number of documents to fetch from each space")
    spaces: Optional[List[str]] = Field(None, description="List of specific space keys to index")
    
@dataclass
class ConfluenceIndexer(Indexer):
    connection_config: ConfluenceConnectionConfig
    indexer_config: ConfluenceIndexerConfig
    connector_type: str = "confluence"
    _confluence: Any = field(init=False, default=None)

    def __post_init__(self):
        self._confluence = None

    @property
    def confluence(self):
        if self._confluence is None:
            from atlassian import Confluence
            self._confluence = Confluence(
                url=self.connection_config.url,
                username=self.connection_config.user_email,
                password=self.connection_config.access_config.api_token.get_secret_value(),
            )
        return self._confluence

    def precheck(self) -> None:
        try:
            self.confluence.get_space(space_key="TEST", expand=None)
            logger.info("Connection to Confluence successful.")
        except Exception as e:
            logger.error(f"Failed to connect to Confluence: {e}", exc_info=True)
            raise SourceConnectionError(f"Failed to connect to Confluence: {e}")

    def _get_space_ids(self) -> List[str]:
        spaces = self.indexer_config.spaces
        if spaces:
            return spaces
        else:
            all_spaces = self.confluence.get_all_spaces(limit=self.indexer_config.max_num_of_spaces)
            space_ids = [space["key"] for space in all_spaces["results"]]
            return space_ids

    def _get_docs_ids_within_one_space(self, space_id: str) -> List[dict]:
        pages = self.confluence.get_all_pages_from_space(
            space=space_id,
            start=0,
            limit=self.indexer_config.max_num_of_docs_from_each_space,
            expand=None,
            content_type='page',
            status=None,
            label=None,
        )
        doc_ids = [{"space_id": space_id, "doc_id": page["id"]} for page in pages]
        return doc_ids

    def run(self) -> Generator[FileData, None, None]:
        space_ids = self._get_space_ids()
        for space_id in space_ids:
            doc_ids = self._get_docs_ids_within_one_space(space_id)
            for doc in doc_ids:
                doc_id = doc["doc_id"]
                metadata = {
                    "space_id": space_id,
                    "document_id": doc_id,
                }
                file_data = FileData(
                    identifier=doc_id,
                    connector_type=self.connector_type,
                    metadata=metadata,
                    source_url=f"{self.connection_config.url}/pages/{doc_id}",
                )
                yield file_data


@dataclass
class ConfluenceDownloaderConfig(DownloaderConfig):
    pass

@dataclass
class ConfluenceDownloader(Downloader):
    connection_config: ConfluenceConnectionConfig
    downloader_config: ConfluenceDownloaderConfig = field(default_factory=ConfluenceDownloaderConfig)
    connector_type: str = "confluence"
    _confluence: Any = field(init=False, default=None)

    def __post_init__(self):
        self._confluence = None

    @property
    def confluence(self):
        if self._confluence is None:
            from atlassian import Confluence
            self._confluence = Confluence(
                url=self.connection_config.url,
                username=self.connection_config.user_email,
                password=self.connection_config.access_config.api_token.get_secret_value(),
            )
        return self._confluence

    def precheck(self) -> None:
        # Optional: Implement any necessary prechecks
        pass

    def run(self, file_data: FileData, **kwargs) -> download_responses:
        doc_id = file_data.identifier
        try:
            page = self.confluence.get_page_by_id(
                page_id=doc_id,
                expand="history.lastUpdated,version,body.view",
            )
        except Exception as e:
            logger.error(f"Failed to retrieve page with ID {doc_id}: {e}", exc_info=True)
            raise SourceConnectionError(f"Failed to retrieve page with ID {doc_id}: {e}")

        if not page:
            raise ValueError(f"Page with ID {doc_id} does not exist.")

        content = page["body"]["view"]["value"]
        # Save content to a temporary file
        filename = f"{doc_id}.html"
        download_path = Path(self.download_dir) / filename
        download_path.parent.mkdir(parents=True, exist_ok=True)
        with open(download_path, "w", encoding="utf8") as f:
            f.write(content)

        # Update file_data with metadata
        file_data.metadata.update({
            "date_created": page["history"]["createdDate"],
            "date_modified": page["version"]["when"],
            "version": page["version"]["number"],
            "title": page["title"],
        })

        return self.generate_download_response(file_data=file_data, download_path=download_path)
    
confluence_source_entry = SourceRegistryEntry(
    connection_config=ConfluenceConnectionConfig,
    indexer_config=ConfluenceIndexerConfig,
    indexer=ConfluenceIndexer,
    downloader_config=ConfluenceDownloaderConfig,
    downloader=ConfluenceDownloader,
)
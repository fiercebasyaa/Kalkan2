from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "app" / "data"
CACHE_DIR = DATA_DIR / "cache"
HISTORY_DIR = DATA_DIR / "history"
MANUAL_FLAGS_PATH = DATA_DIR / "manual_flags.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Zerion — primary source for portfolio + tx history of any address.
    # NOTE: base URL / auth style taken from Zerion docs from memory,
    # needs a live smoke test once a real key is available.
    zerion_api_key: str = ""
    zerion_base_url: str = "https://api.zerion.io/v1"

    # QuickNode — one HTTPS RPC endpoint per chain (+ marketplace add-ons:
    # Token API, Trace API). A chain whose var is unset is simply not
    # available as a fallback for that chain.
    quicknode_rpc_url_ethereum: str = ""
    quicknode_rpc_url_arbitrum: str = ""
    quicknode_rpc_url_base: str = ""
    quicknode_rpc_url_polygon: str = ""
    quicknode_rpc_url_optimism: str = ""
    quicknode_rpc_url_bsc: str = ""
    quicknode_rpc_url_avalanche: str = ""

    # Optional scam-db sources.
    chainabuse_api_key: str = ""
    chainabuse_base_url: str = "https://api.chainabuse.com"

    # Scrapes etherscan.io's address page for community exploit/scam
    # warnings + name tags (e.g. "Kelp DAO Exploiter 3") that aren't
    # exposed through Etherscan's own API. Fragile by nature — flip to
    # false if it starts causing 429s/CAPTCHAs; everything else keeps working.
    etherscan_scrape_enabled: bool = True

    ofac_sdn_xml_url: str = (
        "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.XML"
    )
    cryptoscamdb_addresses_url: str = (
        "https://raw.githubusercontent.com/CryptoScamDB/blacklist/master/data/addresses.json"
    )
    scamsniffer_addresses_url: str = (
        "https://raw.githubusercontent.com/scamsniffer/scam-database/main/blacklist/address.json"
    )
    mew_darklist_url: str = (
        "https://raw.githubusercontent.com/MyEtherWallet/ethereum-lists/master/"
        "src/addresses/addresses-darklist.json"
    )
    # Per-chain URLs for the Etherscan-labels dataset live in
    # etherscan_labels.py's CHAIN_SOURCES — six chains, not one, so a single
    # config field doesn't fit; not worth a config override for this.

    scam_db_cache_ttl_seconds: int = 6 * 3600

    telegram_bot_token: str = ""
    telegram_channel_id: str = ""

    watchlist_poll_interval_seconds: int = 15 * 60
    watchlist_drop_alert_pct: float = 15.0

    cors_origins: list[str] = ["*"]

    @property
    def zerion_enabled(self) -> bool:
        return bool(self.zerion_api_key)

    @property
    def quicknode_urls(self) -> dict[str, str]:
        raw = {
            "ethereum": self.quicknode_rpc_url_ethereum,
            "arbitrum": self.quicknode_rpc_url_arbitrum,
            "base": self.quicknode_rpc_url_base,
            "polygon": self.quicknode_rpc_url_polygon,
            "optimism": self.quicknode_rpc_url_optimism,
            "bsc": self.quicknode_rpc_url_bsc,
            "avalanche": self.quicknode_rpc_url_avalanche,
        }
        return {chain: url for chain, url in raw.items() if url}

    @property
    def quicknode_enabled(self) -> bool:
        return bool(self.quicknode_urls)

    def quicknode_enabled_for(self, chain: str) -> bool:
        return chain in self.quicknode_urls

    @property
    def chainabuse_enabled(self) -> bool:
        return bool(self.chainabuse_api_key)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_channel_id)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return settings

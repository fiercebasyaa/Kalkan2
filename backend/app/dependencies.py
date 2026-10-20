from fastapi import Request

from app.config import Settings
from app.services.quicknode import QuickNodeClient
from app.services.scamdb.aggregator import ScamDbAggregator
from app.services.zerion import ZerionClient


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_zerion(request: Request) -> ZerionClient:
    return request.app.state.zerion


def get_quicknode(request: Request) -> QuickNodeClient:
    return request.app.state.quicknode


def get_scamdb(request: Request) -> ScamDbAggregator:
    return request.app.state.scamdb

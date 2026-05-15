"""
Setup Service
=============

System setup and initialization for Master Prep AI.

Port configuration is done via .env file:
    BACKEND_PORT=8001   (default: 8001)
    FRONTEND_PORT=3782  (default: 3782)

Usage:
    from master_prep_ai.services.setup import init_user_directories, get_backend_port

    # Initialize user directories
    init_user_directories()

    # Get server ports (from .env)
    backend_port = get_backend_port()
    frontend_port = get_frontend_port()
"""

from .init import (
    get_backend_port,
    get_frontend_port,
    get_ports,
    init_user_directories,
)

__all__ = [
    "init_user_directories",
    "get_backend_port",
    "get_frontend_port",
    "get_ports",
]

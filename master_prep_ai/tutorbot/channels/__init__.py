"""Chat channels module with plugin architecture."""

from master_prep_ai.tutorbot.channels.base import BaseChannel
from master_prep_ai.tutorbot.channels.manager import ChannelManager

__all__ = ["BaseChannel", "ChannelManager"]

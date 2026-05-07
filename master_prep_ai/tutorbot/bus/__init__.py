"""Message bus module for decoupled channel-agent communication."""

from master_prep_ai.tutorbot.bus.events import InboundMessage, OutboundMessage
from master_prep_ai.tutorbot.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]

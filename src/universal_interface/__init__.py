"""Universal AI Interface — connector framework and orchestration core."""

from universal_interface.connector import Connector
from universal_interface.models import Action, Capability, UnifiedDataItem

__all__ = ["Connector", "Capability", "Action", "UnifiedDataItem", "__version__"]

__version__ = "0.1.0"

"""
Base Brain Abstract Class for Trader-N Cognitive Architecture.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from core.models import TradeEvent, BrainVote
from core.bonding_curve import PumpBondingCurve


class BaseBrain(ABC):
    """Abstract cognitive observer that evaluates market reality from an orthogonal perspective."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def evaluate(
        self,
        mint: str,
        trade: TradeEvent,
        curve: PumpBondingCurve,
        context: Dict[str, Any],
    ) -> BrainVote:
        """
        Evaluates the trade and context.
        Returns a BrainVote with score [0, 1], confidence [0, 1], key evidence string, and optional veto.
        """
        pass

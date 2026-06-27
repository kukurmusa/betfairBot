"""Historical Betfair data loader.

Parses .bz2 streaming files from the Betfair historical data service
into a sequence of per-tick MarketData objects suitable for replay.
"""

from __future__ import annotations

import bz2
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from betfairlightweight.streaming.listener import StreamListener

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketTick:
    """One price snapshot for the draw runner."""

    timestamp: datetime
    draw_lay_price: Decimal
    draw_back_price: Decimal
    volume: int


@dataclass
class MarketData:
    """Parsed historical data for a single market."""

    market_id: str
    event_name: str
    kick_off: datetime | None
    draw_selection_id: int
    ticks: list[MarketTick] = field(default_factory=list)


class HistoricalLoader:
    """Load and parse Betfair .bz2 historical streaming files."""

    def load_file(self, filepath: Path) -> MarketData | None:
        """Parse a single .bz2 or plain streaming file into tick data.

        Returns None if the file cannot be opened, has no draw runner,
        or produces no valid ticks.
        """
        try:
            lines = self._read_lines(filepath)
        except OSError as exc:
            logger.error("Cannot open %s: %s", filepath, exc)
            return None

        listener = StreamListener(max_latency=None)
        market_data: MarketData | None = None
        draw_selection_id: int | None = None

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                listener.on_data(line)
            except Exception:  # noqa: BLE001
                logger.warning("Parse error in %s — skipping line", filepath.name)
                continue

            for market_book in listener.snap():
                if market_data is None:
                    market_data, draw_selection_id = self._init_market(
                        market_book, filepath
                    )
                if market_data is None or draw_selection_id is None:
                    continue
                tick = self._extract_tick(market_book, draw_selection_id)
                if tick is not None:
                    market_data.ticks.append(tick)

        if not market_data or not market_data.ticks:
            logger.warning("No usable ticks in %s", filepath)
            return None

        logger.info("Loaded %s: %d ticks", market_data.event_name, len(market_data.ticks))
        return market_data

    def load_directory(self, dirpath: Path, pattern: str = "*.bz2") -> Iterator[MarketData]:
        """Yield MarketData for each matching file in dirpath, sorted by name."""
        files = sorted(dirpath.glob(pattern))
        logger.info("Found %d files in %s", len(files), dirpath)
        for filepath in files:
            result = self.load_file(filepath)
            if result is not None:
                yield result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_lines(filepath: Path) -> list[str]:
        """Read file lines, decompressing .bz2 if needed."""
        if filepath.suffix == ".bz2":
            with bz2.open(filepath, "rt", encoding="utf-8") as f:
                return f.readlines()
        with open(filepath, encoding="utf-8") as f:
            return f.readlines()

    @staticmethod
    def _init_market(
        market_book: object, filepath: Path
    ) -> tuple[MarketData | None, int | None]:
        """Extract market metadata from a market book snapshot."""
        market_definition = getattr(market_book, "market_definition", None)
        if market_definition is None:
            return None, None

        draw_id = HistoricalLoader._find_draw_selection_id(market_definition)
        if draw_id is None:
            logger.debug("No 'The Draw' runner in %s — skipping", filepath.name)
            return None, None

        event_name: str = (
            getattr(market_definition, "event_name", None)
            or getattr(market_book, "market_id", filepath.stem)
        )
        kick_off: datetime | None = getattr(market_definition, "market_time", None)
        if kick_off is not None and kick_off.tzinfo is None:
            kick_off = kick_off.replace(tzinfo=UTC)

        return MarketData(
            market_id=getattr(market_book, "market_id", filepath.stem),
            event_name=event_name,
            kick_off=kick_off,
            draw_selection_id=draw_id,
        ), draw_id

    @staticmethod
    def _find_draw_selection_id(market_definition: object) -> int | None:
        """Return selection_id of 'The Draw' runner from market definition."""
        for runner in getattr(market_definition, "runners", None) or []:
            if getattr(runner, "name", None) == "The Draw":
                return int(runner.id)
        return None

    @staticmethod
    def _extract_tick(market_book: object, draw_selection_id: int) -> MarketTick | None:
        """Extract draw runner prices from one market book snapshot."""
        for runner in getattr(market_book, "runners", None) or []:
            if getattr(runner, "selection_id", None) != draw_selection_id:
                continue
            ex = getattr(runner, "ex", None)
            if ex is None:
                return None
            lay_list = getattr(ex, "available_to_lay", None) or []
            back_list = getattr(ex, "available_to_back", None) or []
            if not lay_list or not back_list:
                return None

            timestamp: datetime = (
                getattr(market_book, "publish_time", None) or datetime.now(UTC)
            )
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)

            return MarketTick(
                timestamp=timestamp,
                draw_lay_price=Decimal(str(lay_list[0].price)),
                draw_back_price=Decimal(str(back_list[0].price)),
                volume=int(getattr(market_book, "total_matched", 0) or 0),
            )
        return None

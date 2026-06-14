"""Betfair streaming API connection with auto-reconnect and price logging.

Manages the persistent WebSocket connection to the Betfair Streaming API,
processes market book updates, and writes tick data to the database.

Architecture:
    The ``Stream.start()`` call in betfairlightweight is blocking — it runs
    the WebSocket receive loop in the calling thread.  To keep database I/O
    async, the stream runs in ``asyncio.to_thread`` and pushes market book
    snapshots onto an ``asyncio.Queue``.  A separate async task drains the
    queue, identifies the draw runner, extracts prices, and persists ticks.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

import betfairlightweight
from betfairlightweight import APIClient

from src.config.settings import SecretsConfig, StreamingConfig
from src.db.repository import Repository
from src.exceptions import BetfairStreamError
from src.strategy.ltd_strategy import LTDStrategy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-market state
# ---------------------------------------------------------------------------


@dataclass
class _StreamContext:
    """Cached state for a tracked market."""

    market_id: str
    betfair_market_id: str
    db_market_id: uuid.UUID
    event_name: str
    draw_selection_id: int
    kick_off: object | None = None
    last_draw_lay_price: Decimal | None = None
    last_draw_back_price: Decimal | None = None
    last_volume: int = 0


# ---------------------------------------------------------------------------
# MarketStream
# ---------------------------------------------------------------------------


class MarketStream:
    """Manages the Betfair streaming connection with auto-reconnect.

    Three concurrent tasks:
    1. **Stream reader** (thread) — runs betfairlightweight's blocking stream,
       pushes market books onto an async queue.
    2. **Processor** (async) — drains the queue, identifies the draw runner,
       extracts prices, persists via Repository.
    3. **Logger** (async) — every 30 seconds prints status for all tracked markets.
    """

    def __init__(
        self,
        trading_client: APIClient,
        competition_ids: dict[str, str],
        config: StreamingConfig,
        secrets: SecretsConfig,
        repository: Repository,
        run_id: uuid.UUID,
        strategy: LTDStrategy | None = None,
    ) -> None:
        self._trading_client = trading_client
        self._competition_ids = competition_ids
        self._config = config
        self._secrets = secrets
        self._repository = repository
        self._run_id = run_id
        self._strategy = strategy

        # Internal state
        self._markets: dict[str, _StreamContext] = {}
        self._queue: asyncio.Queue[object] = asyncio.Queue(maxsize=10_000)
        self._running = False
        self._connected = False
        self._stream: object | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start streaming, processing, and logging loops.

        Runs until ``stop()`` is called or the connection fails after
        exhausting all reconnection attempts.
        """
        self._running = True

        processor_task = asyncio.create_task(self._process_updates())
        logger_task = asyncio.create_task(self._logging_loop())

        try:
            await self._connect_with_retry()
        finally:
            self._running = False
            processor_task.cancel()
            logger_task.cancel()
            # Let cancelled tasks clean up
            await asyncio.gather(processor_task, logger_task, return_exceptions=True)

    async def stop(self) -> None:
        """Graceful shutdown: disconnect stream, flush remaining queue items."""
        logger.info("Stopping market stream...")
        self._running = False

        if self._stream is not None:
            try:
                await asyncio.to_thread(self._stream.stop)
            except Exception:
                pass
            self._stream = None

        self._connected = False
        logger.info("Market stream stopped")

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def _connect_with_retry(self) -> None:
        """Connect with exponential backoff, up to the configured max retries.

        The first connection attempt has no delay.  Each subsequent attempt
        doubles the delay (2^attempt seconds) starting from
        ``reconnect_base_delay_s``.
        """
        max_attempts = self._config.max_reconnect_attempts
        base_delay = self._config.reconnect_base_delay_s
        attempt = 0

        while self._running and attempt <= max_attempts:
            try:
                loop = asyncio.get_running_loop()
                self._connected = True
                logger.info(
                    "Starting stream (attempt %d/%d)", attempt + 1, max_attempts + 1
                )

                # Run the blocking stream.start() in a thread
                await asyncio.to_thread(self._start_stream_blocking, loop)

                # stream.start() returned cleanly — connection closed by server
                logger.warning("Stream disconnected (server closed connection)")
                self._connected = False

            except Exception as exc:
                self._connected = False
                logger.error("Stream error: %s", exc)

            if not self._running:
                break

            attempt += 1
            if attempt > max_attempts:
                raise BetfairStreamError(
                    f"Stream reconnection failed after {max_attempts} attempts"
                )

            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "Reconnecting in %.1fs (attempt %d/%d)",
                delay,
                attempt + 1,
                max_attempts + 1,
            )
            await asyncio.sleep(delay)

    def _start_stream_blocking(self, loop: asyncio.AbstractEventLoop) -> None:
        """Create and start the betfairlightweight stream.

        This runs in a thread via ``asyncio.to_thread``.  It blocks until the
        WebSocket disconnects.  Market book callbacks push data onto the async
        queue via ``loop.call_soon_threadsafe``.

        Args:
            loop: The running event loop (needed for thread-safe queue push).
        """
        listener = betfairlightweight.StreamListener(max_latency=0.5)

        def _on_market_book(market_book):
            loop.call_soon_threadsafe(self._queue.put_nowait, market_book)

        listener.on_market_book = _on_market_book

        stream = self._trading_client.streaming.create_stream(listener=listener)
        self._stream = stream

        # Build market filter from resolved competition IDs
        comp_ids = list(self._competition_ids.values())
        if not comp_ids:
            logger.warning(
                "No competition IDs available. Stream will connect but "
                "receive no market data."
            )

        market_filter = {
            "marketTypeCodes": ["MATCH_ODDS"],
        }
        if comp_ids:
            market_filter["competitionIds"] = comp_ids

        data_filter = {
            "fields": ["EX_BEST_OFFERS", "EX_MARKET_DEF"],
            "ladderLevels": 3,
        }

        logger.info(
            "Subscribing to MATCH_ODDS markets (%d competition(s))",
            len(comp_ids),
        )
        stream.subscribe_to_markets(
            market_filter=market_filter,
            market_data_filter=data_filter,
        )

        # Blocks until WebSocket disconnects
        stream.start()

    # ------------------------------------------------------------------
    # Market book processing (async)
    # ------------------------------------------------------------------

    async def _process_updates(self) -> None:
        """Drain the async queue and process each market book update.

        Runs as an asyncio task alongside the logging loop.
        Drains up to 50 items per iteration to avoid starvation.
        """
        while self._running:
            try:
                # Wait for the first item with a short timeout so we can
                # check self._running periodically
                market_book = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            # Drain any additional queued items up to a batch limit
            batch = [market_book]
            for _ in range(49):
                if self._queue.empty():
                    break
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            for mb in batch:
                try:
                    await self._handle_market_book(mb)
                except Exception as exc:
                    logger.error(
                        "Error processing market book for market %s: %s",
                        getattr(mb, "id", "?"),
                        exc,
                    )

    async def _handle_market_book(self, market_book) -> None:
        """Process a single market book snapshot.

        1. If the market is new, discover it: find the draw runner, persist
           to the ``markets`` table.
        2. Extract the best lay / best back prices for the draw runner.
        3. Write one row to the ``ticks`` table.
        """
        market_id = str(market_book.id)
        volume = getattr(market_book, "total_matched", 0) or 0

        # --- Market discovery (first time we see this market) ---
        if market_id not in self._markets:
            await self._discover_market(market_book)
            if market_id not in self._markets:
                return  # Discovery failed (no draw runner, etc.)

        ctx = self._markets[market_id]

        # --- Price extraction ---
        draw_lay_price: Decimal | None = None
        draw_back_price: Decimal | None = None

        for runner in market_book.runners:
            if runner.selection_id == ctx.draw_selection_id:
                ex = runner.ex
                if ex:
                    available_to_lay = getattr(ex, "available_to_lay", None)
                    available_to_back = getattr(ex, "available_to_back", None)

                    if available_to_lay and len(available_to_lay) > 0:
                        draw_lay_price = Decimal(str(available_to_lay[0].price))
                    if available_to_back and len(available_to_back) > 0:
                        draw_back_price = Decimal(str(available_to_back[0].price))
                break

        # Update cache for the 30-second logger
        if draw_lay_price is not None:
            ctx.last_draw_lay_price = draw_lay_price
        if draw_back_price is not None:
            ctx.last_draw_back_price = draw_back_price
        ctx.last_volume = volume

        # --- Persist tick ---
        if draw_lay_price is not None and draw_back_price is not None:
            await self._repository.insert_tick(
                market_id=ctx.db_market_id,
                draw_lay_price=draw_lay_price,
                draw_back_price=draw_back_price,
                volume_matched=volume,
            )

            # --- Forward to strategy ---
            if self._strategy is not None:
                from datetime import UTC, datetime

                await self._strategy.on_market_book(
                    market_id=ctx.market_id,
                    db_market_id=ctx.db_market_id,
                    betfair_market_id=ctx.betfair_market_id,
                    event_name=ctx.event_name,
                    draw_selection_id=ctx.draw_selection_id,
                    draw_lay_price=draw_lay_price,
                    draw_back_price=draw_back_price,
                    volume=volume,
                    timestamp=datetime.now(UTC),
                    kick_off=ctx.kick_off,
                )

    async def _discover_market(self, market_book) -> None:
        """Discover a new market: find the draw runner and persist to DB."""
        market_id = str(market_book.id)
        market_def = getattr(market_book, "market_definition", None)
        if market_def is None:
            logger.debug("Market %s has no definition yet, skipping", market_id)
            return

        # Identify the draw runner
        draw_selection_id = self._find_draw_selection_id(market_def)
        if draw_selection_id is None:
            logger.warning(
                "Market %s has no 'The Draw' runner — skipping",
                market_id,
            )
            return

        # Build event name
        event_name = getattr(market_def, "event_name", None)
        if not event_name:
            home = getattr(market_def, "home_team", "?")
            away = getattr(market_def, "away_team", "?")
            event_name = f"{home} v {away}"

        market_time = getattr(market_def, "market_time", None)

        # Persist
        db_market = await self._repository.upsert_market(
            run_id=self._run_id,
            betfair_market_id=market_id,
            event_name=event_name,
            market_type="MATCH_ODDS",
            kick_off=market_time,
            status="pending",
        )

        self._markets[market_id] = _StreamContext(
            market_id=market_id,
            betfair_market_id=market_id,
            db_market_id=db_market.id,
            event_name=event_name,
            draw_selection_id=draw_selection_id,
            kick_off=market_time,
        )

    # ------------------------------------------------------------------
    # Draw runner identification
    # ------------------------------------------------------------------

    @staticmethod
    def _find_draw_selection_id(market_definition) -> int | None:
        """Find the draw runner's selection_id by matching runner name.

        Args:
            market_definition: A ``MarketDefinition`` object from betfairlightweight.

        Returns:
            The selection_id of "The Draw" runner, or None if not found.
        """
        runners = getattr(market_definition, "runners", None)
        if not runners:
            return None

        for runner in runners:
            desc = getattr(runner, "description", None)
            if desc and getattr(desc, "runner_name", None) == "The Draw":
                return runner.selection_id
        return None

    # ------------------------------------------------------------------
    # Periodic status logger
    # ------------------------------------------------------------------

    async def _logging_loop(self) -> None:
        """Log market status every 30 seconds.

        Prints market name, draw lay price, and volume for every tracked
        market, plus connection status.
        """
        while self._running:
            if self._markets:
                for ctx in list(self._markets.values()):
                    price = ctx.last_draw_lay_price or Decimal("0")
                    volume = ctx.last_volume or 0
                    logger.info(
                        "%s | Draw Lay: %.2f | Volume: %d",
                        ctx.event_name,
                        price,
                        volume,
                    )
            else:
                logger.info("No active markets")

            logger.info(
                "Connection: %s | Tracked markets: %d",
                "connected" if self._connected else "disconnected",
                len(self._markets),
            )

            await asyncio.sleep(30)

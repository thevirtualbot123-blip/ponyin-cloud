"""
main.py — Main entry point for PONYIN bot.
"""
import asyncio, logging, signal, sys
from datetime import datetime
from config import AgentConfig
from telegram_bot import TelegramBot
from data_fetcher import DataFetcher
from filter_engine import FilterEngine, Token
from decision_engine import DecisionEngine
from gmgn_client import GMGNClient

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger("PONYIN.Main")

class PONYINBot:
    def __init__(self):
        self.cfg = AgentConfig()
        self.running = False
        
        # Inisialisasi komponen
        self.telegram_bot = None
        self.data_fetcher = None
        self.filter_engine = None
        self.decision_engine = None
        
        # Stats
        self.stats = {
            'tokens_processed': 0,
            'alerts_sent': 0,
            'last_fetch_time': None
        }

    async def initialize(self):
        """Initialize all components."""
        log.info("Initializing PONYIN bot...")
        
        # Initialize engines
        self.filter_engine = FilterEngine(self.cfg)
        self.decision_engine = DecisionEngine(self.cfg)
        
        # Initialize data fetcher
        self.data_fetcher = DataFetcher(self.cfg)
        await self.data_fetcher.start()
        
        # Initialize Telegram bot
        self.telegram_bot = TelegramBot(self.cfg, self.decision_engine)
        await self.telegram_bot.start()
        
        log.info("All components initialized successfully!")

    async def cleanup(self):
        """Cleanup resources."""
        log.info("Cleaning up resources...")
        
        if self.telegram_bot:
            await self.telegram_bot.stop()
            
        if self.data_fetcher:
            await self.data_fetcher.stop()
            
        if hasattr(self.decision_engine, 'session') and self.decision_engine.session:
            await self.decision_engine.session.close()

        log.info("Cleanup completed.")

    async def process_tokens(self):
        """Fetch, filter, and process tokens."""
        try:
            # Fetch new tokens
            fetched_data = await self.data_fetcher.fetch_new_tokens()
            
            if not fetched_data:
                log.info("No new tokens to process")
                return
                
            log.info(f"Processing {len(fetched_data)} fetched tokens")
            
            processed_count = 0
            for item in fetched_data:
                try:
                    # Apply filters
                    filtered_token = self.filter_engine.apply_filters(item.token)
                    
                    # Make decision
                    decision = await self.decision_engine.decide(
                        filtered_token, 
                        item.source, 
                        item.raw_data
                    )
                    
                    # Send alert if decision is ENTER or WATCH
                    if decision.action in ["ENTER", "WATCH"]:
                        await self.telegram_bot.send_alert(
                            filtered_token, 
                            decision, 
                            item.source, 
                            item.raw_data
                        )
                    
                    # Update stats
                    self.stats['tokens_processed'] += 1
                    if decision.action in ["ENTER", "WATCH"]:
                        self.stats['alerts_sent'] += 1
                        
                    processed_count += 1
                    
                    # Small delay to prevent overwhelming
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    log.error(f"Error processing token {getattr(item.token, 'symbol', 'unknown')}: {e}")
                    continue
            
            self.stats['last_fetch_time'] = datetime.now()
            log.info(f"Processed {processed_count}/{len(fetched_data)} tokens successfully")
            
        except Exception as e:
            log.error(f"Error in process_tokens: {e}")

    async def run(self):
        """Main run loop."""
        self.running = True
        log.info("Starting PONYIN bot main loop...")
        
        while self.running:
            try:
                await self.process_tokens()
                
                # Wait before next fetch
                log.info(f"Waiting {self.cfg.FETCH_INTERVAL_SECONDS} seconds before next fetch...")
                await asyncio.sleep(self.cfg.FETCH_INTERVAL_SECONDS)
                
            except Exception as e:
                log.error(f"Error in main loop: {e}")
                await asyncio.sleep(10)  # Wait before continuing

    def stop(self):
        """Stop the bot gracefully."""
        log.info("Stopping PONYIN bot...")
        self.running = False

async def main():
    """Main entry point."""
    bot = PONYINBot()
    
    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        log.info(f"Received signal {signum}, stopping bot...")
        bot.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await bot.initialize()
        await bot.run()
    except KeyboardInterrupt:
        log.info("Keyboard interrupt received")
    finally:
        await bot.cleanup()
        log.info("PONYIN bot stopped")

if __name__ == "__main__":
    asyncio.run(main())

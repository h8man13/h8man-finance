#!/usr/bin/env python3
"""
Sidecar cron job for portfolio snapshot management.

This script runs as a separate process to handle daily snapshot maintenance.
It calls the portfolio_core admin endpoints to run snapshots for all users.

Usage:
    python snapshot_cron.py [--host HOST] [--port PORT] [--cleanup-days DAYS]

Environment variables:
    PORTFOLIO_CORE_HOST: Host for portfolio_core service (default: localhost)
    PORTFOLIO_CORE_PORT: Port for portfolio_core service (default: 8000)
    CLEANUP_DAYS: Days to keep old snapshots (default: 90)
    LOG_LEVEL: Logging level (default: INFO)
"""
import asyncio
import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional
import httpx

# Setup logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("snapshot_cron")


class SnapshotCronJob:
    """Handles portfolio snapshot cron operations."""

    def __init__(self, host: str = "localhost", port: int = 8000, cleanup_days: int = 90):
        self.base_url = f"http://{host}:{port}"
        self.cleanup_days = cleanup_days
        self.timeout = 300  # 5 minutes timeout for snapshot operations

    async def run_snapshots(self) -> bool:
        """Run daily snapshots for all users."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout)) as client:
                logger.info("Starting daily snapshot run for all users")

                response = await client.post(f"{self.base_url}/admin/snapshots/run")

                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        results = data.get("data", {})
                        processed_users = results.get("processed_users", 0)
                        logger.info(f"Successfully processed snapshots for {processed_users} users")

                        # Log any individual failures
                        for result in results.get("results", []):
                            if not result.get("success"):
                                logger.error(f"Snapshot failed for user {result.get('user_id')}: {result.get('error')}")

                        return True
                    else:
                        error = data.get("error", {})
                        logger.error(f"Snapshot run failed: {error.get('message', 'Unknown error')}")
                        return False
                else:
                    logger.error(f"HTTP {response.status_code}: {response.text}")
                    return False

        except httpx.TimeoutException:
            logger.error("Timeout running snapshots")
            return False
        except httpx.ConnectError:
            logger.error("Cannot connect to portfolio_core service")
            return False
        except Exception as e:
            logger.error(f"Unexpected error running snapshots: {e}")
            return False

    async def cleanup_old_snapshots(self) -> bool:
        """Clean up old snapshots."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60)) as client:
                logger.info(f"Cleaning up snapshots older than {self.cleanup_days} days")

                response = await client.delete(
                    f"{self.base_url}/admin/snapshots/cleanup",
                    params={"days_to_keep": self.cleanup_days}
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        deleted_count = data.get("data", {}).get("deleted_snapshots", 0)
                        logger.info(f"Cleaned up {deleted_count} old snapshots")
                        return True
                    else:
                        error = data.get("error", {})
                        logger.error(f"Cleanup failed: {error.get('message', 'Unknown error')}")
                        return False
                else:
                    logger.error(f"HTTP {response.status_code}: {response.text}")
                    return False

        except Exception as e:
            logger.error(f"Unexpected error during cleanup: {e}")
            return False

    async def health_check(self) -> bool:
        """Check if portfolio_core service is healthy."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10)) as client:
                response = await client.get(f"{self.base_url}/admin/health")

                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        health_data = data.get("data", {})
                        logger.info(f"Service health check passed: {health_data}")
                        return True
                    else:
                        logger.warning("Service health check failed")
                        return False
                else:
                    logger.warning(f"Health check HTTP {response.status_code}")
                    return False

        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False

    async def get_snapshot_status(self) -> Optional[dict]:
        """Get current snapshot status."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
                response = await client.get(f"{self.base_url}/admin/snapshots/status")

                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        return data.get("data", {})

        except Exception as e:
            logger.warning(f"Failed to get snapshot status: {e}")

        return None

    async def run_maintenance(self) -> bool:
        """Run full maintenance cycle: health check, snapshots, cleanup."""
        logger.info(f"Starting portfolio snapshot maintenance at {datetime.now(timezone.utc).isoformat()}")

        # Health check first
        if not await self.health_check():
            logger.error("Health check failed, skipping maintenance")
            return False

        # Get pre-maintenance status
        pre_status = await self.get_snapshot_status()
        if pre_status:
            logger.info(f"Pre-maintenance status: {pre_status.get('total_users', 0)} users")

        success = True

        # Run snapshots
        if not await self.run_snapshots():
            success = False
            logger.error("Snapshot run failed")

        # Run cleanup (even if snapshots failed)
        if not await self.cleanup_old_snapshots():
            success = False
            logger.error("Cleanup failed")

        # Get post-maintenance status
        post_status = await self.get_snapshot_status()
        if post_status:
            logger.info(f"Post-maintenance status: {post_status.get('total_users', 0)} users")

        if success:
            logger.info("Maintenance cycle completed successfully")
        else:
            logger.error("Maintenance cycle completed with errors")

        return success


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Portfolio snapshot cron job")
    parser.add_argument(
        "--host",
        default=os.getenv("PORTFOLIO_CORE_HOST", "localhost"),
        help="Portfolio core service host"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORTFOLIO_CORE_PORT", "8000")),
        help="Portfolio core service port"
    )
    parser.add_argument(
        "--cleanup-days",
        type=int,
        default=int(os.getenv("CLEANUP_DAYS", "90")),
        help="Days to keep old snapshots"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only perform health check and status, no modifications"
    )

    args = parser.parse_args()

    cron_job = SnapshotCronJob(
        host=args.host,
        port=args.port,
        cleanup_days=args.cleanup_days
    )

    if args.dry_run:
        logger.info("Dry run mode: health check and status only")
        healthy = await cron_job.health_check()
        status = await cron_job.get_snapshot_status()

        if healthy:
            logger.info("Service is healthy")
        else:
            logger.error("Service is not healthy")
            sys.exit(1)

        if status:
            logger.info(f"Current status: {status}")
        else:
            logger.warning("Could not retrieve status")

        sys.exit(0)

    # Run full maintenance
    success = await cron_job.run_maintenance()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
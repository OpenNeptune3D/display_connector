"""Thread pool shared by DisplayController for blocking work."""

import asyncio

from concurrent.futures import ThreadPoolExecutor

from src.controller.common import logger


class ResourceManager:
    
    def __init__(self):
        self._thread_pool = None
        self._shutdown = False
        self._lock = asyncio.Lock()
    
    def get_thread_pool(self):
        """Get thread pool, creating it if necessary"""
        if self._thread_pool is None and not self._shutdown:
            logger.info("Creating new thread pool")
            self._thread_pool = ThreadPoolExecutor(max_workers=2)
        return self._thread_pool
    
    async def cleanup(self):
        if self._shutdown or not self._thread_pool:
            return
        
        self._shutdown = True
        tp = self._thread_pool
        self._thread_pool = None 
        
        try:
            tp.shutdown(wait=False, cancel_futures=True)
            logger.info("Thread pool shutdown initiated (non-blocking)")
        except Exception as e:
            logger.warning(f"Exception during thread pool shutdown: {e}")
    
    def allow_new_pool(self):
        """Allow creating a new thread pool after shutdown"""
        logger.info("Allowing new thread pool creation")
        self._shutdown = False

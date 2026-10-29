"""Thumbnail lookup, download and rendering for DisplayController."""

import io
import asyncio
import aiohttp

from PIL import Image

from src.lib_col_pic import parse_thumbnail
from src.mapping import (
    PAGE_PRINTING_KAMP,
)
from src.controller.common import (
    logger,
)


class ThumbnailsMixin:
    """Thumbnail lookup, download and rendering."""

    async def load_thumbnail_for_page(self, filename, page_number, metadata=None):
        logger.info(f"Loading thumbnail for {filename}")
        
        # Store the request details for potential retry
        self._last_thumbnail_request = {
            'filename': filename,
            'page_number': page_number,
            'metadata': metadata
        }
        self._thumbnail_displayed = False
        
        # Check if we're still on the correct page before starting
        current_page = await self._get_current_page()  
        current_page_id = self._page_id(current_page) if current_page else None
        
        if current_page_id != page_number:
            logger.info(f"Page changed before thumbnail load started (expected {page_number}, got {current_page_id})")
            return
        
        # Don't try to load thumbnail if we're in bed leveling
        if current_page == PAGE_PRINTING_KAMP:
            logger.info("Deferring thumbnail load during bed leveling")
            return

        if metadata is None:
            metadata = await self.load_metadata(filename)
        
        best_thumbnail = self.find_best_thumbnail(metadata)
        if not best_thumbnail:
            logger.warning(f"No suitable thumbnail found for {filename}")
            current_page = await self._get_current_page()  
            if current_page and self._page_id(current_page) == page_number:
                await self.display.hide_thumbnail()
            return

        path = self.construct_thumbnail_path(filename, best_thumbnail["relative_path"])
        
        async with self._thumbnail_retry_lock:
            try:
                image = await self.fetch_and_parse_thumbnail(path)
                if image is None:
                    await self.display.hide_thumbnail()
                    return
                
                # Double-check we're still on the correct page before displaying
                current_page = await self._get_current_page()  
                current_page_id = self._page_id(current_page) if current_page else None
                
                if current_page_id != page_number:
                    logger.info(f"Page changed during thumbnail load (expected {page_number}, got {current_page_id}), skipping display")
                    return
                
                logger.info("Displaying the thumbnail")
                await self.display.display_thumbnail(page_number, image)
                logger.info("Thumbnail displayed successfully")
                self._thumbnail_displayed = True
            except asyncio.CancelledError:
                logger.info("Thumbnail loading cancelled")
                # display_thumbnail holds blocked_by="thumbnail_X" with auto_unblock=False.
                # If cancelled mid-loop that block is never released, causing all subsequent
                # write() calls (including navigate_to) to silently queue in blocked_buffer
                # instead of reaching the display.  Release it here before re-raising.
                try:
                    await self.display.unblock(f"thumbnail_{page_number}")
                    # Only hide if the thumbnail wasn't fully written — if display_thumbnail
                    # completed successfully before the cancel arrived, leave it visible.
                    if not self._thumbnail_displayed:
                        await self.display.hide_thumbnail()
                except Exception as cleanup_err:
                    logger.debug(f"Best-effort thumbnail cleanup failed: {cleanup_err}")
                raise
            except Exception as e:
                logger.error(f"Error displaying thumbnail: {e}")

    async def retry_last_thumbnail(self):
        #Retry loading the last thumbnail if there was one
        if self._last_thumbnail_request:
            async with self._thumbnail_retry_lock:
                try:
                    await self.load_thumbnail_for_page(
                        self._last_thumbnail_request['filename'],
                        self._last_thumbnail_request['page_number'],
                        self._last_thumbnail_request['metadata']
                    )
                except Exception as e:
                    logger.error(f"Error retrying thumbnail: {e}")

    def find_best_thumbnail(self, metadata):
        best_thumbnail = None
        for thumbnail in metadata["thumbnails"]:
            if thumbnail["width"] == 160:
                return thumbnail
            if best_thumbnail is None or thumbnail["width"] > best_thumbnail["width"]:
                best_thumbnail = thumbnail
        return best_thumbnail

    def construct_thumbnail_path(self, filename, relative_path):
        path = "/".join(filename.split("/")[:-1])
        if path != "":
            path = path + "/"
        return path + relative_path

    async def fetch_and_parse_thumbnail(self, path):
        thumbnail = None
        try:
            # Construct URL first
            url = f"{self.config.safe_get('general', 'moonraker_url', 'http://localhost:7125')}/server/files/gcodes/{self.pathname2url(path)}"
            
            logger.info(f"Fetching thumbnail image from {url}")
            
            # PHASE 1: Fetch image with timeout (reuse session across calls)
            if self._http_session is None or self._http_session.closed:
                self._http_session = aiohttp.ClientSession()
            async with self._http_session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    raise aiohttp.ClientError(f"Failed to fetch thumbnail, status code: {resp.status}")
                img_data = await resp.read()
            
            thumbnail = Image.open(io.BytesIO(img_data))
            
            # Safely access config
            background = "29354a"  # default color
            try:
                if "thumbnails" in self.config:
                    background = self.config["thumbnails"].get("background_color", background)
            except Exception as e:
                logger.warning(f"Error accessing thumbnail config: {e}")
            
            logger.info("Starting thumbnail parsing")
            loop = asyncio.get_running_loop()

            # Get thread pool (will be created if needed)
            thread_pool = self.resources.get_thread_pool()
            if thread_pool is None:
                logger.error("Thread pool unavailable (shutdown state)")
                return None
            
            # PHASE 2: Parse image with timeout (10 seconds max)
            try:
                image = await asyncio.wait_for(
                    loop.run_in_executor(
                        thread_pool,
                        parse_thumbnail,
                        thumbnail,
                        160,
                        160,
                        background
                    ),
                    timeout=10.0  # Timeout added!
                )
            except asyncio.TimeoutError:
                logger.error(f"Thumbnail parsing timed out after 10 seconds for {path}")
                return None
            
            logger.info("Thumbnail parsing completed")
            return image
            
        except asyncio.TimeoutError:
            logger.error(f"Thumbnail fetch timed out for {path}")
            return None
        except Exception as e:
            logger.error(f"Error in thumbnail processing: {e}")
            return None
        finally:
            if thumbnail is not None:
                try:
                    thumbnail.close()
                except Exception:
                    logger.exception("Unexpected error fetch_and_parse_thumbnail")
                    pass

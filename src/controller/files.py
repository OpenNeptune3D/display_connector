"""G-code file browsing and print preparation for DisplayController."""

import asyncio

from urllib.parse import quote

from src.mapping import (
    build_format_filename,
    PAGE_CONFIRM_PRINT,
)


class FilesMixin:
    """G-code file browsing and print preparation."""

    def pathname2url(self, path):
        return quote(path.replace("\\", "/"))

    def _build_path(self, *components):
        path = ""
        for component in components:
            if component is None or component == "" or component == "/":
                continue
            path += f"/{component}"
        return path[1:]

    def sort_dir_contents(self, dir_contents):
        key = "modified"
        reverse = True
        if "files" in self.config:
            files_config = self.config["files"]
            if "sort_by" in files_config:
                key = files_config["sort_by"]
            if "sort_order" in files_config:
                reverse = files_config["sort_order"] == "desc"
        return sorted(dir_contents, key=lambda k: k[key], reverse=reverse)

    async def _load_files(self):
        data = await self._send_moonraker_request(
            "server.files.get_directory",
            {"path": "/".join(["gcodes", self.current_dir])},
        )
        dir_info = data["result"]
        
        dirs = []
        for item in dir_info["dirs"]:
            if not item["dirname"].startswith("."):
                dirs.append(
                    {
                        "type": "dir",
                        "path": self._build_path(self.current_dir, item["dirname"]),
                        "size": item["size"],
                        "modified": item["modified"],
                        "name": item["dirname"],
                    }
                )
        files = []
        for item in dir_info["files"]:
            if item["filename"].endswith(".gcode"):
                files.append(
                    {
                        "type": "file",
                        "path": self._build_path(self.current_dir, item["filename"]),
                        "size": item["size"],
                        "modified": item["modified"],
                        "name": build_format_filename()(item["filename"]),
                    }
                )
        sort_folders_first = True
        if "files" in self.config:
            sort_folders_first = self.config["files"].getboolean(
                "sort_folders_first", fallback=True
            )
        
        # Update shared state under lock
        async with self._files_lock:
            if sort_folders_first:
                self.dir_contents = self.sort_dir_contents(dirs) + self.sort_dir_contents(files)
            else:
                self.dir_contents = self.sort_dir_contents(dirs + files)
            current_dir = self.current_dir
            dir_contents = self.dir_contents
            files_page = self.files_page
        
        await self.display.show_files_page(current_dir, dir_contents, files_page)

    async def set_data_prepare_screen(self, filename):
        """Set prepare screen data without holding lock during I/O."""
        
        # PHASE 1: Cancel existing task and store filename (under lock - DATA ONLY)
        task_to_cancel = None
        async with self._filename_lock:
            # Get reference to task to cancel
            if self._thumbnail_task and not self._thumbnail_task.done():
                task_to_cancel = self._thumbnail_task
                self._thumbnail_task = None
            
            # Store filename
            current_filename = filename
        
        # PHASE 2: Cancel task if needed (outside lock - ASYNC OPERATION)
        if task_to_cancel:
            task_to_cancel.cancel()
            try:
                await task_to_cancel
            except asyncio.CancelledError:
                pass
        
        # PHASE 3: Load metadata and update display (outside lock - NETWORK + DISPLAY I/O)
        metadata = await self.load_metadata(current_filename)
        await self.display.set_data_prepare_screen(current_filename, metadata)
        
        # PHASE 4: Create new thumbnail task (under lock - DATA ONLY)
        async with self._filename_lock:
            self._thumbnail_task = self._loop.create_task(
                self.load_thumbnail_for_page(
                    current_filename, self._page_id(PAGE_CONFIRM_PRINT), metadata
                )
            )

    async def load_metadata(self, filename):
        metadata = await self._send_moonraker_request(
            "server.files.metadata", {"filename": filename}
        )
        return metadata["result"]

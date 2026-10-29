"""Moonraker socket connection and JSON-RPC requests for DisplayController."""

import json
import pathlib
import os
import os.path
import time
import asyncio

from src.controller.common import (
    logger,
    SOCKET_LIMIT,
)


class MoonrakerMixin:
    """Moonraker socket connection and JSON-RPC requests."""

    async def _cleanup_stale_requests(self):
        #Periodically clean up stale requests
        while True:
            try:
                current_time = time.time()
                async with self.pending_reqs_lock:
                    # Store request timestamps in a separate dict
                    stale_requests = [
                        req_id for req_id, (fut, timestamp) in self.pending_reqs.items()
                        if not fut.done() and (current_time - timestamp) > self.REQUEST_TIMEOUT
                    ]
                    for req_id in stale_requests:
                        fut, _ = self.pending_reqs.pop(req_id)
                        fut.set_exception(asyncio.TimeoutError(f"Request {req_id} timed out"))
                await asyncio.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
                await asyncio.sleep(60)

    async def _send_moonraker_request(self, method, params=None):
        if not self.connected or self.writer is None:
            raise ConnectionError("Not connected to Moonraker")
        
        if params is None:
            params = {}
        message = self._make_rpc_msg(method, **params)
        fut = self._loop.create_future()
        
        # Store request with timestamp
        async with self.pending_reqs_lock:
            self.pending_reqs[message["id"]] = (fut, time.time())

        try:
            data = json.dumps(message).encode() + b"\x03"
            self.writer.write(data)
            await self.writer.drain()
            return await asyncio.wait_for(fut, timeout=self.REQUEST_TIMEOUT)
        except asyncio.CancelledError:
            # External cancellation (shutdown, reconnect) - always propagate
            async with self.pending_reqs_lock:
                self.pending_reqs.pop(message["id"], None)
            raise
        except (asyncio.TimeoutError, ConnectionError):
            # Timeout or connection closed - let caller handle reconnect logic
            async with self.pending_reqs_lock:
                self.pending_reqs.pop(message["id"], None)
            raise
        except Exception:
            # Unexpected error - log but don't call close() here
            # Let the error propagate; caller/listen() handles reconnection
            logger.exception("Unexpected error _send_moonraker_request")
            async with self.pending_reqs_lock:
                self.pending_reqs.pop(message["id"], None)
            raise

    def _find_ips(self, network):
        ips = []
        for key in network:
            if "ip_addresses" in network[key]:
                for ip in network[key]["ip_addresses"]:
                    if ip["family"] == "ipv4":
                        ips.append(ip["address"])
        return ips

    async def connect_moonraker(self) -> None:
        sockfile = os.path.expanduser("~/printer_data/comms/moonraker.sock")
        sockpath = pathlib.Path(sockfile).expanduser().resolve()
        logger.info(f"Connecting to Moonraker at {sockpath}")
        while True:
            try:
                reader, writer = await asyncio.open_unix_connection(
                    sockpath, limit=SOCKET_LIMIT
                )
                self.writer = writer
                self._process_stream_task = self._loop.create_task(self._process_stream(reader))
                self.connected = True
                logger.info("Connected to Moonraker")

                try:
                    software_version_response = await self._send_moonraker_request(
                        "printer.info"
                    )
                    software_version = software_version_response["result"][
                        "software_version"
                    ]
                    software_version = "-".join(
                        software_version.split("-")[:2]
                    )  # clean up version string
                    # Process the software_version...
                    logger.info(f"Software Version: {software_version}")
                    await self.display.update_klipper_version_ui(software_version)
                    break  # Exit the connection retry loop

                except KeyError:
                    logger.error(
                        "KeyError encountered in software_version_response. Attempting to reconnect."
                    )
                    await self.close()
                    await asyncio.sleep(5)  # Wait before reconnecting
                    continue  # Retry the connection loop

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error connecting to Moonraker: {e}")
                await self.close()
                await asyncio.sleep(5)  # Wait before reconnecting
                continue

        # Now identify with Moonraker - wrapped in try/except
        try:
            ret = await self._send_moonraker_request(
                "server.connection.identify",
                {
                    "client_name": "OpenNept4une Display Connector",
                    "version": "0.0.1",
                    "type": "other",
                    "url": "https://github.com/halfbearman/opennept4une",
                },
            )
            
            # Check for error response
            if "error" in ret:
                error_code = ret["error"].get("code")
                error_msg = ret["error"].get("message", "Unknown error")
                
                # Error 400 "already identified" is acceptable - just log and continue
                if error_code == 400 and "already identified" in error_msg.lower():
                    logger.warning(f"Connection already identified: {error_msg}")
                    # Continue execution - don't return or raise
                else:
                    # Other errors are logged but don't crash - we're already connected
                    logger.error(f"Failed to identify with Moonraker: {error_msg}")
                    # Don't raise - we can still function without identification
            elif "result" in ret:
                logger.debug(
                    f"Client Identified With Moonraker: {ret['result']['connection_id']}"
                )
        except Exception as e:
            logger.error(f"Exception during Moonraker identification: {e}")
            # Don't crash - we're already connected and can function

        # Get system info - also wrapped for safety
        if not await self._refresh_ips():
            # Network may not be up yet on first boot - keep retrying in the
            # background so the IP appears without needing a service restart.
            if self._ips_retry_task is None or self._ips_retry_task.done():
                self._ips_retry_task = self._loop.create_task(self._retry_refresh_ips())

    async def _refresh_ips(self) -> bool:
        """Fetch the machine's IP addresses from Moonraker. Returns True if any were found."""
        try:
            system_response = await self._send_moonraker_request("machine.system_info")
            if "result" in system_response:
                system = system_response["result"]["system_info"]
                ips = self._find_ips(system["network"])
                if ips:
                    self.display.ips = ", ".join(ips)
                    return True
            else:
                logger.warning("Could not retrieve system info")
        except Exception as e:
            logger.error(f"Error getting system info: {e}")
            # Continue anyway - not critical
        return False

    async def _retry_refresh_ips(self) -> None:
        for _ in range(12):  # retry for up to a minute
            await asyncio.sleep(5)
            if await self._refresh_ips():
                return
        logger.warning("Gave up waiting for network IP address after retries")

    def _make_rpc_msg(self, method: str, **kwargs):
        msg = {"jsonrpc": "2.0", "method": method}
        uid = id(msg)
        msg["id"] = uid
        self.pending_req = msg
        if kwargs:
            msg["params"] = kwargs
        return msg

    async def _process_stream(self, reader: asyncio.StreamReader) -> None:
        errors_remaining: int = 10
        while not reader.at_eof():
            if self.klipper_restart_event.is_set():
                self.klipper_restart_event.clear()
                await self._attempt_reconnect()
                return  # Exit - new connection started
            try:
                data = await reader.readuntil(b"\x03")
                decoded = data[:-1].decode(encoding="utf-8")
                item = json.loads(decoded)
            except (ConnectionError, asyncio.IncompleteReadError):
                await self._attempt_reconnect()
                return  # Exit - new connection started
            except asyncio.CancelledError:
                raise
            except Exception:
                errors_remaining -= 1
                if not errors_remaining or not self.connected:
                    await self._attempt_reconnect()
                    return  # Exit - new connection started
                continue
            errors_remaining = 10
            if "id" in item:
                async with self.pending_reqs_lock:
                    request_data = self.pending_reqs.pop(item["id"], None)
                    if request_data is not None:
                        fut, _ = request_data
                        if not fut.done():
                            fut.set_result(item)
            elif item.get("method") == "notify_status_update":
                await self.handle_status_update(item["params"][0])
            elif item.get("method") == "notify_gcode_response":
                await self.handle_gcode_response(item["params"][0])
        logger.info("Unix Socket Disconnection from _process_stream()")
        await self.close()

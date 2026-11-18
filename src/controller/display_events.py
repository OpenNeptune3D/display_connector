"""Events coming from the touch screen (touches, inputs, page changes) for DisplayController."""

import asyncio

from src.tjc import EventType
from src.response_actions import (
    response_actions,
    input_actions,
    custom_touch_actions,
    fallback_tab_touch_actions,
    text_input_actions,
)
from src.mapping import (
    PAGE_MAIN,
    PAGE_PRINTING,
    PAGE_PRINTING_COMPLETE,
)
from src.controller.common import (
    logger,
)


# Seconds to wait for a component event from the same tap before using a fallback tab
FALLBACK_TAB_DELAY = 0.15
# Key-press beep for fallback tabs, since the firmware doesn't beep for them
FALLBACK_TAB_BEEP_MS = 50


class DisplayEventsMixin:
    """Events coming from the touch screen (touches, inputs, page changes)."""

    def handle_response(self, page, component):
        extra = self.display.extra_response_actions
        if component in extra.get(page, {}):
            self.execute_action(extra[page][component])
            return
        if page in response_actions:
            if component in response_actions[page]:
                self.execute_action(response_actions[page][component])
                return
        if component == 0:
            # Don't blindly go back if the current logical page owns its navigation
            # through custom_touch_actions (e.g. shutdown_dialog). Blank HMI pages
            # like none_9 fire component-0 TOUCH events on any touch; letting them
            # trigger _go_back() immediately undoes the navigation we just performed.
            # Pages in custom_touch_actions have explicit back actions defined there.
            current_logical = self.history[-1] if self.history else None
            if current_logical not in custom_touch_actions:
                self._loop.create_task(self._go_back())
            return
        logger.info(f"Unhandled Response: {page} {component}")

    def handle_input(self, page, component, value):
        if page in input_actions:
            if component in input_actions[page]:
                self.execute_action(
                    input_actions[page][component].replace("$", str(value))
                )
                return
        logger.info(f"Unhandled Input: {page} {component} {value}")

    def handle_text_input(self, page, component, text):
        action = text_input_actions.get(page)
        # Don't log the text itself, it is usually a password
        logger.debug(f"Text Input: {page} {component}")
        if action == "wifi_password":
            self.handle_wifi_password(text)
            return
        logger.info(f"Unhandled Text Input: {page} {component}")

    async def handle_custom_touch(self, x, y):
        current_page = await self._get_current_page()  
        if current_page in custom_touch_actions:
            actions = custom_touch_actions[current_page]
            for key in actions:
                min_x, min_y, max_x, max_y = key
                if min_x < x and x < max_x and min_y < y and y < max_y:
                    self.execute_action(actions[key])
                    return
        for (min_x, min_y, max_x, max_y), target in fallback_tab_touch_actions.get(current_page, {}).items():
            if min_x < x < max_x and min_y < y < max_y:
                # Give a component event from the same tap (older firmware) time to
                # navigate first; each event runs in its own task, so this doesn't block it.
                await asyncio.sleep(FALLBACK_TAB_DELAY)
                if await self._get_current_page() != current_page:
                    return
                await self.display.write(f"beep {FALLBACK_TAB_BEEP_MS}")
                await self._navigate_to_page(target)
                return

    async def display_event_handler(self, type, data):
        if type == EventType.TOUCH:
            self.handle_response(data.page_id, data.component_id)
        elif type == EventType.TOUCH_COORDINATE:
            await self.handle_wifi_keyboard_touch(data.x, data.y, pressed=data.touch_event == 1)
            if data.touch_event == 0:
                await self.handle_custom_touch(data.x, data.y)
        elif type == EventType.SLIDER_INPUT:
            self.handle_input(data.page_id, data.component_id, data.value)
        elif type == EventType.NUMERIC_INPUT:
            self.handle_input(data.page_id, data.component_id, data.value)
        elif type == EventType.STRING_INPUT:
            self.handle_text_input(data.page_id, data.component_id, data.string)
        elif type == EventType.RECONNECTED:
            logger.info("Reconnected to Display")
            # Re-enable touch coordinate reporting; the panel forgets this
            # setting across a serial reconnect, which breaks custom touch
            # areas (e.g. the shutdown dialogue hotspot on main) even though
            # normal page-button touches keep working.
            await self.display.write("sendxy=1")
            # Clear history so we don't fight with a stale page stack
            async with self._history_lock:
                self.history = []
            # Choose a page based on current printer state to avoid "variable name invalid"
            state = getattr(self, "current_state", None)
            target = PAGE_MAIN
            if state in ("printing", "paused") and not self._bed_leveling_complete:
                target = PAGE_PRINTING
            elif state == "complete":
                target = PAGE_PRINTING_COMPLETE
            await self._navigate_to_page(target, clear_history=True)
        else:
            logger.info(f"Unhandled Event: {type} {data}")

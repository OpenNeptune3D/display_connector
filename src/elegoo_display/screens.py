"""Leveling, thumbnail, status and shutdown screens for ElegooDisplayCommunicator."""

from src.mapping import (
    PAGE_SETTINGS_ABOUT,
    PAGE_LEVELING_Z_OFFSET_ADJUST,
    PAGE_PRINTING,
)
from src.colors import (
    TEXT_ERROR,
    TEXT_SUCCESS,
)


class ElegooScreensMixin:
    """Leveling, thumbnail, status and shutdown screens."""

    async def draw_initial_screw_leveling(self):
        await self.write('b[1].txt="Screws Tilt Adjust"')
        await self.write('b[2].txt="Please Wait..."')
        await self.write('b[3].txt="Heating..."')
        await self.write("vis b[4],0")
        await self.write("vis b[5],0")
        await self.write("vis b[6],0")
        await self.write("vis b[7],0")
        await self.write("vis b[8],0")
        await self.write("fill 0,110,320,290,10665")

    async def draw_completed_screw_leveling(self, screw_levels):
        await self.write('b[1].txt="Screws Tilt Adjust"')
        await self.write('b[2].txt="Adjust the screws as indicated"')
        await self.write(
            'b[3].txt="01:20 means 1  turn and 20 mins\\rCW=clockwise\\rCCW=counter-clockwise"'
        )
        await self.write("vis b[4],0")
        await self.write("vis b[5],0")
        await self.write("vis b[6],0")
        await self.write("vis b[7],0")
        await self.write("vis b[8],1")
        await self.write("fill 0,110,320,290,10665")

        await self.write('xstr 12,320,100,20,1,65535,10665,1,1,1,"front left"')
        await self.draw_screw_level_info_at("12,340,100,20", screw_levels["front left"])

        await self.write('xstr 170,320,100,20,1,65535,10665,1,1,1,"front right"')
        await self.draw_screw_level_info_at("170,340,100,20", screw_levels["front right"])

        await self.write('xstr 12,120,100,20,1,65535,10665,1,1,1,"rear left"')
        await self.draw_screw_level_info_at("12,140,100,20", screw_levels["rear left"])

        await self.write('xstr 170,120,100,20,1,65535,10665,1,1,1,"rear right"')
        await self.draw_screw_level_info_at("170,140,100,20", screw_levels["rear right"])

        if "center right" in screw_levels:
            await self.write('xstr 172,220,100,20,1,65535,10665,1,1,1,"center right"')
            await self.draw_screw_level_info_at("172,240,100,20", screw_levels["center right"])
        if "center left" in screw_levels:
            await self.write('xstr 0,220,100,20,1,65535,10665,1,1,1,"center left"')
            await self.draw_screw_level_info_at("0,240,100,20", screw_levels["center left"])

        await self.write('xstr 106,214,60,60,1,65535,15319,1,1,1,"Retry"')

    async def draw_screw_level_info_at(self, position, level):
        if level == "base":
            await self.write(f'xstr {position},0,65535,10665,1,1,1,"base"')
        else:
            color = TEXT_SUCCESS if int(level[-2:]) < 5 else TEXT_ERROR
            await self.write(f'xstr {position},0,{color},10665,1,1,1,"{level}"')

    async def update_screw_level_description(self, text):
        await self.write(f'b[3].txt="{text}"')

    async def draw_initial_zprobe_leveling(self, z_probe_step, z_probe_distance):
        await self.write(f'{self.mapper.map_page(PAGE_LEVELING_Z_OFFSET_ADJUST)}.b[19].txt="Z-Probe"')
        await self.write("fill 0,250,320,320,10665")
        await self.write("fill 0,50,320,80,10665")
        await self.update_zprobe_leveling_ui(z_probe_step, z_probe_distance)

    async def update_zprobe_leveling_ui(self, z_probe_step, z_probe_distance):
        await self.write(f'{self.mapper.map_page(PAGE_LEVELING_Z_OFFSET_ADJUST)}.b[19].txt="Z-Probe"')
        await self.write(
            f'{self.mapper.map_page(PAGE_LEVELING_Z_OFFSET_ADJUST)}.b[11].pic={7 + ["0.01", "0.1", "1"].index(z_probe_step)}'
        )
        await self.write(f'{self.mapper.map_page(PAGE_LEVELING_Z_OFFSET_ADJUST)}.b[20].txt="{z_probe_distance}"')

    async def draw_kamp_page(self, bed_leveling_counts):
        await self.write("fill 0,45,272,340,10665")
        await self.write('xstr 0,0,272,50,1,65535,10665,1,1,1,"Creating Bed Mesh"')
        max_size = 264  # display width - 4px padding
        x_probes = bed_leveling_counts[0]
        y_probes = bed_leveling_counts[1]
        spacing = 2
        self.bed_leveling_box_size = min(
            40, int(min(max_size / x_probes, max_size / y_probes) - spacing)
        )
        total_width = (x_probes * (self.bed_leveling_box_size + spacing)) - spacing
        total_height = (y_probes * (self.bed_leveling_box_size + spacing)) - spacing
        self.bed_leveling_x_offset = 4 + (max_size - total_width) / 2
        self.bed_leveling_y_offset = 45 + (max_size - total_height) / 2
        for x in range(0, x_probes):
            for y in range(0, y_probes):
                await self.draw_kamp_box(x, y, 17037)

    async def update_kamp_text(self, text):
        await self.write(f'xstr 0,310,320,30,1,65535,10665,1,1,1,"{text}"')

    async def draw_kamp_box_index(self, index, color, bed_leveling_counts):
        if bed_leveling_counts[0] == 0:
            return
        row = int(index / bed_leveling_counts[0])
        inverted_row = (bed_leveling_counts[1] - 1) - row
        col = index % bed_leveling_counts[0]
        if row % 2 == 1:
            col = bed_leveling_counts[0] - 1 - col
        await self.draw_kamp_box(col, inverted_row, color)

    async def draw_kamp_box(self, x, y, color):
        box_size = self.bed_leveling_box_size
        if box_size > 0:
            await self.write(
                f"fill {int(self.bed_leveling_x_offset+x*(box_size+2))},{47+y*(box_size+2)},{box_size},{box_size},{color}"
            )

    async def update_klipper_version_ui(self, software_version):
        await self.write(
            self.mapper.map_page(PAGE_SETTINGS_ABOUT)
            + '.b[10].txt="'
            + software_version
            + '"'
        )

    async def update_machine_size_ui(self, max_x, max_y, max_z):
        await self.write(
            f'{self.mapper.map_page(PAGE_SETTINGS_ABOUT)}.b[9].txt="{max_x}x{max_y}x{max_z}"'
        )

    async def display_thumbnail(self, page_number, thumbnail):
        await self.write("vis cp0,1")
        await self.write(str(page_number) + ".cp0.close()")

        parts = []
        start = 0
        end = 1024
        while start + 1024 < len(thumbnail):
            parts.append(thumbnail[start:end])
            start = start + 1024
            end = end + 1024

        parts.append(thumbnail[start : len(thumbnail)])
        for part in parts:
            await self.write(
                str(page_number) + '.cp0.write("' + str(part) + '")',
                blocked_key=f"thumbnail_{page_number}",
                auto_unblock=False,
            )
        self.logger.debug("Thumbnail sent to display")
        await self.unblock(f"thumbnail_{page_number}")

    async def hide_thumbnail(self):
        await self.write("vis cp0,0")

    async def update_time_remaining(self, time_remaining):
        await self.write(
            f'{self.mapper.map_page(PAGE_PRINTING)}.b[37].txt="{time_remaining}"'
        )

    async def show_bed_mesh_final(self):
        await self.write("vis nozzletemp,0")
        await self.write("vis bedtemp,0")
        await self.update_kamp_text("Bed Mesh completed")
        await self.write(
            'xstr 0,350,272,30,1,65535,10665,1,1,1,"Tap SAVE to update printer config and restart"'
        )
        await self.write('xstr 40,400,200,50,1,65535,15319,1,1,1,"SAVE"')

    async def show_initial_shutdown_screen(self):
        await self.write("cls 44637")
        await self.write(
            'xstr 8,220,256,20,1,54151,44637,1,1,1,"Please wait while your printer"'
        )
        await self.write('xstr 24,240,224,20,1,54151,44637,1,1,1,"shuts down."')

    async def show_shutdown_screens(self):
        await self.show_initial_shutdown_screen()
        # Need to use this method here, because once we send the delay, the display won't respond anymore
        self._write_without_response("delay=8000")
        self._write_without_response("cls BLACK")
        self._write_without_response(
            'xstr 24,220,224,20,1,54150,0,1,1,1,"It\'s now safe to turn off"'
        )
        self._write_without_response('xstr 24,240,224,20,1,54150,0,1,1,1,"your printer."')

    def _write_without_response(self, command):
        # nextion 3.x replaced write_command() with _write_command_raw(), which takes bytes.
        # Both write straight to the port and append the FF FF FF terminator themselves.
        if hasattr(self.display, "_write_command_raw"):
            self.display._write_command_raw(command.encode("utf-8"))
        else:
            self.display.write_command(command)

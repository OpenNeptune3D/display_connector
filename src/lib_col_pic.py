# Copyright (c) 2023 Molodos

# The ElegooNeptuneThumbnails plugin is released under the terms of the AGPLv3 or higher.

import numpy as np

def parse_thumbnail(img, width, height, default_background) -> str:
    img.thumbnail((width, height))
    img = img.convert("RGBA")
    pixels = np.array(img)
    img_size = pixels.shape[:2]

    # Ensure the background color is in the correct format
    r_bkg, g_bkg, b_bkg = ImageColor.getcolor(
        default_background if default_background.startswith("#") else "#" + default_background,
        "RGB"
    )

    # Alpha blending optimization
    alpha = pixels[:, :, 3] / 255.0
    non_opaque_mask = alpha != 1.0
    pixels[non_opaque_mask, 0] = (pixels[non_opaque_mask, 0] * alpha[non_opaque_mask] + (1 - alpha[non_opaque_mask]) * r_bkg).astype(np.uint8)
    pixels[non_opaque_mask, 1] = (pixels[non_opaque_mask, 1] * alpha[non_opaque_mask] + (1 - alpha[non_opaque_mask]) * g_bkg).astype(np.uint8)
    pixels[non_opaque_mask, 2] = (pixels[non_opaque_mask, 2] * alpha[non_opaque_mask] + (1 - alpha[non_opaque_mask]) * b_bkg).astype(np.uint8)

    # Convert to 16-bit color
    r = (pixels[:, :, 0].astype(np.uint16) >> 3) << 11
    g = (pixels[:, :, 1].astype(np.uint16) >> 2) << 5
    b = (pixels[:, :, 2].astype(np.uint16) >> 3)
    color16 = (r | g | b).flatten()

    output_data = bytearray(img_size[0] * img_size[1] * 10)
    ColPic_EncodeStr(color16, img_size[1], img_size[0], output_data, len(output_data), 1024)

    result = ''.join(chr(byte) for byte in output_data if byte)
    return result

# Remaining functions unchanged but can be similarly optimized.

def ColPic_EncodeStr(fromcolor16, picw, pich, outputdata: bytearray, outputmaxtsize, colorsmax):
    qty = ColPicEncode(fromcolor16, picw, pich, outputdata, outputmaxtsize, colorsmax)
    if qty == 0:
        return 0

    # Ensure the data length is a multiple of 3 for encoding
    padding = (3 - qty % 3) % 3
    qty += padding
    outputdata.extend([0] * padding)

    hexindex = qty
    strindex = qty * 4 // 3
    TempBytes = bytearray(4)

    while hexindex > 0:
        hexindex -= 3
        strindex -= 4
        TempBytes[0] = outputdata[hexindex] >> 2
        TempBytes[1] = (outputdata[hexindex] & 0x03) << 4 | outputdata[hexindex + 1] >> 4
        TempBytes[2] = (outputdata[hexindex + 1] & 0x0F) << 2 | outputdata[hexindex + 2] >> 6
        TempBytes[3] = outputdata[hexindex + 2] & 0x3F

        for k in range(4):
            TempBytes[k] += 48
            if TempBytes[k] == ord('\\'):
                TempBytes[k] = 126

        outputdata[int(strindex):int(strindex) + 4] = TempBytes

    outputdata[int(qty * 4 // 3)] = 0
    return qty * 4 // 3

def ColPicEncode(fromcolor16, picw, pich, outputdata: bytearray, outputmaxtsize, colorsmax):
    Head0 = ColPicHead3()

    dotsqty = picw * pich
    colorsmax = min(colorsmax, 1024)

    # Use NumPy to count unique colors and their frequencies
    unique_colors, counts = np.unique(fromcolor16, return_counts=True)
    Listu16 = np.array([U16HEAD() for _ in range(len(unique_colors))])

    for i, (color, qty) in enumerate(zip(unique_colors, counts)):
        Listu16[i].colo16 = color
        Listu16[i].qty = qty
        Listu16[i].A0 = (color >> 11) & 31
        Listu16[i].A1 = (color >> 5) & 63
        Listu16[i].A2 = color & 31

    # Sort the color list by frequency (descending)
    Listu16 = sorted(Listu16, key=lambda x: x.qty, reverse=True)

    # Reduce color list to `colorsmax` by merging similar colors
    while len(Listu16) > colorsmax:
        l0 = Listu16.pop()
        cha = np.array([
            abs(l0.A0 - u16.A0) + abs(l0.A1 - u16.A1) + abs(l0.A2 - u16.A2)
            for u16 in Listu16
        ])
        fid = np.argmin(cha)
        replacement_color = Listu16[fid].colo16
        fromcolor16 = np.where(fromcolor16 == l0.colo16, replacement_color, fromcolor16)

    # Clear the output data
    outputdata[:] = bytearray(outputmaxtsize)

    # Set up header
    Head0.encodever = 3
    Head0.mark = 98419516
    Head0.ListDataSize = len(Listu16) * 2

    # Write header information
    outputdata[0] = 3
    outputdata[12:16] = [60, 195, 221, 5]
    outputdata[16:20] = Head0.ListDataSize.to_bytes(4, 'little')

    sizeofColPicHead3 = 32

    # Convert the Listu16 color data to bytes
    for i in range(len(Listu16)):
        color_bytes = np.array([Listu16[i].colo16], dtype=np.uint16).view(np.uint8)
        outputdata[sizeofColPicHead3 + i * 2: sizeofColPicHead3 + i * 2 + 2] = list(color_bytes)  # Convert to list of ints

    enqty = Byte8bitEncode(
        fromcolor16,
        sizeofColPicHead3,
        Head0.ListDataSize >> 1,
        dotsqty,
        outputdata,
        sizeofColPicHead3 + Head0.ListDataSize,
        outputmaxtsize - sizeofColPicHead3 - Head0.ListDataSize,
    )

    # Finalize header with encoding details
    Head0.ColorDataSize = enqty
    Head0.PicW = picw
    Head0.PicH = pich

    outputdata[4:8] = picw.to_bytes(4, 'little')
    outputdata[8:12] = pich.to_bytes(4, 'little')
    outputdata[20:24] = enqty.to_bytes(4, 'little')

    return sizeofColPicHead3 + Head0.ListDataSize + Head0.ColorDataSize

def ADList0(val, Listu16, ListQty, maxqty):
    if ListQty >= maxqty:
        return ListQty

    for i in range(ListQty):
        if Listu16[i].colo16 == val:
            Listu16[i].qty += 1
            return ListQty

    A0 = (val >> 11) & 31
    A1 = (val >> 5) & 63
    A2 = val & 31
    Listu16[ListQty].colo16 = val
    Listu16[ListQty].A0 = A0
    Listu16[ListQty].A1 = A1
    Listu16[ListQty].A2 = A2
    Listu16[ListQty].qty = 1
    return ListQty + 1

def Byte8bitEncode(
    fromcolor16,
    listu16Index,
    listqty,
    dotsqty,
    outputdata: bytearray,
    outputdataIndex,
    decMaxBytesize,
):
    listu16 = outputdata
    dots = 0
    srcindex = 0
    decindex = 0
    lastid = 0

    while dotsqty > 0:
        dots = min(255, next((i + 1 for i in range(dotsqty - 1) if fromcolor16[srcindex + i] != fromcolor16[srcindex + i + 1]), dotsqty))

        temp = next((i for i in range(listqty) if listu16[i * 2 + 1 + listu16Index] << 8 | listu16[i * 2 + listu16Index] == fromcolor16[srcindex]), 0)
        tid = temp % 32
        sid = temp // 32

        if lastid != sid:
            if decindex >= decMaxBytesize:
                break
            outputdata[decindex + outputdataIndex] = 7 << 5 | sid
            decindex += 1
            lastid = sid

        if dots <= 6:
            if decindex >= decMaxBytesize:
                break
            outputdata[decindex + outputdataIndex] = dots << 5 | tid
            decindex += 1
        else:
            if decindex >= decMaxBytesize:
                break
            outputdata[decindex + outputdataIndex] = tid
            decindex += 1
            if decindex >= decMaxBytesize:
                break
            outputdata[decindex + outputdataIndex] = dots
            decindex += 1

        srcindex += dots
        dotsqty -= dots

    return decindex

class U16HEAD:
    def __init__(self):
        self.colo16 = 0
        self.A0 = 0
        self.A1 = 0
        self.A2 = 0
        self.res0 = 0
        self.res1 = 0
        self.qty = 0

class ColPicHead3:
    def __init__(self):
        self.encodever = 0
        self.res0 = 0
        self.oncelistqty = 0
        self.PicW = 0
        self.PicH = 0
        self.mark = 0
        self.ListDataSize = 0
        self.ColorDataSize = 0
        self.res1 = 0

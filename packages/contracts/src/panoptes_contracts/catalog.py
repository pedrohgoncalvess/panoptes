"""Normalized category attributes; raw specifications remain in ProductDetail."""

import re
from decimal import Decimal
from typing import Literal

from pydantic import Field, StrictBool, model_validator

from .base import Contract

Category = Literal["book", "television", "refrigerator", "school_supplies", "other"]
Attribute = str | int | Decimal | StrictBool | None

UNIT_CASING = {
    "gb": "GB",
    "tb": "TB",
    "mb": "MB",
    "kb": "KB",
    "ghz": "GHz",
    "mhz": "MHz",
    "khz": "kHz",
    "hz": "Hz",
    "mah": "mAh",
}

LOWERCASE_PRODUCT_WORDS = {
    "a",
    "as",
    "o",
    "os",
    "de",
    "da",
    "do",
    "das",
    "dos",
    "e",
    "em",
    "no",
    "na",
    "nos",
    "nas",
    "com",
    "sem",
    "para",
    "por",
    "ao",
    "aos",
    "à",
    "às",
    "um",
    "uma",
}

SPECIAL_PRODUCT_TOKENS = {
    "amd": "AMD",
    "nvidia": "NVIDIA",
    "intel": "Intel",
    "ryzen": "Ryzen",
    "radeon": "Radeon",
    "geforce": "GeForce",
    "threadripper": "Threadripper",
    "athlon": "Athlon",
    "pentium": "Pentium",
    "celeron": "Celeron",
    "xeon": "Xeon",
    "rtx": "RTX",
    "gtx": "GTX",
    "rx": "RX",
    "xt": "XT",
    "xtx": "XTX",
    "gt": "GT",
    "ti": "Ti",
    "x3d": "X3D",
    "am4": "AM4",
    "am5": "AM5",
    "lga": "LGA",
    "tr4": "TR4",
    "ddr3": "DDR3",
    "ddr4": "DDR4",
    "ddr5": "DDR5",
    "gddr5": "GDDR5",
    "gddr6": "GDDR6",
    "gddr6x": "GDDR6X",
    "lpddr4": "LPDDR4",
    "lpddr5": "LPDDR5",
    "lpddr5x": "LPDDR5X",
    "gb": "GB",
    "tb": "TB",
    "mb": "MB",
    "kb": "KB",
    "ghz": "GHz",
    "mhz": "MHz",
    "khz": "kHz",
    "hz": "Hz",
    "mah": "mAh",
    "ssd": "SSD",
    "hdd": "HDD",
    "nvme": "NVMe",
    "sata": "SATA",
    "pcie": "PCIe",
    "m.2": "M.2",
    "ram": "RAM",
    "rom": "ROM",
    "cpu": "CPU",
    "gpu": "GPU",
    "apu": "APU",
    "npu": "NPU",
    "psu": "PSU",
    "aio": "AIO",
    "tv": "TV",
    "led": "LED",
    "oled": "OLED",
    "qled": "QLED",
    "amoled": "AMOLED",
    "miniled": "MiniLED",
    "hd": "HD",
    "fhd": "FHD",
    "qhd": "QHD",
    "uhd": "UHD",
    "wqhd": "WQHD",
    "wuxga": "WUXGA",
    "wxga": "WXGA",
    "ips": "IPS",
    "va": "VA",
    "tn": "TN",
    "usb": "USB",
    "hdmi": "HDMI",
    "dp": "DP",
    "vga": "VGA",
    "dvi": "DVI",
    "rj45": "RJ45",
    "lan": "LAN",
    "wifi": "Wi-Fi",
    "wi-fi": "Wi-Fi",
    "bt": "BT",
    "nfc": "NFC",
    "gps": "GPS",
    "lte": "LTE",
    "rgb": "RGB",
    "argb": "ARGB",
    "atx": "ATX",
    "matx": "mATX",
    "itx": "ITX",
    "bivolt": "Bivolt",
    "ai": "AI",
    "ia": "IA",
    "os": "OS",
    "ios": "iOS",
    "ipados": "iPadOS",
    "macos": "macOS",
    "ps4": "PS4",
    "ps5": "PS5",
    "vr": "VR",
    "cto": "CTO",
    "isbn": "ISBN",
    "se": "SE",
    "fe": "FE",
    "asus": "ASUS",
    "msi": "MSI",
    "asrock": "ASRock",
    "gigabyte": "Gigabyte",
    "aorus": "AORUS",
    "galax": "Galax",
    "zotac": "Zotac",
    "pny": "PNY",
    "evga": "EVGA",
    "sapphire": "Sapphire",
    "powercolor": "PowerColor",
    "xfx": "XFX",
    "inno3d": "Inno3D",
    "kingston": "Kingston",
    "corsair": "Corsair",
    "crucial": "Crucial",
    "adata": "ADATA",
    "xpg": "XPG",
    "sandisk": "SanDisk",
    "seagate": "Seagate",
    "wd": "WD",
    "teamgroup": "TeamGroup",
    "lenovo": "Lenovo",
    "ideapad": "IdeaPad",
    "thinkpad": "ThinkPad",
    "loq": "LOQ",
    "dell": "Dell",
    "alienware": "Alienware",
    "hp": "HP",
    "omen": "OMEN",
    "apple": "Apple",
    "iphone": "iPhone",
    "ipad": "iPad",
    "macbook": "MacBook",
    "imac": "iMac",
    "airpods": "AirPods",
    "airtag": "AirTag",
    "samsung": "Samsung",
    "lg": "LG",
    "ultragear": "UltraGear",
    "ultrawide": "UltraWide",
    "aoc": "AOC",
    "tcl": "TCL",
    "sony": "Sony",
    "playstation": "PlayStation",
    "dualshock": "DualShock",
    "dualsense": "DualSense",
    "xbox": "Xbox",
    "nintendo": "Nintendo",
    "amazon": "Amazon",
    "kindle": "Kindle",
    "paperwhite": "Paperwhite",
    "colorsoft": "Colorsoft",
    "logitech": "Logitech",
    "razer": "Razer",
    "hyperx": "HyperX",
    "redragon": "Redragon",
    "steelseries": "SteelSeries",
    "jbl": "JBL",
    "i3": "i3",
    "i5": "i5",
    "i7": "i7",
    "i9": "i9",
}


def _format_subtoken(token: str, *, is_first: bool) -> str:
    match = re.fullmatch(r"([(\[{]*)(.*?)([)\]},.:;]*)", token)
    prefix, core, suffix = match.groups() if match else ("", token, "")
    if not core:
        return token
    lower = core.casefold()
    if lower in SPECIAL_PRODUCT_TOKENS:
        return f"{prefix}{SPECIAL_PRODUCT_TOKENS[lower]}{suffix}"
    unit_match = re.fullmatch(
        r"(\d+(?:[.,]\d+)?)(gb|tb|mb|kb|ghz|mhz|khz|hz|mah)", core, re.I
    )
    if unit_match:
        number, unit = unit_match.groups()
        return f"{prefix}{number}{UNIT_CASING[unit.casefold()]}{suffix}"
    if re.fullmatch(r"\d+[ªº°]", core) or re.fullmatch(
        r"\d+(?:[.,]\d+)?(?:[x×]\d+(?:[.,]\d+)?)?(?:cm|mm|ml|kg|mg)", core, re.I
    ):
        return f"{prefix}{core.lower()}{suffix}"
    if re.search(r"[0-9]", core) and re.search(r"[a-zA-Z]", core):
        return f"{prefix}{core.upper()}{suffix}"
    if not is_first and lower in LOWERCASE_PRODUCT_WORDS:
        return f"{prefix}{lower}{suffix}"
    return f"{prefix}{core[:1].upper()}{core[1:].lower()}{suffix}"


def format_product_name(value: str | None) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"[\s_]+", " ", value).strip()
    cleaned = re.sub(
        r"\b(\d+(?:[.,]\d+)?)\s*(gb|tb|mb|kb|ghz|mhz|khz|hz|mah)\b",
        lambda m: f"{m.group(1)}{UNIT_CASING[m.group(2).casefold()]}",
        cleaned,
        flags=re.I,
    )
    words = []
    for index, word in enumerate(cleaned.split(" ")):
        if not word:
            continue
        lower = word.casefold()
        if lower in SPECIAL_PRODUCT_TOKENS:
            words.append(SPECIAL_PRODUCT_TOKENS[lower])
            continue
        parts = re.split(r"([-+/])", word)
        formatted_parts = [
            part
            if part in {"-", "+", "/"}
            else _format_subtoken(part, is_first=index == 0 and part_index == 0)
            for part_index, part in enumerate(parts)
        ]
        words.append("".join(formatted_parts))
    return " ".join(words)


class TelevisionAttributes(Contract):
    screen_size_inches: Decimal | None = Field(default=None, gt=0, le=200)
    resolution: str | None = None
    panel_technology: str | None = None
    product_line: str | None = None
    refresh_rate_hz: Decimal | None = Field(default=None, gt=0)
    smart: StrictBool | None = None
    voltage: str | None = None
    color: str | None = None


class RefrigeratorAttributes(Contract):
    capacity_liters: Decimal | None = Field(default=None, gt=0)
    voltage: str | None = None
    color: str | None = None
    frost_free: StrictBool | None = None
    door_count: int | None = Field(default=None, ge=1)


class BookAttributes(Contract):
    isbn: str | None = None
    edition: str | None = None
    format: str | None = None
    language: str | None = None
    page_count: int | None = Field(default=None, ge=1)


class SchoolSuppliesAttributes(Contract):
    item_type: str | None = None
    units_per_pack: int | None = Field(default=None, ge=1)
    material: str | None = None
    color: str | None = None
    volume_ml: Decimal | None = Field(default=None, gt=0)
    sheet_count: int | None = Field(default=None, ge=1)


CATEGORY_ATTRIBUTES = {
    "television": TelevisionAttributes,
    "refrigerator": RefrigeratorAttributes,
    "book": BookAttributes,
    "school_supplies": SchoolSuppliesAttributes,
}


def validate_attributes(category, attributes):
    if category == "other":
        if attributes:
            raise ValueError("Unclassified products cannot have category attributes")
        return {}
    result = (
        CATEGORY_ATTRIBUTES[category]
        .model_validate(attributes)
        .model_dump(exclude_none=True)
    )
    for key, value in result.items():
        if isinstance(value, Decimal):
            result[key] = Decimal(format(value.normalize(), "f"))
    if result.get("voltage"):
        result["voltage"] = re.sub(r"\s+", "", result["voltage"]).casefold()
    if result.get("resolution"):
        value = result["resolution"]
        match = re.fullmatch(r"\s*(\d+)\s*[x×]\s*(\d+)\s*", value, re.I)
        if match:
            result["resolution"] = f"{match.group(1)}x{match.group(2)}"
    return result


class CatalogProduct(Contract):
    category: Category
    brand: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, min_length=1)
    identifiers: dict[str, str] = Field(default_factory=dict)
    attributes: dict[str, Attribute] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_category_attributes(self):
        normalized = validate_attributes(self.category, self.attributes)
        object.__setattr__(self, "attributes", normalized)
        return self

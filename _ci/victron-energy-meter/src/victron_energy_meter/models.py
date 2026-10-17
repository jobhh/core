"""The meter models this library knows, and their firmware version."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from functools import total_ordering
from types import MappingProxyType
from typing import Final


class ProductId(IntEnum):
    """The product id a meter reports at register 0x1000."""

    VM_3P75CT = 0xA1B1
    VM_3P5A = 0xA1B2


@dataclass(frozen=True, slots=True)
class MeterModel:
    """One meter model."""

    product_id: ProductId
    name: str

    @property
    def high_range_current(self) -> bool:
        """Whether the phase currents come from the 32-bit high-range registers.

        The VM-3P5A measures directly, and reports its currents only there. The
        VM-3P75CT reports them in the 16-bit registers of each phase block.
        """
        return self.product_id is ProductId.VM_3P5A


MODELS: Final = MappingProxyType(
    {
        ProductId.VM_3P75CT: MeterModel(ProductId.VM_3P75CT, "VM-3P75CT"),
        ProductId.VM_3P5A: MeterModel(ProductId.VM_3P5A, "VM-3P5A"),
    }
)


def model_for_product_id(product_id: int) -> MeterModel | None:
    """The model a product id belongs to, or ``None`` if unknown."""
    try:
        return MODELS[ProductId(product_id)]
    except ValueError:
        return None


@total_ordering
@dataclass(frozen=True, slots=True)
class FirmwareVersion:
    """A firmware version, from the four bytes at registers 0x1009-0x100A.

    Bytes 1 and 2 are the version, shown in hexadecimal. Byte 3 is ``0xFF``
    for a release and the beta number otherwise. This follows Victron's own
    driver; the manual does not describe the encoding.
    """

    raw: tuple[int, int, int, int]

    @classmethod
    def from_words(cls, high: int, low: int) -> FirmwareVersion:
        """Decode the two registers, high word first."""
        return cls((high >> 8, high & 0xFF, low >> 8, low & 0xFF))

    @property
    def is_beta(self) -> bool:
        """Whether this is a beta release."""
        return self.raw[3] != 0xFF

    def at_least(self, major: int, minor: int, beta: int = 0) -> bool:
        """Whether this version is ``major.minor`` (or the given beta) or newer.

        The comparison is on the raw bytes, as Victron's driver does. A release
        (byte 3 ``0xFF``) sorts after every beta of the same version.
        """
        return self.raw >= (0, major, minor, beta)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, FirmwareVersion):
            return NotImplemented
        return self.raw < other.raw

    def __str__(self) -> str:
        version = f"v{self.raw[1]:x}.{self.raw[2]:02x}"
        if self.is_beta:
            return f"{version}-beta-{self.raw[3]:02x}"
        return version

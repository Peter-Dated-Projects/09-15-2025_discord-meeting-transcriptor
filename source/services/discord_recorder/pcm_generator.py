# -------------------------------------------------------------- #
# PCM Generator
# -------------------------------------------------------------- #

from abc import ABC, abstractmethod


class PCMGenerator(ABC):
    """
    Base class for PCM audio data generators.
    """

    @abstractmethod
    def generate(self, ms: int, offset: int = 0) -> bytes:
        """
        Generate PCM audio data.

        Args:
            ms: Duration in milliseconds
            offset: Optional offset in milliseconds (default: 0)

        Returns:
            PCM audio data as bytes
        """
        pass


# -------------------------------------------------------------- #
# Silent PCM Generator
# -------------------------------------------------------------- #


class SilentPCM(PCMGenerator):
    """
    Generate silent PCM bytes.
    Defaults: 48 kHz, 16-bit signed, stereo, little-endian.
    """

    def __init__(
        self,
        sample_rate: int = 48000,
        bits_per_sample: int = 16,
        channels: int = 2,
        unsigned_8bit: bool = False,
    ):
        if bits_per_sample not in (8, 16, 24, 32):
            raise ValueError("bits_per_sample must be 8,16,24,32")
        self.sample_rate = sample_rate
        self.bits_per_sample = bits_per_sample
        self.channels = channels
        self.unsigned_8bit = unsigned_8bit

    def generate(self, ms: int, offset: int = 0) -> bytes:
        """
        Generate silent PCM audio data.

        Args:
            ms: Duration in milliseconds
            offset: Optional offset in milliseconds (default: 0, currently unused)

        Returns:
            Silent PCM audio data as bytes

        Notes:
            - Silence is all zeros for signed PCM (16/24/32-bit)
            - For unsigned 8-bit PCM, silence is 0x80
            - Byte count = round(ms * sr / 1000) * channels * (bits/8)
        """
        frames = round(self.sample_rate * (ms / 1000.0))
        bytes_per_sample = self.bits_per_sample // 8
        frame_bytes = self.channels * bytes_per_sample
        nbytes = frames * frame_bytes

        if self.bits_per_sample == 8 and self.unsigned_8bit:
            # Unsigned 8-bit PCM silence is 0x80
            return bytes([0x80]) * nbytes
        # Signed PCM silence is 0x00
        return bytes(nbytes)

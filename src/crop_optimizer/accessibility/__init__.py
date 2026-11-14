"""Camada de acessibilidade: Rádio do Tempo (TTS), PDF One-Pager e WhatsApp/Twilio."""

from crop_optimizer.accessibility.one_pager_pdf import (
    WHAT_WE_DONT_KNOW_ITEMS,
    generate_one_pager_pdf,
)
from crop_optimizer.accessibility.radio_tempo import (
    AudioSynthesisResult,
    GoogleTTSProvider,
    OfflineWavTTSProvider,
    OpenAITTSProvider,
    TTSProvider,
    compose_radio_script,
    create_tts_provider,
)
from crop_optimizer.accessibility.whatsapp import (
    TwilioWhatsAppClient,
    WhatsAppDispatchResult,
    build_whatsapp_summary_message,
)

__all__ = [
    "WHAT_WE_DONT_KNOW_ITEMS",
    "AudioSynthesisResult",
    "GoogleTTSProvider",
    "OfflineWavTTSProvider",
    "OpenAITTSProvider",
    "TTSProvider",
    "TwilioWhatsAppClient",
    "WhatsAppDispatchResult",
    "build_whatsapp_summary_message",
    "compose_radio_script",
    "create_tts_provider",
    "generate_one_pager_pdf",
]

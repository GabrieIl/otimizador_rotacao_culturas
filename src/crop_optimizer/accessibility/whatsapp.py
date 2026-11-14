"""Integração de distribuição via WhatsApp (Twilio REST API) para agricultores no Sertão."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from crop_optimizer.domain.models import (
    LocationSpec,
    StrategySimulationResult,
    TrafficLightLevel,
)


@dataclass(slots=True)
class WhatsAppDispatchResult:
    """Resultado do disparo (real ou simulado) via Twilio WhatsApp."""

    sent: bool
    mode: str
    to_number: str
    body: str
    sid: str | None = None
    status_code: int = 200


def build_whatsapp_summary_message(
    farmer_name: str,
    location: LocationSpec,
    delay_days: int,
    traffic_light: TrafficLightLevel,
    traditional_result: StrategySimulationResult,
    resilient_result: StrategySimulationResult,
) -> str:
    """Formata mensagem curta e acessível para WhatsApp."""
    return (
        f"*Conselheiro do Sertão — {location.name}/{location.state}*\n"
        + (f"Olá, *{farmer_name}*!\n\n" if farmer_name else "Olá!\n\n")
        + f"*Semáforo da Chuva ({delay_days}d de atraso):*\n"
        f"Sinal {traffic_light.label.lower()}: *{traffic_light.guidance}*\n\n"
        f"*Placar em 10 anos:*\n"
        f"• {traditional_result.strategy.short_name}: perde a roça em *{traditional_result.loss_years_of_10} de 10* anos\n"
        f"• {resilient_result.strategy.short_name}: sobrevive *{resilient_result.survival_score_of_10} de 10* anos "
        f"({f'{resilient_result.expected_forage_kg_ha_year:,.0f}'.replace(',', '.')} kg/ha de forragem)\n\n"
        f"Ouça o áudio do *Rádio do Tempo* anexo ou peça a Ficha Técnica ao técnico da EMATER."
    )


class TwilioWhatsAppClient:
    """Cliente HTTP para envio de mensagens e áudio/PDF via Twilio WhatsApp API."""

    def __init__(
        self,
        account_sid: str | None = None,
        auth_token: str | None = None,
        from_number: str = "whatsapp:+14155238886",
    ) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number

    @property
    def is_configured(self) -> bool:
        return bool(self.account_sid and self.auth_token)

    def send_message(
        self,
        to_number: str,
        body: str,
        media_url: str | None = None,
    ) -> WhatsAppDispatchResult:
        formatted_to = to_number if to_number.startswith("whatsapp:") else f"whatsapp:{to_number}"
        if not self.is_configured:
            return WhatsAppDispatchResult(
                sent=False,
                mode="simulated_dry_run",
                to_number=formatted_to,
                body=body,
                sid="SIMULATED_TWILIO_SID",
                status_code=200,
            )

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        payload: dict[str, str] = {
            "From": self.from_number,
            "To": formatted_to,
            "Body": body,
        }
        if media_url:
            payload["MediaUrl"] = media_url

        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                url,
                data=payload,
                auth=(self.account_sid or "", self.auth_token or ""),
            )
            resp.raise_for_status()
            data = resp.json()

        return WhatsAppDispatchResult(
            sent=True,
            mode="twilio_live",
            to_number=formatted_to,
            body=body,
            sid=data.get("sid"),
            status_code=resp.status_code,
        )

"""Memória de cada conversa: onde fica a roça e as últimas mensagens.

Fica em data/conversa/sessoes/ (fora do git). O nome do arquivo é um hash da chave (o número do
WhatsApp), então o número não aparece em disco.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from crop_optimizer.agente.local import LocalConversa
from crop_optimizer.config import Settings, get_settings, load_yaml_config


def chave_hash(chave: str) -> str:
    return hashlib.sha256(f"acaua:{chave}".encode()).hexdigest()[:24]


@dataclass(slots=True)
class Sessao:
    id: str
    local: LocalConversa | None = None
    historico: list[dict] = field(default_factory=list)  # {"role": "user"|"assistant", "content": str}
    simular: date | None = None
    atualizada: str = ""
    apresentado: bool = False  # já recebeu a mensagem de boas-vindas (com o aviso de privacidade)

    def lembrar(self, pergunta: str, resposta: str) -> None:
        limit = int(load_yaml_config("conversa")["sessao"]["max_mensagens_historico"])
        self.historico += [{"role": "user", "content": pergunta}, {"role": "assistant", "content": resposta}]
        self.historico = self.historico[-limit:]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "local": self.local.to_dict() if self.local else None,
            "historico": self.historico,
            "simular": self.simular.isoformat() if self.simular else None,
            "atualizada": self.atualizada,
            "apresentado": self.apresentado,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Sessao:
        return cls(
            id=data["id"],
            local=LocalConversa.from_dict(data["local"]) if data.get("local") else None,
            historico=list(data.get("historico", [])),
            simular=date.fromisoformat(data["simular"]) if data.get("simular") else None,
            atualizada=data.get("atualizada", ""),
            apresentado=bool(data.get("apresentado", False)),
        )


class SessaoStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.folder: Path = (settings or get_settings()).paths.root / "conversa" / "sessoes"

    def _path(self, sid: str) -> Path:
        return self.folder / f"{sid}.json"

    def carregar(self, chave: str) -> Sessao:
        sid = chave_hash(chave)
        path = self._path(sid)
        if not path.exists():
            return Sessao(id=sid)
        sessao = Sessao.from_dict(json.loads(path.read_text(encoding="utf-8")))
        days = int(load_yaml_config("conversa")["sessao"]["expira_dias"])
        if sessao.atualizada and datetime.fromisoformat(sessao.atualizada) < datetime.now() - timedelta(days=days):
            sessao.historico = []  # conversa velha recomeça; o local continua valendo
        return sessao

    def salvar(self, sessao: Sessao) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        sessao.atualizada = datetime.now().isoformat(timespec="seconds")
        self._path(sessao.id).write_text(json.dumps(sessao.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")

    def apagar(self, chave: str) -> None:
        self._path(chave_hash(chave)).unlink(missing_ok=True)

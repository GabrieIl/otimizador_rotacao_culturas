"""Rotações candidatas do ranking, montadas em volta das restrições do usuário.

Uma rotação do motor é o conjunto de culturas da propriedade num ano (o motor divide a área entre elas
e repete o conjunto a cada ano). Aqui geramos todas as combinações de 1 a `max_size` culturas de sequeiro
que respeitam:
- "precisa ter": a combinação contém todas essas culturas;
- "não pode ter": nenhuma dessas culturas aparece.

As rotações de exemplo do projeto (domain/presets.py) mantêm o nome e a descrição quando a combinação
coincide. Só culturas de sequeiro entram: as com rega não dependem da chuva que o motor simula.
"""

from __future__ import annotations

from itertools import combinations

from crop_optimizer.config import load_yaml_config
from crop_optimizer.domain.crop_registry import ordered_ids, sequeiro_ids
from crop_optimizer.domain.models import RotationStrategy
from crop_optimizer.domain.presets import DEFAULT_STRATEGIES

CURRENT_ID = "como_planta_hoje"


def _names() -> dict[str, str]:
    return {k: v["nome"] for k, v in load_yaml_config("aptidao")["culturas"].items()}


def _canonical(crops: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    order = {c: i for i, c in enumerate(ordered_ids())}
    return tuple(sorted(dict.fromkeys(crops), key=lambda c: order.get(c, 999)))


def strategy_for(crops: list[str] | tuple[str, ...], strategy_id: str | None = None,
                 name: str | None = None, description: str | None = None) -> RotationStrategy:
    crops = _canonical(crops)
    for preset in DEFAULT_STRATEGIES:
        if _canonical(preset.annual_sequence) == crops and strategy_id is None:
            return preset
    names = _names()
    label = " + ".join(names.get(c, c) for c in crops)
    return RotationStrategy(
        strategy_id=strategy_id or "rot_" + "_".join(crops),
        name=name or label,
        short_name=name or label,
        description=description or f"Rotação com {label.lower()}, montada pelo Acauã a partir das restrições.",
        annual_sequence=list(crops),
    )


def candidate_strategies(required: list[str] | None = None, excluded: list[str] | None = None,
                         max_size: int = 3) -> list[RotationStrategy]:
    """Todas as combinações de culturas de sequeiro que respeitam as restrições."""
    required = [c for c in _canonical(required or []) if c in sequeiro_ids()]
    excluded = set(excluded or [])
    if set(required) & excluded:
        return []
    pool = [c for c in sequeiro_ids() if c not in excluded and c not in required]
    size_max = max(max_size, len(required))
    out: list[RotationStrategy] = []
    for extra in range(0, size_max - len(required) + 1):
        for combo in combinations(pool, extra):
            crops = [*required, *combo]
            if crops:
                out.append(strategy_for(crops))
    return out


def current_strategy(crops_now: list[str]) -> RotationStrategy:
    """O jeito que a roça planta hoje: as culturas de sequeiro dos talhões, ou só milho se não houver."""
    seq = [c for c in _canonical(crops_now) if c in sequeiro_ids()]
    if seq:
        label = " + ".join(_names().get(c, c) for c in seq)
        return strategy_for(seq, strategy_id=CURRENT_ID, name=f"Como planta hoje: {label}",
                            description="As culturas de sequeiro plantadas hoje nos talhões, repetidas a cada ano.")
    return strategy_for(["milho_sertanejo"], strategy_id=CURRENT_ID, name="Como planta hoje (só milho)",
                        description="Sem talhões informados, a referência é o milho de sequeiro todo ano, "
                                    "o jeito mais comum na região.")


def satisfies(strategy: RotationStrategy, required: list[str], excluded: list[str]) -> bool:
    crops = set(strategy.annual_sequence)
    return set(required) <= crops and not (crops & set(excluded))

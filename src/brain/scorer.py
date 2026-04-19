from datetime import datetime, timezone


def score_memory(
    content: str,
    created_at: str,
    frequency: int = 1,
    files_affected: int = 1,
    explicit: bool = False,
) -> float:
    """
    Calcola lo score di una memoria (0.0 - 1.0).
    Determina in quale livello finisce:
      >= 0.7 → L1 (always-on)
      >= 0.4 → L2 (on-demand)
      <  0.4 → L3 (archivio)
    """
    # Recency: decadimento lineare su 30 giorni
    try:
        created = datetime.fromisoformat(created_at).replace(tzinfo=timezone.utc)
    except Exception:
        created = datetime.now(timezone.utc)

    age_days = (datetime.now(timezone.utc) - created).days
    recency = max(0.0, 1.0 - (age_days / 30))

    # Frequency: normalizzato su max 10 occorrenze
    frequency_score = min(1.0, frequency / 10)

    # Impact: normalizzato su max 5 file
    impact_score = min(1.0, files_affected / 5)

    # Explicit: il developer ha marcato esplicitamente questa memoria
    explicit_score = 1.0 if explicit else 0.0

    # Pesi
    score = (
        recency        * 0.35 +
        frequency_score * 0.30 +
        impact_score    * 0.20 +
        explicit_score  * 0.15
    )

    return round(score, 3)


def assign_level(score: float) -> int:
    if score >= 0.7:
        return 1
    elif score >= 0.4:
        return 2
    else:
        return 3
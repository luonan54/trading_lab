from app.classification.config import ClassificationConfig
from app.classification.models import PortfolioRole


def is_role_transition_allowed(
    current: PortfolioRole,
    candidate: PortfolioRole,
    config: ClassificationConfig,
) -> bool:
    if current is candidate:
        return False
    return candidate in config.candidates_for(current)

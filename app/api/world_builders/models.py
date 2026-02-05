from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.utils import current_time


class WorldBuilder(Base):
    __tablename__ = 'world_builders'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    email: Mapped[str]
    world_address: Mapped[str]
    first_name: Mapped[str | None]
    last_name: Mapped[str | None]
    builder_score: Mapped[int | None] = mapped_column(default=0)
    phone: Mapped[str | None]
    location: Mapped[str | None]
    personal_links: Mapped[str | None]
    x_handle: Mapped[str | None]
    project_description: Mapped[str | None]
    project_stage: Mapped[str | None]
    funding_status: Mapped[str | None]
    team_description: Mapped[str | None]
    tech_stack: Mapped[str | None]
    edge_nexus_benefit: Mapped[str | None]
    edge_nexus_cohort: Mapped[str | None]
    financial_situation: Mapped[str | None]
    financial_support_reason: Mapped[str | None]
    extra_info: Mapped[str | None]
    integration_potential: Mapped[str | None]
    send_proposal: Mapped[bool | None] = mapped_column(default=False)
    accepted: Mapped[str | None]
    notes: Mapped[str | None]

    created_at: Mapped[datetime | None] = mapped_column(default=current_time)
    updated_at: Mapped[datetime | None] = mapped_column(
        default=current_time, onupdate=current_time
    )
    created_by: Mapped[str | None]
    updated_by: Mapped[str | None]

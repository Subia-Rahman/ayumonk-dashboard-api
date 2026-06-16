from __future__ import annotations
from config_service.app.core.audit.mixin import AuditMixin
from sqlalchemy import event
from sqlalchemy.orm import Session

from sqlalchemy.orm import with_loader_criteria


@event.listens_for(Session, "before_flush")
def set_audit_fields(session, flush_context, instances):
    """
    Automatically populate created_by and updated_by
    using user_id stored in session.info.
    """
    user_id = session.info.get("user_id")

    for obj in session.new:
        if isinstance(obj, AuditMixin):
            obj.created_by = user_id
            obj.updated_by = None

    for obj in session.dirty:
        if isinstance(obj, AuditMixin):
            obj.updated_by = user_id


@event.listens_for(Session, "do_orm_execute")
def add_soft_delete_filter(execute_state):
    if execute_state.is_select:
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                AuditMixin,
                lambda cls: cls.is_deleted == False,
                include_aliases=True
            )
        )
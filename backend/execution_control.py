"""One platform execution switch, checked at admission and again at execution."""

from fastapi import HTTPException


def execution_allowed(settings):
    return bool(settings.execution_enabled)


def require_execution(settings):
    if not execution_allowed(settings):
        raise HTTPException(409, "Platform execution is disabled; no orders or paper fills are permitted")

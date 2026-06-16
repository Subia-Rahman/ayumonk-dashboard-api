from __future__ import annotations
from datetime import datetime, time as dtime
from authentication_service.app.services.access_control_service import AccessControlService


class PolicyService:
    def __init__(self, access_control: AccessControlService):
        self.ac = access_control

    async def evaluate_abac(self, user, resource: dict, module: str) -> bool:
        policies = await self.ac.list_policies(user.tenant_id, module)
        matched_allow = False
        for policy in policies:
            if not policy.is_active:
                continue
            if self._matches(policy.condition_json, user, resource):
                if policy.effect.lower() == "deny":
                    return False
                matched_allow = True
        if matched_allow:
            return True
        return True  # default allow when no policy matches

    def _matches(self, condition_json: dict, user, resource: dict) -> bool:
        if not condition_json:
            return True
        for key, value in condition_json.items():
            if key == "time":
                if not self._match_time(value):
                    return False
                continue
            if isinstance(value, str) and "==" in value:
                left, right = [v.strip() for v in value.split("==", 1)]
                if not self._resolve_expr(left, user, resource) == self._resolve_expr(
                    right, user, resource
                ):
                    return False
                continue
            if isinstance(value, str) and value.startswith("user."):
                user_val = getattr(user, value.split(".", 1)[1], None)
                res_val = resource.get(key)
                if user_val != res_val:
                    return False
                continue
            if resource.get(key) != value:
                return False
        return True

    def _resolve_expr(self, expr: str, user, resource: dict):
        if expr.startswith("user."):
            return getattr(user, expr.split(".", 1)[1], None)
        if expr.startswith("resource."):
            return resource.get(expr.split(".", 1)[1])
        return expr

    def _match_time(self, value: str) -> bool:
        try:
            if "-" in value:
                start, end = value.split("-", 1)
                start_t = self._parse_time(start)
                end_t = self._parse_time(end)
                now_t = datetime.now().time()
                if start_t <= end_t:
                    return start_t <= now_t <= end_t
                return now_t >= start_t or now_t <= end_t
        except Exception:
            return False
        return True

    def _parse_time(self, value: str) -> dtime:
        value = value.strip()
        if ":" in value:
            h, m = value.split(":")
            return dtime(hour=int(h), minute=int(m))
        return dtime(hour=int(value), minute=0)

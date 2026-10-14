from app.models.leads import Verification
from app.services.provider_http import ProviderError, ProviderHTTP


class NeverBounceService:
    def __init__(self, http: ProviderHTTP, key: str):
        self.http, self.key = http, key

    def verify(self, email: str) -> Verification:
        try:
            payload = self.http.get("https://api.neverbounce.com/v4.2/single/check",
                                    params={"key": self.key, "email": email, "timeout": 20})
        except ProviderError as error:
            return Verification(result="verification_error", failure_reason=error.reason)
        if payload.get("status") != "success" or payload.get("result") not in {"valid", "invalid", "disposable", "catchall", "unknown"}:
            return Verification(result="verification_error", failure_reason="neverbounce_invalid_response")
        return Verification(result=payload["result"], status=payload["status"],
                            flags=[value for value in payload.get("flags", []) if isinstance(value, str)] if isinstance(payload.get("flags"), list) else [],
                            suggested_correction=payload.get("suggested_correction") if isinstance(payload.get("suggested_correction"), str) else None)

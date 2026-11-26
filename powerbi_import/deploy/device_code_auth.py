"""Interactive device-code authentication for Power BI / Fabric.

``FabricAuthenticator`` covers the unattended paths — a service principal or a
managed identity — and both need ``azure-identity`` installed plus, for a
service principal, a tenant admin to register an app, grant API permissions and
switch on "Allow service principals to use Power BI APIs". That approval is
often the slowest part of a migration.

Device code is the interactive alternative: the user signs in as themselves in
a browser, and the token carries their own Power BI permissions. Nothing has to
be registered, and it runs on the standard library alone, so it holds to the
project's zero-dependency rule for the core tool.

Use it when:
  * no service principal has been approved yet, or
  * a one-off deployment is being run by a person rather than a pipeline.

Use ``FabricAuthenticator`` instead for CI and scheduled jobs — device code
needs a human at a browser.

    from deploy.device_code_auth import DeviceCodeAuthenticator

    auth = DeviceCodeAuthenticator(tenant_id="contoso.onmicrosoft.com")
    headers = auth.get_headers()      # prompts once, then caches the token

Secrets are never read from the command line: the tenant comes from the
argument or ``FABRIC_TENANT_ID`` / ``AZURE_TENANT_ID``, and no token is logged.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

__all__ = ["DeviceCodeAuthenticator", "DeviceCodeError"]

#: Microsoft's own public client id for Power BI. It is a well-known public
#: identifier, not a secret, and needs no app registration of its own.
DEFAULT_PUBLIC_CLIENT_ID = "ea0616ba-638b-4df5-95b9-636659ae5121"

AUTHORITY = "https://login.microsoftonline.com"

DEFAULT_SCOPES = (
    "https://analysis.windows.net/powerbi/api/Report.ReadWrite.All "
    "https://analysis.windows.net/powerbi/api/Dataset.ReadWrite.All "
    "https://analysis.windows.net/powerbi/api/Workspace.ReadWrite.All "
    "offline_access"
)


class DeviceCodeError(RuntimeError):
    """Device-code sign-in could not be completed."""


def _post_form(url, fields, timeout=30):
    """POST a form and return (status_code, parsed_json).

    Azure AD returns a JSON body on failure as well as success, and the error
    code in it is what drives the polling loop, so a 400 is read rather than
    raised.
    """
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"error": "http_error", "error_description": raw}
    except urllib.error.URLError as exc:
        raise DeviceCodeError(f"Could not reach {AUTHORITY}: {exc.reason}") from exc


class DeviceCodeAuthenticator:
    """Acquire a Power BI token by interactive device-code sign-in."""

    def __init__(self, tenant_id=None, client_id=None, scopes=None,
                 prompt=print):
        self.tenant_id = (
            tenant_id
            or os.environ.get("FABRIC_TENANT_ID")
            or os.environ.get("AZURE_TENANT_ID")
            or "organizations"
        )
        self.client_id = (
            client_id
            or os.environ.get("FABRIC_CLIENT_ID")
            or DEFAULT_PUBLIC_CLIENT_ID
        )
        self.scopes = scopes or DEFAULT_SCOPES
        self._prompt = prompt
        self._token = None
        self._expires_at = 0.0

    # -- public ------------------------------------------------------
    def get_token(self, force_refresh=False):
        """Return a valid access token, signing in if needed."""
        if not force_refresh and self._token and time.time() < self._expires_at:
            return self._token
        self._token, self._expires_at = self._run_device_code_flow()
        return self._token

    def get_headers(self, content_type="application/json"):
        """Return request headers carrying a valid bearer token."""
        headers = {"Authorization": f"Bearer {self.get_token()}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    # -- flow --------------------------------------------------------
    def _request_device_code(self):
        status, payload = _post_form(
            f"{AUTHORITY}/{self.tenant_id}/oauth2/v2.0/devicecode",
            {"client_id": self.client_id, "scope": self.scopes},
        )
        if status != 200 or "device_code" not in payload:
            raise DeviceCodeError(
                "Could not start device-code sign-in: "
                f"{payload.get('error_description') or payload.get('error') or status}"
            )
        return payload

    def _run_device_code_flow(self):
        device = self._request_device_code()

        # Azure AD supplies a ready-made instruction line; it names the URL and
        # the code and is localised, so show it rather than reassembling one.
        message = device.get("message") or (
            f"Open {device.get('verification_uri')} and enter the code "
            f"{device.get('user_code')}"
        )
        self._prompt("")
        self._prompt("=" * 64)
        self._prompt("  POWER BI SIGN-IN REQUIRED")
        self._prompt("=" * 64)
        self._prompt(f"  {message}")
        self._prompt("=" * 64)
        self._prompt("")

        token_url = f"{AUTHORITY}/{self.tenant_id}/oauth2/v2.0/token"
        interval = max(1, int(device.get("interval", 5)))
        deadline = time.time() + int(device.get("expires_in", 900))

        while time.time() < deadline:
            time.sleep(interval)
            status, payload = _post_form(token_url, {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": self.client_id,
                "device_code": device["device_code"],
            })

            if status == 200 and payload.get("access_token"):
                # Expire a minute early so a long upload cannot start on a
                # token that dies mid-request.
                expires_at = time.time() + int(payload.get("expires_in", 3600)) - 60
                self._prompt("  Signed in.")
                logger.info("Device-code sign-in succeeded")
                return payload["access_token"], expires_at

            error = payload.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue
            if error == "authorization_declined":
                raise DeviceCodeError("Sign-in was declined.")
            if error == "expired_token":
                raise DeviceCodeError(
                    "The device code expired before sign-in completed. Run the "
                    "command again.")
            if error == "bad_verification_code":
                continue
            raise DeviceCodeError(
                payload.get("error_description") or f"Sign-in failed: {error}")

        raise DeviceCodeError(
            "Timed out waiting for sign-in. Run the command again.")

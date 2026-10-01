"""Build a Salesforce record URL from the connected org base and a record id.

One builder shared by the admin Synced tab Salesforce column and the patient
chart Open in Salesforce button, so the two links cannot drift apart. The URL
is always derived from the live ``instance_url`` the OAuth token carries, never
stored, so a My Domain rename or a sandbox to production move follows the org
automatically. With the source object known the exact Lightning record URL is
returned. Without it the bare ``{instance_url}/{external_id}`` redirect lets
Salesforce resolve the object from the record id prefix. An empty instance url
or external id yields an empty string so the caller renders nothing rather than
a dead link.
"""


def build_salesforce_record_url(
    instance_url: str, external_id: str, source_object: str = ""
) -> str:
    """Return the Salesforce record URL, or an empty string when unbuildable."""
    if not instance_url or not external_id:
        return ""
    base = instance_url.rstrip("/")
    if source_object:
        return f"{base}/lightning/r/{source_object}/{external_id}/view"
    return f"{base}/{external_id}"


__all__ = ("build_salesforce_record_url",)

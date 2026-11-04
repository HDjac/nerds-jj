"""Immutable Docker-image allowlist for Pilot 1.

Legacy entries preserve the two validated existing participants.
The RC2 exception is limited to one designated acceptance container.
Never trust a mutable Docker tag alone.
"""

LEGACY_TAG = "devob_instance:cli-pilot-protected"
RC2_TAG = "devob_instance:r2d4-consolidated-rc2"
RC2_NAME = "nerds-pilot1-r2d4-rc2-acceptance"

LEGACY_IDS = frozenset({
    "sha256:d39c6a42b3692246a0ffc086f04ea2f83d261d67cf820fcf96a7e34d78f66581",
    "sha256:787f850c610ec095eaf3b7e62172ada9ffb6d0b2f2ff1dee590434b5a7ed0033",
})

RC2_ID = (
    "sha256:825246d5460d56c0df37444bf113e7c9a03e8867d724b86401a8c24a098a5abf"
)


def image_is_approved(container, name):
    """Validate the actual image ID, configured tag, and RC2 container name.

    Callers must additionally enforce running state, DB instance binding,
    unprivileged user, study label, and participant network.
    """
    if not isinstance(container, dict) or not isinstance(name, str):
        return False

    config = container.get("Config")
    if not isinstance(config, dict):
        return False

    configured_tag = config.get("Image")
    immutable_id = container.get("Image")

    if configured_tag == LEGACY_TAG:
        return immutable_id in LEGACY_IDS

    return (
        name == RC2_NAME
        and configured_tag == RC2_TAG
        and immutable_id == RC2_ID
    )

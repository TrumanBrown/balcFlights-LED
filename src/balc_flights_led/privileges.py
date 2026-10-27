"""Keep root confined to opening the HUB75 panel.

rpi-rgb-led-matrix can drop root itself, but it ignores failures and keeps root's
supplementary groups. The drop is done here instead so it can be completed and
then verified.
"""

from __future__ import annotations

import ctypes
import logging
import os

LOGGER = logging.getLogger(__name__)

# The same account rpi-rgb-led-matrix drops to. It owns none of this project's
# files and is not a sudoer, unlike the account that ran sudo.
UNPRIVILEGED_USER = "daemon"
PR_SET_NO_NEW_PRIVS = 38


def running_as_root() -> bool:
    geteuid = getattr(os, "geteuid", None)
    return geteuid is not None and geteuid() == 0


def drop_root() -> None:
    """Permanently switch from root to ``daemon``, with no way back.

    Raises RuntimeError unless the process is verifiably unprivileged afterwards.
    """
    if not running_as_root():
        _verify_unprivileged()
        return

    uid, gid = _unprivileged_ids()
    try:
        # Groups first: once the uid changes, the right to clear them is gone.
        os.setgroups([])
        os.setresgid(gid, gid, gid)
        os.setresuid(uid, uid, uid)
    except OSError as error:
        raise RuntimeError(f"could not drop root privileges: {error}") from error

    _forbid_new_privileges()
    _verify_unprivileged()
    LOGGER.info("Dropped root after opening the panel; now uid=%d gid=%d", uid, gid)


def _unprivileged_ids() -> tuple[int, int]:
    import pwd

    try:
        account = pwd.getpwnam(UNPRIVILEGED_USER)
    except KeyError as error:
        raise RuntimeError(
            f"no '{UNPRIVILEGED_USER}' account to drop root privileges to"
        ) from error
    if account.pw_uid == 0 or account.pw_gid == 0:
        raise RuntimeError(f"the '{UNPRIVILEGED_USER}' account is privileged")
    return account.pw_uid, account.pw_gid


def _forbid_new_privileges() -> None:
    """Stop setuid binaries such as sudo from handing root back to this process."""
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        error = ctypes.get_errno()
        raise RuntimeError(f"could not set no_new_privs: {os.strerror(error)}")


def _verify_unprivileged() -> None:
    if os.geteuid() == 0 or os.getuid() == 0:
        raise RuntimeError("still running as root after dropping privileges")
    if os.getegid() == 0 or os.getgid() == 0 or 0 in os.getgroups():
        raise RuntimeError("still holding the root group after dropping privileges")

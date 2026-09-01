"""Remote archive backends — declared, sketched, NOT IMPLEMENTED.

Every class here raises ``NotImplementedError`` with a message a reader can act
on. They are in the tree for one reason: to keep ``BlobStorage`` honest. An
interface designed against a single local directory acquires local-directory
assumptions within a week, and the archive is the one store that cannot be
rebuilt after the fact.

What each would need, recorded now while the reasoning is fresh.

S3-COMPATIBLE (AWS S3, Backblaze B2, MinIO, Cloudflare R2, Wasabi)
    Credentials: access key id and secret, named by environment variable in
    settings, never written to a config file. Optionally a session token.
    Config: endpoint_url, region, bucket, prefix, path-style addressing flag for
    MinIO. No OAuth involved — this is the easiest of the four and the one to
    implement first.
    Mapping: key -> ``{prefix}/{key}``; put -> PutObject; usage -> ListObjectsV2
    with pagination, which is why ``usage()`` is allowed to be slow and is only
    ever called from the Settings screen.

OAUTH BACKENDS (Dropbox, Google Drive, OneDrive)
    All three are authorisation-code flow with PKCE, and all three need the same
    four things the interface above does not yet carry:

      1. A *local redirect*. The dashboard already runs an HTTP server on
         127.0.0.1, so the redirect URI is ``http://127.0.0.1:<port>/api/oauth/
         callback/<backend>``. No cloud component and no shared client secret in
         a self-hosted application: PKCE exists precisely for this case.
      2. A *token store*. Refresh tokens are long-lived credentials and must not
         land in ``settings.yaml``, which readers are encouraged to copy and
         version-control. They belong in a separate file with restrictive
         permissions under the data directory, or in the OS keychain.
      3. A *refresh-on-401 wrapper* around every call, because access tokens
         expire mid-run and the collector is a long-lived process.
      4. A *folder handle* rather than a path. Drive and OneDrive address files
         by id, not by path, so a backend keeps a small local map from logical
         key to remote id. ``normalise_key`` already guarantees keys are stable
         and hierarchical, which is what makes that map possible.

    Per service:

    Dropbox      Scopes ``files.content.write files.content.read``.
                 Endpoints ``/oauth2/authorize`` and ``/oauth2/token``; content
                 operations on ``content.dropboxapi.com``. Paths are real paths,
                 so no id map is needed — the simplest of the three.
    Google Drive Scope ``https://www.googleapis.com/auth/drive.file``, which
                 grants access only to files this application created. Anything
                 broader would be inappropriate for a news archive.
                 Resumable upload for blobs over 5 MB. Needs the id map.
    OneDrive     Microsoft identity platform, scopes ``Files.ReadWrite.AppFolder
                 offline_access``. The app folder keeps the archive out of the
                 reader's own document tree. Upload sessions above 4 MB.

    A reader must be able to see, in the Settings screen, exactly which account
    is connected and revoke it in one click. That requirement is why
    ``describe()`` exists on the interface and why it is documented as
    containing no secrets.
"""
from __future__ import annotations

from collections.abc import Iterable

from mcpnews.storage.base import BlobStorage, Usage, register

_HOW_TO = ("Set blob.backend to 'local' in config/settings.yaml, or choose a local "
           "folder in the Storage section of the Settings screen.")


class _Unimplemented(BlobStorage):
    kind = "unimplemented"
    service = "this backend"
    #: OAuth backends need an interactive grant; S3 needs only static credentials.
    needs_oauth = False

    def __init__(self, *_args, **_kwargs):
        raise NotImplementedError(
            f"The {self.service} archive backend is not implemented in this release. {_HOW_TO}")

    def put(self, key: str, data: bytes, *, content_type: str = "application/octet-stream",
            metadata: dict[str, str] | None = None) -> str:
        raise NotImplementedError(self.service)

    def get(self, key: str) -> bytes:
        raise NotImplementedError(self.service)

    def exists(self, key: str) -> bool:
        raise NotImplementedError(self.service)

    def delete(self, key: str) -> None:
        raise NotImplementedError(self.service)

    def list(self, prefix: str = "") -> Iterable[str]:
        raise NotImplementedError(self.service)

    def usage(self) -> Usage:
        raise NotImplementedError(self.service)

    def describe(self) -> dict:
        return {"kind": self.kind, "implemented": False, "needs_oauth": self.needs_oauth}

    def health(self) -> tuple[bool, str]:
        return False, "err.generic"


@register("s3")
class S3Storage(_Unimplemented):
    kind = "s3"
    service = "S3-compatible object storage"
    needs_oauth = False


@register("dropbox")
class DropboxStorage(_Unimplemented):
    kind = "dropbox"
    service = "Dropbox"
    needs_oauth = True


@register("gdrive")
class GoogleDriveStorage(_Unimplemented):
    kind = "gdrive"
    service = "Google Drive"
    needs_oauth = True


@register("onedrive")
class OneDriveStorage(_Unimplemented):
    kind = "onedrive"
    service = "OneDrive"
    needs_oauth = True

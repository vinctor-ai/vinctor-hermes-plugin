from __future__ import annotations

import ipaddress
import posixpath
import re
from urllib.parse import urlparse


def normalize_path(path: str) -> str | None:
    if "\0" in path:
        return None
    stripped = path.strip().replace("\\", "/")
    while stripped.startswith("./"):
        stripped = stripped[2:]
    stripped = stripped.lstrip("/")
    normalized = posixpath.normpath(stripped)
    # PKA-190: `".."` had to be listed separately. `normpath` returns a bare
    # `".."` with no trailing slash for `..`, `/..` and anything that folds down
    # to it (`/a/../..`), so the `startswith("../")` check below sailed past all
    # three and this returned `".."` — emitted as the resource `repo/..`, which
    # names the parent of the tree while textually sitting inside it. The escape
    # is decided AFTER the fold for the same reason: `/a/../..` only escapes
    # once folded, so a check against the raw path would miss it.
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        return None
    return normalized


def _is_absolute_path(path: str) -> bool:
    return path.strip().replace("\\", "/").startswith("/")


def repo_or_secret_resource(path: str) -> str | None:
    normalized = normalize_path(path)
    if normalized is None:
        return None
    secret_kind = secret_kind_for_path(normalized)
    if secret_kind:
        return f"secret/{secret_kind}"
    # D-4: in-tree (relative) paths → repo/; external (absolute) paths → fs/.
    # `..`-escaping paths already return None from normalize_path (unmapped),
    # so the only "external" case reaching here is an absolute path.
    prefix = "fs" if _is_absolute_path(path) else "repo"
    return f"{prefix}/{normalized}"


def secret_kind_for_path(path: str) -> str | None:
    normalized = path.lower().replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    basename = parts[-1] if parts else normalized

    if basename == ".env" or basename.startswith(".env."):
        return "env"
    if ".ssh" in parts or basename in {"id_rsa", "id_ed25519", "known_hosts"}:
        return "ssh"
    if ".aws" in parts:
        return "aws"
    if ".config" in parts and "gcloud" in parts:
        return "gcp"
    if basename == "application_default_credentials.json":
        return "gcp"
    if ".azure" in parts:
        return "azure"
    if basename in {".netrc", "_netrc"}:
        return "netrc"
    if basename in {".npmrc", ".pypirc"}:
        return "package-registry"
    if ".kube" in parts and basename == "config":
        return "kube"
    if basename in {".git-credentials", ".gitconfig"}:
        return "git"
    if any(token in basename for token in ("secret", "secrets", "credential", "credentials")):
        return "app"
    return None


def network_resource_for_url(url: str) -> str | None:
    if "\0" in url:
        return None
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.hostname
    if not host:
        return None
    normalized_host = host.lower().strip(".")
    if not normalized_host:
        return None
    scope = "internal" if _is_internal_host(normalized_host) else "external"
    return f"net/{scope}/{normalized_host}"


def network_resource_for_urls(urls: list[str]) -> str | None:
    resources = []
    for url in urls:
        resource = network_resource_for_url(url)
        if resource is None:
            return None
        resources.append(resource)
    unique = sorted(set(resources))
    if not unique:
        return None
    if len(unique) == 1:
        return unique[0]
    scopes = {resource.split("/", 2)[1] for resource in unique}
    scope = scopes.pop() if len(scopes) == 1 else "mixed"
    return f"net/{scope}/multiple"


def safe_identifier(value: str, *, default: str | None = None) -> str | None:
    if "\0" in value:
        return None
    normalized = value.strip().replace("/", "-")
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"[^A-Za-z0-9._:-]", "-", normalized)
    normalized = normalized.strip(".-")
    if not normalized or normalized in {"..", "."}:
        return default
    return normalized


def _is_internal_host(host: str) -> bool:
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(address.is_private or address.is_loopback or address.is_link_local)

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.dependencies import current_user, get_store, require_admin
from app.store import (
    DEFAULT_ORGANIZATION_ID,
    MetadataStore,
    PolicyGroupRecord,
    UserRecord,
)


router = APIRouter(prefix="/api/scim/v2", tags=["scim"])

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"


@dataclass
class ScimActor:
    user_id: str | None
    organization_id: str
    auth_type: str


def _scim_actor(request: Request, store: MetadataStore = Depends(get_store)) -> ScimActor:
    authorization = request.headers.get("authorization") or ""
    scheme, _, token = authorization.partition(" ")
    configured_token = store.settings.scim_bearer_token
    if scheme.lower() == "bearer" and token:
        if configured_token and secrets.compare_digest(token, configured_token):
            return ScimActor(
                user_id=None,
                organization_id=DEFAULT_ORGANIZATION_ID,
                auth_type="bearer",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid SCIM bearer token",
        )
    user = require_admin(current_user(request))
    return ScimActor(
        user_id=user.id,
        organization_id=user.organization_id,
        auth_type="admin_session",
    )


def _primary_email(payload: dict[str, Any], fallback: str) -> str:
    emails = payload.get("emails")
    if isinstance(emails, list):
        for item in emails:
            if isinstance(item, dict) and item.get("primary") and item.get("value"):
                return str(item["value"])
        for item in emails:
            if isinstance(item, dict) and item.get("value"):
                return str(item["value"])
    return fallback


def _display_name(payload: dict[str, Any]) -> str | None:
    name = payload.get("name")
    if isinstance(name, dict):
        formatted = name.get("formatted")
        if formatted:
            return str(formatted)
        parts = [name.get("givenName"), name.get("familyName")]
        joined = " ".join(str(part) for part in parts if part)
        return joined or None
    display_name = payload.get("displayName")
    return str(display_name) if display_name else None


def _username_from_scim(user_name: str) -> str:
    base = user_name.split("@", 1)[0] if "@" in user_name else user_name
    username = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in base)
    return username.strip("-_") or f"scim-{secrets.token_hex(4)}"


def _scim_user(user: UserRecord) -> dict[str, Any]:
    return {
        "schemas": [SCIM_USER_SCHEMA],
        "id": user.id,
        "externalId": user.external_id,
        "userName": user.email,
        "name": {"formatted": user.full_name or user.username},
        "displayName": user.full_name or user.username,
        "emails": [{"value": user.email, "primary": True}],
        "active": user.is_active,
        "meta": {
            "resourceType": "User",
            "created": user.created_at.isoformat(),
            "location": f"/api/scim/v2/Users/{user.id}",
        },
    }


def _scim_group(store: MetadataStore, group: PolicyGroupRecord) -> dict[str, Any]:
    members = store.list_policy_group_members(group.id)
    return {
        "schemas": [SCIM_GROUP_SCHEMA],
        "id": group.id,
        "externalId": group.external_id,
        "displayName": group.name,
        "members": [
            {
                "value": member.user_id,
                "display": member.email or member.username or member.user_id,
                "$ref": f"/api/scim/v2/Users/{member.user_id}",
            }
            for member in members
        ],
        "meta": {
            "resourceType": "Group",
            "created": group.created_at.isoformat(),
            "lastModified": group.updated_at.isoformat(),
            "location": f"/api/scim/v2/Groups/{group.id}",
        },
    }


def _list_response(resources: list[dict[str, Any]], *, start_index: int, count: int) -> dict[str, Any]:
    return {
        "schemas": [SCIM_LIST_SCHEMA],
        "totalResults": len(resources),
        "startIndex": start_index,
        "itemsPerPage": min(count, len(resources)),
        "Resources": resources[start_index - 1 : start_index - 1 + count],
    }


def _visible_user(store: MetadataStore, actor: ScimActor, user_id: str) -> UserRecord:
    user = store.get_user(user_id)
    if user is None or user.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="SCIM user not found")
    return user


def _visible_group(
    store: MetadataStore, actor: ScimActor, group_id: str
) -> PolicyGroupRecord:
    group = store.get_policy_group(group_id)
    if group is None or group.organization_id != actor.organization_id:
        raise HTTPException(status_code=404, detail="SCIM group not found")
    return group


def _audit(
    store: MetadataStore,
    actor: ScimActor,
    *,
    action: str,
    target_type: str,
    target_id: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    safe_metadata = {
        "auth_type": actor.auth_type,
        "organization_id": actor.organization_id,
        **(metadata or {}),
    }
    store.record_audit(
        action=action,
        user_id=actor.user_id,
        target_type=target_type,
        target_id=target_id,
        metadata=safe_metadata,
    )


@router.get("/Users")
def list_users(
    startIndex: int = 1,
    count: int = 100,
    filter: str | None = None,
    actor: ScimActor = Depends(_scim_actor),
    store: MetadataStore = Depends(get_store),
) -> dict[str, Any]:
    q = None
    if filter:
        lowered = filter.lower()
        if lowered.startswith("username eq "):
            q = filter.split(" ", 2)[2].strip().strip('"')
    users, _total = store.list_users(
        q=q,
        organization_id=actor.organization_id,
        offset=0,
        limit=None,
    )
    return _list_response(
        [_scim_user(user) for user in users],
        start_index=max(1, startIndex),
        count=max(1, min(count, 500)),
    )


@router.post("/Users", status_code=201)
def create_user(
    payload: dict[str, Any],
    actor: ScimActor = Depends(_scim_actor),
    store: MetadataStore = Depends(get_store),
) -> dict[str, Any]:
    user_name = str(payload.get("userName") or "").strip()
    if not user_name:
        raise HTTPException(status_code=400, detail="userName is required")
    email = _primary_email(payload, user_name)
    try:
        user = store.register_user(
            email=email,
            username=_username_from_scim(user_name),
            full_name=_display_name(payload),
            password=secrets.token_urlsafe(24),
            organization_id=actor.organization_id,
            external_id=str(payload.get("externalId")) if payload.get("externalId") else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if payload.get("active") is False:
        user = store.set_user_active(
            user_id=user.id, is_active=False, updated_by=actor.user_id
        )
    _audit(store, actor, action="scim.user.create", target_type="user", target_id=user.id)
    return _scim_user(user)


@router.get("/Users/{user_id}")
def get_user(
    user_id: str,
    actor: ScimActor = Depends(_scim_actor),
    store: MetadataStore = Depends(get_store),
) -> dict[str, Any]:
    return _scim_user(_visible_user(store, actor, user_id))


def _apply_user_replace(
    store: MetadataStore,
    actor: ScimActor,
    user: UserRecord,
    value: dict[str, Any],
) -> UserRecord:
    email = _primary_email(value, str(value.get("userName") or user.email))
    updated = store.update_user_profile(
        user_id=user.id,
        email=email,
        username=(
            _username_from_scim(str(value["userName"]))
            if value.get("userName")
            else None
        ),
        full_name=_display_name(value),
        external_id=str(value.get("externalId")) if value.get("externalId") else None,
        updated_by=actor.user_id,
    )
    if "active" in value:
        updated = store.set_user_active(
            user_id=user.id,
            is_active=bool(value["active"]),
            updated_by=actor.user_id,
        )
    return updated


@router.put("/Users/{user_id}")
def update_user(
    user_id: str,
    payload: dict[str, Any],
    actor: ScimActor = Depends(_scim_actor),
    store: MetadataStore = Depends(get_store),
) -> dict[str, Any]:
    user = _visible_user(store, actor, user_id)
    updated = _apply_user_replace(store, actor, user, payload)
    _audit(store, actor, action="scim.user.update", target_type="user", target_id=user_id)
    return _scim_user(updated)


@router.patch("/Users/{user_id}")
def patch_user(
    user_id: str,
    payload: dict[str, Any],
    actor: ScimActor = Depends(_scim_actor),
    store: MetadataStore = Depends(get_store),
) -> dict[str, Any]:
    user = _visible_user(store, actor, user_id)
    operations = payload.get("Operations")
    if not isinstance(operations, list):
        raise HTTPException(status_code=400, detail="Operations is required")
    updated = user
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        op = str(operation.get("op") or "replace").lower()
        path = str(operation.get("path") or "").lower()
        value = operation.get("value")
        if op == "replace" and path == "active":
            updated = store.set_user_active(
                user_id=user_id,
                is_active=bool(value),
                updated_by=actor.user_id,
            )
        elif op == "replace" and isinstance(value, dict):
            updated = _apply_user_replace(store, actor, updated, value)
    _audit(store, actor, action="scim.user.patch", target_type="user", target_id=user_id)
    return _scim_user(updated)


@router.delete("/Users/{user_id}", status_code=204)
def deactivate_user(
    user_id: str,
    actor: ScimActor = Depends(_scim_actor),
    store: MetadataStore = Depends(get_store),
) -> Response:
    _visible_user(store, actor, user_id)
    store.set_user_active(user_id=user_id, is_active=False, updated_by=actor.user_id)
    _audit(store, actor, action="scim.user.deactivate", target_type="user", target_id=user_id)
    return Response(status_code=204)


@router.get("/Groups")
def list_groups(
    startIndex: int = 1,
    count: int = 100,
    actor: ScimActor = Depends(_scim_actor),
    store: MetadataStore = Depends(get_store),
) -> dict[str, Any]:
    groups = store.list_policy_groups(organization_id=actor.organization_id)
    return _list_response(
        [_scim_group(store, group) for group in groups],
        start_index=max(1, startIndex),
        count=max(1, min(count, 500)),
    )


def _sync_group_members(
    store: MetadataStore,
    actor: ScimActor,
    group_id: str,
    members: Any,
) -> None:
    if not isinstance(members, list):
        return
    desired = {
        str(member["value"])
        for member in members
        if isinstance(member, dict) and member.get("value")
    }
    current = {member.user_id for member in store.list_policy_group_members(group_id)}
    for user_id in desired - current:
        user = store.get_user(user_id)
        if user and user.organization_id == actor.organization_id:
            store.upsert_policy_group_member(
                group_id=group_id,
                user_id=user_id,
                role="viewer",
                added_by=actor.user_id,
            )
            _audit(
                store,
                actor,
                action="scim.group.member.add",
                target_type="policy_group",
                target_id=group_id,
                metadata={"member_user_id": user_id},
            )
    for user_id in current - desired:
        store.remove_policy_group_member(
            group_id=group_id,
            user_id=user_id,
            removed_by=actor.user_id,
        )
        _audit(
            store,
            actor,
            action="scim.group.member.remove",
            target_type="policy_group",
            target_id=group_id,
            metadata={"member_user_id": user_id},
        )


@router.post("/Groups", status_code=201)
def create_group(
    payload: dict[str, Any],
    actor: ScimActor = Depends(_scim_actor),
    store: MetadataStore = Depends(get_store),
) -> dict[str, Any]:
    display_name = str(payload.get("displayName") or "").strip()
    if not display_name:
        raise HTTPException(status_code=400, detail="displayName is required")
    try:
        group = store.create_policy_group(
            organization_id=actor.organization_id,
            name=display_name,
            external_id=str(payload.get("externalId")) if payload.get("externalId") else None,
            created_by=actor.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _sync_group_members(store, actor, group.id, payload.get("members"))
    _audit(store, actor, action="scim.group.create", target_type="policy_group", target_id=group.id)
    return _scim_group(store, group)


@router.get("/Groups/{group_id}")
def get_group(
    group_id: str,
    actor: ScimActor = Depends(_scim_actor),
    store: MetadataStore = Depends(get_store),
) -> dict[str, Any]:
    return _scim_group(store, _visible_group(store, actor, group_id))


@router.put("/Groups/{group_id}")
def update_group(
    group_id: str,
    payload: dict[str, Any],
    actor: ScimActor = Depends(_scim_actor),
    store: MetadataStore = Depends(get_store),
) -> dict[str, Any]:
    group = _visible_group(store, actor, group_id)
    updated = store.update_policy_group(
        group_id=group.id,
        name=str(payload.get("displayName")) if payload.get("displayName") else None,
        external_id=str(payload.get("externalId")) if payload.get("externalId") else None,
        updated_by=actor.user_id,
    )
    _sync_group_members(store, actor, group.id, payload.get("members"))
    _audit(store, actor, action="scim.group.update", target_type="policy_group", target_id=group_id)
    return _scim_group(store, updated)


@router.patch("/Groups/{group_id}")
def patch_group(
    group_id: str,
    payload: dict[str, Any],
    actor: ScimActor = Depends(_scim_actor),
    store: MetadataStore = Depends(get_store),
) -> dict[str, Any]:
    group = _visible_group(store, actor, group_id)
    operations = payload.get("Operations")
    if not isinstance(operations, list):
        raise HTTPException(status_code=400, detail="Operations is required")
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        op = str(operation.get("op") or "replace").lower()
        path = str(operation.get("path") or "").lower()
        value = operation.get("value")
        if op == "replace" and path in {"displayname", ""} and isinstance(value, str):
            group = store.update_policy_group(
                group_id=group.id,
                name=value,
                updated_by=actor.user_id,
            )
        elif op in {"add", "replace"} and path in {"members", ""}:
            if op == "replace":
                _sync_group_members(store, actor, group.id, value)
            elif isinstance(value, list):
                for member in value:
                    if not isinstance(member, dict) or not member.get("value"):
                        continue
                    user_id = str(member["value"])
                    user = store.get_user(user_id)
                    if user and user.organization_id == actor.organization_id:
                        store.upsert_policy_group_member(
                            group_id=group.id,
                            user_id=user_id,
                            role="viewer",
                            added_by=actor.user_id,
                        )
        elif op == "remove" and path.startswith("members"):
            if isinstance(value, list):
                user_ids = [
                    str(member["value"])
                    for member in value
                    if isinstance(member, dict) and member.get("value")
                ]
            else:
                user_ids = [str(value)] if value else []
            for user_id in user_ids:
                store.remove_policy_group_member(
                    group_id=group.id,
                    user_id=user_id,
                    removed_by=actor.user_id,
                )
    _audit(store, actor, action="scim.group.patch", target_type="policy_group", target_id=group_id)
    return _scim_group(store, group)

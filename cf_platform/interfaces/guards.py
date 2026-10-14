"""Tenant guards — every run- and project-scoped route answers only for its owner (P-AUTH S3, F2).

Two layers, both fail closed:

* :func:`enforce_scope` is a *router-level* dependency. It reads ``run_id`` and
  ``project_id`` from the matched path, so a route cannot be added without it and
  forget the ownership check.
  It also checks a ``run_id`` named in a JSON request **body** (the worker routes,
  idea-to-script), so those are covered without each route repeating the call.
* :func:`require_run` / :func:`require_project` / :func:`ensure_run` are for the
  few places that find a run id some other way.

A run or project that belongs to someone else answers **404**, the same as one that
does not exist — the response never confirms that an id is real.

A run with no ``runs`` row is one made before accounts existed (a Studio run known
only to a browser): only the owner's tenant may use it. Every run a signed-in user
creates through the platform has a row, so for anyone else "no row" means "not yours".
"""

from fastapi import Depends, HTTPException, Request

from cf_platform.core.accounts import OWNER_TENANT_ID, Principal
from cf_platform.core.projects import ProjectNotFoundError
from cf_platform.core.run_manager import RunNotFoundError
from cf_platform.interfaces.dependencies import current_user, get_project_repository, get_run_repository


def _repo(request: Request, dependency):
    """Resolve a repository dependency, honouring test overrides."""
    return request.app.dependency_overrides.get(dependency, dependency)()


def _not_found(what: str, ident: str) -> HTTPException:
    """The one answer for 'not yours' and 'not there'."""
    return HTTPException(status_code=404, detail=f"{what} not found: {ident}")


async def require_run(run_id: str, runs, principal: Principal) -> None:
    """Raise 404 unless run_id belongs to principal's tenant (or is an unregistered owner run)."""
    try:
        record = await runs.get(run_id)
    except RunNotFoundError:
        if principal.tenant_id == OWNER_TENANT_ID:
            return
        raise _not_found("Run", run_id) from None
    owner = record.tenant_id or record.user_id
    if owner != principal.tenant_id:
        raise _not_found("Run", run_id)


async def require_project(project_id: str, projects, principal: Principal) -> None:
    """Raise 404 unless project_id belongs to principal's tenant."""
    try:
        project = await projects.get(project_id)
    except ProjectNotFoundError:
        raise _not_found("Project", project_id) from None
    if project.tenant_id != principal.tenant_id:
        raise _not_found("Project", project_id)


async def enforce_scope(request: Request, principal: Principal = Depends(current_user)) -> None:
    """Router-level guard: check ownership of whatever ``run_id`` / ``project_id`` the path names."""
    params = request.path_params
    run_id = params.get("run_id")
    if run_id:
        await require_run(run_id, _repo(request, get_run_repository), principal)
    project_id = params.get("project_id")
    if project_id:
        await require_project(project_id, _repo(request, get_project_repository), principal)
    # A run named in a JSON body (the worker routes, idea-to-script, asset-from-run).
    if request.method in {"POST", "PUT", "PATCH"} and "application/json" in request.headers.get("content-type", ""):
        try:
            body = await request.json()
        except Exception:
            body = None
        body_run = body.get("run_id") if isinstance(body, dict) else None
        if isinstance(body_run, str) and body_run and body_run != run_id:
            await require_run(body_run, _repo(request, get_run_repository), principal)


def require_owner(principal: Principal = Depends(current_user)) -> Principal:
    """Dependency: only the owner's tenant (the legacy pipeline and bucket-wide routes)."""
    if principal.tenant_id != OWNER_TENANT_ID:
        raise HTTPException(status_code=403, detail="Owner only.")
    return principal


async def ensure_run(run_id: str, runs) -> None:
    """require_run for the signed-in principal — for routes that read run_id from the body."""
    from cf_platform.core.accounts import NotAuthenticatedError, current_principal

    try:
        principal = current_principal()
    except NotAuthenticatedError:
        raise HTTPException(status_code=401, detail="Unauthorized") from None
    await require_run(run_id, runs, principal)

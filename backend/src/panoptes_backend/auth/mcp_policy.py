"""Fail-closed MCP authorization, shared by API endpoints and SQL list filters."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from .mcp_models import MCPPermissions


def deny():
    raise HTTPException(403, "A chave MCP não permite esta operação ou este recurso.")


def key_for(session):
    info = getattr(session, "info", {})
    return info.get("mcp_key") if isinstance(info, dict) else None


def term_scope(alias="t"):
    return f"""({alias}.site=ANY(CAST(:mcp_sites AS text[])) AND (
      EXISTS (SELECT 1 FROM auth.mcp_key_term kt WHERE kt.key_id=:mcp_key AND kt.term_id={alias}.id)
      OR EXISTS (SELECT 1 FROM scraping.routine_search_term rt
        JOIN auth.mcp_key_routine kr ON kr.routine_id=rt.routine_id
        WHERE kr.key_id=:mcp_key AND rt.search_term_id={alias}.id)))"""


def entity_scope(alias="e"):
    return f"""({alias}.site=ANY(CAST(:mcp_sites AS text[])) AND EXISTS (
      SELECT 1 FROM scraping.search_term_entity se JOIN scraping.search_term mt ON mt.id=se.search_term_id
      WHERE se.entity_id={alias}.id AND {term_scope("mt")}))"""


def request_scope(alias="r"):
    return f"""((({alias}.routine_public_id IS NOT NULL AND EXISTS (
      SELECT 1 FROM auth.mcp_key_routine kr JOIN scraping.scheduled_routine mr ON mr.id=kr.routine_id
      WHERE kr.key_id=:mcp_key AND mr.public_id={alias}.routine_public_id))
      OR ({alias}.routine_public_id IS NULL AND (
        EXISTS (SELECT 1 FROM scraping.search_term mt WHERE mt.id={alias}.search_term_id AND {term_scope("mt")})
        OR EXISTS (SELECT 1 FROM scraping.tracking_target tt JOIN scraping.entity me ON me.id=tt.entity_id
          WHERE tt.id={alias}.tracking_target_id AND {entity_scope("me")}))))
      AND coalesce(t.site,e.site)=ANY(CAST(:mcp_sites AS text[])))"""


def bindings(key):
    return {"mcp_key": key["id"], "mcp_sites": key["permissions"].get("sites", [])}


def observation_scope(alias="o"):
    # An entity may be shared by several routines. Authorize the capture's
    # originating request as well, rather than exposing all of its history.
    return f"""EXISTS (SELECT 1 FROM scraping.job mj
      JOIN scraping.scrape_request mreq ON mreq.id=mj.scrape_request_id
      LEFT JOIN scraping.search_term t ON t.id=mreq.search_term_id
      LEFT JOIN scraping.tracking_target mtarget ON mtarget.id=mreq.tracking_target_id
      LEFT JOIN scraping.entity e ON e.id=mtarget.entity_id
      WHERE mj.id={alias}.job_id AND {request_scope("mreq")})"""


def pricing_scope(alias="o"):
    return f"""EXISTS (SELECT 1 FROM scraping.observation msource
      WHERE msource.id={alias}.source_observation_id AND {observation_scope("msource")})"""


def scoped_clause(session, predicate):
    key = key_for(session)
    return (" AND " + predicate, bindings(key)) if key else ("", {})


async def check_resource(session, key, kind, public_id):
    try:
        public_id = UUID(str(public_id))
    except (ValueError, TypeError):
        deny()
    queries = {
        "term": f"SELECT 1 FROM scraping.search_term t WHERE t.public_id=:pid AND {term_scope()}",
        "entity": f"SELECT 1 FROM scraping.entity e WHERE e.public_id=:pid AND {entity_scope()}",
        "routine": """SELECT 1 FROM auth.mcp_key_routine kr
          JOIN scraping.scheduled_routine r ON r.id=kr.routine_id
          WHERE kr.key_id=:mcp_key AND r.public_id=:pid
          AND NOT EXISTS (SELECT 1 FROM scraping.routine_search_term rt
            JOIN scraping.search_term st ON st.id=rt.search_term_id
            WHERE rt.routine_id=r.id AND NOT(st.site=ANY(CAST(:mcp_sites AS text[]))))""",
        "request": f"""SELECT 1 FROM scraping.scrape_request r
          LEFT JOIN scraping.search_term t ON t.id=r.search_term_id
          LEFT JOIN scraping.tracking_target tt ON tt.id=r.tracking_target_id
          LEFT JOIN scraping.entity e ON e.id=tt.entity_id
          WHERE r.public_id=:pid AND {request_scope()}""",
        "offer": f"""SELECT 1 FROM pricing.offer f JOIN catalog.listing l ON l.id=f.listing_id
          JOIN scraping.entity e ON e.id=l.entity_id WHERE f.public_id=:pid AND {entity_scope()}""",
        "webhook": "SELECT 1 FROM alerting.webhook WHERE public_id=:pid AND mcp_key_id=:mcp_key",
    }
    found = (
        await session.execute(text(queries[kind]), {**bindings(key), "pid": public_id})
    ).first()
    if not found:
        deny()


def check_sites(key, sites):
    if not sites or not set(sites).issubset(key["permissions"].get("sites", [])):
        deny()


async def authorize(request, session, user):
    key = user["mcp_key"]
    path, method = request.url.path.rstrip("/"), request.method
    # Issuing other keys always requires a browser session, even for MCP admin.
    if path.startswith("/auth/mcp-keys"):
        deny()
    if key["admin"]:
        return
    permissions = MCPPermissions.model_validate(key["permissions"])
    if path == "/auth/me":
        return
    if method == "GET" and (
        path in {"/sources", "/categories", "/catalog/taxonomy"}
        or path.startswith("/contracts")
    ):
        return
    parts = path.strip("/").split("/")
    try:
        data = (
            await request.json()
            if method in {"POST", "PUT", "PATCH"} and await request.body()
            else {}
        )
    except ValueError:
        raise HTTPException(422, "JSON inválido.") from None
    if not isinstance(data, dict):
        deny()
    if parts[0] == "routines":
        if method == "GET" and len(parts) == 1:
            return  # SQL filters before pagination.
        if len(parts) > 1:
            await check_resource(session, key, "routine", parts[1])
        if method == "GET":
            return
        if method == "POST" and len(parts) == 2 + 1 and parts[-1] == "advance":
            if not permissions.create_extractions:
                deny()
            return
        if method == "POST" and len(parts) == 1:
            if not permissions.create_routines:
                deny()
            await check_resource(session, key, "term", data.get("search_term_id"))
        elif not permissions.manage_routines:
            deny()
        if data.get("sites"):
            check_sites(key, data["sites"])
        return
    if parts[0] == "search-terms":
        if method == "POST" and (len(parts) == 1 or parts[1] == "batch"):
            if not permissions.create_extractions:
                deny()
            check_sites(key, data.get("sites", [data.get("site", "amazon_br")]))
            return
        if len(parts) > 1:
            await check_resource(session, key, "term", parts[1])
        if method == "GET":
            if not permissions.view_extractions:
                deny()
            return
        if method == "POST" and parts[-1] in {"discover", "discover-sources"}:
            if not permissions.create_extractions:
                deny()
            if parts[-1] == "discover-sources":
                from panoptes_contracts.sources import SOURCES

                sites = data.get("sites", "all")
                check_sites(key, list(SOURCES) if sites == "all" else sites)
            return
    if parts[0] == "products" and len(parts) > 2:
        await check_resource(session, key, "entity", parts[1])
        if method == "GET" and permissions.view_extractions:
            return
        if (
            method == "POST"
            and parts[-1] == "refresh"
            and permissions.create_extractions
        ):
            return
    if method == "GET" and permissions.view_extractions:
        if path in {"/scrape-requests", "/extraction-groups"}:
            return
        if parts[0] == "scrape-requests" and len(parts) > 1:
            await check_resource(session, key, "request", parts[1])
            return
        if parts[0] == "offers" and len(parts) == 3:
            await check_resource(session, key, "offer", parts[1])
            return
        if path in {
            "/products/search",
            "/analytics/prices",
            "/analytics/prices/dashboard",
            "/analytics/detail",
        }:
            # Aggregate endpoints require an explicit authorized term; global aggregates are admin-only.
            await check_resource(
                session, key, "term", request.query_params.get("term_id")
            )
            return
    if path.startswith("/alerts/webhooks") and permissions.create_alerts:
        if len(parts) > 2:
            await check_resource(session, key, "webhook", parts[2])
            # Recheck routine grants on every read/update, including deliveries.
            rules = (
                await session.execute(
                    text("SELECT rules FROM alerting.webhook WHERE public_id=:pid"),
                    {"pid": UUID(parts[2])},
                )
            ).scalar_one()
            await check_rules(session, key, rules)
        if method in {"POST", "PUT"}:
            await check_rules(session, key, data.get("rules", []))
        return
    deny()


async def check_rules(session, key, rules):
    if not rules:
        deny()
    for rule in rules:
        if not rule.get("routine_ids"):
            deny()
        for rid in rule["routine_ids"]:
            await check_resource(session, key, "routine", rid)
        if rule.get("entity_id"):
            await check_resource(session, key, "entity", rule["entity_id"])


async def grant_term(session, term_id):
    key = key_for(session)
    if key:
        await session.execute(
            text("""INSERT INTO auth.mcp_key_term(key_id,term_id)
          SELECT :kid,id FROM scraping.search_term WHERE public_id=:pid ON CONFLICT DO NOTHING"""),
            {"kid": key["id"], "pid": term_id},
        )


async def reserve_routine(session):
    key = key_for(session)
    if not key:
        return
    # Keep the lock until the routine and its grant commit to prevent quota races.
    await session.execute(
        text("SELECT id FROM auth.mcp_key WHERE id=:kid FOR UPDATE"), {"kid": key["id"]}
    )
    total = (
        await session.execute(
            text("""SELECT count(*) FROM auth.mcp_key_routine
      WHERE key_id=:kid AND created_by_key"""),
            {"kid": key["id"]},
        )
    ).scalar_one()
    maximum = key["permissions"].get("max_routines", 0)
    if maximum is not None and total >= maximum:
        raise HTTPException(403, "Limite de rotinas desta chave MCP atingido.")


async def grant_routine(session, routine_id):
    key = key_for(session)
    if key:
        await session.execute(
            text("""INSERT INTO auth.mcp_key_routine(key_id,routine_id,created_by_key)
          SELECT :kid,id,true FROM scraping.scheduled_routine WHERE public_id=:pid"""),
            {"kid": key["id"], "pid": routine_id},
        )

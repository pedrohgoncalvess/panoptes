from datetime import UTC, datetime
from uuid import uuid4

from panoptes_contracts.schedules import next_run

from ..catalog.repository import find_term, routine_sources
from ..core.errors import ConflictError, NotFoundError
from . import repository


async def read(session, public_id):
    row = await repository.read(session, public_id)
    if row is None:
        raise NotFoundError("Routine not found")
    return row


async def create(session, value):
    from ..auth.mcp_policy import check_sites, grant_routine, key_for, reserve_routine

    await reserve_routine(session)
    term = await find_term(session, value.search_term_id)
    if term is None:
        raise NotFoundError("Search term not found")
    if key_for(session):
        check_sites(
            key_for(session), value.sites if value.sites is not None else [term["site"]]
        )
    term_ids = await selected_terms(
        session,
        value.search_term_id,
        value.sites if value.sites is not None else [term["site"]],
    )
    public_id = uuid4()
    upcoming = next_run(value.schedule, datetime.now(UTC), str(public_id))
    await repository.insert(session, value, term["id"], public_id, upcoming)
    await repository.set_terms(session, public_id, term_ids)
    await grant_routine(session, public_id)
    return await read(session, public_id)


async def update(session, public_id, value):
    row = await read(session, public_id)
    term_ids = (
        await selected_terms(session, row["search_term_id"], value.sites)
        if value.sites is not None
        else None
    )
    upcoming = next_run(value.schedule, datetime.now(UTC), str(public_id))
    await repository.update(session, public_id, value, upcoming)
    if term_ids is not None:
        await repository.set_terms(session, public_id, term_ids)
    return await read(session, public_id)


async def selected_terms(session, term_id, sites):
    available = await routine_sources(session, term_id)
    by_site = {row["site"]: row["id"] for row in available}
    if not sites or not set(sites).issubset(by_site):
        raise ConflictError("Selecione pelo menos um marketplace da primeira extração.")
    return [by_site[site] for site in dict.fromkeys(sites)]


async def delete(session, public_id):
    await read(session, public_id)
    await repository.delete(session, public_id)


async def advance(session, public_id, value):
    await read(session, public_id)
    if await repository.advance(session, public_id, value.next_run_at) is None:
        raise ConflictError(
            "A agenda mudou, está pausada ou já foi liberada. Atualize a lista."
        )
    return await read(session, public_id)

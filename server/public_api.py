"""Versioned external API and authenticated, self-hosted usage guide."""
from typing import Literal
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator
from optimizer.specs import Spec
from optimizer.catalog import PRESETS
from . import api_access, model_catalog, meta_ai, modal_worker


class APIRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID = Field(default_factory=uuid4, description='Reuse this UUID for retries of the same input while the job is retained. Do not reuse it for another operation or input.')
    question: str | None = Field(default=None, min_length=1, max_length=12000)
    spec: Spec | None = None
    language: Literal['en', 'es', 'fr', 'de'] = 'en'
    model: str | None = Field(default=None, min_length=1, max_length=100,
                              description='Optional configured model ID from /api/v1/info. Both comparison paths use this model.')

    @model_validator(mode='after')
    def input_mode(self):
        if (self.question is None) == (self.spec is None):
            raise ValueError('Provide exactly one of question or spec.')
        if self.question is not None and not self.question.strip():
            raise ValueError('A question must contain text.')
        return self


def service_info():
    try:
        selected = model_catalog.resolve()
        model = {'id': selected['id'], 'label': selected['label']}
    except model_catalog.ModelSelectionError:
        model = None
    return {'api_version': 'v1', 'api_status': api_access.configuration_status(),
            'model': model, 'models': model_catalog.public_catalog(),
            'meta_configured': meta_ai.configured(), 'optimizer_available': modal_worker.configured(),
            'limits': api_access.limits(), 'max_binary_decisions': 64}


def envelope(job):
    # Job snapshots already exclude private fields. Links are relative to this service.
    key = job['id']
    return {'api_version': 'v1', **job, 'links': {'self': f'/api/v1/jobs/{key}',
            'cancel': f'/api/v1/jobs/{key}/cancel'}}


def install(app, submit, get_job, cancel):
    bearer = HTTPBearer(auto_error=False, scheme_name='AIPlusKey',
                        description='Your own AI_PLUS_API_KEY or a named client key from Render. Never use your Fireworks or Modal key.')
    router = APIRouter(prefix=api_access.PREFIX, dependencies=[Depends(bearer)], tags=['AI+ API'])

    async def create(body, request, operation):
        job = await submit(body, request, operation=operation, channel='api')
        return JSONResponse(envelope(job), status_code=202,
                            headers={'Location': f"/api/v1/jobs/{job['id']}", 'Retry-After': '2'})

    @router.post('/solve', status_code=202, summary='Run only AI with its optional optimizer')
    async def solve(body: APIRequest, request: Request):
        return await create(body, request, 'solve')

    @router.post('/compare', status_code=202, summary='Compare direct AI with the assisted path')
    async def compare(body: APIRequest, request: Request):
        return await create(body, request, 'compare')

    @router.get('/jobs/{job_id}', summary='Read a job owned by this API key')
    async def status(job_id: UUID, request: Request):
        return envelope(await get_job(job_id.hex, request))

    @router.post('/jobs/{job_id}/cancel', status_code=202, summary='Request cancellation of your job')
    async def stop(job_id: UUID, request: Request):
        return JSONResponse(envelope(await cancel(job_id.hex, request)), status_code=202)

    @router.get('/info', summary='Configuration and service limits; no inference is run')
    async def info():
        return service_info()

    @router.get('/examples', summary='The same numerical examples as the website; no inference is run')
    async def examples():
        return {'examples': [{'id': p['id'], 'description': p['prompts']['en'], 'spec': p['spec']} for p in PRESETS]}

    def schema():
        document = get_openapi(title='AI+ API', version='1.1.0',
            routes=[route for route in app.routes if getattr(route, 'path', '').startswith('/api/v1/')],
            description='Asynchronous text, optimization and media comparisons. Bearer authentication is required. Poll every 2 seconds. Jobs are transient. Models and GPU tools can incur provider charges.')
        for path, operations in document['paths'].items():
            if path.startswith('/api/v1/media/'):
                for operation in operations.values():
                    operation['security'] = [{'AIPlusKey': []}]
        return document

    @router.get('/openapi.json', include_in_schema=False)
    async def api_schema():
        return JSONResponse(schema())

    app.include_router(router)

    @app.get('/api/service-info', include_in_schema=False)
    async def guide_info():
        return service_info()

    @app.get('/api/service-schema', include_in_schema=False)
    async def guide_schema():
        return JSONResponse(schema())

"""Render web gateway for a real AI versus AI with tools comparison."""
import asyncio
from collections import deque
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time
from typing import Literal
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse, RedirectResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator
from optimizer.catalog import CATEGORIES, PRESETS
from optimizer.specs import Spec, resolve_input, InputError
from . import meta_ai, model_catalog, modal_worker, benchmark, questions, access, api_access, public_api, solving, datasets, media
from .protocol import SCHEMA, MAX_BITS, canonical, prepare

ROOT = Path(__file__).resolve().parents[1]
SESSION_KEY = os.getenv('SESSION_SECRET') or secrets.token_hex(32)
JOBS, PLANS, RECENT, LISTENERS = {}, {}, {}, {}
DATASETS = {}
ACTIVE = None
PLANNING = False
TERMINAL = {'completed', 'failed', 'cancelled'}


class TextRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question: str = Field(min_length=1, max_length=100000)
    language: Literal['en', 'es', 'fr', 'de'] = 'en'
    model: str | None = Field(default=None, min_length=1, max_length=100)


class RunRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    output_format: Literal['text', 'csv'] = 'text'
    spec: Spec | None = None
    question: str | None = Field(default=None, min_length=1, max_length=12000)
    language: Literal['en', 'es', 'fr', 'de'] = 'en'
    plan_id: UUID | None = None
    model: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode='after')
    def input_mode(self):
        if (self.spec is None) == (self.question is None):
            raise ValueError('Provide either a numerical spec or a question.')
        if self.question is not None and (not self.question.strip() or self.plan_id is not None):
            raise ValueError('A question must contain text and cannot use a numerical plan.')
        if self.output_format == 'csv' and self.question is None:
            raise ValueError('CSV response format requires a question; numerical CSV is generated from the confirmed plan.')
        return self


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    password: str = Field(min_length=1, max_length=256)


def sign(value):
    return hmac.new(SESSION_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def rate_many(rules):
    now = time.monotonic()
    queues = []
    for key, limit, window in rules:
        if key not in RECENT and len(RECENT) > 2048:
            RECENT.pop(next(iter(RECENT)))
        q = RECENT.setdefault(key, deque())
        while q and now - q[0] >= window:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(429, 'rate_limit', headers={
                'Retry-After': str(max(1, int(window - (now - q[0])) + 1))})
        queues.append(q)
    for q in queues:
        q.append(now)


def rate(key, limit, window=60):
    rate_many([(key, limit, window)])


def snapshot(job):
    return {k: v for k, v in job.items() if not k.startswith('_')}


def lookup(request, key):
    job = JOBS.get(key)
    if job and job['status'] in TERMINAL and time.monotonic() - job['_started'] > api_access.JOB_TTL:
        JOBS.pop(key, None)
        job = None
    if not job or job['_owner'] != request.state.owner:
        raise HTTPException(404, 'job_expired')
    return job


def update_job(key, **changes):
    job = JOBS[key]
    if job['status'] in TERMINAL:
        return
    job.update(changes)
    job['gateway_elapsed_ms'] = (time.monotonic() - job['_started']) * 1000
    for queue in tuple(LISTENERS.get(key, ())):
        if queue.empty():
            queue.put_nowait(True)


async def run_job(key):
    global ACTIVE
    job = JOBS[key]
    try:
        async with asyncio.timeout(400):
            def publish(**kw):
                if job.get('_workspace') and kw.get('partial'):
                    datasets.decorate(kw['partial'],job['_workspace'])
                update_job(key, **kw)
            if job['mode'] == 'media':
                result = await media.compare(job, publish)
            elif job.get('operation') == 'solve':
                result = await solving.solve(job['spec'], job['question'], publish, job['_config'], job['_optimizer_available'])
            elif job['mode'] == 'question':
                result = await questions.compare(job['question'], publish, job['_config'], job['_optimizer_available'], output_format=job.get('output_format', 'text'))
            else:
                result = await benchmark.compare(job['spec'], publish, job['_plan'], job['_config'])
            if job.get('_workspace'):
                datasets.decorate(result,job['_workspace'])
        if job.get('operation') == 'solve' and result['engine']['status'] == 'failed':
            update_job(key, status='failed', stage='failed', error=result['engine']['error'], result=result)
        else:
            update_job(key, status='completed', stage='completed', result=result)
    except asyncio.CancelledError:
        update_job(key, status='cancelled', stage='cancelled')
    except TimeoutError:
        update_job(key, status='failed', stage='job_timeout', error='job_timeout')
    except Exception:
        update_job(key, status='failed', stage='failed', error='compute_failed')
    finally:
        if job.get('mode') == 'media':
            job.pop('_media_input', None)
        if ACTIVE == key:
            ACTIVE = None


@asynccontextmanager
async def lifespan(app):
    access.require_configuration()
    yield
    pending = [j['_task'] for j in JOBS.values() if j['status'] not in TERMINAL]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


app = FastAPI(title='AI+', lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware('http')
async def session(request: Request, call_next):
    external = request.url.path == api_access.PREFIX or request.url.path.startswith(api_access.PREFIX + '/')
    if external:
        try:
            request.state.owner = api_access.authenticate(request.headers.get('authorization', ''))
            rate(request.state.owner + '-http', api_access.READS_PER_MINUTE)
        except HTTPException as exc:
            return JSONResponse({'detail': exc.detail}, exc.status_code,
                headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', **(exc.headers or {})})
    parts = request.cookies.get('mq_session', '').split('.')
    valid = len(parts) == 2 and len(parts[0]) == 32 and hmac.compare_digest(sign(parts[0]).encode(), parts[1].encode())
    sid = parts[0] if valid else uuid4().hex
    if not external:
        request.state.owner = sid
    if request.method == 'POST':
        if not external and request.headers.get('x-metaquant-request') != '1':
            return JSONResponse({'detail': 'invalid_request'}, 403)
        if (not external or request.url.path.rstrip('/').endswith(('/solve', '/compare'))) and request.headers.get('content-type', '').split(';')[0].lower() != 'application/json':
            return JSONResponse({'detail': 'invalid_request'}, 415)
        length = request.headers.get('content-length', '')
        body_limit = 5_700_000 if request.url.path in ('/api/media/jobs', '/api/v1/media/compare') else 150000
        if length.isdigit() and int(length) > body_limit:
            return JSONResponse({'detail': 'input_too_large'}, 413)
        chunks, received = [], 0
        async for chunk in request.stream():
            received += len(chunk)
            if received > body_limit:
                return JSONResponse({'detail': 'input_too_large'}, 413)
            chunks.append(chunk)
        request._body = b''.join(chunks)
    public_paths = {'/health', '/login', '/login.js', '/mark.svg', '/favicon-ai-plus.svg', '/style.css', '/api/login'}
    authenticated = access.valid(request.cookies.get(access.COOKIE, ''), SESSION_KEY)
    if request.url.path not in public_paths and not authenticated and not external:
        if request.url.path.startswith('/api/'):
            return JSONResponse({'detail': 'authentication_required'}, 401)
        return RedirectResponse('/login', status_code=303)
    response = await call_next(request)
    if not valid and not external:
        response.set_cookie('mq_session', sid + '.' + sign(sid), httponly=True,
                            samesite='strict', secure=True, max_age=86400)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    if request.url.path in ('/', '/login'):
        response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


@app.get('/login')
async def login_page(request: Request):
    if access.valid(request.cookies.get(access.COOKIE, ''), SESSION_KEY):
        return RedirectResponse('/', status_code=303)
    return FileResponse(ROOT / 'dist' / 'login.html')


@app.post('/api/login')
async def login(body: LoginRequest, request: Request):
    rate('login-global', 30)
    rate('login-ip-' + (request.client.host if request.client else 'unknown'), 8)
    if not access.matches(body.password):
        raise HTTPException(401, 'incorrect_password')
    response = JSONResponse({'ok': True})
    response.set_cookie(access.COOKIE, access.issue(SESSION_KEY), httponly=True,
                        secure=True, samesite='strict', max_age=access.TTL, path='/')
    return response


@app.post('/api/logout')
async def logout(request: Request):
    for job in JOBS.values():
        if job['_owner'] == request.state.owner and job['status'] not in TERMINAL:
            job['_task'].cancel()
    response = JSONResponse({'ok': True})
    response.delete_cookie(access.COOKIE, path='/', secure=True, httponly=True, samesite='strict')
    response.delete_cookie('mq_session', path='/', secure=True, httponly=True, samesite='strict')
    return response


@app.get('/health')
async def health():
    return {'status': 'ok', 'version': SCHEMA}


@app.get('/api/info')
async def info():
    try:
        default_model = model_catalog.default_id()
    except model_catalog.ModelSelectionError:
        default_model = None
    return {'version': SCHEMA, 'gpu_configured': modal_worker.configured(),
            'meta_configured': meta_ai.configured(), 'categories': CATEGORIES, 'presets': PRESETS,
            'model': os.getenv('META_MODEL', meta_ai.DEFAULT_MODEL),
            'default_model': default_model, 'models': model_catalog.public_catalog(),
            'reasoning_effort': os.getenv('META_REASONING_EFFORT', 'low'),
            'busy': ACTIVE is not None, 'streaming': True, 'max_bits': MAX_BITS,
            'storage': 'Transient; export results before a service restart.'}


@app.post('/api/plan')
async def plan(body: TextRequest, request: Request):
    global PLANNING
    rate('ai-global', 10)
    rate(request.state.owner + '-ai', 5)
    if PLANNING:
        raise HTTPException(429, 'busy', headers={'Retry-After': '2'})
    PLANNING = True
    try:
        start = time.perf_counter()
        config = meta_ai.configuration(body.model)
        proposal = await meta_ai.formulate(body.question, body.language, config)
        if proposal['status'] == 'ready':
            if len(PLANS) >= 20:
                PLANS.pop(next(iter(PLANS)))
            key = uuid4().hex
            PLANS[key] = {'owner': request.state.owner, 'spec': proposal['spec'], 'created': time.monotonic(),
                          'meta': proposal['meta'], 'model_configuration': config.public(),
                          'elapsed_ms': (time.perf_counter() - start) * 1000}
            proposal['plan_id'] = key
        return proposal
    except meta_ai.AIError as exc:
        raise HTTPException(422, exc.detail()) from None
    finally:
        PLANNING = False


@app.post('/api/validate')
async def validate(body: TextRequest):
    try:
        spec, adapter = resolve_input(body.question)
        prepare(spec.model_dump(exclude_none=True))
        return {'spec': spec.model_dump(exclude_none=True), 'source': adapter['source']}
    except InputError as exc:
        raise HTTPException(422, {'code': str(exc), 'issues': exc.issues}) from None
    except ValueError:
        raise HTTPException(422, 'comparison_size_limit') from None


@app.post('/api/jobs')
async def submit(body: RunRequest, request: Request):
    return await submit_job(body, request)


async def submit_job(body, request, operation='compare', channel='web'):
    global ACTIVE
    optimizer_available = modal_worker.configured()
    if body.spec is not None and not optimizer_available:
        raise HTTPException(503, 'gpu_not_configured')
    try:
        config = meta_ai.configuration(body.model)
        if config.modality != 'text':
            raise meta_ai.AIError('model_requires_media_workspace')
    except meta_ai.AIError as exc:
        raise HTTPException(422, exc.detail()) from None
    output_format = getattr(body, 'output_format', 'text')
    key = body.request_id.hex
    spec = body.spec.model_dump(exclude_none=True) if body.spec is not None else None
    if key in JOBS:
        job = lookup(request, key)
        if (job['spec'] != spec or job.get('question') != body.question
            or job.get('output_format', 'text') != output_format
            or job.get('operation', 'compare') != operation or job.get('_channel', 'web') != channel
            or job['_language'] != body.language or job['_config'].public() != config.public()
            or job.get('_plan_id') != (getattr(body,'plan_id',None).hex if getattr(body,'plan_id',None) else None)):
            raise HTTPException(409, 'request_id_conflict')
        return snapshot(job)
    if ACTIVE:
        raise HTTPException(429, 'busy', headers={'Retry-After': '2'})
    try:
        if spec is not None:
            prepare(spec)
    except ValueError:
        raise HTTPException(422, 'comparison_size_limit') from None
    shared_plan = None
    plan_id = getattr(body, 'plan_id', None)
    if plan_id:
        record = PLANS.get(plan_id.hex)
        if not record or record['owner'] != request.state.owner or time.monotonic() - record['created'] > 3600:
            raise HTTPException(422, 'plan_expired')
        if canonical(record['spec']) != canonical(spec):
            raise HTTPException(422, 'plan_mismatch')
        if record['model_configuration'] != config.public():
            raise HTTPException(422, 'plan_model_mismatch')
        shared_plan = {'elapsed_ms': record['elapsed_ms'], 'evidence': record['meta']}
    rules = [('runs-global', 8, 60), (request.state.owner + '-run', api_access.PER_MINUTE, 60)]
    if channel == 'api':
        rules.extend([('api-runs-daily', api_access.GLOBAL_PER_DAY, 86400),
                      (request.state.owner + '-daily', api_access.PER_DAY, 86400)])
    rate_many(rules)
    for expired in [k for k, j in JOBS.items() if j['status'] in TERMINAL and time.monotonic() - j['_started'] > api_access.JOB_TTL]:
        JOBS.pop(expired)
    while len(JOBS) >= api_access.MAX_JOBS:
        old = next((k for k, v in JOBS.items() if v['status'] in TERMINAL), None)
        if old is None:
            raise HTTPException(429, 'busy', headers={'Retry-After': '2'})
        JOBS.pop(old)
    job = {'id': key, 'operation': operation, '_channel': channel, 'spec': spec, 'question': body.question, 'mode': 'question' if body.question is not None else 'optimization',
           'status': 'running', 'stage': 'preparing_problem', 'output_format': output_format,
           'created_at': time.time(), '_started': time.monotonic(), '_owner': request.state.owner,
           'model': config.selection_id, 'model_configuration': config.public(),
           '_language': body.language, '_plan': shared_plan, '_config': config,
           '_workspace': record.get('workspace') if plan_id else None,
           '_plan_id': plan_id.hex if plan_id else None,
           '_optimizer_available': optimizer_available}
    JOBS[key] = job
    ACTIVE = key
    job['_task'] = asyncio.create_task(run_job(key))
    return snapshot(job)


@app.post('/api/media/jobs')
@app.post('/api/v1/media/compare', status_code=202)
async def submit_media(body: media.MediaRequest, request: Request):
    global ACTIVE
    channel = 'api' if request.url.path.startswith('/api/v1/') else 'web'
    key = body.request_id.hex
    digest = hashlib.sha256(body.model_dump_json(exclude={'request_id'}).encode()).hexdigest()
    if key in JOBS:
        old = lookup(request, key)
        if old.get('_media_digest') != digest or old.get('_channel') != channel:
            raise HTTPException(409, 'request_id_conflict')
        return snapshot(old)
    if ACTIVE or PLANNING:
        raise HTTPException(429, 'busy', headers={'Retry-After': '2'})
    try:
        config = meta_ai.configuration(body.model)
        planner = meta_ai.configuration('muse-spark-1.3')
        raw = media.upload_image(body.image)
    except meta_ai.AIError as exc:
        raise HTTPException(422, exc.detail()) from None
    rules = [('runs-global', 8, 60), (request.state.owner + '-run', api_access.PER_MINUTE, 60)]
    if channel == 'api':
        rules.extend([('api-runs-daily', api_access.GLOBAL_PER_DAY, 86400),
                      (request.state.owner + '-daily', api_access.PER_DAY, 86400)])
    rate_many(rules)
    # Media carries binary artifacts. Retain at most 3 jobs and the existing global cap.
    old_media = [k for k, j in JOBS.items() if j.get('mode') == 'media' and j['status'] in TERMINAL]
    for old in old_media[:-2]:
        JOBS.pop(old, None)
    for old in [k for k, j in JOBS.items() if j['status'] in TERMINAL and time.monotonic() - j['_started'] > api_access.JOB_TTL]:
        JOBS.pop(old, None)
    while len(JOBS) >= api_access.MAX_JOBS:
        old = next((k for k, j in JOBS.items() if j['status'] in TERMINAL), None)
        if old is None:
            raise HTTPException(429, 'busy')
        JOBS.pop(old)
    job = {'id': key, 'operation': 'compare', 'mode': 'media', 'action': body.action, '_channel': channel,
           'question': body.prompt.strip(), 'model': config.selection_id, 'model_configuration': config.public(),
           'status': 'running', 'stage': 'running', 'created_at': time.time(),
           '_started': time.monotonic(), '_owner': request.state.owner, '_config': config,
           '_planner_config': planner, '_media_input': raw, '_media_digest': digest, '_media_assets': {}}
    JOBS[key] = job
    ACTIVE = key
    job['_task'] = asyncio.create_task(run_job(key))
    return snapshot(job)


@app.get('/api/media/jobs/{key}/assets/{filename}')
@app.get('/api/v1/media/jobs/{key}/assets/{filename}')
async def media_asset(key: str, filename: str, request: Request, download: bool = False):
    job = lookup(request, key)
    value = job.get('_media_assets', {}).get(filename)
    if value is None:
        raise HTTPException(404, 'asset_expired')
    return Response(value, media_type='image/png', headers={
        'Content-Disposition': ('attachment' if download else 'inline') + '; filename="' + filename + '"'})


@app.get('/api/jobs/{key}')
async def get_job(key: str, request: Request):
    return snapshot(lookup(request, key))


async def stream_job(key, request):
    queue = asyncio.Queue(maxsize=1)
    LISTENERS.setdefault(key, set()).add(queue)
    try:
        while True:
            if await request.is_disconnected():
                return
            job = JOBS.get(key)
            payload = snapshot(job) if job else {'status': 'failed', 'stage': 'job_expired', 'error': 'job_expired'}
            yield 'data: ' + json.dumps(payload, allow_nan=False, separators=(',', ':')) + '\n\n'
            if payload['status'] in TERMINAL:
                return
            try:
                await asyncio.wait_for(queue.get(), 15)
            except TimeoutError:
                yield 'event: heartbeat\ndata: {}\n\n'
    finally:
        LISTENERS.get(key, set()).discard(queue)
        if not LISTENERS.get(key):
            LISTENERS.pop(key, None)


@app.get('/api/jobs/{key}/events')
async def events(key: str, request: Request):
    lookup(request, key)
    return StreamingResponse(stream_job(key, request), media_type='text/event-stream',
        headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})


@app.post('/api/jobs/{key}/cancel')
async def cancel(key: str, request: Request):
    job = lookup(request, key)
    if job['status'] not in TERMINAL:
        update_job(key, stage='cancelling')
        job['_task'].cancel()
    return snapshot(job)


@app.post('/api/jobs/{key}/explain')
async def explain(key: str, request: Request):
    job = lookup(request, key)
    if job.get('mode') == 'media':
        raise HTTPException(422, 'media_use_result_evidence')
    if job['status'] != 'completed':
        raise HTTPException(409, 'not_completed')
    if 'explanation' in job:
        return job['explanation']
    if job.get('_explaining'):
        raise HTTPException(429, 'busy', headers={'Retry-After': '2'})
    rate('ai-global', 10)
    rate(request.state.owner + '-ai', 5)
    job['_explaining'] = True
    try:
        job['explanation'] = await meta_ai.explain(job['result'], job['_language'], job['_config'])
        return job['explanation']
    except meta_ai.AIError as exc:
        raise HTTPException(422, exc.detail()) from None
    finally:
        job['_explaining'] = False


class CSVRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kind: Literal['balance','choices','groups','selection','assignment','qubo','own']
    csv: str=Field(min_length=1,max_length=100000)

class DataReviewRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    dataset_id: UUID | None=None
    instructions: str=Field(default='',max_length=6000)
    previous_plan_id: UUID | None=None
    language: Literal['en','es','fr','de']='en'
    model: str | None=None

class DataRunRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id: UUID
    plan_id: UUID
    confirmed: Literal[True]
    language: Literal['en','es','fr','de']='en'

def retained(mapping,key,owner):
    record=mapping.get(key)
    if not record or record['owner']!=owner or time.monotonic()-record['created']>3600:
        raise HTTPException(404,{'code':'data_expired','message':'This data or review has expired. Upload the CSV again.'})
    return record

def trim_records(mapping):
    for key in [k for k,v in mapping.items() if time.monotonic()-v['created']>3600]: mapping.pop(key)
    while len(mapping)>=40: mapping.pop(next(iter(mapping)))

@app.get('/api/data/formats')
async def data_formats():
    return {'formats':datasets.FORMATS,'max_bits':64,'max_csv_bytes':100000}

@app.post('/api/data/preview')
async def data_preview(body:CSVRequest,request:Request):
    rate(request.state.owner+'-upload',12)
    try:
        dataset=datasets.parse_csv(body.kind,body.csv)
    except (datasets.DataError,ValueError) as exc:
        raise HTTPException(422,{'code':'invalid_csv','message':str(exc)[:500]}) from None
    trim_records(DATASETS)
    key=uuid4().hex
    DATASETS[key]={'owner':request.state.owner,'created':time.monotonic(),'dataset':dataset}
    return {'dataset_id':key,**datasets.preview(dataset)}

@app.post('/api/data/review')
async def data_review(body:DataReviewRequest,request:Request):
    global PLANNING
    source=retained(DATASETS,body.dataset_id.hex,request.state.owner) if body.dataset_id else {'dataset':{'kind':'own','payload':'{"columns":[],"rows":[]}'}}
    if body.previous_plan_id and not body.dataset_id: raise HTTPException(422,'plan_mismatch')
    previous=[]
    if body.previous_plan_id:
        previous_record=retained(PLANS,body.previous_plan_id.hex,request.state.owner)
        workspace=previous_record.get('workspace')
        if not workspace or workspace['dataset_id']!=body.dataset_id.hex: raise HTTPException(409,'plan_mismatch')
        previous=workspace['extra_rules']
    if PLANNING or ACTIVE: raise HTTPException(429,'busy',headers={'Retry-After':'2'})
    rate_many([('ai-global',10,60),(request.state.owner+'-ai',5,60)])
    PLANNING=True
    try:
        config=meta_ai.configuration(body.model);start=time.perf_counter()
        proposal=await datasets.review(source['dataset'],body.instructions,previous,body.language,config)
        if proposal['status']=='ready' and source['dataset']['kind']!='own':
            key=uuid4().hex;trim_records(PLANS)
            workspace={'dataset':source['dataset'],'dataset_id':body.dataset_id.hex,'plan_id':key,
                'extra_rules':proposal['extra_rules'],'message':proposal['message'],'instructions':body.instructions}
            PLANS[key]={'owner':request.state.owner,'created':time.monotonic(),'spec':proposal['spec'],
                'model_configuration':config.public(),'meta':proposal['meta'],
                'elapsed_ms':(time.perf_counter()-start)*1000,'workspace':workspace}
            proposal['plan_id']=key
        return {k:v for k,v in proposal.items() if k not in ('spec','meta','extra_rules')}
    except meta_ai.AIError as exc: raise HTTPException(422,exc.detail()) from None
    finally: PLANNING=False

@app.get('/api/data/plans/{key}')
async def data_plan(key:str,request:Request):
    record=retained(PLANS,key,request.state.owner);w=record.get('workspace')
    if not w: raise HTTPException(404,'plan_expired')
    return {**datasets.preview(w['dataset']),'dataset_id':w['dataset_id'],'plan_id':key,'instructions':w['instructions'],
            'message':w['message'],'rules':datasets.describe_rules(w['dataset'],w['dataset']['base_rules']+w['extra_rules']),
            'solver_bits':prepare(record['spec'])[0].n}

@app.post('/api/data/run')
async def data_run(body:DataRunRequest,request:Request):
    record=retained(PLANS,body.plan_id.hex,request.state.owner)
    if not record.get('workspace'): raise HTTPException(404,'plan_expired')
    internal=RunRequest(request_id=body.request_id,spec=Spec.model_validate(record['spec']),
        plan_id=body.plan_id,language=body.language,model=record['model_configuration']['selection_id'])
    return await submit_job(internal,request)

public_api.install(app, submit_job, get_job, cancel)


app.mount('/', StaticFiles(directory=ROOT / 'dist', html=True), name='web')
